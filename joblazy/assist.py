"""One visible application session, with durable ownership of manual outcomes."""
import queue
import threading
import copy
import uuid
import weakref
from pathlib import Path
from .common import NeedsInput,DailyModelLimit,read_json,write_json,digest
from .checkpoints import load_materials,resume_material_hash
from .pipeline import run_queue
from .browser import apply,field_snapshot,step_signature
from .routes import resolve_application
from .locking import run_lock
from .profiles import require_profile,load_profile
from .route_cleanup import release_routes
from .work_mode import require_application_work

_live_sessions=weakref.WeakKeyDictionary()


def remember_handoff(page,store,key,profile,job,data,fixture_origin):
    directory=Path(data)/'applications'/key
    report=read_json(directory/'browser.json')
    frames=[f for f in page.frames if not f.is_detached() and f.url==report['form_url']]
    if len(frames)!=1:raise NeedsInput('Cannot bind resume to one application frame')
    form=frames[0];token=uuid.uuid4().hex
    form.evaluate('(token)=>{window.__joblazyHandoffToken=token}',token)
    _live_sessions[page]={'key':key,'data':Path(data).resolve(),'profile':copy.deepcopy(profile),'job':copy.deepcopy(job),
        'source_job_hash':digest(store.get(key)['data']),'report':report,'form':form,'token':token,
        'url':page.url,'form_url':form.url,'signature':step_signature(form),'fields':field_snapshot(form),'fixture_origin':fixture_origin}


def resume_assisted(store,key,profile_path,model,page,data):
    """Explicitly resume the same live document; preserve operator edits."""
    data=Path(data).resolve();directory=data/'applications'/key
    state=_live_sessions.get(page)
    if not state or state['key']!=key or state['data']!=data:
        raise NeedsInput('No matching live preparation session; inspect or reconcile the application')
    if state['fixture_origin'] is None:require_application_work(data,profile_path)
    with run_lock(data/'run.lock'):
        profile=load_profile(profile_path)
        row=store.get(key);form=state['form']
        if row['status']!='manual_review' or digest(row['data'])!=state['source_job_hash']:
            raise NeedsInput('Application ownership or posting changed; resume paused')
        if page.is_closed() or form.is_detached() or page.url!=state['url'] or form.url!=state['form_url']:
            raise NeedsInput('Application page changed or closed; inspect its outcome before retrying')
        if form.evaluate('window.__joblazyHandoffToken')!=state['token'] or step_signature(form)!=state['signature']:
            raise NeedsInput('Application document or step changed; resume paused without reloading it')
        if resume_material_hash(profile)!=resume_material_hash(state['profile']):
            raise NeedsInput('Career facts, residence, targeting or CV content changed; review materials before resuming')
        checkpoint=load_materials(directory,row['data'],state['profile'])
        if checkpoint is None:raise NeedsInput('Original verified CV checkpoint changed; resume paused')
        current=field_snapshot(form);previous=state['fields']
        preserved=set(state.get('preserved',()))|{key for key,value in current.items() if
            (key in previous and value!=previous[key]) or
            (key not in previous and any(str(x).strip() for x in value['actual']))}
        try:
            status=apply(page,state['job'],profile,checkpoint['artifact'],ManualPreparation(store),key,directory,
                fixture_origin=state['fixture_origin'],allow_live=state['fixture_origin'] is None,model=model,
                resume={'form':form,'steps':state['report'].get('steps',[])[:-1],'preserved':preserved})
            # Keep the original profile for artifact validation, while refreshing
            # only browser evidence. Form-only updates do not rewrite checkpoints.
            remember_handoff(page,store,key,state['profile'],state['job'],data,state['fixture_origin'])
            refreshed=_live_sessions[page]
            if refreshed['form']==form and refreshed['signature']==state['signature']:
                refreshed['preserved']=preserved
            return status
        except DailyModelLimit as e:
            # No new model request was issued. Keep the live binding so the
            # operator can resume the same form after the allowance resets.
            store.transition(key,'manual_review',{'preparation_status':'paused','reason':str(e),
                             'failure_kind':'daily_model_limit'},expected={'manual_review'})
            raise
        except Exception as e:
            _live_sessions.pop(page,None)
            store.transition(key,'manual_review',{'preparation_status':'interrupted','reason':str(e)},expected={'manual_review'})
            raise
        finally:
            release_routes(page,directory)


