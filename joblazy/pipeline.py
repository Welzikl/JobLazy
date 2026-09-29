import json
import subprocess
import sys
import re
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from datetime import datetime,timezone,timedelta
from collections import deque
from .common import ROOT, NeedsInput, PostingDescriptionError, InvalidModelOutput, ModelUnavailable, DailyModelLimit, PostingUnavailable, write_json,digest
from .materials import rank, tailor, render, PageOverflow, AssessmentFailed,TailoringFailed
from .browser import apply,disconnected
from .checkpoints import load_materials, save_materials
from .profiles import require_profile
from .work_mode import require_application_work,PreparationPaused

def discover(boards_path, store, checkpoint=None, *, timeout=600):
    if type(timeout) not in (int, float) or not 0 < timeout <= 600:
        raise ValueError('Discovery timeout must be positive and at most 600 seconds')
    configuration=json.loads(Path(boards_path).read_text(encoding='utf-8-sig'))
    from .discovery_intake import validate_locations
    validate_locations(configuration.get('location_classes'))
    args=['node',str(ROOT/'scripts/scan.mjs'),str(Path(boards_path).resolve())]
    if checkpoint:
        checkpoint=Path(checkpoint); checkpoint.parent.mkdir(parents=True,exist_ok=True)
        write_json(checkpoint,{'jobs':[],'errors':[],'source_runs':[]})
        args.append(str(checkpoint.resolve()))
    warnings=[];failure=None
    try:
        result = subprocess.run(args,capture_output=True,text=True,encoding='utf-8',timeout=timeout)
        warnings=result.stderr.strip().splitlines() if result.stderr.strip() else []
        if result.returncode:
            failure=f'Scanner exited with code {result.returncode}'
            if not checkpoint:raise RuntimeError(failure+': '+result.stderr)
        else:
            data = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        if not checkpoint: raise
        failure='Scan time budget exceeded'
    if failure:
        try:
            data=json.loads(checkpoint.read_text(encoding='utf-8'))
            if (not isinstance(data,dict) or not isinstance(data.get('jobs'),list)
                    or any(not isinstance(job,dict) for job in data['jobs'])
                    or not isinstance(data.get('errors'),list) or not isinstance(data.get('source_runs',[]),list)
                    or any(not isinstance(run,dict) for run in data.get('source_runs',[]))):
                raise ValueError('Invalid checkpoint structure')
        except (OSError,ValueError) as error:
            raise RuntimeError(f'Scanner interrupted and checkpoint is unreadable: {error}') from error
        failure+='; last complete checkpoint retained'
        data['errors'].append({'board':'scan','error':failure})
        for run in data.get('source_runs',[]):
            if run.get('status')=='in_progress':
                run.update(status='interrupted',error=failure,finished_at=datetime.now(timezone.utc).isoformat())
    return ingest_discovery_result(data,store,checkpoint,configuration.get('location_classes'),warnings)


def ingest_discovery_result(data,store,checkpoint=None,location_classes=None,warnings=None):
    from .discovery_intake import ingest_jobs
    warnings=warnings or []
    known_ids={r[0] for r in store.db.execute('SELECT id FROM jobs')}
    for job in data['jobs']:
        if not job.get('url'): continue
        job['description'] = plain_text(job.get('description',''))
    intake=ingest_jobs(store,data['jobs'],location_classes);ids=intake['ids']
    report={'discovered':len(ids),'new_unique_jobs':len(set(ids)-known_ids),'errors':data['errors'],
        'fetched_records':len(data['jobs']),**{k:intake[k] for k in ('excluded_by_location','exact_route_joins','ambiguous_route_matches')}}
    if warnings:report['warnings']=warnings
    if checkpoint:
        from .source_registry import record_sources
        checkpoint=Path(checkpoint)
        record_sources(checkpoint.parent/'source-registry.json',data.get('source_runs',[]),set(ids)-known_ids,intake['observed_ids'])
        data['intake']={**report,'location_classes':location_classes}
        if warnings:data['warnings']=warnings
        write_json(checkpoint,data)
    return report

