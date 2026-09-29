import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from joblazy.common import InvalidModelOutput, ModelUnavailable, read_json, write_json
from joblazy.materials import obj
from joblazy.model import CodexModel
from joblazy.usage import ModelCall, model_context, summarize


class UsageTests(unittest.TestCase):
    def test_killed_process_leaves_unknown_time_and_restart_creates_a_separate_attempt(self):
        from contextlib import closing
        from joblazy.pipeline import run_queue
        from joblazy.store import Store
        from .support import example_profile,FixtureModel
        code='''
import sys,os
from pathlib import Path
from joblazy.store import Store
from joblazy.pipeline import run_queue
from tests.support import example_profile,job,FixtureModel
base=Path(sys.argv[1]);store=Store(base/'jobs.sqlite')
store.ingest(job('http://fictional.test/killed'))
class Killed(FixtureModel):
    def generate(self,*args):os._exit(7)
run_queue(store,example_profile(),Killed(),None,base/'applications',rank_only=True,fixture_origin='http://fictional.test')
'''
        with tempfile.TemporaryDirectory() as temp:
            result=subprocess.run([sys.executable,'-c',code,temp],capture_output=True,text=True)
            self.assertEqual(result.returncode,7,result.stderr)
            report=summarize(Path(temp)/'model-cache')['workflow']
            self.assertEqual(report['incomplete_attempts'],1)
            self.assertIsNone(report['completed_attempt_seconds'])
            with closing(Store(Path(temp)/'jobs.sqlite')) as store:
                run_queue(store,example_profile(),FixtureModel(),None,Path(temp)/'applications',rank_only=True,fixture_origin='http://fictional.test')
            report=summarize(Path(temp)/'model-cache')['workflow']
            self.assertEqual((report['attempts'],report['completed_attempts'],report['incomplete_attempts']),(2,1,1))
            self.assertEqual(report['outcomes'],{'ranked':1})
            self.assertTrue(report['by_job_mode'][0]['fixture_mode'])

    def test_workflow_report_does_not_invent_history_or_accept_invalid_durations(self):
        from joblazy.workflow_usage import ProcessingAttempt
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);report=summarize(base/'model-cache')['workflow']
            self.assertEqual(report['attempts'],0)
            self.assertIsNone(report['completed_attempt_seconds'])
            self.assertIsNone(report['recorded_operator_actions']['by_kind'])
            self.assertFalse((base/'jobs.sqlite').exists())
            attempt=ProcessingAttempt(base/'applications'/'example','example','prepare',True)
            attempt.finish('prepared')
            record=read_json(attempt.path);record['elapsed_seconds']=-2;write_json(attempt.path,record)
            report=summarize(base/'model-cache')['workflow']
            self.assertEqual(report['unreadable_records'],1)
            self.assertEqual(report['completed_attempts'],0)

    def test_whole_job_timing_separates_modes_and_recorded_operator_actions(self):
        from contextlib import closing
        from joblazy.pipeline import run_queue
        from joblazy.store import Store
        from .support import example_profile,job,FixtureModel
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            key=store.ingest(job('https://example.test/timing'))
            store.record_choice(key,'pursue','Explicit fictional choice')
            with patch('joblazy.discovery.enrich',side_effect=lambda p,*a,**k:p):
                run_queue(store,example_profile(),FixtureModel(),None,Path(temp)/'applications',rank_only=True)
            report=summarize(Path(temp)/'model-cache',job_id=key)
            workflow=report['workflow']
            self.assertEqual(workflow['attempts'],1)
            self.assertEqual(workflow['completed_attempts'],1)
            self.assertEqual(workflow['by_job_mode'][0]['mode'],'rank_only')
            self.assertEqual(workflow['by_job_mode'][0]['outcomes'],{'ranked':1})
            self.assertGreaterEqual(workflow['completed_attempt_seconds'],0)
            self.assertEqual(workflow['recorded_operator_actions']['by_kind'],{'job_choice':1})
            self.assertFalse(workflow['recorded_operator_actions']['all_interventions_measured'])
            self.assertEqual(report['totals']['inference_attempts'],0)
            self.assertEqual(summarize(Path(temp)/'model-cache',job_id='absent')['workflow']['attempts'],0)
            store.transition(key,'needs_input',{'reason':'Fictional question'})
            store.transition(key,'retryable',{'reason':'Operator supplied a scoped answer','question':'Fictional question'})
            store.transition(key,'manual_review')
            store.reconcile(key,'not-submitted','Fictional operator report')
            events=list(store.db.execute('SELECT * FROM events'))
            updated=summarize(Path(temp)/'model-cache',job_id=key)['workflow']
            self.assertEqual(updated['recorded_operator_actions']['by_kind'],{'job_choice':1,'scoped_answer':1,'outcome_report':1})
            self.assertEqual(updated['outcomes'],{'ranked':1})
            self.assertEqual(list(store.db.execute('SELECT * FROM events')),events)

    def test_cache_replay_records_zero_new_tokens_instead_of_historical_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            model=CodexModel(temp,executable='fictional-codex')
            def cli(args,**kwargs):
                if args[1]=='login':return subprocess.CompletedProcess(args,0,'Signed in','')
                write_json(args[args.index('--output-last-message')+1],{'value':'ok'})
                return subprocess.CompletedProcess(args,0,json.dumps({'type':'turn.completed',
                    'usage':{'input_tokens':100,'cached_input_tokens':20,'output_tokens':12}}),'')
            with patch('joblazy.model.subprocess.run',side_effect=cli) as run:
                for _ in range(2):model.generate('private task',{'private':'facts'},obj({'value':{'type':'string'}}))
                self.assertEqual(run.call_count,2)  # One login check and one inference.
            records=[read_json(p) for p in Path(temp).glob('calls/*/*.json')]
            self.assertEqual(len(records),2)
            fresh=next(r for r in records if r['cache']=='miss')
            cached=next(r for r in records if r['cache']=='hit')
            self.assertTrue(fresh['inference_attempted']);self.assertEqual(fresh['usage']['input_tokens'],100)
            self.assertFalse(cached['inference_attempted']);self.assertIsNone(cached['usage'])
            self.assertNotIn('private',json.dumps(records))
            report=summarize(temp)
            self.assertEqual(report['totals']['calls'],2)
            self.assertEqual(report['totals']['tokens']['input_tokens'],{'reported':100,'unknown_attempts':0})
            self.assertEqual(report['totals']['tokens']['reasoning_output_tokens'],{'reported':0,'unknown_attempts':1})

    def test_failed_output_and_cached_failure_are_not_charged_twice(self):
        with tempfile.TemporaryDirectory() as temp:
            def cli(args,**kwargs):
                if args[1]=='login':return subprocess.CompletedProcess(args,0,'Signed in','')
                Path(args[args.index('--output-last-message')+1]).write_text('malformed')
                return subprocess.CompletedProcess(args,0,json.dumps({'type':'turn.completed','usage':{'output_tokens':7}}),'')
            model=CodexModel(temp,executable='fictional-codex')
            with patch('joblazy.model.subprocess.run',side_effect=cli) as run:
                for _ in range(2):
                    with self.assertRaises(InvalidModelOutput):model.generate('fixture',{},obj({'value':{'type':'string'}}))
                self.assertEqual(run.call_count,2)
            report=summarize(temp)['totals']
            self.assertEqual((report['failed_calls'],report['cached_failures'],report['inference_attempts']),(2,1,1))
            self.assertEqual(report['tokens']['output_tokens'],{'reported':7,'unknown_attempts':0})

    def test_timeout_budget_and_auth_are_distinguished_from_confirmed_zero_usage(self):
        for failure in ('timeout','budget','auth','process'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as temp:
                def cli(args,**kwargs):
                    if args[1]=='login':return subprocess.CompletedProcess(args,1 if failure=='auth' else 0,'','')
                    if failure=='timeout':raise subprocess.TimeoutExpired(args,1)
                    return subprocess.CompletedProcess(args,1,json.dumps({'type':'turn.completed','usage':{'output_tokens':4}}),'private error')
                def reserve():
                    if failure=='budget':raise ModelUnavailable('Daily limit')
                model=CodexModel(temp,executable='fictional-codex',before_request=reserve)
                with patch('joblazy.model.subprocess.run',side_effect=cli),self.assertRaises(ModelUnavailable):
                    model.generate('fixture',{},obj({'value':{'type':'string'}}))
                report=summarize(temp)['totals']
                self.assertEqual(report['inference_attempts'],int(failure in ('timeout','process')))
                self.assertEqual(report['tokens']['output_tokens'],{'reported':4 if failure=='process' else 0,
                    'unknown_attempts':int(failure=='timeout')})

    def test_killed_inference_leaves_durable_incomplete_unknown_usage(self):
        with tempfile.TemporaryDirectory() as temp:
            script='''
import os,sys,subprocess
from unittest.mock import patch
from joblazy.model import CodexModel
def cli(args,**kwargs):
    if args[1]=='login':return subprocess.CompletedProcess(args,0,'','')
    os._exit(17)
with patch('joblazy.model.subprocess.run',side_effect=cli):
    CodexModel(sys.argv[1],executable='fictional-codex').generate('fixture',{}, {})
'''
            child=subprocess.run([sys.executable,'-c',script,temp],capture_output=True,text=True,timeout=15)
            self.assertEqual(child.returncode,17,child.stderr)
            report=summarize(temp)['totals']
            self.assertEqual(report['incomplete_calls'],1);self.assertEqual(report['inference_attempts'],1)
            self.assertEqual(report['tokens']['input_tokens'],{'reported':0,'unknown_attempts':1})

    def test_day_job_filters_and_cli_are_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            cache=Path(temp)/'model-cache'
            token=model_context.set({'job_id':'fictional-a','stage':'ranking'})
            try:call=ModelCall(cache,'fictional-model');call.update(cache='hit');call.finish('complete')
            finally:model_context.reset(token)
            write_json(cache/'calls'/'2000-01-01'/'old.json',read_json(call.path))
            (call.path.parent/'broken.json').write_text('{')
            before={str(p):p.read_bytes() for p in cache.rglob('*.json')}
            result=subprocess.run([sys.executable,'-m','joblazy','--data',temp,'usage','--job','fictional-a'],capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            report=json.loads(result.stdout);self.assertEqual(report['totals']['cache_hits'],1)
            self.assertEqual(report['unreadable_records'],1)
            self.assertEqual(summarize(cache,job_id='fictional-b')['totals']['calls'],0)
            self.assertEqual(summarize(cache,day='2000-01-01')['totals']['calls'],1)
            self.assertEqual(before,{str(p):p.read_bytes() for p in cache.rglob('*.json')})
            self.assertFalse((Path(temp)/'jobs.sqlite').exists())
            with self.assertRaises(ValueError):summarize(cache,day='../elsewhere')

    def test_queue_attributes_correction_calls_and_restores_context_after_failure(self):
        from contextlib import closing
        from joblazy.pipeline import run_queue
        from joblazy.store import Store
        from .support import example_profile,job,FixtureModel
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            key=store.ingest(job('https://example.test/usage'))
            calls=[]
            def cli(args,**kwargs):
                if args[1]=='login':return subprocess.CompletedProcess(args,0,'','')
                calls.append(1)
                if len(calls)==1:Path(args[args.index('--output-last-message')+1]).write_text('malformed')
                else:write_json(args[args.index('--output-last-message')+1],FixtureModel().generate('Rank this',{},{}))
                return subprocess.CompletedProcess(args,0,json.dumps({'type':'turn.completed','usage':{'input_tokens':10,'output_tokens':1}}),'')
            model=CodexModel(Path(temp)/'model-cache',executable='fictional-codex')
            with patch('joblazy.model.subprocess.run',side_effect=cli),patch('joblazy.discovery.enrich',side_effect=lambda job,*a,**k:job):
                result=run_queue(store,example_profile(),model,None,Path(temp)/'applications',rank_only=True)
            self.assertEqual(result[0]['status'],'ranked');self.assertIsNone(model_context.get())
            report=summarize(model.cache,job_id=key)
            self.assertEqual(report['totals']['inference_attempts'],2)
            self.assertEqual(report['totals']['tokens']['input_tokens']['reported'],20)
            self.assertEqual(report['by_job_stage'][0]['stage'],'ranking')


if __name__=='__main__':unittest.main()