def operator_prompt(page,message,*,review_pages=None,stop_when=None):
    """Keep Playwright servicing browser requests while terminal input waits."""
    # Only batch review opts into sibling pages. A closed sign-in/application
    # page must still stop its own single-page prompt.
    pages=tuple(review_pages) if review_pages is not None else (page,)
    if any(p.context!=page.context for p in pages):
        raise ValueError('Review pages must belong to the same browser context')
    result=queue.Queue()
    def read():
        try:result.put(('input',input(message+'\n> ').strip().casefold()))
        except EOFError:
            # Dashboard-launched Windows consoles can have no stdin. That must
            # not close a visible employer form before its operator reviews it.
            result.put(('eof',None))
        except KeyboardInterrupt:result.put(('input','done'))
    threading.Thread(target=read,daemon=True).start()
    while True:
        # An outcome can be reconciled from another terminal while this helper
        # has no stdin (for example, after the operator submits in the visible
        # employer page).  Do not leave the exclusive browser session alive in
        # that case; the reconciled durable state is authoritative.
        if stop_when is not None and stop_when():
            return 'done'
        try:
            kind,value=result.get_nowait()
            if kind=='input':return value
            # EOF means there is no interactive terminal. Keep the browser
            # session open and finish only when its operator closes the page.
        except queue.Empty:pass
        if page.is_closed():
            page=next((p for p in pages if not p.is_closed()),None)
            if page is None:return 'done'
        try:page.wait_for_timeout(200)
        except Exception:
            if page.is_closed():continue
            raise


class ManualPreparation:
    """Save preparation progress without releasing the durable manual handoff."""
    def __init__(self,store):self.store=store
    def prior_application(self,job,exclude_id=None):return self.store.prior_application(job,exclude_id)
    def transition(self,key,status,detail=None,expected=None):
        if status not in ('prepared','needs_input'):
            raise ValueError('Assisted mode cannot submit applications')
        self.store.transition(key,'manual_review',{'preparation_status':status,'preparation':detail},expected={'manual_review'})


def prepare_assisted(store,key,profile,model,context,data,*,prompt=operator_prompt,emit=print,fixture_origin=None,
                     reviewed_cv_sha256=None,profile_path=None):
    """Return a live page for manual completion. Caller owns browser lifetime."""
    require_profile(profile)
    data=Path(data);directory=data/'applications'/key
    if fixture_origin is None:require_application_work(data)
    with run_lock(data/'run.lock'):
        if profile_path and digest(load_profile(profile_path)) != digest(profile):
            raise NeedsInput('Your profile changed before preparation started. Review the current CV again.')
        store.recover()
        row=store.get(key)
        if row['status'] not in ('discovered','ranked','retryable','materials_ready','prepared','needs_input'):
            raise NeedsInput(f"Job is {row['status']}; inspect or reconcile it before assisted preparation")
        checkpoint=load_materials(directory,row['data'],profile)
        if reviewed_cv_sha256 is not None and (checkpoint is None or checkpoint['artifact']['sha256'] != reviewed_cv_sha256):
            raise NeedsInput('The reviewed CV changed. Generate and review the current CV before preparing this application.')
        if checkpoint is None:
            if row['status'] in ('prepared','needs_input','materials_ready'):
                store.transition(key,'retryable',{'reason':'Explicit assisted preparation request'})
            results=run_queue(store,profile,model,context,data/'applications',1,only=key,fixture_origin=fixture_origin)
            checkpoint=load_materials(directory,row['data'],profile)
            if checkpoint is None:
                raise NeedsInput(f'No verified application materials are ready: {results}')
        job=checkpoint['job'];artifact=checkpoint['artifact']
        page=context.new_page()
        # Before any employer page is displayed: an operator could submit while
        # the tool is waiting for sign-in or after an interrupted preparation.
        store.transition(key,'manual_review',{'reason':'Assisted browser session opened; outcome requires reconciliation'})
        write_json(directory/'handoff.json',{'status':'manual_review','artifact':artifact,'job_url':job['url']})
        try:
            if fixture_origin is None:
                while True:
                    try:
                        job=resolve_application(job,context,directory,page=page)
                        break
                    except NeedsInput as e:
                        evidence=read_json(directory/'application-route.json')
                        if not evidence.get('observations') or evidence['observations'][-1].get('boundary')!='employer_sign_in':raise
                        emit(str(e))
                        response=prompt(page,'Sign in in the browser. If you have only signed in, type prepare to fill the application; otherwise press Enter to continue manually.')
                        if response not in {'prepare','resume'}:return page,'sign_in_handoff'
            status=apply(page,job,profile,artifact,ManualPreparation(store),key,directory,
                submit=False,fixture_origin=fixture_origin,allow_live=fixture_origin is None,model=model)
            remember_handoff(page,store,key,profile,job,data,fixture_origin)
            return page,status
        except Exception as e:
            store.transition(key,'manual_review',{'reason':str(e),'preparation_status':'interrupted'},expected={'manual_review'})
            emit(f'Preparation paused: {e}')
            return page,'interrupted'
        finally:
            # Once the operator owns the page, ordinary browser requests must not
            # depend on automation routing handlers or their DNS guard cache.
            if not release_routes(page,directory):
                emit('Browser cleanup is pending; keep this session open while reviewing the application.')


