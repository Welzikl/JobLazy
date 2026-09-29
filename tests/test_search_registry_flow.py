import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from joblazy.ats_cache import SearchATSCache
from joblazy.ats_postings import verify_posting
from joblazy.ats_registry import scan_board
from joblazy.ats_registry import learn_board
from joblazy.common import read_json, write_json
from joblazy.search_coordinator import discover_missions
from joblazy.store import Store
from .test_ats_postings import ASHBY, ashby
from .test_search_coordinator import ENTRY


class RegistryFlowTests(unittest.TestCase):
    def test_resume_preserves_partial_board_results_and_rescues_failed_individual_read(self):
        verification = verify_posting(ASHBY, fetch_json=lambda *a, **kw: ashby())
        registry = {}; self.assertTrue(learn_board(registry, verification))
        class Model:
            def generate(inner, *args):
                return {'jobs': [{'url': ASHBY, 'title': verification['job']['title'],
                                  'company': '', 'location': '', 'reason': ''}], 'gaps': []}
        calls = []
        def board_read(board):
            calls.append(1)
            result = scan_board(board, fetch_json=lambda *a, **kw: ashby())
            result.update(status='partial', complete=False)
            result['observation']['errors'] = ['Fixture second-page failure']
            return result
        def fail(*args): raise TimeoutError('Fixture individual posting failure')
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp) / 'jobs.sqlite')) as store:
            root = Path(temp); write_json(root / 'boards.json', registry)
            kwargs = dict(missions=[{**ENTRY, 'id': 'one'}], model_factory=lambda mission: Model(), verifier=fail,
                          registry_path=root / 'boards.json', board_reader=board_read, run_id='resume')
            first = discover_missions(ENTRY, store, root / 'search', **kwargs)
            self.assertEqual(first['metrics']['verified'], 1)
            second = discover_missions(ENTRY, store, root / 'search', **kwargs)
            self.assertEqual(second['metrics']['verified'], 1)
            self.assertEqual(len(calls), 1)
            self.assertEqual(len(read_json(root / 'search/checkpoint.json')['jobs']), 1)

    def test_learn_scan_and_reuse_board_roles_without_claiming_fresh_reads(self):
        payload = ashby()
        second = copy.deepcopy(payload['jobs'][0])
        second['id'] = second['id'][:-1] + 'd'
        second['jobUrl'] = ASHBY[:-1] + 'd'
        payload['jobs'].append(second)
        def fetch(*args, **kwargs): return copy.deepcopy(payload)
        class Model:
            def generate(inner, *args):
                return {'jobs': [{'url': ASHBY, 'title': payload['jobs'][0]['title'],
                                  'company': '', 'location': '', 'reason': ''}], 'gaps': []}
        def verify(candidate, evidence):
            result = verify_posting(candidate['url'], fetch_json=fetch)
            write_json(evidence / 'ats.json', result)
            return result['job']
        board_reads = []
        def board_read(board):
            board_reads.append(board)
            return scan_board(board, fetch_json=fetch)
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp) / 'jobs.sqlite')) as store:
            root = Path(temp)
            kwargs = dict(missions=[{**ENTRY, 'id': 'only'}], model_factory=lambda mission: Model(),
                          verifier=verify, registry_path=root / 'boards.json', board_reader=board_read)
            first = discover_missions(ENTRY, store, root / 'search', **kwargs)
            self.assertEqual(first['new_unique_jobs'], 2)
            self.assertEqual(first['metrics']['boards_scanned'], 1)
            second_run = discover_missions(ENTRY, store, root / 'search', **kwargs)
            self.assertEqual(len(board_reads), 1)
            self.assertEqual(second_run['metrics']['cached_board_jobs'], 1)
            self.assertEqual(second_run['metrics']['verified'], 1)
            self.assertEqual(len(read_json(root / 'search/checkpoint.json')['jobs']), 2)
            self.assertEqual(len(store.list()), 2)

    def test_shared_ats_reads_coalesce_and_return_independent_payloads(self):
        started, release = threading.Event(), threading.Event()
        calls = []
        def fetch(url, **kwargs):
            calls.append(url); started.set(); release.wait(5)
            return {'jobs': [1]}
        cache = SearchATSCache(fetch)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(cache, 'https://api.ashbyhq.com/fixture')
            self.assertTrue(started.wait(2))
            second = pool.submit(cache, 'https://api.ashbyhq.com/fixture')
            release.set()
            one, two = first.result(), second.result()
        one['jobs'].append(2)
        self.assertEqual(two, {'jobs': [1]})
        self.assertEqual(len(calls), 1)
        self.assertEqual(cache.cache_hits, 1)

    def test_failed_ats_read_is_not_cached_as_empty_success(self):
        calls = []
        def fetch(url, **kwargs):
            calls.append(url)
            if len(calls) == 1: raise TimeoutError('Fixture timeout')
            return {'jobs': []}
        cache = SearchATSCache(fetch)
        with self.assertRaises(TimeoutError): cache('https://api.ashbyhq.com/fixture')
        self.assertEqual(cache('https://api.ashbyhq.com/fixture'), {'jobs': []})
        self.assertEqual(len(calls), 2)


if __name__ == '__main__': unittest.main()
