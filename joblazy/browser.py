"""JobPilot scan/fill scripts with JobLazy provenance and durable outcome handling."""
import ipaddress
import re
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import Error as BrowserError
from .common import ROOT, NeedsInput, digest, write_json
from .mapping import plan_fields
from .forms import application_url,locate_form,application_root,open_application_form
from .outcomes import observe_receipt,origin as receipt_origin
from .profiles import require_profile

EXT = ROOT/'vendor/personal-jobpilot/browser-extension/content'

def disconnected(browser):
    """Require an explicit disconnect observation; fixtures may have no browser."""
    return getattr(browser,'is_connected',lambda:True)() is False

def public_url(url):
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password: return False
    try:
        addresses = socket.getaddrinfo(p.hostname,p.port or 443,type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(a[4][0]).is_global for a in addresses)
    except (OSError,ValueError): return False

def scan(page):
    # Evaluate through Playwright's execution context, not DOM script tags, which
    # production Ashby CSP rejects. No server policy or browser setting is changed.
    if not page.evaluate("typeof window.__jpafScan === 'function'"):
        page.evaluate((EXT/'scan.js').read_text(encoding='utf-8'))
    if not page.evaluate("typeof window.__jpafApply === 'function'"):
        page.evaluate((EXT/'fill.js').read_text(encoding='utf-8'))
    fields = page.evaluate('window.__jpafScan()')
    # Add exact choices for native radio/checkbox groups, using the upstream metadata IDs.
    fields = page.evaluate('''fields => fields.map(f => {
      const e=document.querySelector(`[data-jpaf-id="${f.id}"]`);
      if(e) {
        if(e.tagName==='SELECT' && !e.multiple)f.type='select';
        f.max_length=e.maxLength>0 ? e.maxLength : null;
        f.min_length=e.minLength>0 ? e.minLength : null;
        f.description=(e.getAttribute('aria-describedby')||'').split(/\\s+/)
          .map(id=>document.getElementById(id)?.innerText?.trim()||'').filter(Boolean).join(' ');
      }
      // Radio labels name individual options; the upstream group label names
      // the question. Replacing it with "Immediate" loses its meaning.
      if(e?.labels?.length===1 && e.type!=='radio') {
        const label=e.labels[0].cloneNode(true);
        label.querySelectorAll('input,select,textarea,button').forEach(x=>x.remove());
        const text=label.textContent.trim().replace(/\\s+/g,' ');
        if(text) f.label=text;
      }
      if(e?.type==='file' && ['resume','cover_letter'].includes(e.id))
        f.label=e.id==='resume' ? 'Resume' : 'Cover letter';
      if(e && ['radio','checkbox'].includes(e.type)) {
        const group=e.name ? [...document.getElementsByName(e.name)] : [e];
        f.options=group.map(x => (x.labels?.[0]?.innerText || x.value).trim());
      }
      return f;
    })''',fields)
    fields=page.evaluate((ROOT/'joblazy/ashby.js').read_text(encoding='utf-8'),fields)
    fields=page.evaluate((ROOT/'joblazy/lever.js').read_text(encoding='utf-8'),fields)
    fields=page.evaluate((ROOT/'joblazy/teamtailor.js').read_text(encoding='utf-8'),fields)
    return page.evaluate('''fields=>{
      const root=document.querySelector('[data-joblazy-form-root]');
      return root ? fields.filter(f=>root.contains(document.querySelector(`[data-jpaf-id="${f.id}"]`))) : fields;
    }''',fields)