def run_assisted(data,key,profile_path,model_name='gpt-5.6-terra',browser_channel='chrome',*,ui_session=False,reviewed_cv_sha256=None):
    from playwright.sync_api import sync_playwright
    from .model import CodexModel
    from .store import Store
    from .review import render_review
    data=Path(data).resolve();require_application_work(data,profile_path);profile=load_profile(profile_path)
    if profile.get('example_only',True):raise NeedsInput('Fictional example profiles cannot be used on employer sites')
    with run_lock(data/'browser.lock'),sync_playwright() as pw:
        options={'headless':False}
        if browser_channel!='chromium':options['channel']=browser_channel
        context=pw.chromium.launch_persistent_context(str(data/'browser-profile'),**options)
        store=Store(data/'jobs.sqlite')
        from .assist_bridge import BrowserBridge
        bridge=BrowserBridge(store,key) if ui_session else None
        prompt=bridge.wait if bridge else operator_prompt
        session_error=None
        try:
            from .limits import account_model
            model=account_model(data,store,model_name)
            page,status=prepare_assisted(store,key,profile,model,context,data,prompt=prompt,
                                        reviewed_cv_sha256=reviewed_cv_sha256,profile_path=profile_path)
            render_review(store,data,profile=profile)
            while not page.is_closed():
                page.bring_to_front()
                response=prompt(
                    page,
                    f'Preparation status: {status}. Save answers with the answer command, then type resume to apply them to this form. Review and finish in the browser. JobLazy will not click Submit. Press Enter when finished to close this browser session.',
                    stop_when=lambda: store.get(key)['status'] != 'manual_review',
                )
                if response!='resume':break
                try:
                    status=resume_assisted(store,key,profile_path,model,page,data)
                    render_review(store,data,profile=load_profile(profile_path))
                except Exception as e:
                    status='paused';print(f'Resume paused: {e}')
            print(f'Record a verified outcome with python -m joblazy --data "{data}" reconcile {key}, adding --outcome submitted or --outcome not-submitted and --note "What you verified".')
            return {'id':key,'status':store.get(key)['status'],'preparation_status':status,'outcome_required':True}
        except Exception as error:
            session_error=str(error)
            raise
        finally:
            if bridge:
                bridge.close('Preparation stopped: '+session_error if session_error else
                             'Browser session closed. Record the outcome you checked.')
            try:context.close()
            finally:store.close()
