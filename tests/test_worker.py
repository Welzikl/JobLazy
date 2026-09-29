import tempfile
import time
import unittest
import subprocess
import sys
import json
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
from joblazy.common import ModelUnavailable,write_json
from joblazy.store import Store
from joblazy.worker import Worker,utc_day
from joblazy.locking import run_lock
from .support import example_profile,job,FixtureModel


class WorkerTests(unittest.TestCase):
    def test_malformed_rankings_stop_locally_and_other_jobs_survive_worker_restart(self):
        from joblazy.model import CodexModel
        requests=[];scans=[]
        def cli(args,**kwargs):
            if args[1]=='login':return subprocess.CompletedProcess(args,0,'Logged in','')
            requests.append(kwargs['input']);answer=Path(args[args.index('--output-last-message')+1])
            if len(requests)<=2:answer.write_text('Fictional malformed response',encoding='utf-8')
            else:write_json(answer,FixtureModel().generate('Rank this',{},{}))
            return subprocess.CompletedProcess(args,0,json.dumps({'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':1}}),'')
        def scan(boards,store,checkpoint):
            scans.append(1)
            for name in ('one','two'):store.ingest(job('https://example.test/'+name))
            return {'discovered':2}
        options={'rank_only':True,'daily_jobs':10,'daily_model_requests':6,'scanner':scan,
            'browser_factory':lambda:nullcontext(None),
            'model_factory':lambda store:CodexModel(self.data/'model-cache',executable='fixture-codex',
                before_request=lambda:store.reserve_model_request(utc_day(),6))}
        with patch('joblazy.model.subprocess.run',side_effect=cli):
            first=Worker(self.data,self.profile,self.boards,**options).tick()
            second=Worker(self.data,self.profile,self.boards,**options).tick()
        self.assertEqual(sorted(r['status'] for r in first['results']),['assessment_failed','ranked'])
        failed=next(r for r in first['results'] if r['status']=='assessment_failed')
        self.assertFalse(failed['requires_user_input']);self.assertEqual(len(requests),3)
        self.assertEqual(first['usage']['model_requests'],3)
        self.assertEqual(second['results'],[]);self.assertEqual(second['state'],'idle');self.assertEqual(len(scans),1)

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        # These scheduler tests inject no browser. Vacancy behavior is exercised
        # separately with real Chrome and a local HTTP server.
        checker=patch('joblazy.discovery.enrich',side_effect=lambda job,*args,**kwargs:job)
        checker.start();self.addCleanup(checker.stop)
        self.data=Path(self.temp.name);self.profile=self.data/'profile.json';self.boards=self.data/'boards.json'
        write_json(self.profile,example_profile());write_json(self.boards,{'boards':[]})

    def test_restart_can_continue_ranked_roles_and_reassess_instead_of_trusting_saved_score(self):
        store=Store(self.data/'jobs.sqlite');key=store.ingest(job('https://example.test/ranked'))
        store.transition(key,'ranked',{'ranking':{'score':100}});store.close()
        calls=[]
        class Reassess(FixtureModel):
            def generate(self,task,data,schema):
                calls.append(task);result=super().generate(task,data,schema)
                result.update(score=10,fit_category='poor_fit');return result
        worker=Worker(self.data,self.profile,self.boards,scanner=lambda *a:{'discovered':0},
            browser_factory=lambda:nullcontext(None),model_factory=lambda s:Reassess())
        result=worker.tick()
        self.assertEqual(result['state'],'processed');self.assertEqual(result['results'][0]['status'],'not_selected')
        self.assertEqual(result['results'][0]['id'],key);self.assertEqual(len(calls),1)

    def test_model_slots_survive_restart_and_reset_by_utc_day(self):
        store=Store(self.data/'jobs.sqlite')
        store.reserve_model_request('2026-09-11',2);store.reserve_model_request('2026-09-11',2);store.close()
        store=Store(self.data/'jobs.sqlite')
        try:
            with self.assertRaises(ModelUnavailable):store.reserve_model_request('2026-09-11',2)
            self.assertEqual(store.daily_usage('2026-09-11')['model_requests'],2)
            store.reserve_model_request('2026-09-12',2)
            self.assertEqual(store.daily_usage('2026-09-12')['model_requests'],1)
        finally:store.close()

    def test_mid_batch_request_limit_is_not_provider_failure_and_resumes_next_day(self):
        from datetime import datetime,timezone
        from joblazy.model import CodexModel
        now=[datetime(2026,9,14,23,59,55,tzinfo=timezone.utc).timestamp()]
        requests=[]
        def cli(args,**kwargs):
            if args[1]=='login':return subprocess.CompletedProcess(args,0,'Logged in','')
            requests.append(kwargs['input'])
            write_json(Path(args[args.index('--output-last-message')+1]),FixtureModel().generate('Rank this',{},{}))
            return subprocess.CompletedProcess(args,0,'','')
        def scan(boards,store,checkpoint):
            for name in ('one','two'):store.ingest(job('https://example.test/'+name))
            return {'discovered':2}
        options={'rank_only':True,'batch_size':2,'daily_jobs':100,'daily_model_requests':1,
            'clock':lambda:now[0],'scanner':scan,'browser_factory':lambda:nullcontext(None),
            'model_factory':lambda store:CodexModel(self.data/'model-cache',executable='fixture-codex',
                before_request=lambda:store.reserve_model_request(utc_day(now[0]),1))}
        with patch('joblazy.model.subprocess.run',side_effect=cli):
            worker=Worker(self.data,self.profile,self.boards,**options);first=worker.tick()
            self.assertEqual(first['state'],'daily_limit')
            self.assertEqual(len(requests),1)
            stopped=next(r for r in first['results'] if r['status']=='retryable')
            self.assertTrue(stopped['budget_paused']);self.assertNotIn('provider_paused',stopped)
            self.assertEqual(worker.state.get('provider_failures',0),0)
            self.assertEqual(worker.state.get('next_run',0),0)
            self.assertNotIn(stopped['id'],worker.state['retries'])
            self.assertEqual(Worker(self.data,self.profile,self.boards,**options).tick()['state'],'daily_limit')
            self.assertEqual(len(requests),1)
            now[0]+=10
            restarted=Worker(self.data,self.profile,self.boards,**options);second=restarted.tick()
            self.assertEqual(second['state'],'processed')
            self.assertEqual([(r['id'],r['status']) for r in second['results']],[(stopped['id'],'ranked')])
            self.assertEqual(len(requests),2)
        store=Store(self.data/'jobs.sqlite')
        try:
            for day in ('2026-09-14','2026-09-15'):self.assertEqual(store.daily_usage(day)['model_requests'],1)
        finally:store.close()

    def test_provider_backoff_and_scan_deadline_survive_restart(self):
        calls=[];scans=[]
        class Unavailable:
            def generate(self,*args):calls.append(1);raise ModelUnavailable('Provider unavailable')
        def scan(boards,store,checkpoint):
            scans.append(1)
            for i in range(2):store.ingest(job(f'https://example.test/{i}'))
            return {'discovered':2,'errors':[]}
        options={'model_factory':lambda store:Unavailable(),'scanner':scan,'browser_factory':lambda:nullcontext(None)}
        worker=Worker(self.data,self.profile,self.boards,**options)
        first=worker.tick();self.assertEqual(first['state'],'provider_backoff')
        restarted=Worker(self.data,self.profile,self.boards,**options)
        second=restarted.tick();self.assertEqual(second['state'],'provider_backoff')
        self.assertEqual(len(calls),1);self.assertEqual(len(scans),1)
        store=Store(self.data/'jobs.sqlite')
        try:self.assertEqual(sorted(r['status'] for r in store.list()),['discovered','retryable'])
        finally:store.close()

    def test_daily_limit_during_rank_correction_reuses_failed_initial_response_next_day(self):
        from datetime import datetime,timezone
        from joblazy.model import CodexModel
        now=[datetime(2026,9,14,23,59,55,tzinfo=timezone.utc).timestamp()];requests=[]
        def cli(args,**kwargs):
            if args[1]=='login':return subprocess.CompletedProcess(args,0,'Logged in','')
            requests.append(kwargs['input']);answer=Path(args[args.index('--output-last-message')+1])
            if len(requests)==1:answer.write_text('Fictional malformed response',encoding='utf-8')
            else:write_json(answer,FixtureModel().generate('Rank this',{},{}))
            return subprocess.CompletedProcess(args,0,'','')
        def scan(boards,store,checkpoint):
            store.ingest(job('https://example.test/correction'));return {'discovered':1}
        options={'rank_only':True,'daily_jobs':100,'daily_model_requests':1,'clock':lambda:now[0],
            'scanner':scan,'browser_factory':lambda:nullcontext(None),
            'model_factory':lambda store:CodexModel(self.data/'model-cache',executable='fixture-codex',
                before_request=lambda:store.reserve_model_request(utc_day(now[0]),1))}
        with patch('joblazy.model.subprocess.run',side_effect=cli):
            first=Worker(self.data,self.profile,self.boards,**options).tick()
            self.assertEqual(first['state'],'daily_limit');self.assertEqual(len(requests),1)
            self.assertTrue(first['results'][0]['budget_paused'])
            now[0]+=10
            second=Worker(self.data,self.profile,self.boards,**options).tick()
        self.assertEqual(second['state'],'processed');self.assertEqual(second['results'][0]['status'],'ranked')
        self.assertEqual(len(requests),2)
        self.assertIn('Correct',requests[1])
        self.assertEqual(second['usage']['model_requests'],1)

    def test_repeated_job_failure_becomes_exception_and_other_job_advances(self):
        current=[time.time()]
        class Mixed(FixtureModel):
            def generate(self,task,data,schema):
                if 'Rank this' in task:
                    if data['job']['url'].endswith('/bad'):raise RuntimeError('Transient fixture failure')
                    result=super().generate(task,data,schema)
                    result['fit_category']='poor_fit'
                    return result
                return super().generate(task,data,schema)
        def scan(boards,store,checkpoint):
            for suffix in ('bad','good'):store.ingest(job('https://example.test/'+suffix))
            return {'discovered':2,'errors':[]}
        options={'rank_only':True,'clock':lambda:current[0],'scanner':scan,
            'browser_factory':lambda:nullcontext(None),'model_factory':lambda store:Mixed()}
        def worker():return Worker(self.data,self.profile,self.boards,**options)
        first=worker().tick()
        bad=next(r['id'] for r in first['results'] if r['status']=='retryable')
        write_json(self.data/'applications'/bad/'ranking.json',{'score':99,'reason':'Obsolete failed assessment'})
        current[0]+=121;worker().tick();current[0]+=241
        final=worker().tick()
        store=Store(self.data/'jobs.sqlite')
        try:
            self.assertEqual(sorted(r['status'] for r in store.list()),['not_selected','processing_failed'])
            failed=store.list({'processing_failed'})[0];detail=failed['result']
            self.assertFalse(detail['requires_user_input']);self.assertEqual(detail['attempts'],3)
            self.assertEqual(detail['last_failure']['error'],'RuntimeError')
            self.assertEqual(detail['last_failure']['detail'],'Transient fixture failure')
            self.assertEqual(detail['last_failure']['stage'],'ranking')
            self.assertEqual(final['results'][0]['status'],'processing_failed')
            self.assertFalse(final['results'][0]['requires_user_input'])
            current[0]+=1000
            self.assertEqual(worker().tick()['results'],[])
            html=(self.data/'review.html').read_text(encoding='utf-8')
            self.assertIn('processing failed',html);self.assertIn('Transient fixture failure',html)
            self.assertIn('No candidate answer is required',html)
            self.assertNotIn('Fit score 99/100',html);self.assertNotIn('Obsolete failed assessment',html)
            # The public retry command is the deliberate recovery path after diagnosis.
            retried=subprocess.run([sys.executable,'-m','joblazy','--data',str(self.data),
                'retry',failed['id']],capture_output=True,text=True,timeout=30,check=True)
            self.assertEqual(json.loads(retried.stdout)['status'],'retryable')
            options['model_factory']=lambda s:FixtureModel()
            recovered=worker().tick()
            self.assertEqual(recovered['results'][0]['status'],'ranked')
            self.assertNotIn(failed['id'],worker().state['retries'])
        finally:store.close()

    def test_stop_request_ends_runner_between_cycles(self):
        worker=Worker(self.data,self.profile,self.boards,interval=.01,scanner=lambda *args:{'discovered':0,'errors':[]})
        reports=[]
        def emit(report):reports.append(report);worker.stop_path.write_text('stop',encoding='utf-8')
        result=worker.run(max_cycles=3,emit=emit)
        self.assertEqual(result['cycles'],1);self.assertTrue(result['stop_requested'])
        self.assertEqual(len(reports),1)

    def test_changed_posting_resets_bound_failure_backoff_but_unchanged_scan_does_not(self):
        from joblazy.store import choice_job_hash
        current=time.time();original=job('https://example.test/changed')
        store=Store(self.data/'jobs.sqlite')
        try:
            key=store.ingest(original)
            store.transition(key,'processing_failed',{'reason':'Previous technical failure'})
            write_json(self.data/'worker-state.json',{'retries':{key:{'attempts':3,
                'after':current+1000,'job_hash':choice_job_hash(original)}}})
            changed={**original,'description':original['description']+' Additional coordination responsibilities.'}
            store.ingest(changed)
            self.assertEqual(store.get(key)['status'],'discovered')
        finally:store.close()
        class Failing:
            def generate(self,*args):raise RuntimeError('Changed posting still fails')
        options={'rank_only':True,'clock':lambda:current,'scanner':lambda *a:{'discovered':0},
            'browser_factory':lambda:nullcontext(None),'model_factory':lambda s:Failing()}
        worker=Worker(self.data,self.profile,self.boards,**options)
        result=worker.tick()
        self.assertEqual(result['results'][0]['status'],'retryable')
        self.assertEqual(worker.state['retries'][key]['attempts'],1)
        store=Store(self.data/'jobs.sqlite')
        try:store.ingest(changed)
        finally:store.close()
        self.assertEqual(Worker(self.data,self.profile,self.boards,**options).tick()['results'],[])

    def test_failed_preparation_keeps_original_posting_and_checkpoint_history(self):
        store=Store(self.data/'jobs.sqlite')
        try:
            original=job('https://example.test/preserved');key=store.ingest(original)
            store.transition(key,'materials_ready',{'artifact':{'sha256':'fixture'}})
            store.transition(key,'processing_failed',{'last_failure':{'stage':'application_answers'}})
            before=store.get(key)
            store.ingest({**original,'description':'A different posting now occupies this URL.'})
            self.assertEqual(store.get(key),before)
        finally:store.close()

    def test_queue_contention_resumes_without_provider_backoff(self):
        worker=Worker(self.data,self.profile,self.boards,interval=.01,scanner=lambda *args:{'discovered':0,'errors':[]})
        worker.state['next_run']=0;reports=[]
        lock=run_lock(self.data/'run.lock');lock.__enter__()
        released=False
        def emit(report):
            nonlocal released
            reports.append(report)
            if report['state']=='busy':lock.__exit__(None,None,None);released=True
        try:worker.run(max_cycles=2,emit=emit)
        finally:
            if not released:lock.__exit__(None,None,None)
        self.assertEqual([r['state'] for r in reports],['busy','idle'])
        self.assertEqual(worker.state['next_run'],0)
        self.assertNotIn('provider_failures',worker.state)

    def test_watch_cli_runs_empty_scan_without_model_calls(self):
        result=subprocess.run([sys.executable,'-m','joblazy','--data',str(self.data),'watch',
            '--profile',str(self.profile),'--boards',str(self.boards),'--max-cycles','2','--interval','1'],
            capture_output=True,text=True,timeout=30,check=True)
        self.assertIn('"cycles": 2',result.stdout)
        store=Store(self.data/'jobs.sqlite')
        try:self.assertEqual(store.daily_usage(utc_day())['model_requests'],0)
        finally:store.close()
