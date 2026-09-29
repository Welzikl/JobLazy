import copy
import json
import os
import subprocess
import tempfile
import threading
import unittest
from contextlib import closing
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from joblazy.common import ROOT, NeedsInput, digest, read_json, write_json
from joblazy.dashboard import dashboard_data, make_handler
from joblazy.locking import LockBusy, run_lock
from joblazy.pipeline import ingest_discovery_result, processing_priority, run_queue
from joblazy.search import SearchController, boards_for, generate_plan, query_matches
from joblazy.store import Store
from .support import FixtureModel, example_profile, fixture_server, job


PLAN = {'queries': ['partner operations', 'partnerships'], 'location': 'Bristol, United Kingdom',
        'sources': ['themuse'], 'categories': ['Business Operations'], 'reason': 'Look for partner coordination work in your chosen city.'}


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.data = self.root / 'runtime'
        self.path = self.root / 'local/profile.json'
        self.profile = example_profile()
        self.profile['targeting'] = {'desired_work': 'Coordinate partnerships', 'city': 'Bristol', 'country': 'United Kingdom'}
        self.profile['search_location'] = {'city': 'Bristol', 'country': 'United Kingdom'}
        self.profile['discovery_preferences'] = {'title_filter': {'midcareer_default': False}}
        write_json(self.path, self.profile)
        self.controller = SearchController(self.data, self.path)

    def finish(self, action, payload=None):
        self.controller.start(action, payload or {})
        self.controller.thread.join(20)
        self.assertFalse(self.controller.thread.is_alive())
        return self.controller.snapshot()['operation']

    def save(self):
        self.assertEqual(self.finish('save', {'plan': copy.deepcopy(PLAN)})['state'], 'complete')

    def test_no_verified_sources_skips_queue_lookup(self):
        with closing(Store(self.data / 'jobs.sqlite')) as store, \
             patch.object(store,'list',side_effect=AssertionError('No source URLs need queue lookup')):
            self.assertEqual(self.controller.verified_search_ids(PLAN,self.profile,store),set())

    def test_verified_sources_reuse_rows_but_preserve_alias_ambiguity(self):
        plan={**PLAN,'sources':['web_search']}
        entry=boards_for(plan,self.profile['targeting'])['boards'][0]
        url='https://lifeattiktok.com/search/1111111111111111111'
        checkpoint=self.controller.directory/'sources'/digest(entry)/'checkpoint.json'
        write_json(checkpoint,{'source_runs':[{'urls':[url]}]})
        with closing(Store(self.data / 'jobs.sqlite')) as store:
            key=store.ingest(job('https://aggregator.test/jobs/one'))
            store.record_application_route(key,{'url':url,'source_url':'https://aggregator.test/jobs/one',
                'checked_at':'2026-09-28T12:00:00Z','method':'visible apply link'})
            rows=store.list()
            with patch.object(store,'list',side_effect=AssertionError('Rows already loaded')):
                self.assertEqual(self.controller.verified_search_ids(plan,self.profile,store,rows=rows),{key})
            # A second saved record claiming the same exact route is ambiguous.
            store.ingest(job(url));rows=store.list()
            with patch.object(store,'list',side_effect=AssertionError('Rows already loaded')):
                self.assertEqual(self.controller.verified_search_ids(plan,self.profile,store,rows=rows),set())

    def test_delegation_runs_before_feeds_and_feed_failure_preserves_other_results(self):
        order = []
        plan = {**PLAN, 'sources': ['themuse', 'web_search', 'remotive']}
        def targeted(entry, store, directory):
            order.append('web_search')
            posting = job('https://example.test/delegated')
            return ingest_discovery_result({'jobs': [posting], 'errors': [], 'source_runs': [
                {'entry': entry, 'status': 'completed', 'urls': [posting['url']]}]}, store, directory / 'checkpoint.json')
        def feed(path, store, checkpoint, *, timeout):
            self.assertEqual(timeout, 45)
            entry = read_json(path)['boards'][0]; order.append(entry['provider'])
            if entry['provider'] == 'themuse': raise OSError('Fixture diagnostic must stay out of UI')
            posting = job('https://example.test/feed')
            return ingest_discovery_result({'jobs': [posting], 'errors': [], 'source_runs': [
                {'entry': entry, 'status': 'completed', 'urls': [posting['url']]}]}, store, checkpoint)
        with closing(Store(self.data / 'jobs.sqlite')) as store, \
             patch.object(self.controller, 'targeted', side_effect=targeted), \
             patch('joblazy.search.discover', side_effect=feed):
            first = self.controller.scan(plan, store)
            second = self.controller.scan(plan, store)
            self.assertEqual(len(store.list()), 2)
        self.assertEqual(order, ['web_search', 'themuse', 'remotive', 'web_search'])
        self.assertEqual(first['report']['new_unique_jobs'], 2)
        self.assertEqual(len(first['report']['errors']), 1)
        self.assertNotIn('Fixture diagnostic', json.dumps(first))
        self.assertEqual([source['status'] for source in second['sources']], ['completed', 'failed', 'completed'])
        self.assertTrue(second['sources'][1]['cached'])

    def test_planning_uses_each_future_brief_without_private_identity_or_employers(self):
        inputs = []
        class Model:
            def generate(_, task, data, schema):
                self.assertNotIn('uniqueItems', json.dumps(schema))
                inputs.append(data)
                desired = data['brief']['targeting']['desired_work']
                return {**PLAN, 'queries': [desired], 'location': data['brief']['targeting']['city']}
        other = copy.deepcopy(self.profile)
        other['targeting'].update(desired_work='Graduate chemical engineer', city='Berlin', country='Germany')
        plans = [generate_plan(p, Model()) for p in (self.profile, other)]
        self.assertNotEqual(plans[0]['queries'], plans[1]['queries'])
        self.assertNotEqual(plans[0]['location'], plans[1]['location'])
        self.assertNotIn(self.profile['applicant']['identity']['full_name'], json.dumps(inputs))
        self.assertNotIn('resume', json.dumps(inputs))
        self.assertEqual(boards_for(plans[1])['boards'][0]['themuse'], {'location': 'Berlin', 'category': 'Business Operations'})
        self.assertNotIn('company', json.dumps(boards_for(plans[1])))

    def test_saved_plan_survives_restart_but_not_changed_profile(self):
        self.save()
        before = self.path.read_bytes()
        restored = SearchController(self.data, self.path).snapshot()
        self.assertTrue(restored['plan']['confirmed'])
        self.assertEqual(before, self.path.read_bytes())
        self.profile['targeting']['city'] = 'Glasgow'; write_json(self.path, self.profile)
        self.assertIsNone(self.controller.snapshot()['plan'])
        self.assertEqual(self.finish('scan')['state'], 'needs_attention')

    def test_punctuation_cannot_match_every_role_and_new_users_have_no_legacy_level_bias(self):
        with self.assertRaises(ValueError): self.controller.start('save', {'plan': {**PLAN, 'queries': ['***']}})
        self.assertFalse(query_matches(job('https://example.test'), ['***']))
        self.assertEqual(query_matches({'title': 'Operations & Partner Manager'}, ['partner operations']), ['partner operations'])
        self.assertFalse(query_matches({'title': 'Operational Management'}, ['operations']))
        self.assertEqual(processing_priority({'title': 'Graduate Engineer'}, self.profile),
                         processing_priority({'title': 'Senior Engineer'}, self.profile))

    def test_busy_workers_and_cross_process_lock_do_not_start_duplicate_work(self):
        self.save(); started = threading.Event(); release = threading.Event()
        def hold(*args): started.set(); release.wait(10); return {}
        with patch.object(self.controller, 'scan', side_effect=hold):
            self.controller.start('scan', {}); self.assertTrue(started.wait(5))
            with self.assertRaises(LockBusy): self.controller.start('scan', {})
            self.assertEqual(self.controller.snapshot()['operation']['state'], 'running')
            release.set(); self.controller.thread.join(5)
        with run_lock(self.data / 'run.lock'):
            self.assertEqual(self.finish('scan')['state'], 'needs_attention')
        write_json(self.data / 'search/operation.json', {'state': 'running', 'id': 'previous-process'})
        self.assertEqual(SearchController(self.data, self.path).snapshot()['operation']['state'], 'interrupted')

    def test_partial_source_results_are_durable_cached_and_never_empty_success(self):
        self.save()
        def scan(path, store, checkpoint, *, timeout):
            self.assertEqual(timeout, 45)
            self.assertEqual(read_json(path), boards_for(PLAN))
            result = {'jobs': [job('https://example.test/first')],
                      'errors': [{'board': 'The Muse', 'error': 'Page 2 failed'}],
                      'source_runs': [{'entry': boards_for(PLAN)['boards'][0], 'status': 'completed_with_warnings',
                                       'urls': ['https://example.test/first'], 'warnings': ['Only first page available']}]}
            return ingest_discovery_result(result, store, checkpoint)
        with patch('joblazy.search.discover', side_effect=scan) as scanner:
            first = self.finish('scan'); second = self.finish('scan')
        self.assertEqual(scanner.call_count, 1)
        self.assertEqual(first['result']['report']['new_unique_jobs'], 1)
        self.assertEqual(first['result']['sources'][0]['status'], 'completed_with_warnings')
        self.assertTrue(second['result']['cached'])
        self.assertTrue(self.controller.snapshot()['last_scan']['report']['errors'])
        self.assertEqual(self.controller.snapshot()['saved_roles'], 1)

    def test_changing_city_does_not_refetch_unchanged_remote_feed(self):
        plan = {**PLAN, 'sources': ['themuse', 'remotive']}
        calls = []
        def scan(path, store, checkpoint, *, timeout):
            self.assertEqual(timeout, 45)
            entry = read_json(path)['boards'][0]; calls.append(entry['provider'])
            return ingest_discovery_result({'jobs': [], 'errors': [], 'source_runs': [
                {'entry': entry, 'status': 'completed', 'urls': []}]}, store, checkpoint)
        with closing(Store(self.data / 'jobs.sqlite')) as store, patch('joblazy.search.discover', side_effect=scan):
            self.controller.scan(plan, store)
            result = self.controller.scan({**plan, 'location': 'Berlin, Germany'}, store)
        self.assertEqual(calls, ['themuse', 'remotive', 'themuse'])
        self.assertEqual([s['cached'] for s in result['sources']], [False, True])

    def test_real_muse_adapter_partial_page_failure_can_retry_after_five_minutes(self):
        script = r'''
          import muse from './vendor/career-ops/providers/themuse.mjs';
          const original=muse.fetch;
          muse.fetch=entry=>original(entry,{sleep:async()=>{},fetchJson:async url=>{
            if(new URL(url).searchParams.get('page')!=='0') throw new Error('Temporary page failure');
            return {page:0,page_count:2,results:[{name:'Researcher',company:{name:'Fictional'},
              refs:{landing_page:'https://example.test/research'},locations:[{name:'Bristol, United Kingdom'}]}]};
          }});
          process.argv=['node','scan.mjs',...process.argv.slice(1)];
          await import('./scripts/scan.mjs');
        '''
        real_run = subprocess.run
        def scanner(args, **kwargs):
            return real_run(['node', '--input-type=module', '-e', script, args[2], args[3]], cwd=ROOT, **kwargs)
        with closing(Store(self.data / 'jobs.sqlite')) as store, patch('joblazy.pipeline.subprocess.run', side_effect=scanner) as calls:
            first = self.controller.scan(PLAN, store)
            self.assertTrue(first['report']['errors'])
            self.assertEqual(first['sources'][0]['status'], 'completed_with_warnings')
            self.assertEqual(first['report']['new_unique_jobs'], 1)
            report_path = next((self.data / 'search/sources').glob('*/report.json'))
            saved = read_json(report_path)
            saved['fetched_at'] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
            write_json(report_path, saved)
            second = self.controller.scan(PLAN, store)
            self.assertEqual(calls.call_count, 2)
            self.assertFalse(second['cached'])
            self.assertEqual(second['report']['new_unique_jobs'], 0)

    def test_rank_respects_persisted_request_budget_before_opening_browser(self):
        self.save()
        from joblazy.worker import utc_day
        with closing(Store(self.data / 'jobs.sqlite')) as store:
            for _ in range(50): store.reserve_model_request(utc_day(), 50)
        with patch('playwright.sync_api.sync_playwright') as browser:
            outcome = self.finish('rank', {'limit': 5})
        self.assertEqual(outcome['state'], 'needs_attention')
        self.assertIn('allowance', outcome['error'])
        browser.assert_not_called()

    def test_shared_daily_job_allowance_preserves_usage_and_stops_at_25(self):
        with closing(Store(self.data / 'jobs.sqlite')) as store:
            key=store.ingest(job('https://example.test/allowance'))
            for _ in range(24):
                store.transition(key,'processing',{})
                store.transition(key,'retryable',{})
            with patch('joblazy.shortlist_flow.shortlist_verified',return_value={'shortlist':[]}) as review:
                self.controller.shortlist(PLAN,self.profile,store,5)
                self.assertEqual(review.call_args.kwargs['limit'],1)
            store.transition(key,'processing',{})
            store.transition(key,'retryable',{})
            with patch('joblazy.shortlist_flow.shortlist_verified') as review:
                with self.assertRaises(NeedsInput):self.controller.shortlist(PLAN,self.profile,store,5)
                review.assert_not_called()
        snapshot=self.controller.snapshot()
        self.assertEqual(snapshot['usage']['job_attempts'],25)
        self.assertEqual(snapshot['limits'],{'daily_jobs':25,'daily_requests':50})

    @patch('joblazy.dashboard.CodexModel.status', return_value={'available': True})
    def test_feed_jobs_and_low_fit_results_remain_accessible(self, _status):
        with closing(Store(self.data / 'jobs.sqlite')) as store:
            for index in range(40):
                key = store.ingest({**job('https://example.test/' + str(index)), 'ats': 'themuse'})
            store.transition(key, 'not_selected', {'score': 42, 'reason': 'Fictional mismatch'})
        inventory = dashboard_data(self.data, self.path, 'saved')
        self.assertEqual(len(inventory['jobs']), 40)
        self.assertEqual(dashboard_data(self.data, self.path, 'ats')['jobs'], [])
        reviewed = dashboard_data(self.data, self.path, 'all')['jobs']
        self.assertEqual(reviewed[0]['score'], 42)
        self.assertFalse(reviewed[0]['can_prepare'])

    def test_browser_search_controls_reach_real_rank_pipeline_without_submitting(self):
        from playwright.sync_api import sync_playwright
        channel = os.environ.get('JOBLAZY_TEST_BROWSER_CHANNEL', 'chrome')
        with fixture_server() as (origin, received):
            def scan(path, store, checkpoint, *, timeout):
                self.assertEqual(timeout, 45)
                jobs = [job(origin + '/success'), job(origin + '/other', 'Civil Engineer')]
                result = {'jobs': jobs, 'errors': [], 'source_runs': [
                    {'entry': boards_for(PLAN)['boards'][0], 'status': 'completed', 'urls': [j['url'] for j in jobs]}]}
                return ingest_discovery_result(result, store, checkpoint)
            def fixture_run(*args, **kwargs):
                return run_queue(*args, **kwargs, fixture_origin=origin)
            with patch('joblazy.search.generate_plan', return_value=copy.deepcopy(PLAN)), \
                 patch('joblazy.search.discover', side_effect=scan), \
                 patch('joblazy.search.SearchController.model', return_value=FixtureModel()), \
                 patch('joblazy.search.run_queue', side_effect=fixture_run), \
                 patch('joblazy.dashboard.CodexModel.status', return_value={'available': True}):
                server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.data, self.path, 'test-token', browser_channel=channel))
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    connection = HTTPConnection('127.0.0.1', server.server_port)
                    connection.request('POST', '/api/search/scan', body='{}')
                    response = connection.getresponse(); self.assertEqual(response.status, 403); response.read(); connection.close()
                    with sync_playwright() as pw:
                        browser = pw.chromium.launch(headless=True, **({'channel': channel} if channel != 'chromium' else {}))
                        try:
                            page = browser.new_page(); errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
                            page.goto(f'http://127.0.0.1:{server.server_port}/search')
                            page.get_by_role('button', name='Suggest search plan').click()
                            page.wait_for_function("document.querySelector('#planSection').className !== 'hidden'")
                            page.get_by_role('button', name='Save search plan', exact=True).click()
                            page.wait_for_function("!document.querySelector('#scan').disabled")
                            page.get_by_role('button', name='Fetch vacancies', exact=True).click()
                            page.wait_for_function("document.querySelector('#counts').textContent.includes('2 saved roles')")
                            page.reload(); page.wait_for_function("document.querySelector('#counts').textContent.includes('1 title matches')")
                            page.get_by_role('button', name='Rank matching roles', exact=True).click()
                            page.wait_for_function("document.querySelector('#status').textContent.includes('Ranking finished')", timeout=20000)
                            page.get_by_role('link', name='Review fit scores', exact=True).click()
                            page.get_by_role('heading', name='Partner Operations Associate', exact=True).wait_for()
                            self.assertIn('85', page.locator('#jobs').inner_text())
                            self.assertEqual(errors, [])
                            self.assertEqual(received, [])
                            with closing(Store(self.data / 'jobs.sqlite')) as store:
                                rows = store.list()
                            self.assertEqual({r['data']['title']: r['status'] for r in rows},
                                             {'Partner Operations Associate': 'ranked', 'Civil Engineer': 'discovered'})
                        finally: browser.close()
                finally: server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__':
    unittest.main()