def fill_plan(page, plan):
    # These sessions start in a fresh browser. Existing values can come from an
    # ATS's résumé parser, not a user edit. Correct only explicitly planned facts.
    metas={f['id']:f for f in plan['_scanMeta']}
    for field in plan['fields']:
        if field.get('phone_country'):
            from .phones import fill_phone_country
            fill_phone_country(page,field)
    # Fill the national number only after its own country control is committed.
    from .phones import install_phone_controls
    if any(f.get('phone_number') for f in plan['fields']):install_phone_controls(page)
    active=[]
    for field in plan['fields']:
        if field.get('phone_country'):continue
        if field.get('phone_number'):
            info=field['phone_number']
            if not page.evaluate('q=>window.__joblazyPhoneControl({...q,mode:"read"})',{'id':info['country_field'],'info':info})['ok']:continue
            if verify_fields(page,{'fields':[field],'_scanMeta':[metas[field['id']]]})[0]['ok']:continue
        active.append(field)
    plan={**plan,'fields':active}
    corrected=[]
    for field in plan['fields']:
        if field.get('exact_location') and metas[field['id']].get('adapter')!='lever_location':
            from .locations import fill_location
            if not verify_fields(page,{'fields':[field],'_scanMeta':[metas[field['id']]]})[0]['ok']:
                fill_location(page,field)
    for field in plan['fields']:
        meta=metas[field['id']]
        if meta.get('adapter')=='ashby_date':
            from .dates import select_ashby_date
            if not verify_fields(page,{'fields':[field],'_scanMeta':[meta]})[0]['ok']:
                select_ashby_date(page,field)
            continue
        if meta.get('combo'):continue
        loc=page.locator(f'[data-jpaf-id="{field["id"]}"]')
        if meta['type'] in ('text','email','tel','url','textarea','number','date') and loc.count()==1:
            current=loc.input_value()
            if current and current!=str(field['value']):
                loc.fill('');corrected.append(field['id'])
        elif meta['type']=='select' and loc.count()==1:
            # Native option values need not equal their human-readable labels.
            loc.select_option(label=str(field['value']))
    for field in plan['fields']:
        if metas[field['id']].get('adapter')!='lever_location': continue
        loc=page.locator(f'[data-jpaf-id="{field["id"]}"]')
        if verify_fields(page,{'fields':[field],'_scanMeta':[metas[field['id']]]})[0]['ok']: continue
        loc.fill(str(field['value']))
        root=loc.locator('xpath=ancestor::*[contains(concat(" ",normalize-space(@class)," ")," application-question ")][1]')
        choice=root.locator('.dropdown-results').get_by_text(str(field['value']),exact=True).filter(visible=True)
        try:
            choice.wait_for(state='visible',timeout=2500)
            if choice.count()!=1: continue
            choice.click()
            loc.evaluate('''e=>{
              const selected=e.closest('.application-question').querySelector('input[name=selectedLocation]');
              if(selected?.value) e.setAttribute('data-joblazy-selection',JSON.stringify({value:e.value,token:selected.value}));
            }''')
        except Exception:
            # The actual-value audit records this as unresolved, never successful.
            continue
    for field in plan['fields']:
        meta=metas[field['id']]
        if meta.get('adapter')!='teamtailor_choice': continue
        options=[o for o in meta['option_values'] if o['label']==field['value']]
        if len(options)!=1: raise NeedsInput('Ambiguous Teamtailor choice')
        loc=page.locator(f'[data-jpaf-id="{field["id"]}"]')
        controls=loc.locator('xpath=ancestor::form[1]').locator('input').all()
        matches=[c for c in controls if c.get_attribute('type')==meta['type'] and c.get_attribute('name')==meta['name'] and c.input_value()==options[0]['value']]
        if len(matches)!=1: raise NeedsInput('Teamtailor choice control changed')
        matches[0].set_checked(True)
    generic={**plan,'fields':[f for f in plan['fields'] if not f.get('exact_location') and metas[f['id']]['type']!='button_group' and metas[f['id']].get('adapter') not in ('lever_location','teamtailor_choice','ashby_date')]}
    stats=page.evaluate('(p)=>window.__jpafApply(p)',generic)
    stats['corrected_prefilled']=corrected
    types={f['id']:f['type'] for f in plan['_scanMeta']}
    for field in plan['fields']:
        if types[field['id']] != 'button_group': continue
        group=page.locator(f'[data-jpaf-id="{field["id"]}"]')
        choice=group.get_by_role('button',name=str(field['value']),exact=True)
        if choice.count()!=1: raise NeedsInput('Ambiguous button-group option')
        if choice.get_attribute('aria-pressed') != 'true': choice.click()
        if choice.get_attribute('aria-pressed') != 'true': raise NeedsInput('Button-group choice did not persist')
        group.evaluate("e=>e.setAttribute('data-jpaf-state','verified')")
    return stats

