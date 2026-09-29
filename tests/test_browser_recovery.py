import tempfile
import time
import unittest
from contextlib import closing,contextmanager
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from joblazy.common import write_json
from joblazy.pipeline import run_queue
from joblazy.store import Store
from joblazy.worker import Worker
from .support import example_profile,job,FixtureModel,fixture_server


class BrowserRecoveryTests(unittest.TestCase):
    def test_disconnect_during_posting_read_keeps_diagnostic_and_stops_batch(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store,sync_playwright() as pw:
            for name in ('one','two'):store.ingest(job('https://example.test/'+name))
            browser=pw.chromium.launch(channel='chrome',headless=True)
            new_page=browser.new_page
            def interrupted_page():
                page=new_page();goto=page.goto
                def interrupted_goto(*args,**kwargs):
                    browser.close()
                    return goto(*args,**kwargs)
                page.goto=interrupted_goto
                return page
            with patch.object(browser,'new_page',side_effect=interrupted_page),patch('joblazy.discovery.public_url',return_value=True):
                results=run_queue(store,example_profile(),FixtureModel(),browser,temp,rank_only=True)
            self.assertEqual(len(results),1)
            self.assertTrue(results[0]['browser_paused'])
            self.assertEqual(results[0]['availability']['state'],'temporary_failure')
            self.assertTrue((Path(temp)/results[0]['id']/'availability.json').is_file())
            self.assertEqual(sorted(r['status'] for r in store.list()),['discovered','retryable'])

    def test_closed_browser_stops_batch_and_restart_recovers_after_backoff(self):
        with tempfile.TemporaryDirectory() as temp,fixture_server() as (origin,received),sync_playwright() as pw:
            data=Path(temp);profile=data/'profile.json';boards=data/'boards.json'
            write_json(profile,example_profile());write_json(boards,{'boards':[]})
            with closing(Store(data/'jobs.sqlite')) as store:
                for name in ('one','two','three'):store.ingest(job(origin+'/'+name))
            current=[time.time()];launches=[];calls=[]
            class Model(FixtureModel):
                def generate(self,*args):calls.append(1);return super().generate(*args)
            @contextmanager
            def browser_factory():
                browser=pw.chromium.launch(channel='chrome',headless=True)
                launches.append(1)
                if len(launches)==1:browser.close()
                try:yield browser
                finally:
                    if browser.is_connected():browser.close()
            def worker():return Worker(data,profile,boards,rank_only=True,clock=lambda:current[0],
                scanner=lambda *a:{'discovered':0},browser_factory=browser_factory,
                model_factory=lambda s:Model())
            with patch('joblazy.discovery.public_url',return_value=True):
                first=worker().tick()
                self.assertEqual(len(first['results']),1)
                self.assertEqual(first['state'],'browser_backoff')
                self.assertTrue(first['results'][0]['browser_paused'])
                self.assertEqual(calls,[])
                with closing(Store(data/'jobs.sqlite')) as store:
                    self.assertEqual(sorted(r['status'] for r in store.list()),['discovered','discovered','retryable'])
                restarted=worker();second=restarted.tick()
                self.assertEqual(second['state'],'browser_backoff');self.assertEqual(len(launches),1)
                self.assertEqual(restarted.state['retries'],{})
                current[0]=restarted.state['next_browser_run']+1
                third=worker().tick()
            self.assertEqual([r['status'] for r in third['results']],['ranked']*3)
            self.assertEqual(third['state'],'processed');self.assertEqual(len(launches),2)
            self.assertEqual(len(calls),3);self.assertEqual(received,[])
            self.assertEqual(third['usage']['model_requests'],0)

    def test_disconnection_preserves_uncertain_submission_and_other_jobs(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store,sync_playwright() as pw:
            first=store.ingest(job('https://example.test/one'));second=store.ingest(job('https://example.test/two'))
            browser=pw.chromium.launch(channel='chrome',headless=True)
            def interrupted(*args,**kwargs):
                store.transition(first,'submitting',{'fixture':'durable submission intent'})
                browser.close();raise RuntimeError('Injected disconnect after submission intent')
            with patch('joblazy.discovery.enrich',side_effect=interrupted):
                results=run_queue(store,example_profile(),FixtureModel(),browser,temp,rank_only=True)
            self.assertEqual(len(results),1)
            self.assertEqual(store.get(first)['status'],'submission_unknown')
            self.assertEqual(store.get(second)['status'],'discovered')
            store.recover();self.assertEqual(store.get(first)['status'],'submission_unknown')