def plain_text(value):
    class Text(HTMLParser):
        def __init__(self): super().__init__(); self.parts=[]; self.skip=0
        def handle_starttag(self,tag,attrs):
            if tag in ('script','style'): self.skip+=1
            if tag in ('p','br','li','div','h1','h2','h3'): self.parts.append('\n')
        def handle_endtag(self,tag):
            if tag in ('script','style'): self.skip=max(0,self.skip-1)
        def handle_data(self,data):
            if not self.skip: self.parts.append(data)
    # Greenhouse content can arrive entity-escaped. A single parser pass then
    # exposes markup as text; decode before parsing so it cannot reach ranking.
    parser=Text(); parser.feed(unescape(value));parser.close()
    return re.sub(r'\n\s*\n+','\n\n',''.join(parser.parts)).strip()

def processing_priority(job,profile):
    # Cheap scheduling hints only. Full-JD model ranking still makes the fit decision.
    location = job.get('location','').casefold()
    city=profile.get('search_location',{}).get('city','').casefold()
    regions=profile.get('discovery_preferences',{}).get('location_filter',{}).get('always_allow',[])
    country=profile.get('search_location',{}).get('country','').strip().casefold()
    if city=='london' and country in ('united kingdom','uk','gb','gbr','england','great britain'):
        from .coverage import location_class
        category=location_class(location)
        score={'london_uk_explicit':1000,'london_country_unverified':750,
            'uk_remote_candidate':1000,'uk_city_unspecified_or_elsewhere':500}.get(category,0)
    else:
        score = 1000 if city and re.search(r'\b'+re.escape(city)+r'\b',location) else 500 if any(re.search(r'\b'+re.escape(r.casefold())+r'\b',location) for r in regions) else 0
    titles=profile.get('discovery_preferences',{}).get('title_filter',{})
    title=job.get('title','').casefold()
    def matches(phrase):
        tokens=[token.strip().casefold() for token in phrase.split('+')]
        return bool(tokens) and all(token and re.search(r'(?<!\w)'+re.escape(token)+r'(?!\w)',title) for token in tokens)
    # Aliases describe the same preference; overlapping or repeated aliases
    # must not outweigh another matching role or the location preference.
    if any(matches(phrase) for phrase in titles.get('positive',[])):score+=50
    # Explicit lower-interest titles wait behind other roles in the same area;
    # they remain candidates and still receive the normal full assessment.
    if any(matches(phrase) for phrase in titles.get('deprioritized',[])):score-=100
    # A title cannot prove mandatory experience, so it must not exclude a role.
    # It can still preserve the user's 1–5-year search focus by making clear
    # seniority signals wait behind otherwise equivalent target-track work.
    if titles.get('midcareer_default', True) and re.search(r'(?<!\w)(senior|principal|director|head|vice president|vp)(?!\w)',title):score-=100
    # Internships and graduate schemes are distinct early-career tracks from
    # the user's 1–5-year target. Keep them eligible for an explicit choice,
    # but do not spend a scarce first ranking batch on a title-only match.
    if titles.get('midcareer_default', True) and re.search(r'(?<!\w)(intern\w*|graduate|apprentice|student)(?!\w)',title):score-=100
    return score

def queue_candidates(store,*,rank_only=False,prepare=False,profile=None):
    """Use the same readiness rules for one-shot and continuous processing."""
    ready_states={'discovered','retryable'} | (set() if rank_only else {'ranked'}) | ({'materials_ready'} if prepare else set())
    from .assessment_state import assessment_stale,assessment_profile_hash
    profile_hash=digest(profile) if profile is not None else None
    assessment_hash=assessment_profile_hash(profile) if profile is not None else None
    stale_ids={r['id'] for r in store.list({'ranked','not_selected'}) if assessment_stale(r,profile_hash,assessment_hash)}
    if stale_ids:ready_states.update({'ranked','not_selected'})
    # A user may explicitly select a worthwhile stretch below the numeric cutoff.
    # This does not release submitted, uncertain or manual-review ownership.
    selected_rejections={r['id'] for r in store.list({'not_selected'})
        if (choice:=store.choice(r['id'])) and choice['current'] and choice['decision']=='pursue'
        and (previous:=(r['result'] or {}).get('ranking',r['result'] or {})).get('eligible')
        and previous.get('fit_category')!='poor_fit'}
    if selected_rejections:ready_states.add('not_selected')
    return [r for r in store.list(ready_states)
        if (r['status']!='not_selected' or r['id'] in selected_rejections or r['id'] in stale_ids)
        and (not rank_only or r['status']!='ranked' or r['id'] in stale_ids)]

