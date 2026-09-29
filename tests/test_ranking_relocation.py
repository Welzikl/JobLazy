import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from joblazy.materials import rank,AssessmentFailed,title_relocation_clauses
from joblazy.pipeline import run_queue
from joblazy.store import Store
from joblazy.review import render_review
from .support import FixtureModel,example_profile,job


class RelocationRankingTests(unittest.TestCase):
    def test_only_bounded_literal_relocation_clauses_are_exposed(self):
        for title,expected in [
            ('Operations (Relocation to Singapore)',['Relocation to Singapore']),
            ('Engineering (Relocate to Singapore)',['Relocate to Singapore']),
            ('Operations — Relocate to New York',['Relocate to New York']),
            ('Relocation to London',['Relocation to London']),
            ('Relocation Manager',[]),
            ('Operations (optional relocation to Singapore)',[]),
            ('Operations (no relocation to Singapore)',[]),
            ('Operations (Relocation to Singapore; 8 years required)',[])]:
            with self.subTest(title=title):self.assertEqual(title_relocation_clauses({'title':title}),expected)

    def profile(self):
        profile=example_profile()
        profile['targeting']={'career_preferences':'Current search scope: London-based roles only.'}
        return profile

    def model(self,quote,kind='hard_constraint',status='not_met'):
        class Model(FixtureModel):
            def generate(self,task,data,schema):
                result=super().generate(task,data,schema)
                result['requirements'].append({'requirement':'Relocation placement',
                    'job_quote':quote,'kind':kind,'status':status,
                    'candidate_source_ids':['preference.career_rules'],
                    'explanation':'Fictional location policy comparison.'})
                return result
        return Model()

    def test_explicit_title_relocation_is_citable_and_blocks_even_high_score(self):
        posting=job('https://example.test/relocation','Operations Associate (Relocation to Singapore)')
        posting['location']='London, United Kingdom | Singapore'
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            key=store.ingest(posting)
            with patch('joblazy.discovery.enrich',side_effect=lambda p,*a,**k:p):
                result=run_queue(store,self.profile(),self.model('Relocation to Singapore'),None,
                    Path(temp)/'applications',rank_only=True,only=key)
            self.assertEqual(result[0]['status'],'not_selected')
            assessment=store.get(key)['result']
            self.assertFalse(assessment['eligible'])
            self.assertEqual(assessment['eligibility_status'],'blocked')
            self.assertEqual(assessment['requirements'][-1]['job_quote_source'],'title')
            rendered=render_review(store,Path(temp),profile=self.profile())
            self.assertIn('source: job title',Path(rendered['path']).read_text(encoding='utf-8'))

    def test_title_exception_does_not_admit_seniority_years_or_other_qualifications(self):
        for title,quote,kind in [
            ('Senior Manager (Relocation to Singapore)','Senior Manager','hard_constraint'),
            ('8 years experience (Relocation to Singapore)','8 years experience','required_experience'),
            ('Operations (Relocation to Singapore)','Relocation to Singapore','required_experience'),
            ('Operations (Relocation to Singapore)','Relocation to Berlin','hard_constraint')]:
            with self.subTest(title=title,quote=quote,kind=kind):
                with self.assertRaises(AssessmentFailed):
                    rank(job('https://example.test/role',title),self.profile(),self.model(quote,kind))

    def test_optional_relocation_in_description_is_not_forced_to_fail_policy(self):
        posting=job('https://example.test/optional','Operations Associate')
        posting['description']+=' London placement is available; relocation to Singapore is optional.'
        result=rank(posting,self.profile(),self.model('London placement is available; relocation to Singapore is optional.',status='met'))
        self.assertTrue(result['eligible']);self.assertEqual(result['eligibility_status'],'no_known_conflict')
        self.assertEqual(result['requirements'][-1]['job_quote_source'],'description')
