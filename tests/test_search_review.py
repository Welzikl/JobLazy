import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from joblazy.common import ModelUnavailable, digest, read_json, write_json
from joblazy.search import SearchController, boards_for
from joblazy.search_review import review_verified, snapshot_matches, SnapshotIndex
from joblazy.store import Store
from joblazy.worker import utc_day
from .support import example_profile, job
from .test_shortlist_review import BatchModel
from .test_search import PLAN


class SearchReviewTests(unittest.TestCase):
    def test_snapshot_index_keeps_source_checks_and_skips_unrelated_comparisons(self):
        index=SnapshotIndex(self.jobs)
        with patch('joblazy.search_review.snapshot_matches',wraps=snapshot_matches) as compare:
            for i in range(100):
                self.assertFalse(index.matches(job('https://unrelated.test/'+str(i))))
            self.assertTrue(index.matches(self.jobs[0]))
            self.assertFalse(index.matches({**self.jobs[0],'description':'Changed requirements'}))
            self.assertEqual(compare.call_count,2)
        old={**self.jobs[0],'observed_at':(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()}
        self.assertFalse(SnapshotIndex([old]).matches(self.jobs[0]))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'jobs.sqlite'); self.addCleanup(self.store.close)
        self.profile = example_profile()
        self.jobs = [{**job('https://example.test/' + str(i)), 'observed_at': datetime.now(timezone.utc).isoformat()}
                     for i in range(3)]
        self.ids = [self.store.ingest(value) for value in self.jobs]

    def review(self, model=None, **kwargs):
        return review_verified(self.store, self.profile, model or BatchModel(), self.jobs,
                               self.root / 'applications', directory=self.root / 'audit', **kwargs)

    def test_small_batches_share_calls_and_keep_attempt_accounting(self):
        model = BatchModel()
        results = self.review(model)
        self.assertEqual(len(model.calls), 2)
        self.assertEqual([row['status'] for row in results], ['ranked'] * 3)
        self.assertEqual(self.store.daily_usage(utc_day())['job_attempts'], 3)
        for key in self.ids:
            self.assertEqual(read_json(self.root / 'applications' / key / 'ranking.json')['score'], 85)
            self.assertFalse((self.root / 'applications' / key / 'artifact.json').exists())

    def test_stale_or_changed_verification_cannot_skip_public_read(self):
        now = datetime.now(timezone.utc)
        observed = {**self.jobs[0], 'observed_at': (now - timedelta(minutes=16)).isoformat()}
        self.assertFalse(snapshot_matches(observed, self.jobs[0], now=now))
        self.assertFalse(snapshot_matches(self.jobs[0], {**self.jobs[0], 'description': 'Changed'}, now=now))
        self.assertFalse(snapshot_matches({**self.jobs[0], 'observed_at': (now + timedelta(seconds=1)).isoformat()}, self.jobs[0], now=now))
        self.jobs = [observed]
        self.assertIsNone(self.review())
        self.assertEqual(self.store.daily_usage(utc_day())['job_attempts'], 0)

    def test_later_batch_timeout_preserves_first_reviewed_pair(self):
        def mutate(response, attempt):
            if attempt == 2:
                raise ModelUnavailable('Fixture timeout on later batch')
        results = self.review(BatchModel(mutate))
        self.assertEqual([row['status'] for row in results], ['ranked', 'ranked', 'retryable'])
        self.assertEqual(self.store.daily_usage(utc_day())['job_attempts'], 3)
        self.assertFalse(self.store.list({'processing'}))

    def test_invalid_batch_size_does_not_consume_attempts(self):
        for value in (0, 6, True, 1.5):
            with self.assertRaises(ValueError):
                self.review(batch_size=value)
        self.assertEqual(self.store.daily_usage(utc_day())['job_attempts'], 0)

    def test_manual_handoffs_and_explicit_pass_are_preserved(self):
        self.store.transition(self.ids[0], 'manual_review', {'reason': 'User owns browser'})
        self.store.record_choice(self.ids[1], 'pass', 'Not interested')
        self.review()
        self.assertEqual(self.store.get(self.ids[0])['status'], 'manual_review')
        self.assertEqual(self.store.get(self.ids[1])['status'], 'not_selected')
        self.assertEqual(self.store.get(self.ids[2])['status'], 'ranked')
        self.assertEqual(self.store.daily_usage(utc_day())['job_attempts'], 1)

    def test_interrupted_correction_keeps_valid_siblings(self):
        def mutate(response, attempt):
            if attempt == 1: response['results'][1]['assessment']['evidence'][0]['quote'] = 'Invented quote'
            else: raise ModelUnavailable('Fixture connection loss')
        results = self.review(BatchModel(mutate), batch_size=3)
        self.assertEqual(sorted(row['status'] for row in results), ['ranked', 'ranked', 'retryable'])
        self.assertFalse(self.store.list({'processing'}))

    def test_controller_uses_batch_without_browser_then_returns_current_shortlist(self):
        path = self.root / 'profile.json'; write_json(path, self.profile)
        controller = SearchController(self.root, path)
        plan = {**PLAN, 'sources': ['web_search']}
        entry = boards_for(plan, self.profile['targeting'])['boards'][0]
        write_json(self.root / 'search/sources' / digest(entry) / 'checkpoint.json', {
            'jobs': self.jobs, 'source_runs': [{'urls': [value['url'] for value in self.jobs]}]})
        model = BatchModel()
        with patch.object(controller, 'model', return_value=model), patch('playwright.sync_api.sync_playwright') as browser:
            first = controller.rank(plan, self.profile, self.store, 3)
            again = controller.rank(plan, self.profile, self.store, 3)
        self.assertEqual(len(model.calls), 2)
        browser.assert_not_called()
        self.assertEqual(len(first['shortlist']), 3)
        self.assertEqual(first['shortlist'], again['shortlist'])

    def test_resume_uses_saved_run_identifier_and_rejects_missing_one(self):
        path = self.root / 'profile.json'; write_json(path, self.profile)
        controller = SearchController(self.root, path)
        with self.assertRaisesRegex(Exception, 'No saved delegated'):
            controller.start('resume', {})
        write_json(self.root / 'search/plan.json', {'plan': {**PLAN, 'sources': ['web_search']},
                   'confirmed': True, 'profile_hash': digest(self.profile), 'created_at': 'now'})
        controller.operation = {'state': 'interrupted', 'progress': {'run_id': 'saved123'}}
        with patch.object(controller, 'scan', return_value={'report': {'errors': []}}) as scan, \
             patch.object(controller, 'shortlist', return_value={'results': [], 'message': 'Reviewed'}):
            controller.start('resume', {})
            controller.thread.join(5)
        self.assertFalse(controller.thread.is_alive())
        self.assertEqual(scan.call_args.kwargs['resume_run_id'], 'saved123')
        self.assertEqual(controller.operation['state'], 'complete')

    def test_search_reuses_only_fresh_previously_scored_roles(self):
        self.review()
        path = self.root / 'profile.json'; write_json(path, self.profile)
        controller = SearchController(self.root, path)
        plan = {**PLAN, 'sources': ['web_search']}
        entry = boards_for(plan, self.profile['targeting'])['boards'][0]
        observations = copy.deepcopy(self.jobs)
        observations[0]['observed_at'] = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        write_json(self.root / 'search/sources' / digest(entry) / 'checkpoint.json', {'jobs': observations})
        model = BatchModel()
        with patch.object(controller, 'model', return_value=model):
            result = controller.shortlist(plan, self.profile, self.store, 3)
        self.assertEqual(len(result['shortlist']), 2)
        self.assertNotIn(self.ids[0], {row['id'] for row in result['shortlist']})
        self.assertEqual(model.calls, [])


if __name__ == '__main__': unittest.main()