def employer_rotation_aliases(profile):
    """Only explicit exact labels share a rotation slot; never infer ownership."""
    from .coverage import normalized
    configured=profile.get('discovery_preferences',{}).get('employer_rotation_groups',{})
    if not isinstance(configured,dict):raise ValueError('Employer rotation groups must map names to label lists')
    aliases={};names=set()
    for name,labels in configured.items():
        if not isinstance(name,str) or not normalized(name) or normalized(name) in names:
            raise ValueError('Employer rotation group names must be nonempty and unique')
        if not isinstance(labels,list) or not labels or any(not isinstance(label,str) or not normalized(label) for label in labels):
            raise ValueError('Employer rotation groups require nonempty employer labels')
        group=normalized(name);names.add(group)
        for label in labels:
            alias=normalized(label)
            if alias in aliases and aliases[alias]!=group:
                raise ValueError('An employer label cannot belong to multiple rotation groups')
            aliases[alias]=group
    return aliases


def schedule_candidates(candidates,profile,*,now=None,prioritized_ids=()):
    """Order work without rejecting jobs or treating scheduling as a fit score."""
    from .coverage import timestamp,normalized
    now=now or datetime.now(timezone.utc)
    days=profile.get('discovery_preferences',{}).get('max_posting_age_days')
    if days is not None and (isinstance(days,bool) or not isinstance(days,int) or days<1):
        raise ValueError('Posting age threshold must be a positive integer')
    cutoff=now-timedelta(days=days) if days is not None else None
    aliases=employer_rotation_aliases(profile)
    groups={}
    prioritized_ids=set(prioritized_ids)
    for row in candidates:
        posting=row['data'];date=timestamp(posting.get('postedAt')) if cutoff else None
        if date is not None and date>now+timedelta(days=1):date=None
        freshness=1 if date is None else 2 if date>=cutoff else 0
        key=(processing_priority(posting,profile),freshness)
        groups.setdefault(key,[]).append((date.timestamp() if date else 0,row))
    ordered=[]
    for key in sorted(groups,reverse=True):
        employers={}
        # Most recent posting first within each equivalent group. Unknown dates
        # retain stable input order; discovery time is never a posting date.
        for _,row in sorted(groups[key],key=lambda pair:pair[0],reverse=True):
            label=normalized(row['data'].get('company'))
            company=('group',aliases[label]) if label in aliases else ('employer',label) if label else ('unknown',row['id'])
            employers.setdefault(company,deque()).append(row)
        active=deque(employers.values())
        while active:
            employer=active.popleft();ordered.append(employer.popleft())
            if employer:active.append(employer)
    # Move explicit pursuits forward after ordinary ordering, preserving the
    # relative order and employer rotation of all remaining candidates.
    return [row for row in ordered if row['id'] in prioritized_ids]+[row for row in ordered if row['id'] not in prioritized_ids]


