import copy
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

from joblazy.common import digest
from joblazy.materials import rank
from joblazy.pipeline import queue_candidates
from joblazy.status import summary
from joblazy.review import render_review
from joblazy.store import Store
from .support import example_profile,job,FixtureModel


class AssessmentProfileTests(unittest.TestCase):
    def test_discovery_only_edits_keep_scores_current_but_evidence_edits_refresh(self):
        profile=example_profile();profile['discovery_preferences']={'max_posting_age_days':45}
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            posting={**job('https://example.test/role'),'location':'United Kingdom (Remote)'}
            assessment=rank(posting,profile,FixtureModel())
            self.assertEqual(assessment['candidate_profile_hash'],digest(profile))
            key=store.ingest(posting);store.transition(key,'ranked',{'ranking':assessment})
            before=store.get(key)
            changed=copy.deepcopy(profile);changed['discovery_preferences']={'max_posting_age_days':30,'title_filter':{'positive':['Strategy']}}
            self.assertEqual(queue_candidates(store,rank_only=True,profile=changed),[])
            result=summary(store,profile=changed)['recent_results'][0]
            self.assertFalse(result['assessment_stale']);self.assertEqual(result['score'],85)
            html=Path(render_review(store,Path(temp),profile=changed)['path']).read_text(encoding='utf-8')
            self.assertNotIn('Stale assessment',html);self.assertIn('Fit score 85',html)
            self.assertEqual(store.get(key),before)
            changed['resume']['summary']+=' Additional confirmed fictional work.'
            self.assertEqual([r['id'] for r in queue_candidates(store,rank_only=True,profile=changed)],[key])
            self.assertTrue(summary(store,profile=changed)['recent_results'][0]['assessment_stale'])
            self.assertIsNone(summary(store,profile=changed)['recent_results'][0]['score'])

    def test_legacy_context_is_not_inferred_after_a_profile_change(self):
        profile=example_profile()
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            posting=job('https://example.test/legacy');assessment=rank(posting,profile,FixtureModel())
            assessment.pop('assessment_profile_hash',None)
            key=store.ingest(posting);store.transition(key,'not_selected',assessment)
            changed=copy.deepcopy(profile);changed['discovery_preferences']={'max_posting_age_days':30}
            self.assertEqual([r['id'] for r in queue_candidates(store,rank_only=True,profile=changed)],[key])

    def test_profile_aware_status_receives_the_remote_location_data(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            posting={**job('https://example.test/remote'),'location':'United Kingdom (Remote)'}
            profile=example_profile();key=store.ingest(posting)
            store.transition(key,'ranked',{'ranking':rank(posting,profile,FixtureModel())})
            result=summary(store,profile=profile)['recent_results'][0]
            self.assertEqual(result['score'],85);self.assertFalse(result['assessment_stale'])

    def test_screen_survives_discovery_edit_but_refreshes_for_changed_ceiling(self):
        from unittest.mock import Mock
        from joblazy.experience_screen import screen_experience
        profile=example_profile()
        profile['targeting']={'config':{'target_roles':{'seniority':{'mode':'required_experience_range','maximum_required_years':5}}}}
        quote='Required: eight years of operations experience.'
        posting=job('https://example.test/screen');posting['description']+=' '+quote
        model=Mock();model.generate.return_value={'decision':'exclude','minimum_required_years':8,
            'requirement_quote':quote,'reason':'Above the five-year ceiling.','uncertainties':[]}
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            key=store.ingest(posting)
            store.transition(key,'not_selected',screen_experience(posting,profile,model,None))
            changed=copy.deepcopy(profile);changed['discovery_preferences']={'max_posting_age_days':30}
            self.assertEqual(queue_candidates(store,rank_only=True,profile=changed),[])
            changed['targeting']['config']['target_roles']['seniority']['maximum_required_years']=8
            self.assertEqual([r['id'] for r in queue_candidates(store,rank_only=True,profile=changed)],[key])
