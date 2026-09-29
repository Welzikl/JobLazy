from datetime import datetime, timedelta, timezone
import copy
from contextlib import closing
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from joblazy.common import ModelUnavailable
from joblazy.shortlist_flow import shortlist_verified
from joblazy.store import Store
from joblazy.worker import utc_day
from .support import example_profile, job


class ShortlistFlowTests(unittest.TestCase):
    def test_invalid_limit_cannot_expand_batch_and_zero_never_starts_inference(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            posting={**job('https://example.test/limits'),'observed_at':datetime.now(timezone.utc).isoformat()}
            store.ingest(posting)
            with patch('joblazy.search_shortlist.review_shortlist') as reviewer:
                for limit in (-1,True,1.5):
                    with self.subTest(limit=limit),self.assertRaises(ValueError):
                        shortlist_verified(store,example_profile(),object(),[posting],Path(temp)/'shortlist',limit=limit)
                result=shortlist_verified(store,example_profile(),object(),[posting],Path(temp)/'shortlist',limit=0)
                self.assertEqual(result['results'],[])
                reviewer.assert_not_called()
            self.assertEqual(store.daily_usage(utc_day())['job_attempts'],0)

    def test_freshness_refresh_reuses_decision_but_changed_evidence_and_profile_do_not(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            root=Path(temp);profile=example_profile()
            posting={**job('https://example.test/cache'),'observed_at':datetime.now(timezone.utc).isoformat()}
            posting['source_provenance']={'checked_at':posting['observed_at'],'identity':'fixture-role',
                                          'board_api_url':'https://api.example.test/board'}
            key=store.ingest(posting)
            response={'results':{key:{'recommend':True,'reason':'Fixture','job_quotes':['partner onboarding'],
                'candidate_source_ids':['experience.0.0'],'caveats':[]}},'errors':{}}
            with patch('joblazy.search_shortlist.review_shortlist',return_value=response) as reviewer:
                shortlist_verified(store,profile,object(),[posting],root/'shortlist')
                posting={**posting,'observed_at':datetime.now(timezone.utc).isoformat(),
                         'description_source':'https://example.test/cache','description_method':'fresh public read'}
                posting['source_provenance']={**posting['source_provenance'],'checked_at':posting['observed_at']}
                posting['source_provenance'].pop('board_api_url')
                posting['source_provenance']['api_url']='https://api.example.test/posting'
                store.ingest(posting)
                again=shortlist_verified(store,profile,object(),[posting],root/'shortlist')
                self.assertEqual(again['reused_decisions'],1)
                self.assertEqual(reviewer.call_count,1)
                expired={**posting,'observed_at':(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()}
                self.assertEqual(shortlist_verified(store,profile,object(),[expired],root/'shortlist')['shortlist'],[])
                self.assertEqual(reviewer.call_count,1)
                posting={**posting,'additional_requirement':'Must be available every Saturday'}
                store.ingest(posting)
                shortlist_verified(store,profile,object(),[posting],root/'shortlist')
                self.assertEqual(reviewer.call_count,2)
                changed=copy.deepcopy(profile);changed['targeting']={'desired_work':'Different career direction'}
                shortlist_verified(store,changed,object(),[posting],root/'shortlist')
                self.assertEqual(reviewer.call_count,3)
                class OtherModel:
                    model='other-model'
                shortlist_verified(store,changed,OtherModel(),[posting],root/'shortlist')
                self.assertEqual(reviewer.call_count,4)
            self.assertEqual(store.daily_usage(utc_day())['job_attempts'],4)

    def test_preliminary_result_never_promotes_queue_and_reuses_same_evidence(self):
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp) / 'jobs.sqlite')) as store:
            root = Path(temp)
            posting = {**job('https://example.test/one'), 'observed_at': datetime.now(timezone.utc).isoformat()}
            key = store.ingest(posting)
            store.ingest({**posting, 'url': 'https://example.test/outside-this-search'})
            response = {'results': {key: {'recommend': True, 'reason': 'Fixture', 'job_quotes': ['partner onboarding'],
                         'candidate_source_ids': ['experience.0.0'], 'caveats': ['Assessment pending']}}, 'errors': {}}
            with patch('joblazy.search_shortlist.review_shortlist', return_value=response) as reviewer, \
                 patch.object(store, 'prior_application', wraps=store.prior_application) as prior:
                first = shortlist_verified(store, example_profile(), object(), [posting], root / 'shortlist')
                second = shortlist_verified(store, example_profile(), object(), [posting], root / 'shortlist')
            self.assertEqual(reviewer.call_count, 1)
            self.assertEqual(prior.call_count, 2)
            self.assertEqual(first['shortlist'], second['shortlist'])
            self.assertTrue(first['shortlist'][0]['preliminary'])
            self.assertIsNone(first['shortlist'][0]['score'])
            self.assertEqual(store.get(key)['status'], 'discovered')
            self.assertIsNone(store.get(key)['result'])
            self.assertEqual(store.daily_usage(utc_day())['job_attempts'], 1)
            self.assertFalse((root / 'applications').exists())

    def test_interruption_restores_previous_retry_detail_and_preserves_manual_handoff(self):
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp) / 'jobs.sqlite')) as store:
            root = Path(temp)
            postings = [{**job('https://example.test/' + str(i)), 'observed_at': datetime.now(timezone.utc).isoformat()} for i in range(2)]
            keys = [store.ingest(posting) for posting in postings]
            detail = {'reason': 'Existing source read failure'}
            store.transition(keys[0], 'retryable', detail)
            store.transition(keys[1], 'manual_review', {'reason': 'User owns form'})
            with patch('joblazy.search_shortlist.review_shortlist', side_effect=ModelUnavailable('Fixture timeout')):
                result = shortlist_verified(store, example_profile(), object(), postings, root / 'shortlist')
            self.assertEqual(result['results'][0]['status'], 'review_failed')
            self.assertEqual(store.get(keys[0])['status'], 'retryable')
            self.assertEqual(store.get(keys[0])['result'], detail)
            self.assertEqual(store.get(keys[1])['status'], 'manual_review')
            self.assertEqual(store.daily_usage(utc_day())['job_attempts'], 1)

    def test_attempt_log_failure_restores_original_state_before_inference(self):
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp) / 'jobs.sqlite')) as store:
            posting = {**job('https://example.test/setup-failure'), 'observed_at': datetime.now(timezone.utc).isoformat()}
            key = store.ingest(posting)
            detail = {'reason': 'Prior retry context'}
            store.transition(key, 'retryable', detail)
            with patch('joblazy.shortlist_flow.ProcessingAttempt', side_effect=OSError('Fixture disk full')), \
                 patch('joblazy.search_shortlist.review_shortlist') as reviewer:
                with self.assertRaises(OSError):
                    shortlist_verified(store, example_profile(), object(), [posting], Path(temp) / 'shortlist')
            reviewer.assert_not_called()
            self.assertEqual(store.get(key)['status'], 'retryable')
            self.assertEqual(store.get(key)['result'], detail)

    def test_recovery_restores_prior_scored_state_after_process_interruption(self):
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp) / 'jobs.sqlite')) as store:
            key = store.ingest(job('https://example.test/interrupted'))
            detail = {'ranking': {'score': 85, 'reason': 'Previous assessment'}}
            store.transition(key, 'ranked', detail)
            store.transition(key, 'processing', {'stage': 'search_shortlist', 'prior_status': 'ranked', 'prior_result': detail})
            store.recover()
            self.assertEqual(store.get(key)['status'], 'ranked')
            self.assertEqual(store.get(key)['result'], detail)


if __name__ == '__main__': unittest.main()
