import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch, Mock
from joblazy.common import write_json,InvalidModelOutput,ModelUnavailable
from joblazy.pipeline import run_queue
from joblazy.store import Store
from joblazy.review import render_review
from .support import example_profile,job,FixtureModel


class ScreenTests(unittest.TestCase):
    def profile(self):
        profile=example_profile()
        profile['targeting']={'config':{'target_roles':{'seniority':{'mode':'required_experience_range','maximum_required_years':5}}}}
        return profile

    def test_company_history_and_customer_ages_bypass_only_the_optional_screen(self):
        from joblazy.experience_screen import screen_experience
        for text in ('Our product has grown in the last 10 years. Accounts for 16-17 year olds.',
                     'Our company was founded eight years ago.',
                     'The product is ten years old.',
                     'We expanded over the past eight years.'):
            with self.subTest(text=text):
                posting=job('https://example.test/history');posting['description']+=' '+text
                model=Mock()
                self.assertIsNone(screen_experience(posting,self.profile(),model,None))
                model.generate.assert_not_called()
                calls=[]
                class FullModel(FixtureModel):
                    def generate(self,task,data,schema):
                        calls.append(task)
                        self_test.assertIn(text,data['job']['description'])
                        return super().generate(task,data,schema)
                self_test=self
                with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
                    store.ingest(posting)
                    with patch('joblazy.discovery.enrich',side_effect=lambda j,*a,**k:j):
                        results=run_queue(store,self.profile(),FullModel(),None,temp,rank_only=True)
                    self.assertEqual(results[0]['status'],'ranked')
                    self.assertEqual(len(calls),1);self.assertTrue(calls[0].startswith('Rank this'))

    def test_unrelated_ages_do_not_hide_a_separate_required_duration(self):
        from joblazy.experience_screen import screen_experience
        quote='Required: six years of operations experience gained in the past ten years.'
        posting=job('https://example.test/required');posting['description']='Accounts for 16-17 year olds. '+quote
        model=Mock();model.generate.return_value={'decision':'defer','minimum_required_years':None,
            'requirement_quote':None,'reason':'Review complete requirement.','uncertainties':[]}
        self.assertIsNone(screen_experience(posting,self.profile(),model,None))
        model.generate.assert_called_once()
        self.assertEqual(model.generate.call_args.args[1]['job']['description'],posting['description'])

    def test_exclusion_skips_full_ranking_and_hides_historical_score(self):
        quote='Required: at least eight years of experience in operations.'
        class Model:
            def generate(self,task,data,schema):
                self_test.assertTrue(task.startswith('Check only'))
                self_test.assertNotIn('resume',data)
                return {'decision':'exclude','minimum_required_years':8,'requirement_quote':quote,'reason':'Mandatory eight-year minimum exceeds five.','uncertainties':[]}
        self_test=self
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            data=Path(temp);posting=job('https://example.test/high');posting['description']+=' '+quote
            key=store.ingest(posting);directory=data/'applications'/key
            write_json(directory/'ranking.json',{'score':99,'reason':'Historical score'})
            with patch('joblazy.discovery.enrich',side_effect=lambda j,*a,**k:j):
                results=run_queue(store,self.profile(),Model(),None,data/'applications',rank_only=True)
            self.assertEqual(results[0]['status'],'not_selected')
            result=store.get(key)['result'];self.assertEqual(result['assessment_stage'],'experience_screen')
            self.assertNotIn('score',result);self.assertFalse(result['eligible'])
            render_review(store,data)
            review=(data/'review.html').read_text(encoding='utf-8')
            self.assertIn('Eligibility screen',review);self.assertNotIn('Fit score 99',review)
            self.assertFalse((directory/'cv.pdf').exists())
            from joblazy.evaluation import evaluate
            from joblazy.store import choice_job_hash
            case={'id':key,'job':posting,'split':'development','category':'hard_constraint',
                'judgment':{'worthwhile':True,'job_hash':choice_job_hash(posting),
                    'source':{'kind':'user','quote':'Fictional test interest','recorded_at':'2026-09-14','basis':'fixture'}}}
            dataset={'version':1,'example_only':True,'cases':[case]}
            predictions={'version':1,'predictions':[{'id':key,'job_hash':choice_job_hash(posting),
                    'profile_hash':result['candidate_profile_hash'],'assessment':result}]}
            report=evaluate(dataset,predictions)
            self.assertEqual(report['splits']['development']['assessed'],1)
            self.assertEqual(report['splits']['development']['worthwhile_not_recommended_ids'],[key])
            self.assertEqual(report['splits']['development']['eligibility_screened'],1)
            result['score']=0
            invalid=evaluate(dataset,predictions)
            self.assertEqual(invalid['splits']['development']['missing_assessment_ids'],[key])

    def test_provider_failure_remains_retryable_and_stops_batch(self):
        calls=[]
        class Model:
            def generate(self,*args):calls.append(1);raise ModelUnavailable('Provider unavailable')
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            posting=job('https://example.test/high');posting['description']+=' Required: eight years of experience.'
            store.ingest(posting);store.ingest({**posting,'url':'https://example.test/second'})
            with patch('joblazy.discovery.enrich',side_effect=lambda j,*a,**k:j):
                results=run_queue(store,self.profile(),Model(),None,temp,rank_only=True)
            self.assertEqual(len(calls),1);self.assertTrue(results[0]['provider_paused'])
            self.assertEqual(sorted(r['status'] for r in store.list()),['discovered','retryable'])

    def test_deferred_and_invalid_screen_use_full_ranking_instead_of_rejecting(self):
        for response in ({'decision':'defer','minimum_required_years':None,'requirement_quote':None,'reason':'Alternative routes.','uncertainties':[]},
                         {'decision':'exclude','minimum_required_years':8,'requirement_quote':'Invented quote','reason':'Invalid','uncertainties':[]},
                         InvalidModelOutput('Invalid structured output')):
            with self.subTest(response=response),tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
                calls=[]
                class Model(FixtureModel):
                    def generate(self,task,data,schema):
                        calls.append(task)
                        if task.startswith('Check only'):
                            if isinstance(response,Exception):raise response
                            return response
                        return super().generate(task,data,schema)
                posting=job('https://example.test/alternative');posting['description']+=' Preferred: eight years of experience.'
                store.ingest(posting)
                with patch('joblazy.discovery.enrich',side_effect=lambda j,*a,**k:j):
                    results=run_queue(store,self.profile(),Model(),None,temp,rank_only=True)
                self.assertEqual(results[0]['status'],'ranked');self.assertEqual(len(calls),2)

    def test_without_high_duration_no_screen_request(self):
        calls=[]
        class Model(FixtureModel):
            def generate(self,task,data,schema):calls.append(task);return super().generate(task,data,schema)
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            posting=job('https://example.test/range');posting['description']+=' Required: 3-6 years of experience.'
            store.ingest(posting)
            with patch('joblazy.discovery.enrich',side_effect=lambda j,*a,**k:j):
                results=run_queue(store,self.profile(),Model(),None,temp,rank_only=True)
            self.assertEqual(results[0]['status'],'ranked');self.assertEqual(len(calls),1)
            self.assertTrue(calls[0].startswith('Rank this'))