def verify_fields(page,plan):
    from .phones import install_phone_controls,same_phone
    if any(f.get('phone_country') or f.get('phone_number') for f in plan['fields']):install_phone_controls(page)
    results=page.evaluate((ROOT/'joblazy/field-values.js').read_text(encoding='utf-8'),plan)
    fields={f['id']:f for f in plan['fields']}
    for result in results:
        info=fields[result['id']].get('phone_number')
        if info and result['ok']:result['ok']=len(result['actual'])==1 and same_phone(result['actual'][0],info)
    return results

def field_snapshot(form):
    fields=scan(form)
    values=verify_fields(form,{'fields':[{'id':f['id'],'value':'','source_ref':''} for f in fields],'_scanMeta':fields})
    actual={v['id']:v['actual'] for v in values}
    return {f['id']:{'actual':actual[f['id']],'label':f.get('label'),'name':f.get('name'),'type':f['type']} for f in fields}


def prepare_step(page, form, profile, scope, artifact, drafter=None, *, preserved=None, job=None):
    from .uploads import application_feedback, cv_filename, cv_upload
    preserved=set(preserved or ())
    attached = False
    all_plans = []
    upload_attempted=set()
    blockers=application_feedback(form)
    for _ in range(3):
        if blockers: break
        fields = scan(form)
        # Attach only an explicitly identified CV field, never every file input.
        for field in fields:
            if field['type'] != 'file': continue
            if field['id'] in preserved: continue
            label = (field.get('label','')+' '+field.get('name','')).lower()
            if re.search(r'resume|résumé|\bcv\b',label) and 'cover' not in label:
                if field.get('adapter')=='ashby_upload':
                    from .uploads import attach_ashby_upload
                    attach_ashby_upload(page,form,field,artifact,upload_attempted,filename=cv_filename(profile,job or {}))
                    continue
                if field.get('adapter')=='teamtailor_upload':
                    from .uploads import attach_upload
                    attach_upload(page,form,field,artifact,upload_attempted,filename=cv_filename(profile,job or {}))
                    continue
                loc = form.locator(f'[data-jpaf-id="{field["id"]}"]')
                if field['id'] not in upload_attempted and loc.evaluate('e=>!e.files.length'):
                    # A removed/rejected file must not trigger repeated uploads.
                    upload_attempted.add(field['id'])
                    loc.set_input_files(cv_upload(artifact,cv_filename(profile,job or {}))); page.wait_for_timeout(300)
                attached = True
        blockers=application_feedback(form)
        if blockers: break
        fields = scan(form)
        plan = plan_fields(fields,profile,scope,job=job)
        if drafter: plan=drafter.extend(plan)
        # The reused filler never submits; exact file attachment is owned above.
        stats = fill_plan(form,{**plan,'fields':[f for f in plan['fields'] if f['id'] not in preserved]})
        all_plans.append({'plan':plan,'stats':stats})
        page.wait_for_timeout(200)
        blockers=application_feedback(form)
    fields = scan(form)
    plan = plan_fields(fields,profile,scope,job=job)
    if drafter and not blockers: plan=drafter.extend(plan)
    file_audit = form.evaluate('''async fields => {
      const out=[];
      for(const f of fields.filter(f=>f.type==='file' && !['teamtailor_upload','ashby_upload'].includes(f.adapter))) {
        const e=document.querySelector(`[data-jpaf-id="${f.id}"]`);
        const files=[];
        for(const file of [...(e?.files||[])]) {
          const hash=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
          files.push({name:file.name,sha256:[...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,'0')).join('')});
        }
        out.push({label:f.label,name:f.name,required:f.required,files});
      }
      return out;
    }''',fields)
    from .uploads import upload_state,ashby_upload_state
    for field in fields:
        if field.get('adapter') in ('teamtailor_upload','ashby_upload'):
            state=(ashby_upload_state if field['adapter']=='ashby_upload' else upload_state)(form,field)
            file_audit.append({'label':field['label'],'name':field['name'],'required':field['required'],**state})
    resumes = [f for f in file_audit if re.search(r'resume|résumé|\bcv\b',(f.get('label','')+' '+f.get('name','')).lower())
        and 'cover' not in (f.get('label','')+' '+f.get('name','')).lower()]
    blockers=blockers or application_feedback(form)
    attached = not blockers and bool(resumes) and all(len(f['files']) == 1 and f['files'][0]['sha256'] == artifact['sha256'] for f in resumes)
    missing_files = [f.get('label') or f.get('name') for f in file_audit if f['required'] and not f['files']]
    invalid = form.evaluate('''() => [...(document.querySelector('[data-joblazy-form-root]')||document).querySelectorAll('input,select,textarea,[aria-required=true]')]
      .filter(e=>e.getClientRects().length && !e.disabled && (e.required || e.getAttribute('aria-required')==='true'))
      .filter(e=> e.getAttribute('aria-invalid')==='true' ||
        (typeof e.checkValidity==='function' && !e.checkValidity()) ||
        (!e.value && !['checkbox','radio','file'].includes(e.type) && e.getAttribute('data-jpaf-state')!=='verified'))
      .map(e=>e.name||e.id||e.tagName)''')
    values=verify_fields(form,plan)
    unverified=[f['id'] for f in values if not f['ok']]
    report = {'attached':attached,'resume_mismatch':bool(resumes) and not attached,'artifact':artifact,'file_audit':file_audit,'missing_files':missing_files,'rounds':all_plans,'invalid':invalid,
        'unverified':unverified,'values':values,'fields':fields,'unresolved':plan['unresolved'],'scope':scope,'url':page.url,'form_url':form.url,
        'application_blockers':blockers,
        'attachment_verification':'Selected file hash and observed page feedback; employer acceptance is not established',
        'preserved_edits':[f for f in fields if f['id'] in preserved]}
    return report

