"""Resumable continuous operation; ordinary Python sleeps while there is no work."""
import os
import time
from contextlib import contextmanager
from datetime import datetime,timezone
from pathlib import Path
from .common import NeedsInput,read_json,write_json
from .locking import run_lock,LockBusy
from .model import CodexModel
from .pipeline import discover,run_queue,queue_candidates
from .store import Store,choice_job_hash
from .profiles import load_profile,InvalidProfile
from .work_mode import require_application_work,PreparationPaused
from .limits import DAILY_JOBS,DAILY_REQUESTS


def utc_day(timestamp=None):
    return datetime.fromtimestamp(time.time() if timestamp is None else timestamp,timezone.utc).date().isoformat()


@contextmanager
def chrome(channel):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,**({} if channel=='chromium' else {'channel':channel}))
        try: yield browser
        finally: browser.close()


class Worker:
    def __init__(self,data,profile,boards,*,model_name='gpt-5.6-terra',batch_size=3,daily_jobs=DAILY_JOBS,
                 daily_model_requests=DAILY_REQUESTS,interval=60,scan_interval=3600,prepare=False,rank_only=False,browser_channel='chrome',
                 clock=time.time,browser_factory=None,scanner=discover,model_factory=None,run_options=None):
        for value in (batch_size,daily_jobs,daily_model_requests,interval,scan_interval):
            if value<=0: raise ValueError('Worker limits and intervals must be positive')
        self.data=Path(data);self.profile=Path(profile);self.boards=Path(boards)
        self.batch_size=batch_size;self.daily_jobs=daily_jobs;self.daily_model_requests=daily_model_requests
        self.interval=interval;self.scan_interval=scan_interval;self.prepare=prepare;self.clock=clock
        self.rank_only=rank_only
        if rank_only and prepare:raise ValueError('Ranking-only cannot prepare applications')
        self.browser_factory=browser_factory or (lambda:chrome(browser_channel))
        self.scanner=scanner;self.model_factory=model_factory;self.model_name=model_name
        self.run_options=run_options or {}
        self.state_path=self.data/'worker-state.json';self.stop_path=self.data/'STOP'
        self.data.mkdir(parents=True,exist_ok=True)
        try:self.state=read_json(self.state_path)
        except FileNotFoundError:self.state={}

    def tick(self):
        now=self.clock();day=utc_day(now)
        mode='rank_only' if self.rank_only else 'prepare' if self.prepare else 'cv_only'
        if not self.rank_only and not self.run_options.get('fixture_origin'):
            try:require_application_work(self.data,self.profile)
            except PreparationPaused as error:
                report={'day':day,'scan':None,'results':[],'state':'preparation_paused','mode':mode,'reason':str(error)}
                self.state.update({'pid':os.getpid(),'last_cycle':now,'last_report':report})
                write_json(self.state_path,self.state);return report
        with run_lock(self.data/'run.lock'):
            store=Store(self.data/'jobs.sqlite')
            try:
                store.recover()
                profile=load_profile(self.profile)
                if self.prepare and profile.get('example_only',True) and not self.run_options.get('fixture_origin'):
                    raise NeedsInput('Fictional profiles cannot be used on employer sites')
                report={'day':day,'scan':None,'results':[],'state':'idle','mode':mode}
                if now>=self.state.get('next_scan',0):
                    # Save the next deadline before a scan so a crash cannot produce a tight rescan loop.
                    self.state['next_scan']=now+self.scan_interval
                    write_json(self.state_path,self.state)
                    try:report['scan']=self.scanner(self.boards,store,self.data/'last-scan.json')
                    except Exception as error:report['scan']={'error':str(error)}
                usage=store.daily_usage(day)
                remaining=self.daily_jobs-usage['job_attempts']
                retries=self.state.setdefault('retries',{})
                ready=queue_candidates(store,rank_only=self.rank_only,prepare=self.prepare,profile=profile)
                for row in ready:
                    previous=retries.get(row['id'],{})
                    if previous.get('job_hash') and previous['job_hash']!=choice_job_hash(row['data']):
                        retries.pop(row['id'],None)
                    if (row['result'] or {}).get('reason') in ('Explicit operator retry','Operator supplied a scoped answer'):
                        retries.pop(row['id'],None)
                excluded={key for key,value in retries.items() if value['after']>now}
                ready=[r for r in ready if r['id'] not in excluded]
                if remaining<=0 or usage['model_requests']>=self.daily_model_requests:
                    report['state']='daily_limit'
                elif now<self.state.get('next_run',0):
                    report['state']='provider_backoff'
                elif now<self.state.get('next_browser_run',0):
                    report['state']='browser_backoff'
                elif ready:
                    model=self.model_factory(store) if self.model_factory else CodexModel(self.data/'model-cache',self.model_name,
                        before_request=lambda:store.reserve_model_request(utc_day(self.clock()),self.daily_model_requests))
                    with self.browser_factory() as browser:
                        report['results']=run_queue(store,profile,model,browser,self.data/'applications',min(self.batch_size,remaining),
                            prepare=self.prepare,rank_only=self.rank_only,profile_path=self.profile,
                            allow_live=self.prepare,exclude=excluded,**self.run_options)
                    report['state']='processed'
                    if any(r.get('preparation_paused') for r in report['results']):report['state']='preparation_paused'
                    budget_paused=any(r.get('budget_paused') for r in report['results'])
                    if budget_paused:report['state']='daily_limit'
                    paused=any(r.get('provider_paused') for r in report['results'])
                    if paused:
                        failures=self.state.get('provider_failures',0)+1
                        self.state['provider_failures']=failures
                        self.state['next_run']=self.clock()+min(900*2**min(failures-1,5),21600)
                        report['state']='provider_backoff'
                    elif not budget_paused:self.state['provider_failures']=0;self.state['next_run']=0
                    browser_paused=any(r.get('browser_paused') for r in report['results'])
                    if browser_paused:
                        failures=self.state.get('browser_failures',0)+1
                        self.state['browser_failures']=failures
                        self.state['next_browser_run']=self.clock()+min(120*2**min(failures-1,5),3600)
                        report['state']='browser_backoff'
                    else:self.state['browser_failures']=0;self.state['next_browser_run']=0
                    for result in report['results']:
                        key=result['id']
                        # A shared browser failure is not a defect in each job.
                        # Preserve any earlier job-specific retry history.
                        if result.get('browser_paused') or result.get('budget_paused'):continue
                        if result['status']=='retryable' and not result.get('provider_paused'):
                            attempts=retries.get(key,{}).get('attempts',0)+1
                            retries[key]={'attempts':attempts,'after':self.clock()+min(60*2**attempts,3600),
                                'job_hash':choice_job_hash(store.get(key)['data'])}
                            if attempts>=3:
                                failure=store.get(key)['result'] or {}
                                detail={'reason':'Processing stopped after three worker attempts: '+str(
                                    failure.get('detail') or failure.get('reason') or result.get('error') or 'Unknown technical error'),
                                    'failure_kind':'processing_error','requires_user_input':False,
                                    'attempts':attempts,'last_failure':failure,
                                    'next_action':'No candidate answer is required. Inspect the technical failure and retry explicitly after resolving its cause.'}
                                store.transition(key,'processing_failed',detail,expected={'retryable'})
                                result.update(status='processing_failed',**detail)
                        elif not result.get('provider_paused'):retries.pop(key,None)
                report['usage']=store.daily_usage(utc_day(self.clock()))
                if report['results'] or report['scan'] is not None:
                    from .review import render_review
                    report['review']=render_review(store,self.data,profile=profile)
                self.state.update({'pid':os.getpid(),'last_cycle':self.clock(),'last_report':report})
                write_json(self.state_path,self.state)
                return report
            finally:store.close()

    def run(self,max_cycles=None,emit=print):
        with run_lock(self.data/'worker.lock'):
            self.stop_path.unlink(missing_ok=True)
            cycles=0;last_state=None
            while not self.stop_path.exists():
                try:report=self.tick()
                except InvalidProfile as error:
                    report={'state':'profile_input','reason':str(error),'results':[],'scan':None}
                    self.state.update({'last_cycle':self.clock(),'last_report':report,'pid':os.getpid()})
                    write_json(self.state_path,self.state)
                except LockBusy:
                    report={'state':'busy','reason':'Another queue operation is active','results':[],'scan':None}
                    self.state.update({'last_cycle':self.clock(),'last_report':report,'pid':os.getpid()})
                    write_json(self.state_path,self.state)
                except Exception as error:
                    report={'state':'runtime_error','reason':str(error),'results':[],'scan':None}
                    self.state.update({'last_cycle':self.clock(),'last_report':report,'pid':os.getpid(),
                        'next_run':self.clock()+900})
                    write_json(self.state_path,self.state)
                cycles+=1
                if report['results'] or report['scan'] is not None or report['state']!=last_state:emit(report)
                last_state=report['state']
                if max_cycles is not None and cycles>=max_cycles:break
                deadline=time.monotonic()+self.interval
                while time.monotonic()<deadline and not self.stop_path.exists():time.sleep(min(1,max(0,deadline-time.monotonic())))
            return {'cycles':cycles,'state':'stopped','stop_requested':self.stop_path.exists()}
