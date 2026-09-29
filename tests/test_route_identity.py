import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from joblazy.store import Store,choice_job_hash
from joblazy.pipeline import run_queue
from joblazy.discovery_intake import ingest_jobs,identity
from joblazy.common import read_json
from .support import example_profile,job,FixtureModel


class RouteIdentityTests(unittest.TestCase):
    def test_alias_validation_hashes_only_rows_with_observations_once_per_call(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            keys=[store.ingest(job('https://aggregator.test/jobs/'+str(n))) for n in range(40)]
            old='https://lifeattiktok.com/search/1111111111111111111'
            new='https://lifeattiktok.com/search/2222222222222222222'
            store.record_application_route(keys[0],self.observation(old))
            store.record_application_route(keys[0],self.observation(new))
            store.record_application_route(keys[1],self.observation(old))
            rows=[row for row in store.list() if row['id']!=keys[1]]
            with patch('joblazy.store.choice_job_hash',wraps=choice_job_hash) as hashing:
                self.assertEqual(store.observed_routes(rows),{keys[0]:{identity(new)}})
                self.assertEqual(hashing.call_count,1)
            # A later content change must still invalidate the latest binding.
            store.ingest({**store.get(keys[0])['data'],'title':'Changed role'})
            self.assertEqual(store.observed_routes([store.get(keys[0])]),{})

    def test_shared_application_portals_do_not_merge_or_block_distinct_postings(self):
        portals=['https://employer.test/', 'https://employer.test/login?lang=en',
            'https://employer.test/en/careers', 'https://employer.test/company/apply',
            'https://jobs.ashbyhq.com/fictional', 'https://job-boards.greenhouse.io/fictional']
        for portal in portals:
            with self.subTest(portal=portal),tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
                first={**job('https://aggregator.test/jobs/first'),'application_url':portal}
                second={**job('https://aggregator.test/jobs/second'),'application_url':portal}
                prior=ingest_jobs(store,[first])['ids'][0]
                store.transition(prior,'submitted',{'receipt':'Fictional receipt'})
                self.assertIsNone(store.prior_application(second))
                result=ingest_jobs(store,[second])
                self.assertNotEqual(result['ids'],[prior]);self.assertEqual(len(store.list()),2)
                self.assertEqual(result['exact_route_joins'],[])
                self.assertEqual(store.get(result['ids'][0])['data']['application_url'],portal)

    def test_specific_application_routes_still_join_and_block_prior_applications(self):
        targets=['https://employer.test/jobs/operations-associate/apply',
            'https://employer.test/careers?gh_jid=123',
            'https://employer.test/apply?jobId=123',
            'https://jobs.ashbyhq.com/fictional/11111111-1111-1111-1111-111111111111/application']
        for target in targets:
            with self.subTest(target=target),tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
                prior=store.ingest({**job('https://aggregator.test/jobs/first'),'application_url':target})
                store.transition(prior,'submitted',{'receipt':'Fictional receipt'})
                self.assertEqual(store.prior_application(job(target))['id'],prior)
                result=ingest_jobs(store,[job(target)])
                self.assertEqual(result['ids'],[prior]);self.assertEqual(len(store.list()),1)

    def test_newly_observed_shared_login_does_not_stop_ranking(self):
        portal='https://employer.test/login'
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            prior=store.ingest({**job('https://aggregator.test/jobs/first'),'application_url':portal})
            store.transition(prior,'submitted',{'receipt':'Fictional receipt'})
            key=store.ingest(job('https://aggregator.test/jobs/second'))
            with patch('joblazy.discovery.enrich',side_effect=lambda p,*a,**k:{**p,'application_url':portal,
                '_application_route_observation':self.observation(portal)}):
                result=run_queue(store,example_profile(),FixtureModel(),None,Path(temp)/'applications',rank_only=True,only=key)
            self.assertEqual(result[0]['status'],'ranked')
            self.assertEqual(store.observed_routes([store.get(key)]),{})

    def observation(self,target):
        return {'url':target,'source_url':'https://aggregator.test/jobs/fictional',
            'checked_at':'2026-09-14T12:00:00Z','method':'visible apply link'}

    def test_newly_discovered_route_stops_prior_application_before_ranking(self):
        target='https://jobs.ashbyhq.com/fictional/11111111-1111-1111-1111-111111111111'
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            prior=store.ingest(job(target));store.transition(prior,'submitted',{'receipt':'fictional receipt'})
            key=store.ingest(job('https://aggregator.test/jobs/fictional'))
            class NoModel:
                def generate(self,*args):raise AssertionError('Known prior application must not consume inference')
            with patch('joblazy.discovery.enrich',side_effect=lambda posting,*a,**k:{**posting,'application_url':target}):
                result=run_queue(store,example_profile(),NoModel(),None,Path(temp)/'applications',rank_only=True,only=key)
            self.assertEqual(result[0]['status'],'needs_input')
            self.assertEqual(store.get(key)['result']['prior_job_id'],prior)

    def test_recorded_routes_survive_restart_without_mutating_jobs_and_join_future_feed(self):
        target='https://jobs.ashbyhq.com/fictional/11111111-1111-1111-1111-111111111111'
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'jobs.sqlite'
            with closing(Store(path)) as store:
                key=store.ingest(job('https://aggregator.test/jobs/fictional'))
                row=store.get(key)
                self.assertTrue(store.record_application_route(key,self.observation(target)))
                self.assertEqual(store.get(key),row)
            with closing(Store(path)) as store:
                result=ingest_jobs(store,[job(target+'/application')])
                self.assertEqual(result['ids'],[key]);self.assertEqual(len(store.list()),1)
                self.assertEqual(len(result['exact_route_joins']),1)
                self.assertIn(target+'/application',store.get(key)['data']['discovery_source_urls'])

    def test_changed_posting_invalidates_route_binding_but_never_rewrites_handoffs(self):
        target='https://jobs.ashbyhq.com/fictional/11111111-1111-1111-1111-111111111111'
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            original=job('https://aggregator.test/jobs/fictional');key=store.ingest(original)
            store.record_application_route(key,self.observation(target))
            # In one batch, source changes must invalidate the alias before the
            # formerly linked direct posting arrives. These now stay separate.
            result=ingest_jobs(store,[{**original,'title':'Different fictional role'},job(target)])
            self.assertEqual(len(store.list()),2);self.assertNotEqual(result['ids'][0],result['ids'][1])
            self.assertEqual(store.observed_routes([store.get(key)]),{})
            direct=result['ids'][1];store.transition(direct,'manual_review',{'note':'Fictional handoff'})
            before=store.get(direct)
            with self.assertRaisesRegex(ValueError,'handoff'):store.record_application_route(direct,self.observation(target))
            self.assertEqual(store.get(direct),before)

    def test_distinct_requisitions_and_generic_account_links_never_merge(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            keys=[]
            for n in (1111111111111111111,2222222222222222222):
                key=store.ingest(job('https://aggregator.test/jobs/'+str(n)));keys.append(key)
                target='https://lifeattiktok.com/search/'+str(n)
                self.assertTrue(store.record_application_route(key,self.observation(target)))
                self.assertEqual(identity(target),'tiktok:'+str(n))
            result=ingest_jobs(store,[job('https://lifeattiktok.com/search/'+str(n)) for n in (1111111111111111111,2222222222222222222)])
            self.assertEqual(result['ids'],keys);self.assertEqual(len(store.list()),2)
            for url in ('https://employer.test/login','https://jobs.ashbyhq.com/fictional','https://lifeattiktok.com/search'):
                self.assertFalse(store.record_application_route(keys[0],self.observation(url)))

    def test_replaced_link_does_not_accumulate_old_requisitions_as_current_aliases(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            key=store.ingest(job('https://aggregator.test/jobs/fictional'))
            old='https://lifeattiktok.com/search/1111111111111111111'
            new='https://lifeattiktok.com/search/2222222222222222222'
            store.record_application_route(key,self.observation(old));store.record_application_route(key,self.observation(new))
            self.assertEqual(store.observed_routes([store.get(key)])[key],{identity(new)})
            result=ingest_jobs(store,[job(old)])
            self.assertNotEqual(result['ids'],[key]);self.assertEqual(len(store.list()),2)

    def test_full_feed_description_read_retains_the_observed_link_without_following_it(self):
        from playwright.sync_api import sync_playwright
        from joblazy.discovery import enrich
        from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
        import threading
        target='https://jobs.ashbyhq.com/fictional/11111111-1111-1111-1111-111111111111'
        requests=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers()
                self.wfile.write(f'<main><h1>Partner Operations Associate</h1><a href="{target}">Apply at Fictional</a></main>'.encode())
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp,sync_playwright() as pw:
                browser=pw.chromium.launch(channel='chrome',headless=True);context=browser.new_context()
                context.on('request',lambda request:requests.append(request.url))
                try:
                    posting=job(f'http://127.0.0.1:{server.server_port}/fictional')
                    with patch('joblazy.discovery.public_url',return_value=True),patch('joblazy.routes.public_url',return_value=True):
                        result=enrich(posting,context,Path(temp),check_only=True)
                    self.assertEqual(result['description'],posting['description'])
                    self.assertEqual(result['application_url'],target)
                    self.assertEqual(result['_application_route_observation']['source_url'],posting['url'])
                    self.assertEqual(requests,[posting['url']])
                finally:browser.close()
        finally:server.shutdown();server.server_close();thread.join(timeout=5)

    def test_pipeline_records_observation_for_later_duplicate_outcome_checks(self):
        target='https://jobs.ashbyhq.com/fictional/11111111-1111-1111-1111-111111111111'
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            key=store.ingest(job('https://aggregator.test/jobs/fictional'));before=store.get(key)['data']
            with patch('joblazy.discovery.enrich',side_effect=lambda p,*a,**k:{**p,'application_url':target,
                '_application_route_observation':self.observation(target)}):
                result=run_queue(store,example_profile(),FixtureModel(),None,Path(temp)/'applications',rank_only=True,only=key)
            self.assertEqual(result[0]['status'],'ranked');self.assertEqual(store.get(key)['data'],before)
            saved=read_json(Path(temp)/'applications'/key/'ranking.json')
            self.assertNotIn('_application_route_observation',str(saved))
            store.transition(key,'submitted',{'receipt':'Fictional receipt'})
            self.assertEqual(store.prior_application(job(target))['id'],key)
