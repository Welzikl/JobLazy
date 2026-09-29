import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from joblazy.common import NeedsInput,read_json
from joblazy.pipeline import run_queue
from joblazy.store import Store
from .support import FixtureModel,example_profile,job

class LowScore(FixtureModel):
    def generate(self,*args):
        result=super().generate(*args);result.update(score=65,fit_category='worthwhile_stretch');return result

class JobChoiceTests(unittest.TestCase):
    def test_current_pursuit_precedes_hints_and_freshness_after_restart(self):
        profile=example_profile()
        profile['discovery_preferences']={'max_posting_age_days':45,'title_filter':{'positive':['Operations']}}
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            with closing(Store(base/'jobs.sqlite')) as store:
                ordinary=store.ingest({**job('https://example.test/ordinary'),'postedAt':'2026-09-14'})
                wanted=store.ingest({**job('https://example.test/wanted','Unfamiliar Analyst'),'postedAt':'2020-01-01'})
                store.record_choice(wanted,'pursue','This is the role I want to inspect first')
            with closing(Store(base/'jobs.sqlite')) as store,patch('joblazy.discovery.enrich',side_effect=lambda j,*a,**k:j):
                first=run_queue(store,profile,FixtureModel(),None,base/'applications',limit=1,rank_only=True)
                self.assertEqual(first[0]['id'],wanted)
                self.assertEqual(store.get(ordinary)['status'],'discovered')
                second=run_queue(store,profile,FixtureModel(),None,base/'applications',limit=1,rank_only=True)
                self.assertEqual(second[0]['id'],ordinary)

    def test_stale_or_withdrawn_pursuit_and_posting_flags_cannot_set_priority(self):
        profile=example_profile();profile['discovery_preferences']={'title_filter':{'positive':['Operations']}}
        for change in ('posting_changed','automatic','pass','untrusted_posting_flag'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp,closing(Store(Path(tmp)/'jobs.sqlite')) as store:
                base=Path(tmp);ordinary=store.ingest(job('https://example.test/ordinary'))
                posting={**job('https://example.test/wanted','Unfamiliar Analyst'),'prioritized':True,'user_choice':'pursue'}
                wanted=store.ingest(posting)
                if change!='untrusted_posting_flag':store.record_choice(wanted,'pursue','Initially interested')
                if change=='posting_changed':store.ingest({**posting,'description':posting['description']+' Different responsibilities.'})
                elif change in ('automatic','pass'):store.record_choice(wanted,change,'Use this updated choice')
                with patch('joblazy.discovery.enrich',side_effect=lambda j,*a,**k:j):
                    results=run_queue(store,profile,FixtureModel(),None,base/'applications',limit=1,rank_only=True)
                self.assertEqual(results[0]['id'],ordinary)

    def run_rank(self,store,base,key,model=None,profile=None):
        with patch('joblazy.discovery.enrich',side_effect=lambda job,*a,**k:job):
            return run_queue(store,profile or example_profile(),model or LowScore(),None,base/'applications',
                rank_only=True,only=key)

    def test_user_interest_restores_below_cutoff_role_without_changing_score(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp)
            with closing(Store(base/'jobs.sqlite')) as store:
                key=store.ingest(job('https://example.test/one'))
                self.assertEqual(self.run_rank(store,base,key)[0]['status'],'not_selected')
                store.record_choice(key,'pursue','I want this role')
            with closing(Store(base/'jobs.sqlite')) as store:
                self.assertEqual(self.run_rank(store,base,key)[0]['status'],'ranked')
                self.assertEqual(store.get(key)['result']['ranking']['score'],65)
                self.assertTrue(read_json(base/'applications'/key/'selection.json')['below_cutoff_override'])

    def test_pass_skips_inference_and_automatic_restores_normal_rules(self):
        class NoModel:
            def generate(self,*a):raise AssertionError('User pass should not invoke inference')
        with tempfile.TemporaryDirectory() as tmp,closing(Store(Path(tmp)/'jobs.sqlite')) as store:
            base=Path(tmp);key=store.ingest(job('https://example.test/one'))
            store.record_choice(key,'pass','Not interested')
            self.assertEqual(self.run_rank(store,base,key,NoModel())[0]['status'],'not_selected')
            store.record_choice(key,'automatic','Use normal matching again')
            store.transition(key,'discovered',expected={'not_selected'})
            self.assertEqual(self.run_rank(store,base,key)[0]['status'],'not_selected')

    def test_changed_posting_does_not_inherit_numeric_override(self):
        with tempfile.TemporaryDirectory() as tmp,closing(Store(Path(tmp)/'jobs.sqlite')) as store:
            base=Path(tmp);posting=job('https://example.test/one');key=store.ingest(posting)
            store.record_choice(key,'pursue','I want this role')
            store.ingest({**posting,'description':posting['description']+' Additional duties.'})
            self.assertFalse(store.choice(key)['current'])
            self.assertEqual(self.run_rank(store,base,key)[0]['status'],'not_selected')

    def test_interest_does_not_bypass_experience_policy_or_loop_rejected_role(self):
        profile=example_profile();profile['targeting']={'config':{'target_roles':{'seniority':{'mode':'required_experience_range','maximum_required_years':5}}}}
        quote='Requires 6–11 years of experience.'
        class TooSenior(LowScore):
            def generate(self,*args):
                if args[0].startswith('Check only'):
                    return {'decision':'exclude','minimum_required_years':6,'requirement_quote':quote,
                        'reason':'Required minimum exceeds five years.','uncertainties':[]}
                result=super().generate(*args)
                result['requirements'].append({'requirement':'Experience','job_quote':quote,'kind':'required_experience',
                    'status':'unverified','candidate_source_ids':[],'explanation':'Not established'})
                return result
        with tempfile.TemporaryDirectory() as tmp,closing(Store(Path(tmp)/'jobs.sqlite')) as store:
            base=Path(tmp);posting=job('https://example.test/one');posting['description']+=' '+quote
            key=store.ingest(posting);store.record_choice(key,'pursue','Interested in the work')
            self.assertEqual(self.run_rank(store,base,key,TooSenior(),profile)[0]['status'],'not_selected')
            self.assertFalse(read_json(base/'applications'/key/'selection.json')['below_cutoff_override'])
            with self.assertRaises(NeedsInput):self.run_rank(store,base,key,TooSenior(),profile)

    def test_choice_never_releases_manual_or_submission_ownership(self):
        for status in ('manual_review','submitted','submission_unknown','submitting'):
            with self.subTest(status=status),tempfile.TemporaryDirectory() as tmp,closing(Store(Path(tmp)/'jobs.sqlite')) as store:
                base=Path(tmp);key=store.ingest(job('https://example.test/one'));store.transition(key,status)
                store.record_choice(key,'pursue','Interested')
                with self.assertRaises(NeedsInput):self.run_rank(store,base,key)
                self.assertIn(store.get(key)['status'],{status,'submission_unknown'})
