import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from joblazy.common import NeedsInput
from joblazy.materials import rank,source_facts
from joblazy.pipeline import run_queue
from joblazy.review import render_review
from joblazy.store import Store
from .support import FixtureModel,example_profile,job


class RankingTests(unittest.TestCase):
    def model(self,change):
        class Modified(FixtureModel):
            def generate(self,task,data,schema):
                result=super().generate(task,data,schema)
                if 'Rank this' in task:change(result)
                return result
        return Modified()

    def test_unverified_hard_constraint_is_uncertain_not_proven_eligible(self):
        def change(result):
            result['fit_category']='worthwhile_stretch'
            result['requirements'][0].update(kind='hard_constraint',status='unverified',candidate_source_ids=[])
        result=rank(job('https://example.test/one'),example_profile(),self.model(change))
        self.assertEqual(result['assessment_version'],9);self.assertTrue(result['eligible'])
        self.assertEqual(result['eligibility_status'],'uncertain')
        self.assertEqual(result['candidate_facts']['experience.0.0'],example_profile()['resume']['experience'][0]['bullets'][0])

    def test_unsupported_requirement_judgments_or_invented_quotes_are_rejected(self):
        def blocked(result):result['requirements'][0].update(kind='hard_constraint',status='not_met',candidate_source_ids=[])
        def unsupported(result):result['requirements'][0]['candidate_source_ids']=[]
        def invented_quote(result):result['requirements'][0]['job_quote']='Invented required qualification'
        for change in (blocked,unsupported,invented_quote):
            with self.subTest(change=change.__name__):
                with self.assertRaises(NeedsInput):rank(job('https://example.test/one'),example_profile(),self.model(change))

    def test_known_blocked_constraint_can_never_be_eligible(self):
        profile=example_profile();profile['facts']=[{'text':'I do not have authorization to work in the United Kingdom.'}]
        posting=job('https://example.test/one')
        posting['description']+=' Requires UK work authorization. Requires an active security clearance.'
        def change(result):
            result['requirements']+=[{'requirement':'UK work authorization','job_quote':'Requires UK work authorization.',
                'kind':'hard_constraint','status':'not_met','candidate_source_ids':['fact.0'],'explanation':'Fictional candidate explicitly confirms no authorization.'},
                {'requirement':'Security clearance','job_quote':'Requires an active security clearance.',
                'kind':'hard_constraint','status':'unverified','candidate_source_ids':[],'explanation':'Not provided.'}]
        result=rank(posting,profile,self.model(change))
        self.assertFalse(result['eligible']);self.assertEqual(result['eligibility_status'],'blocked')

    def test_education_and_projects_are_citable_without_generated_material(self):
        profile=example_profile()
        profile['resume']['education']=[{'org':'Example College','title':'MSc Example','year':'2026','description':'Award status not supplied'}]
        profile['resume']['projects']=[{'description':'Built a fictional prototype','bullets':['Tested with one fictional user']}]
        profile['targeting']={'config':{'location':{'visa_status':'Explicit fictional authorization statement'}}}
        profile['generated_cv']={'summary':'Not a source fact'}
        facts=source_facts(profile)
        self.assertIn('Award status not supplied',facts['education.0'])
        self.assertEqual(facts['project.0.0'],'Tested with one fictional user')
        self.assertEqual(facts['work_authorization.statement'],'Explicit fictional authorization statement')
        self.assertNotIn('Not a source fact',facts.values())

    def test_high_score_cannot_promote_poor_fit_and_review_explains_requirements(self):
        def change(result):
            result['score']=99;result['fit_category']='poor_fit'
            result['requirements'][0]['requirement']='<script>unsafe employer text</script>'
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            data=Path(temp);key=store.ingest(job('https://example.test/one'))
            with patch('joblazy.discovery.enrich',side_effect=lambda job,*args,**kwargs:job):
                result=run_queue(store,example_profile(),self.model(change),None,data/'applications',1)
            self.assertEqual(result[0]['status'],'not_selected')
            self.assertFalse((data/'applications'/key/'cv.pdf').exists())
            changed_profile=example_profile()
            changed_profile['resume']['experience'][0]['bullets'][0]='Changed later: must not replace assessed evidence'
            output=render_review(store,data,profile=changed_profile);html=Path(output['path']).read_text(encoding='utf-8')
            self.assertIn('Stale assessment',html)
            self.assertNotIn('Requirement-by-requirement assessment',html)
            # Historical review can show the recorded evidence without substituting
            # later profile edits for the evidence actually used in that decision.
            output=render_review(store,data);html=Path(output['path']).read_text(encoding='utf-8')
            self.assertIn('Requirement-by-requirement assessment',html)
            self.assertIn('Recorded candidate evidence',html)
            self.assertIn(example_profile()['resume']['experience'][0]['bullets'][0],html)
            self.assertNotIn('Changed later: must not replace assessed evidence',html)
            self.assertIn('&lt;script&gt;unsafe employer text&lt;/script&gt;',html)
            self.assertNotIn('<script>unsafe employer text</script>',html)


if __name__=='__main__':unittest.main()
