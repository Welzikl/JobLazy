import copy
from datetime import timedelta
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from joblazy.ats_postings import verify_posting
from joblazy.ats_registry import cached_jobs, due_boards, learn_board, record_scan, scan_board
from tests.test_ats_postings import ASHBY, GREENHOUSE, LEVER, NOW, ashby, greenhouse, lever


def registry_for(url=ASHBY, payload=None):
    payload = ashby() if payload is None else payload
    verification = verify_posting(url, fetch_json=lambda *args, **kwargs: copy.deepcopy(payload), now=NOW)
    registry = {}
    assert learn_board(registry, verification)
    return registry, next(iter(registry.values())), verification


class AtsRegistryTests(unittest.TestCase):
    def test_only_independently_verified_posting_results_learn_boards(self):
        registry, entry, verified = registry_for()
        self.assertEqual(entry['board'], 'fictional')
        self.assertEqual(entry['proof']['observed_url'], ASHBY)
        self.assertEqual(entry['first_observed_at'], NOW.isoformat())
        for field, value in [('status', 'failed'), ('observation', {}), ('job', {'url': ASHBY})]:
            bad = copy.deepcopy(verified)
            bad[field] = value
            self.assertFalse(learn_board({}, bad))
        for key in ('board', 'identity', 'api_url', 'checked_at'):
            bad = copy.deepcopy(verified)
            bad['job']['source_provenance'][key] = 'model-hint'
            self.assertFalse(learn_board({}, bad))
        self.assertFalse(learn_board({}, {'board': 'guessed-company'}))

    def test_ashby_single_response_expands_board_and_omits_unlisted(self):
        registry, entry, _ = registry_for()
        payload = ashby()
        second = copy.deepcopy(payload['jobs'][0])
        second['id'] = second['id'][:-1] + 'd'
        second['jobUrl'] = ASHBY[:-1] + 'd'
        second['isListed'] = False
        payload['jobs'].append(second)
        result = scan_board(entry, fetch_json=lambda *a, **kw: payload, now=NOW)
        self.assertTrue(result['complete'])
        self.assertEqual(len(result['jobs']), 1)
        self.assertEqual(result['observation']['unlisted'], 1)
        self.assertFalse(result['observation']['closure_inferred'])
        self.assertEqual(result['jobs'][0]['source_provenance']['board_api_url'], result['jobs'][0]['description_source'])
        record_scan(registry, result)
        self.assertEqual(len(cached_jobs(entry, now=NOW)), 1)
        self.assertEqual(due_boards(registry, now=NOW + timedelta(hours=5)), [])
        self.assertEqual(len(due_boards(registry, now=NOW + timedelta(hours=6))), 1)
        self.assertEqual(cached_jobs(entry, now=NOW + timedelta(hours=6)), [])

    def test_greenhouse_complete_description_and_custom_employer_url(self):
        _, entry, _ = registry_for(GREENHOUSE, greenhouse())
        record = greenhouse()
        record['absolute_url'] = 'https://careers.fictional.test/jobs/12345'
        calls = []
        def fetch(url, **kwargs):
            calls.append(url)
            return {'jobs': [record], 'meta': {'total': 1}}
        result = scan_board(entry, fetch_json=fetch, now=NOW)
        self.assertTrue(result['complete'])
        self.assertEqual(calls, ['https://boards-api.greenhouse.io/v1/boards/fictional/jobs?content=true'])
        self.assertEqual(result['jobs'][0]['company'], 'Fictional Company')
        self.assertEqual(result['jobs'][0]['url'], GREENHOUSE)
        self.assertEqual(result['jobs'][0]['description_source'], calls[0])

    def test_lever_eu_pagination_uses_own_host_and_preserves_fields(self):
        url = LEVER.replace('jobs.lever.co', 'jobs.eu.lever.co')
        _, entry, _ = registry_for(url, lever(url))
        calls = []
        def fetch(api, **kwargs):
            calls.append(api)
            return [lever(url)] if len(calls) == 1 else []
        result = scan_board(entry, fetch_json=fetch, page_size=1, now=NOW)
        self.assertTrue(result['complete'])
        self.assertEqual(len(calls), 2)
        self.assertIn('api.eu.lever.co/v0/postings/fictional?', calls[0])
        self.assertTrue(calls[1].endswith('&skip=1&limit=1'))
        self.assertIn('Two years of experience', result['jobs'][0]['description'])
        self.assertIn('Paris', result['jobs'][0]['location'])

    def test_failure_after_page_retains_good_records_without_success_cache(self):
        registry, entry, _ = registry_for(LEVER, lever())
        calls = []
        def fetch(api, **kwargs):
            calls.append(api)
            if len(calls) > 1:
                raise HTTPError(api, 429, 'rate limited', {}, None)
            return [lever()]
        result = scan_board(entry, fetch_json=fetch, page_size=1, now=NOW)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(len(result['jobs']), 1)
        self.assertEqual(result['observation']['http_status'], 429)
        record_scan(registry, result)
        self.assertEqual(cached_jobs(entry, now=NOW), [])
        self.assertEqual(due_boards(registry, now=NOW + timedelta(minutes=4)), [])
        self.assertEqual(len(due_boards(registry, now=NOW + timedelta(minutes=5))), 1)

    def test_records_pages_duplicates_and_malformed_rows_are_partial(self):
        _, entry, _ = registry_for()
        for payload, limit in [({'jobs': ashby()['jobs'] + [None]}, 10),
                               ({'jobs': ashby()['jobs'] * 2}, 10),
                               ({'jobs': ashby()['jobs'] * 2}, 1)]:
            result = scan_board(entry, fetch_json=lambda *a, **kw: payload, max_records=limit, now=NOW)
            self.assertEqual(result['status'], 'partial')
            self.assertFalse(result['complete'])
            self.assertEqual(len(result['jobs']), 1)
            self.assertTrue(result['observation']['errors'])
        _, entry, _ = registry_for(LEVER, lever())
        result = scan_board(entry, fetch_json=lambda *a, **kw: [lever()], page_size=1, max_pages=1, now=NOW)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['observation']['pages'], 1)

    def test_empty_board_success_does_not_claim_prior_postings_closed(self):
        registry, entry, _ = registry_for()
        result = scan_board(entry, fetch_json=lambda *a, **kw: {'jobs': []}, now=NOW)
        record_scan(registry, result)
        self.assertTrue(result['complete'])
        self.assertFalse(result['observation']['closure_inferred'])
        self.assertNotIn('closed', result)
        self.assertEqual(entry['proof']['observed_url'], ASHBY)

    def test_failed_scan_preserves_prior_success_and_stale_writes_are_ignored(self):
        registry, entry, verification = registry_for()
        success = scan_board(entry, fetch_json=lambda *a, **kw: ashby(), now=NOW)
        record_scan(registry, success)
        failed = scan_board(entry, fetch_json=lambda *a, **kw: {}, now=NOW + timedelta(hours=1))
        record_scan(registry, failed)
        self.assertEqual(entry['last_scan_status'], 'failed')
        self.assertEqual(len(cached_jobs(entry, now=NOW + timedelta(hours=2))), 1)
        self.assertFalse(record_scan(registry, success))
        learn_board(registry, verification)
        self.assertEqual(entry['last_scan_status'], 'failed')

    def test_unproven_board_never_fetches_and_bounds_are_validated(self):
        with patch('joblazy.ats_registry.public_fetch_json') as fetch:
            with self.assertRaises(ValueError):
                scan_board({'provider': 'ashby', 'board': 'invented'})
            fetch.assert_not_called()
        _, entry, _ = registry_for()
        for kwargs in ({'max_records': 0}, {'max_pages': True}, {'page_size': 1001}, {'timeout': float('inf')}):
            with self.assertRaises(ValueError):
                scan_board(entry, **kwargs)

    def test_total_deadline_shared_across_pages(self):
        _, entry, _ = registry_for(LEVER, lever())
        with patch('joblazy.ats_registry.time.monotonic', side_effect=[0, 1, 3, 4, 21]):
            result = scan_board(entry, fetch_json=lambda *a, **kw: [lever()], page_size=1, timeout=20, now=NOW)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['observation']['pages'], 1)
        self.assertIn('time limit', result['observation']['errors'][0])

    def test_foreign_board_identity_does_not_pollute_results(self):
        _, entry, _ = registry_for()
        payload = ashby()
        payload['jobs'][0]['jobUrl'] = ASHBY.replace('/fictional/', '/someoneelse/')
        result = scan_board(entry, fetch_json=lambda *a, **kw: payload, now=NOW)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['jobs'], [])

    def test_greenhouse_reported_truncation_is_partial(self):
        _, entry, _ = registry_for(GREENHOUSE, greenhouse())
        result = scan_board(entry, fetch_json=lambda *a, **kw: {'jobs': [greenhouse()], 'meta': {'total': 2}}, now=NOW)
        self.assertEqual(result['status'], 'partial')
        self.assertFalse(result['complete'])
        self.assertEqual(len(result['jobs']), 1)

    def test_bad_saved_proof_is_skipped_without_network(self):
        registry = {'bad': {'proof': 'invalid'}}
        self.assertEqual(due_boards(registry, now=NOW), [])


if __name__ == '__main__':
    unittest.main()
