import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from joblazy.common import read_json,write_json,ModelUnavailable,InvalidModelOutput
from joblazy.materials import rank,AssessmentFailed
from joblazy.model import CodexModel
from joblazy.pipeline import run_queue
from joblazy.store import Store
from joblazy.review import render_review
from .support import FixtureModel,example_profile,job

class RecoveryTests(unittest.TestCase):
    def test_structure_and_source_failures_share_one_correction_budget(self):
        calls=[]
        class Mixed(FixtureModel):
            def generate(self,task,data,schema):
                calls.append(data)
                if len(calls)==1:raise InvalidModelOutput('Fictional malformed response')
                result=super().generate(task,data,schema)
                if len(calls)==2:result['evidence'][0]['quote']='Invented quotation'
                return result
        with tempfile.TemporaryDirectory() as tmp,closing(Store(Path(tmp)/'jobs.sqlite')) as store:
            keys=[store.ingest(job('https://example.test/'+s)) for s in ('one','two')]
            with patch('joblazy.discovery.enrich',side_effect=lambda job,*a,**k:job):
                results=run_queue(store,example_profile(),Mixed(),None,Path(tmp)/'applications',rank_only=True)
                self.assertEqual([r['status'] for r in results],['assessment_failed','ranked'])
                self.assertFalse(results[0]['requires_user_input']);self.assertEqual(len(calls),3)
                self.assertEqual(run_queue(store,example_profile(),Mixed(),None,Path(tmp)/'applications',rank_only=True),[])

    def test_drafting_contract_failure_is_technical_and_does_not_loop(self):
        class BrokenDraft(FixtureModel):
            def generate(self,task,data,schema):
                if 'Tailor the CV' in task:raise InvalidModelOutput('Fictional malformed CV response')
                return super().generate(task,data,schema)
        with tempfile.TemporaryDirectory() as tmp,closing(Store(Path(tmp)/'jobs.sqlite')) as store:
            key=store.ingest(job('https://example.test/draft'))
            with patch('joblazy.discovery.enrich',side_effect=lambda job,*a,**k:job):
                result=run_queue(store,example_profile(),BrokenDraft(),None,Path(tmp)/'applications',fixture_origin='http://fictional.test')
                self.assertEqual(result[0]['status'],'model_failed');self.assertFalse(result[0]['requires_user_input'])
                self.assertEqual(run_queue(store,example_profile(),BrokenDraft(),None,Path(tmp)/'applications',fixture_origin='http://fictional.test'),[])
            original=store.get(key)['data'];store.ingest(original)
            self.assertEqual(store.get(key)['status'],'model_failed')
            store.ingest({**original,'description':original['description']+' Changed duties.'})
            self.assertEqual(store.get(key)['status'],'discovered')

    def test_malformed_response_recovers_once_and_retains_failed_usage(self):
        requests=[]
        def cli(args,**kwargs):
            if args[1]=='login':return subprocess.CompletedProcess(args,0,'Logged in','')
            requests.append(kwargs['input'])
            answer=Path(args[args.index('--output-last-message')+1])
            if len(requests)==1:answer.write_text('not JSON: fictional rejected output',encoding='utf-8')
            else:write_json(answer,FixtureModel().generate('Rank this',{},{}))
            return subprocess.CompletedProcess(args,0,json.dumps({'type':'turn.completed','usage':{'input_tokens':123,'output_tokens':4}}),'')
        with tempfile.TemporaryDirectory() as tmp,patch('joblazy.model.subprocess.run',side_effect=cli):
            base=Path(tmp);model=CodexModel(base/'cache',executable='fictional-codex')
            result=rank(job('https://example.test/malformed'),example_profile(),model,directory=base)
            self.assertEqual(result['validation']['status'],'corrected');self.assertEqual(len(requests),2)
            failures=list((base/'cache/failures').glob('*.json'));self.assertEqual(len(failures),1)
            evidence=read_json(failures[0]);self.assertEqual(evidence['usage']['input_tokens'],123)
            self.assertEqual(evidence['response_text'],'not JSON: fictional rejected output')
            self.assertEqual(read_json(base/'ranking-validation.json')['attempts'][0]['failure_kind'],'model_output')
            self.assertEqual(rank(job('https://example.test/malformed'),example_profile(),model,directory=base),result)
            self.assertEqual(len(requests),2)

    def test_correction_cache_is_reused_without_overwriting_rejected_response(self):
        requests=[]
        def cli(args,**kwargs):
            if args[1]=='login':return subprocess.CompletedProcess(args,0,'Logged in','')
            prompt=kwargs['input'];task=prompt.split('TASK: ',1)[1].split('\nINPUT JSON:',1)[0]
            payload=json.loads(prompt.split('\nINPUT JSON:\n',1)[1])
            schema=read_json(args[args.index('--output-schema')+1]);requests.append(task)
            response=FixtureModel().generate(task,payload,schema)
            if len(requests)==1:response['evidence'][0]['quote']='Invented source'
            write_json(args[args.index('--output-last-message')+1],response)
            return subprocess.CompletedProcess(args,0,'','')
        with tempfile.TemporaryDirectory() as tmp,patch('joblazy.model.subprocess.run',side_effect=cli):
            base=Path(tmp);posting=job('https://example.test/job');profile=example_profile()
            first=rank(posting,profile,CodexModel(base/'cache',executable='fictional-codex'))
            restarted=rank(posting,profile,CodexModel(base/'cache',executable='fictional-codex'))
            self.assertEqual(len(requests),2);self.assertEqual(first,restarted)
            cached=[read_json(p) for p in (base/'cache').glob('*.json') if not p.name.endswith('.meta.json')]
            self.assertEqual(len(cached),2)
            self.assertEqual(sum(r['evidence'][0]['quote']=='Invented source' for r in cached),1)

    def test_title_is_valid_rubric_evidence_but_not_an_experience_requirement(self):
        posting=job('https://example.test/job','Senior Engineer <script>')
        class TitleModel(FixtureModel):
            def generate(self,*args):
                result=super().generate(*args)
                result['dimensions']['career_direction'].update(job_quotes=[posting['title']])
                return result
        result=rank(posting,example_profile(),TitleModel())
        self.assertEqual(result['validation']['correction_attempts'],0)
        self.assertEqual(result['dimensions']['career_direction']['job_quote_sources'],[{'field':'title','quote':posting['title']}])
        class TitleRequirement(TitleModel):
            def generate(self,*args):
                result=super().generate(*args);result['requirements'][0]['job_quote']=posting['title'];return result
        with self.assertRaises(AssessmentFailed):rank(posting,example_profile(),TitleRequirement())
        with tempfile.TemporaryDirectory() as tmp,closing(Store(Path(tmp)/'jobs.sqlite')) as store:
            key=store.ingest(posting);store.transition(key,'ranked',{'ranking':result})
            rendered=Path(render_review(store,Path(tmp))['path']).read_text(encoding='utf-8')
            self.assertIn('title: Senior Engineer &lt;script&gt;',rendered)
            self.assertNotIn('<script>',rendered)

    def test_one_correction_preserves_original_and_revalidates_all_evidence(self):
        calls=[];original=None
        class Corrected(FixtureModel):
            def generate(self,task,data,schema):
                nonlocal original
                calls.append(data);result=super().generate(task,data,schema)
                if len(calls)==1:
                    result['dimensions']['cv_fit']['job_quotes']=['Invented posting sentence']
                    original=copy.deepcopy(result)
                return result
        with tempfile.TemporaryDirectory() as tmp:
            result=rank(job('https://example.test/job'),example_profile(),Corrected(),directory=tmp)
            self.assertEqual(len(calls),2);self.assertEqual(result['validation']['status'],'corrected')
            self.assertIn('original_input',calls[1]);self.assertEqual(calls[1]['rejected_assessment'],original)
            audit=read_json(Path(tmp)/'ranking-validation.json')
            self.assertEqual(audit['attempts'][0]['response'],original)
            self.assertEqual(audit['correction_attempts'],1)

    def test_exhausted_correction_is_not_a_user_question_or_a_queue_block(self):
        calls=[]
        class Broken(FixtureModel):
            def generate(self,task,data,schema):
                calls.append(data);result=super().generate(task,data,schema)
                if len(calls)<=2:result['evidence'][0]['quote']='Invented evidence'
                return result
        with tempfile.TemporaryDirectory() as tmp,closing(Store(Path(tmp)/'jobs.sqlite')) as store:
            base=Path(tmp);keys=[store.ingest(job('https://example.test/'+name)) for name in ('one','two')]
            with patch('joblazy.discovery.enrich',side_effect=lambda job,*a,**k:job):
                results=run_queue(store,example_profile(),Broken(),None,base/'applications',rank_only=True)
                self.assertEqual([r['status'] for r in results],['assessment_failed','ranked'])
                self.assertFalse(results[0]['requires_user_input']);self.assertEqual(len(calls),3)
                self.assertEqual(run_queue(store,example_profile(),Broken(),None,base/'applications',rank_only=True),[])
            failed=results[0]['id'];unchanged=store.get(failed)['data']
            store.ingest(unchanged);self.assertEqual(store.get(failed)['status'],'assessment_failed')
            write_json(base/'applications'/failed/'ranking.json',{'score':99,'reason':'Stale successful assessment'})
            rendered=Path(render_review(store,base)['path']).read_text(encoding='utf-8')
            self.assertNotIn('Stale successful assessment',rendered)
            store.ingest({**unchanged,'description':unchanged['description']+' Changed requirement.'})
            self.assertEqual(store.get(failed)['status'],'discovered')

    def test_request_limit_during_correction_keeps_provider_resume_behavior(self):
        calls=[]
        class Limited(FixtureModel):
            def generate(self,*args):
                calls.append(1)
                if len(calls)>1:raise ModelUnavailable('Daily request cap reached')
                result=super().generate(*args);result['evidence'][0]['quote']='Invented evidence';return result
        with tempfile.TemporaryDirectory() as tmp,closing(Store(Path(tmp)/'jobs.sqlite')) as store:
            base=Path(tmp);key=store.ingest(job('https://example.test/one'))
            with patch('joblazy.discovery.enrich',side_effect=lambda job,*a,**k:job):
                results=run_queue(store,example_profile(),Limited(),None,base/'applications',rank_only=True)
            self.assertEqual(results[0]['status'],'retryable');self.assertTrue(results[0]['provider_paused'])
            self.assertEqual(read_json(base/'applications'/key/'ranking-validation.json')['status'],'correction_pending')