def run_queue(store, profile, model, browser, output, limit=5, *, prepare=False, submit=False, rank_only=False,
              fixture_origin=None, allow_live=False, verify_seconds=15, only=None, exclude=None,profile_path=None):
    require_profile(profile)
    if rank_only and (prepare or submit):raise ValueError('Ranking-only cannot prepare or submit applications')
    def check_mode():
        if not rank_only and fixture_origin is None:require_application_work(Path(output).parent,profile_path)
    check_mode()
    results = []
    # Recover only under the caller's process lock; one active pipeline at a time.
    store.recover()
    candidates=queue_candidates(store,rank_only=rank_only,prepare=prepare,profile=profile)
    ready_states={row['status'] for row in candidates}
    if only is not None:
        row=store.get(only)
        if only not in {candidate['id'] for candidate in candidates}:
            raise NeedsInput(f"Job is {row['status']}; resolve its state before running it")
        candidates=[row]
    else:candidates=[r for r in candidates if r['id'] not in (exclude or set())]
    candidates=schedule_candidates(candidates,profile,prioritized_ids=store.pursued_ids(candidates))
    for row in candidates[:limit]:
        check_mode()
        key, job = row['id'], row['data']
        choice=store.choice(key,job)
        if choice and choice['current'] and choice['decision']=='pass':
            store.transition(key,'not_selected',{'reason':'User chose to pass on this role','user_choice':choice},expected=ready_states)
            results.append({'id':key,'status':'not_selected','reason':'User chose to pass'});continue
        prior=store.prior_application(job,exclude_id=key)
        if prior:
            store.transition(key,'needs_input',{'reason':'Exact posting has a prior application or unresolved handoff',
                'prior_job_id':prior['id'],'prior_status':prior['status']},expected=ready_states)
            results.append({'id':key,'status':'needs_input'});continue
        directory = Path(output)/key
        source_job=job
        store.transition(key,'processing',expected=ready_states)
        page = None
        from .usage import model_context
        from .workflow_usage import ProcessingAttempt
        timing=ProcessingAttempt(directory,key,'rank_only' if rank_only else 'submit' if submit else 'prepare' if prepare else 'cv_only',fixture_origin is not None)
        usage_context=model_context.set({'job_id':key,'stage':'ranking'})
        try:
            checkpoint=load_materials(directory,source_job,profile)
            if checkpoint:
                job=checkpoint['job']
                ranking=checkpoint['ranking']
                artifact=checkpoint['artifact']
            else:
                ranking=None
                job={**job,'description':plain_text(job.get('description',''))}
            if fixture_origin is None:
                from .discovery import enrich
                # Full feed descriptions and cached CVs can outlive a vacancy.
                # One fresh public read precedes model work or checkpoint reuse.
                job=enrich(job,browser,directory,check_only=bool(checkpoint) or (
                    len(job.get('description','').strip())>=200 and not job.get('description_refresh_required')))
                if not checkpoint:
                    source_job=store.record_description(key,source_job,job)
                route_observation=job.pop('_application_route_observation',None)
                if route_observation:store.record_application_route(key,route_observation)
                prior=store.prior_application(job,exclude_id=key)
                if prior:
                    store.transition(key,'needs_input',{'reason':'Observed employer route has a prior application or unresolved handoff',
                        'prior_job_id':prior['id'],'prior_status':prior['status']})
                    results.append({'id':key,'status':'needs_input','reason':'Prior employer application found'});continue
            if ranking is None:
                from .experience_screen import screen_experience
                screen_context=model_context.set({'job_id':key,'stage':'experience_screen'})
                try:screen=screen_experience(job,profile,model,directory)
                finally:model_context.reset(screen_context)
                if screen:
                    write_json(directory/'selection.json',{'user_choice':store.choice(key,job),
                        'below_cutoff_override':False,'blocked_by':'experience_screen'})
                    store.transition(key,'not_selected',screen)
                    results.append({'id':key,'status':'not_selected','assessment_stage':'experience_screen'})
                    continue
                ranking = rank(job,profile,model,directory=directory)
            write_json(directory/'ranking.json',ranking)
            choice=store.choice(key,job)
            pursue=bool(choice and choice['current'] and choice['decision']=='pursue')
            selection={'user_choice':choice,'below_cutoff_override':bool(pursue and ranking['eligible']
                and ranking.get('fit_category')!='poor_fit' and ranking['score']<profile.get('minimum_score',70))}
            write_json(directory/'selection.json',selection)
            if not ranking['eligible'] or ranking.get('fit_category')=='poor_fit' or (ranking['score'] < profile.get('minimum_score',70) and not pursue):
                store.transition(key,'not_selected',ranking)
                results.append({'id':key,'status':'not_selected'}); continue
            if rank_only:
                store.transition(key,'ranked',{'ranking':ranking})
                results.append({'id':key,'status':'ranked'});continue
            check_mode()
            if prepare and fixture_origin is None and allow_live:
                # Assess fit first, then avoid tailoring for an inaccessible
                # employer route. CV-only work does not depend on form access.
                from .routes import resolve_application
                job=resolve_application(job,browser,directory)
            if not checkpoint:
                model_context.set({'job_id':key,'stage':'tailoring'})
                material = tailor(job,profile,model)
                for attempt in range(3):
                    try:
                        artifact = render(material,directory,browser)
                        break
                    except PageOverflow as e:
                        if attempt == 2: raise
                        material = tailor(job,profile,model,fit_feedback={'problem':str(e),
                            'previous_payload':material['payload'],'instruction':'Reduce low-relevance content by about 25%. Preserve font sizes and relevant strongest evidence.'})
                save_materials(directory,source_job,job,profile,ranking,artifact)
            store.transition(key,'materials_ready',{'ranking':ranking,'artifact':artifact,'reused_materials':bool(checkpoint)})
            if prepare:
                check_mode()
                model_context.set({'job_id':key,'stage':'application_answers'})
                page = browser.new_page()
                status = apply(page,job,profile,artifact,store,key,directory,submit=submit,
                    fixture_origin=fixture_origin,allow_live=allow_live,verify_seconds=verify_seconds,model=model)
            else: status = 'materials_ready'
            results.append({'id':key,'status':status,'reused_materials':bool(checkpoint)})
        except PreparationPaused as e:
            store.transition(key,row['status'],row['result'],expected={'processing','materials_ready'})
            results.append({'id':key,'status':row['status'],'preparation_paused':True,'reason':str(e)})
            break
        except PostingUnavailable as e:
            store.transition(key,e.status,{'reason':str(e),'availability':e.observation})
            results.append({'id':key,'status':e.status,'reason':str(e),'availability':e.observation})
            if disconnected(browser):
                results[-1]['browser_paused']=True
                break
        except DailyModelLimit as e:
            store.transition(key,'retryable',{'reason':str(e),'failure_kind':'daily_model_limit','requires_user_input':False})
            results.append({'id':key,'status':'retryable','budget_paused':True,'reason':str(e)})
            break
        except ModelUnavailable as e:
            store.transition(key,'retryable',{'reason':str(e)})
            results.append({'id':key,'status':'retryable','provider_paused':True,'reason':str(e)})
            break
        except AssessmentFailed as e:
            detail={'reason':str(e),'failure_kind':'assessment_validation','requires_user_input':False,
                'next_action':'Inspect rejected output and correction; retry explicitly after resolving the cause.'}
            store.transition(key,'assessment_failed',detail,expected={'processing'})
            results.append({'id':key,'status':'assessment_failed',**detail})
        except TailoringFailed as e:
            evidence_path=directory/'tailoring-validation.json';write_json(evidence_path,e.evidence)
            detail={'reason':str(e),'failure_kind':'tailoring_validation','requires_user_input':False,
                'evidence_path':str(evidence_path),'next_action':'Inspect the rejected draft and source references; retry explicitly after resolving the cause.'}
            store.transition(key,'model_failed',detail,expected={'processing'})
            results.append({'id':key,'status':'model_failed',**detail})
        except InvalidModelOutput as e:
            detail={'reason':str(e),'failure_kind':'model_output','requires_user_input':False,
                'evidence_path':e.evidence_path,'next_action':'Inspect the failed response and retry explicitly after resolving the cause.'}
            store.transition(key,'model_failed',detail,expected={'processing'})
            results.append({'id':key,'status':'model_failed',**detail})
        except PostingDescriptionError as e:
            detail={'reason':str(e),'failure_kind':'posting_description','requires_user_input':False,
                'evidence_path':e.evidence_path,
                'next_action':'Resolve the specific employer posting, then refresh its source or retry explicitly. No candidate answer is required.'}
            store.transition(key,'processing_failed',detail,expected={'processing'})
            results.append({'id':key,'status':'processing_failed',**detail})
        except NeedsInput as e:
            if store.get(key)['status'] not in ('submitting','submitted','submission_unknown'):
                store.transition(key,'needs_input',{'reason':str(e)})
            results.append({'id':key,'status':store.get(key)['status'],'reason':str(e)})
        except Exception as e:
            state = store.get(key)['status']
            target = 'submission_unknown' if state == 'submitting' else 'retryable'
            if state not in ('submitted','submission_unknown'):
                store.transition(key,target,{'error':type(e).__name__,'detail':str(e),
                    'stage':(model_context.get() or {}).get('stage')})
            results.append({'id':key,'status':store.get(key)['status'],'error':str(e)})
            if disconnected(browser):
                results[-1]['browser_paused']=True
                break
        finally:
            model_context.reset(usage_context)
            if page and not disconnected(browser): page.close()
            if sys.exc_info()[0] is None:timing.finish(store.get(key)['status'])
    return results
