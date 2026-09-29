"""Reproducible orchestration benchmark; fictional latency, no live requests.

This measures serial versus concurrent execution of identical six-mission work.
It does not establish live search relevance, token efficiency or ATS latency.
"""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from joblazy.common import write_json
from joblazy.search_coordinator import discover_missions
from joblazy.search_missions import build_search_missions
from joblazy.store import Store


def benchmark(workers, delay):
    entry = {'name': 'Fictional benchmark', 'queries': ['partner operations', 'growth strategy', 'product operations'],
             'location': 'Bristol, United Kingdom', 'brief': {'desired_work': 'Partner operations'}}
    missions = build_search_missions(entry, entry['brief'])
    def factory(mission):
        class Model:
            def generate(self, task, data, schema):
                time.sleep(delay)
                return {'jobs': [{'url': 'https://example.test/' + mission['id'], 'title': 'Partner Operations',
                                  'company': '', 'location': '', 'reason': ''}], 'gaps': []}
        return Model()
    def verify(candidate, path):
        time.sleep(delay / 4)
        return {'url': candidate['url'], 'title': candidate['title'], 'company': 'Fictional employer',
                'location': 'Bristol, United Kingdom', 'description': 'Fictional source: coordinate partner onboarding.',
                'ats': 'fixture'}
    with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp) / 'jobs.sqlite')) as store:
        result = discover_missions(entry, store, Path(temp) / 'search', missions=missions,
                                  model_factory=factory, verifier=verify, max_workers=workers)
        return result['metrics']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--delay', type=float, default=0.2)
    args = parser.parse_args()
    if not 0.05 <= args.delay <= 2: parser.error('delay must be between 0.05 and 2 seconds')
    sequential, concurrent = benchmark(1, args.delay), benchmark(3, args.delay)
    result = {'kind': 'fictional_orchestration_benchmark', 'live_requests': 0,
              'sequential': sequential, 'concurrent': concurrent,
              'elapsed_ratio': round(sequential['elapsed_seconds'] / concurrent['elapsed_seconds'], 2),
              'limitations': 'Simulated model/network latency; no evidence of live relevance, token savings or production speed.'}
    write_json(args.output, result)
    print(json.dumps(result, indent=2))
