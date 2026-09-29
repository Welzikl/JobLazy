import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from joblazy.common import NeedsInput, read_json, write_json
from joblazy.search_coordinator import discover_missions
from joblazy.store import Store
from .support import job
from .support import example_profile
from .test_search import PLAN


ENTRY = {'name': 'Delegated search', 'queries': ['partner operations'],
         'location': 'Bristol, United Kingdom', 'brief': {'desired_work': 'Partner operations'}}


class SearchCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'jobs.sqlite')
        self.addCleanup(self.store.close)
        self.missions = [{**ENTRY, 'id': str(i), 'scope': str(i)} for i in range(6)]

    def model_factory(self, mission):
        class Model:
            def generate(inner, task, data, schema):
                return {'jobs': [{'url': 'https://example.test/' + mission['id'], 'title': 'Partner Operations',
                                  'company': 'Unverified hint', 'location': 'Invented', 'reason': ''}], 'gaps': []}
        return Model()

    def verify(self, candidate, directory):
        return job(candidate['url'])

    def run_search(self, **kwargs):
        return discover_missions(ENTRY, self.store, self.root / 'search', missions=self.missions,
                                 model_factory=kwargs.pop('model_factory', self.model_factory),
                                 verifier=kwargs.pop('verifier', self.verify), **kwargs)

    def test_parallel_search_has_bounded_concurrency_and_main_thread_intake(self):
        barrier = threading.Barrier(3, timeout=5)
        mutex = threading.Lock()
        active = 0
        maximum = 0
        owner = threading.get_ident()
        def factory(mission):
            model = self.model_factory(mission)
            generate = model.generate
            def call(*args):
                nonlocal active, maximum
                with mutex:
                    active += 1
                    maximum = max(maximum, active)
                barrier.wait()
                try: return generate(*args)
                finally:
                    with mutex: active -= 1
            model.generate = call
            return model
        progress = []
        def update(value):
            self.assertEqual(threading.get_ident(), owner)
            progress.append(value)
        result = self.run_search(model_factory=factory, progress=update)
        self.assertEqual(maximum, 3)
        self.assertEqual(result['new_unique_jobs'], 6)
        self.assertEqual(result['metrics']['missions_completed'], 6)
        self.assertEqual(progress[-1]['verified'], 6)
        self.assertIsNotNone(result['metrics']['first_verified_seconds'])
        self.assertEqual(len(self.store.list()), 6)

    def test_partial_failure_and_exact_alias_dedupe_preserve_verified_output(self):
        url = 'https://jobs.ashbyhq.com/example/12345678-1234-1234-1234-123456789abc'
        def factory(mission):
            class Model:
                def generate(inner, *args):
                    if mission['id'] == '5': raise NeedsInput('Fixture model outage')
                    candidate = {'url': url + ('/application' if int(mission['id']) % 2 else ''),
                                 'title': 'Partner Operations', 'company': '', 'location': '', 'reason': ''}
                    return {'jobs': [candidate], 'gaps': []}
            return Model()
        seen = []
        def verify(candidate, path):
            seen.append(candidate['url'])
            return job(url)
        report = self.run_search(model_factory=factory, verifier=verify)
        self.assertEqual(len(seen), 1)
        self.assertEqual(report['metrics']['duplicate_leads'], 4)
        self.assertEqual(report['metrics']['missions_failed'], 1)
        self.assertEqual(report['metrics']['state'], 'complete_with_gaps')
        saved = read_json(self.root / 'search/checkpoint.json')
        self.assertEqual(len(saved['jobs']), 1)
        self.assertEqual(saved['source_runs'][0]['urls'], [url])

    def test_resume_reuses_completed_artifacts_new_search_does_not(self):
        first = self.run_search(run_id='resume1')
        def forbidden(*args): raise AssertionError('Completed work was repeated')
        second = self.run_search(run_id='resume1', model_factory=forbidden, verifier=forbidden)
        self.assertEqual(second['metrics']['verified'], 6)
        self.assertEqual(second['new_unique_jobs'], 0)
        self.assertEqual(first['new_unique_jobs'], 6)
        third = self.run_search()
        self.assertNotEqual(third['metrics']['run_id'], 'resume1')
        self.missions[0]['scope'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'inputs changed'):
            self.run_search(run_id='resume1')

    def test_failed_verification_is_not_a_successful_empty_search(self):
        def fail(*args): raise NeedsInput('No authoritative description')
        result = self.run_search(verifier=fail)
        self.assertEqual(result['metrics']['verified'], 0)
        self.assertEqual(len(result['errors']), 6)
        self.assertEqual(result['metrics']['rejected'], 6)
        self.assertFalse(self.store.list())

    def test_invalid_limits_do_not_launch_workers(self):
        for value in (0, 7, True):
            with self.assertRaises(ValueError): self.run_search(max_workers=value)

    def test_controller_dispatches_luna_uses_shared_ledger_and_prefers_ats_reads(self):
        from joblazy.search import SearchController
        profile = self.root / 'profile.json'
        write_json(profile, example_profile())
        controller = SearchController(self.root, profile)
        routing = []
        class Model:
            def __init__(inner, cache, **kwargs):
                routing.append(kwargs['model'])
                inner.reserve = kwargs['before_request']
            def generate(inner, task, data, schema):
                inner.reserve()
                # One shared exact posting across all six workers.
                return {'jobs': [{'url': 'https://example.test/role', 'title': 'Partner Operations',
                                  'company': 'Hint', 'location': 'Hint', 'reason': ''}], 'gaps': []}
        def ats(url, **kwargs): return {'status': 'verified', 'job': job(url)}
        with patch('joblazy.search.CodexWebSearch', Model), \
             patch('joblazy.ats_postings.verify_posting', side_effect=ats) as reads, \
             patch('playwright.sync_api.sync_playwright') as browser:
            result = controller.scan({**PLAN, 'sources': ['web_search']}, self.store)
        self.assertEqual(routing, ['gpt-6-luna'] * 6)
        self.assertEqual(self.store.daily_usage(__import__('joblazy.worker', fromlist=['utc_day']).utc_day())['model_requests'], 6)
        self.assertEqual(result['report']['new_unique_jobs'], 1)
        reads.assert_called_once()
        browser.assert_not_called()
        self.assertEqual(controller.model(self.store, review=True).model, 'gpt-6-astra')

    def test_one_search_action_adds_delegation_to_legacy_feed_plan_then_reviews(self):
        from joblazy.search import SearchController
        from joblazy.common import digest
        profile = example_profile()
        path = self.root / 'profile.json'
        write_json(path, profile)
        controller = SearchController(self.root, path)
        write_json(self.root / 'search/plan.json', {'plan': PLAN, 'confirmed': True,
                    'profile_hash': digest(profile), 'created_at': '2026-09-28'})
        stages = []
        def scan(plan, store, **kwargs):
            self.assertIn('web_search', plan['sources'])
            stages.append('search')
            return {'report': {'errors': [{'error': 'One source unavailable'}]}, 'sources': []}
        def rank(plan, profile, store, limit):
            stages.append('review')
            return {'results': [], 'message': 'Ranking finished.'}
        with patch.object(controller, 'scan', side_effect=scan), patch.object(controller, 'shortlist', side_effect=rank):
            controller.start('search', {'limit': 5})
            controller.thread.join(5)
        self.assertFalse(controller.thread.is_alive())
        self.assertEqual(stages, ['search', 'review'])
        self.assertIn('coverage gaps', controller.operation['result']['message'])
        self.assertIn('web_search', read_json(self.root / 'search/plan.json')['plan']['sources'])

    def test_supported_ats_aliases_dedupe_and_source_employer_survives_refresh(self):
        from joblazy.discovery_intake import identity, ingest_jobs
        base = 'https://jobs.eu.lever.co/example/12345678-1234-1234-1234-123456789abc'
        self.assertEqual(identity(base), identity(base + '/apply'))
        self.assertNotEqual(identity(base), identity(base.replace('jobs.eu.', 'jobs.')))
        old = {**job(base), 'company': 'Sourced Employer', 'description_source': base,
               'source_metadata': {'hiringOrganization': {'name': 'Sourced Employer'}}}
        key = self.store.ingest(old)
        refresh = {**old, 'url': base + '/apply', 'company': 'Employer unverified',
                   'description_source': 'https://api.eu.lever.co/fixture', 'source_metadata': {}}
        ingest_jobs(self.store, [refresh])
        updated = self.store.get(key)['data']
        self.assertEqual(updated['company'], 'Sourced Employer')
        self.assertEqual(updated['retained_source_fields']['company']['source'], base)
        ingest_jobs(self.store, [refresh])
        self.assertEqual(self.store.get(key)['data']['retained_source_fields']['company']['source'], base)



if __name__ == '__main__': unittest.main()