def step_signature(form):
    fields=scan(form)
    return digest({'url':form.url,'fields':[{k:f.get(k) for k in ('label','name','type','required','options')} for f in fields],
        'buttons':application_root(form).get_by_role('button').all_text_contents()})

def apply(page, job, profile, artifact, store, key, directory, *, submit=False, fixture_origin=None, allow_live=False, verify_seconds=15, model=None, resume=None):
    if fixture_origin is None:
        from .work_mode import require_application_work
        require_application_work(Path(directory).parent.parent)
    prior=store.prior_application(job,exclude_id=key)
    if prior:
        raise NeedsInput(f"Exact posting already has application history ({prior['status']}, job {prior['id']}); review its outcome before another preparation")
    require_profile(profile)
    if resume is not None and submit:raise NeedsInput('Resumed operator sessions cannot submit automatically')
    directory = Path(directory); directory.mkdir(parents=True,exist_ok=True)
    scope = job.get('application_url') or job['url']
    url = application_url(scope)
    p = urlsplit(url)
    origin = f'{p.scheme}://{p.netloc}'
    fixture = fixture_origin is not None and origin == fixture_origin and p.hostname in ('127.0.0.1','localhost')
    if not fixture and not allow_live: raise NeedsInput('Live browser operation is disabled for this run')
    if not fixture and not public_url(url): raise NeedsInput('Application URL is not a public HTTPS address')
    if digest(Path(artifact['path']).read_bytes()) != artifact['sha256']:
        raise NeedsInput('CV changed after verification')
    checked = {}
    def route_request(route):
        u = urlsplit(route.request.url)
        if fixture:
            allowed = f'{u.scheme}://{u.netloc}' == fixture_origin
        elif u.scheme in ('data','blob'):
            allowed = True
        else:
            host = f'{u.scheme}://{u.netloc}'
            if host not in checked: checked[host] = public_url(route.request.url)
            allowed = checked[host]
        if allowed: route.continue_()
        else: route.abort()
    page.route('**/*', route_request)
    if resume is None:
        page.goto(url,wait_until='domcontentloaded',timeout=45000)
        form=open_application_form(page)
    else:
        form=resume['form']
    drafter=None
    if model is not None:
        from .narratives import AnswerDrafter
        drafter=AnswerDrafter(profile,job,model,directory,scope)
    steps=list(resume['steps']) if resume is not None else []
    for step in range(8):
        # A later document or replacement frame can introduce sign-in too.
        if form.locator('input[type=password]:visible, iframe[src*="hcaptcha"]:visible, .cf-turnstile:visible').count():
            raise NeedsInput('Application requires authentication or a challenge')
        report=prepare_step(page,form,profile,scope,artifact,drafter,job=job,
            preserved=resume['preserved'] if resume is not None and step==0 else None)
        steps.append(report)
        combined={**report,'steps':steps.copy(),'attached':not report['application_blockers'] and any(s['attached'] for s in steps)}
        write_json(directory/'browser.json',combined)
        page.screenshot(path=str(directory/f'step-{step+1}.png'),full_page=True)
        unresolved_required=[x for x in report['unresolved'] if x['required']]
        if report['application_blockers'] or unresolved_required or report['invalid'] or report['unverified'] or report['missing_files'] or report['resume_mismatch']:
            store.transition(key,'needs_input',combined)
            return 'needs_input'
        next_buttons=application_root(form).get_by_role('button',name=re.compile(r'^(next|continue|next step|save and continue)$',re.I)).filter(visible=True)
        final_buttons=application_root(form).get_by_role('button',name=re.compile(r'^(submit application|submit|send application|apply)$',re.I)).filter(visible=True)
        if next_buttons.count():
            if next_buttons.count()!=1 or final_buttons.count() or not next_buttons.is_enabled():
                raise NeedsInput('Cannot identify an unambiguous next-step control')
            previous=step_signature(form)
            next_buttons.click(timeout=10000)
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                page.wait_for_timeout(200)
                if form.is_detached():
                    # A parent page can replace its embedded application between
                    # steps. Locate a unique visible replacement before filling.
                    form=locate_form(page,timeout=max(0,deadline-time.monotonic()))
                try:
                    if step_signature(form)!=previous: break
                except BrowserError:
                    # The frame can detach between the check and the evaluation.
                    if not form.is_detached():raise
            else: raise NeedsInput('Next step did not produce a changed application form')
            continue
        if not combined['attached']:
            store.transition(key,'needs_input',{**combined,'reason':'No verified CV attachment in application steps'})
            return 'needs_input'
        if final_buttons.count()!=1 or not final_buttons.is_enabled():
            raise NeedsInput('No unique enabled final application control after preparation')
        report=combined
        page.screenshot(path=str(directory/'prepared.png'),full_page=True)
        break
    else: raise NeedsInput('Application exceeded eight steps')
    store.transition(key,'prepared',report)
    if not submit: return 'prepared'
    expected_origin=receipt_origin(form.url)
    before=observe_receipt(form,expected_origin)['confirmed']
    submitters = application_root(form).get_by_role('button',name=re.compile(r'^(submit application|submit|send application|apply)$',re.I)).filter(visible=True)
    if submitters.count() != 1 or not submitters.is_enabled():
        raise NeedsInput('Cannot identify exactly one enabled application submit control')
    # Persist before any request can leave. Any later exception remains unknown, never retryable.
    store.transition(key,'submitting',{'artifact':artifact,'url':page.url,'application_frame_url':form.url},expected={'prepared'})
    try:
        submitters.click(timeout=10000)
        deadline = time.monotonic()+verify_seconds
        last_observation=None
        while time.monotonic() < deadline:
            observation=observe_receipt(form,expected_origin)
            if observation!=last_observation:
                write_json(directory/'outcome-observation.json',observation)
                last_observation=observation
            fresh=[t for t in observation['confirmed'] if t not in before]
            if fresh:
                page.screenshot(path=str(directory/'confirmation.png'),full_page=True)
                detail = {'url':page.url,'application_frame_url':form.url,'confirmation':fresh,'artifact':artifact}
                write_json(directory/'confirmation.json',detail)
                store.transition(key,'submitted',detail,expected={'submitting'})
                return 'submitted'
            page.wait_for_timeout(200)
        store.transition(key,'submission_unknown',{'reason':'No explicit new application confirmation','url':page.url})
    except Exception as e:
        store.transition(key,'submission_unknown',{'reason':type(e).__name__,'url':page.url})
    return 'submission_unknown'
