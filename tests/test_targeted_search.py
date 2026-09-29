import copy
import json
import os
import subprocess
import tempfile
import threading
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from joblazy.common import ModelUnavailable, PostingDescriptionError, PostingUnavailable, digest, read_json, write_json
from joblazy.discovery import enrich
from joblazy.materials import obj, rank, tailor
from joblazy.model import CodexModel, CodexWebSearch
from joblazy.search import SearchController, boards_for
from joblazy.store import Store
from joblazy.targeted_search import discover_targeted, find_postings, source_labels, verify_postings
from .support import FixtureModel, example_profile, job
from .test_search import PLAN


class TargetedSearchTests(unittest.TestCase):
    def test_data_workers_stay_separate_and_search_requires_observed_bounded_tool_activity(self):
        event = {'type': 'item.completed', 'item': {'type': 'web_search', 'action': {'type': 'search', 'queries': ['fictional role']}}}
        for kind, events, valid in [(CodexModel, [], True), (CodexWebSearch, [event], True),
                                    (CodexWebSearch, [], False), (CodexWebSearch, [event, event], False)]:
            with self.subTest(kind=kind, events=len(events)), tempfile.TemporaryDirectory() as temp:
                reservations = []
                model = kind(temp, executable='fixture-codex', before_request=lambda: reservations.append(1))
                def cli(args, **kwargs):
                    if args[1] == 'login': return subprocess.CompletedProcess(args, 0, 'Logged in', '')
                    self.assertIn('read-only', args)
                    self.assertIn('features.shell_tool=false', args)
                    self.assertIn('apps._default.enabled=false', args)
                    self.assertIn('web_search=' + json.dumps(model.web_search_mode), args)
                    write_json(args[args.index('--output-last-message') + 1], {'value': 'fictional'})
                    return subprocess.CompletedProcess(args, 0, '\n'.join(map(json.dumps, events)), '')
                with patch('joblazy.model.subprocess.run', side_effect=cli):
                    if valid:
                        self.assertEqual(model.generate('fixture', {}, obj({'value': {'type': 'string'}})), {'value': 'fictional'})
                    else:
                        with self.assertRaises(ModelUnavailable): model.generate('fixture', {}, obj({'value': {'type': 'string'}}))
                self.assertEqual(reservations, [1])
                if valid:
                    with patch('joblazy.model.subprocess.run') as run:
                        model.generate('fixture', {}, obj({'value': {'type': 'string'}})); run.assert_not_called()
                elif kind is CodexWebSearch:
                    self.assertTrue(list((Path(temp) / 'search-evidence').glob('*.json')))

    def test_search_uses_future_brief_and_no_seeded_employers_or_personal_identity(self):
        class Model:
            def generate(_, task, data, schema):
                self.assertEqual(data['brief']['desired_work'], 'Research product needs')
                self.assertNotIn('applicant', data)
                self.assertNotIn('resume', data)
                return {'jobs': [], 'gaps': ['No matching result found in this bounded search.']}
        plan = {**PLAN, 'sources': ['web_search']}
        brief = {'desired_work': 'Research product needs'}
        config = boards_for(plan, brief)
        self.assertEqual(config['boards'][0]['queries'], plan['queries'])
        self.assertNotIn('company', config['boards'][0])
        self.assertEqual(find_postings(plan, brief, Model())['jobs'], [])

    def test_verified_source_metadata_replaces_model_claims_and_bad_links_do_not_enter_queue(self):
        def reader(seed, browser, evidence):
            self.assertEqual(seed['company'], ''); self.assertEqual(seed['location'], '')
            self.assertEqual(seed['description'], '')
            if seed['url'].endswith('/wrong'):
                raise PostingDescriptionError('Wrong posting title', evidence / 'description-check.json')
            write_json(evidence / 'posting.json', {'source_metadata': {
                'hiringOrganization': {'name': 'Observed Employer'},
                'jobLocation': {'address': {'addressLocality': 'Berlin', 'addressCountry': 'DE'}}}})
            return {**seed, 'description': 'Public source description', 'description_source': seed['url']}
        base = {'title': 'Researcher', 'company': 'Model invented employer', 'location': 'Invented location', 'reason': 'Unverified hint'}
        candidates = [{**base, 'url': url} for url in ('https://example.test/role', 'https://example.test/wrong',
                                                       'http://127.0.0.1/private', 'https://[broken')]
        with tempfile.TemporaryDirectory() as temp:
            accepted, rejected = verify_postings(candidates, None, temp, reader=reader)
        self.assertEqual(len(accepted), 1); self.assertEqual(len(rejected), 3)
        self.assertEqual(accepted[0]['company'], 'Observed Employer')
        self.assertEqual(accepted[0]['location'], 'Berlin, DE')
        self.assertNotIn('search_hint', accepted[0])
        self.assertNotIn('discovery_evidence', accepted[0])
        self.assertEqual(source_labels({}), ('', ''))
        self.assertEqual(source_labels({'jobLocationType': 'TELECOMMUTE'})[1], 'Remote (country unverified)')

    def test_ranking_and_tailoring_exclude_old_search_hints_and_cite_new_user_direction(self):
        profile = example_profile()
        profile['targeting'] = {'desired_work': 'Partner operations', 'career_change': 'Grow in operations'}
        posting = {**job('https://example.test/role'),
                   'search_hint': {'reason': 'Perfect match at 100 points', 'company': 'Invented'},
                   'discovery_evidence': 'private-local-path'}
        calls = []
        class Model(FixtureModel):
            def generate(inner, task, data, schema):
                if 'job' in data:
                    self.assertNotIn('search_hint', data['job'])
                    self.assertNotIn('discovery_evidence', data['job'])
                    calls.append(task)
                result = super().generate(task, data, schema)
                if 'Rank this' in task:
                    self.assertEqual(json.loads(data['candidate_facts']['preference.targeting']), profile['targeting'])
                    result['dimensions']['career_direction'] = {
                        'score': 4, 'explanation': 'Aligns with the saved next move',
                        'job_quotes': ['partner onboarding'], 'candidate_source_ids': ['preference.targeting']}
                return result
        assessment = rank(posting, profile, Model())
        self.assertEqual(assessment['dimensions']['career_direction']['score'], 4)
        tailor(posting, profile, Model())
        self.assertEqual(len(calls), 2)

    def test_partial_targeted_reads_preserve_jobs_and_retry_transient_failures_after_five_minutes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); profile = root / 'profile.json'; write_json(profile, example_profile())
            controller = SearchController(root, profile)
            lead = {'url': 'https://example.test/timeout', 'title': 'Researcher',
                    'company': '', 'location': '', 'reason': ''}
            def reader(*args):
                raise PostingUnavailable({'reason': 'Temporary timeout', 'queue_status': 'retryable'})
            accepted, rejected = verify_postings([lead], None, root / 'check', reader=reader)
            self.assertEqual(rejected[0]['state'], 'retryable')
            def targeted(entry, store, directory):
                with patch('joblazy.targeted_search.find_postings', return_value={'jobs': [lead], 'gaps': []}), \
                     patch('joblazy.targeted_search.verify_postings', return_value=([job('https://example.test/ok')], rejected)):
                    return discover_targeted(entry, None, None, store, directory)
            with closing(Store(root / 'jobs.sqlite')) as store, patch.object(controller, 'targeted', side_effect=targeted) as calls:
                first = controller.scan({**PLAN, 'sources': ['web_search']}, store)
                self.assertEqual(first['report']['new_unique_jobs'], 1)
                self.assertEqual(first['report']['errors'][0]['error'], 'Temporary timeout')
                path = next((root / 'search/sources').glob('*/report.json'))
                saved = read_json(path)
                saved['fetched_at'] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
                write_json(path, saved)
                second = controller.scan({**PLAN, 'sources': ['web_search']}, store)
                self.assertEqual(calls.call_count, 2)
                self.assertFalse(second['cached'])
                self.assertEqual(second['report']['new_unique_jobs'], 0)

    def test_verified_related_titles_reach_ranking_only_for_the_current_search(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); profile = example_profile(); path = root / 'profile.json'; write_json(path, profile)
            controller = SearchController(root, path)
            plan = {**PLAN, 'sources': ['web_search'], 'queries': ['user researcher']}
            entry = boards_for(plan, profile['targeting'])['boards'][0]
            url = 'https://jobs.ashbyhq.com/fictional/12345678-1234-1234-1234-123456789abc'
            with closing(Store(root / 'jobs.sqlite')) as store:
                included = store.ingest(job(url + '/application', 'Design Researcher'))
                from joblazy.pipeline import ingest_discovery_result
                report = ingest_discovery_result({'jobs': [job(url, 'Design Researcher')], 'errors': [],
                    'source_runs': [{'entry': entry, 'status': 'completed', 'urls': [url]}]}, store,
                    root / 'search/sources' / digest(entry) / 'checkpoint.json')
                self.assertEqual(report['new_unique_jobs'], 0)
                self.assertEqual(report['exact_route_joins'][0]['id'], included)
                unrelated = store.ingest(job('https://example.test/unrelated', 'Accountant'))
                write_json(root / 'search/plan.json', {'plan': plan, 'confirmed': True,
                    'created_at': datetime.now(timezone.utc).isoformat(), 'profile_hash': digest(profile)})
                self.assertEqual(controller.snapshot()['verified_related_roles'], 1)
                def run(*args, **kwargs):
                    self.assertNotIn(included, kwargs['exclude'])
                    self.assertIn(unrelated, kwargs['exclude'])
                    return [{'id': included, 'status': 'assessment_failed'}]
                with patch('playwright.sync_api.sync_playwright'), patch('joblazy.search.run_queue', side_effect=run) as runner:
                    result = controller.rank(plan, profile, store, 1)
                    self.assertIn('1 unresolved', result['message'])
                    runner.assert_called_once()
                with patch('playwright.sync_api.sync_playwright') as browser:
                    other = controller.rank({**plan, 'location': 'Tokyo, Japan'}, profile, store, 1)
                    self.assertEqual(other['results'], [])
                    browser.assert_not_called()

    def test_real_public_reader_preserves_structured_employer_and_location_metadata(self):
        from playwright.sync_api import sync_playwright
        description = job('unused')['description']
        posting = {'@type': 'JobPosting', 'title': 'Researcher', 'description': description,
                   'hiringOrganization': {'name': 'Observed Employer'},
                   'jobLocation': [{'address': {'addressLocality': 'Bristol', 'addressCountry': 'GB'}}],
                   'jobLocationType': 'TELECOMMUTE', 'applicantLocationRequirements': {'name': 'United Kingdom'}}
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                body = ('<h1>Researcher</h1><p>' + description + '</p><script type="application/ld+json">' + json.dumps(posting) + '</script>').encode()
                self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers(); self.wfile.write(body)
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp, sync_playwright() as pw:
                channel = os.environ.get('JOBLAZY_TEST_BROWSER_CHANNEL', 'chrome')
                browser = pw.chromium.launch(headless=True, **({'channel': channel} if channel != 'chromium' else {}))
                try:
                    with patch('joblazy.discovery.public_url', return_value=True):
                        observed = enrich({'url': f'http://127.0.0.1:{server.server_port}/role', 'title': 'Researcher'}, browser, Path(temp))
                    company, location = source_labels(read_json(Path(temp) / 'posting.json')['source_metadata'])
                    self.assertEqual(company, 'Observed Employer')
                    self.assertIn('Bristol, GB', location); self.assertIn('Remote: United Kingdom', location)
                    self.assertEqual(observed['description'], description)
                finally: browser.close()
        finally: server.shutdown(); server.server_close(); thread.join()

    def test_each_new_web_scan_delegates_again_and_preserves_durable_intake(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); profile = root / 'profile.json'; write_json(profile, example_profile())
            controller = SearchController(root, profile)
            def targeted(entry, store, directory):
                self.assertEqual(entry['brief'], example_profile()['targeting'])
                from joblazy.pipeline import ingest_discovery_result
                data = {'jobs': [job('https://example.test/web')], 'errors': [], 'source_runs': [
                    {'entry': entry, 'status': 'completed', 'urls': ['https://example.test/web'], 'warnings': []}]}
                return ingest_discovery_result(data, store, directory / 'checkpoint.json')
            with closing(Store(root / 'jobs.sqlite')) as store, patch.object(controller, 'targeted', side_effect=targeted) as web:
                first = controller.scan({**PLAN, 'sources': ['web_search']}, store)
                second = controller.scan({**PLAN, 'sources': ['web_search']}, store)
                self.assertEqual(web.call_count, 2)
                self.assertEqual(first['report']['new_unique_jobs'], 1)
                self.assertFalse(second['cached']); self.assertEqual(second['report']['new_unique_jobs'], 0)


if __name__ == '__main__': unittest.main()
