import json
import tempfile
import threading
import subprocess
import sys
import unittest
from contextlib import closing
from datetime import datetime,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright,TimeoutError as BrowserTimeout
from joblazy.common import read_json
from joblazy.coverage import audit_rows
from joblazy.discovery import availability
from joblazy.pipeline import run_queue
from joblazy.store import Store
from .support import FixtureModel,example_profile,job


class AvailabilityTests(unittest.TestCase):
    def test_deadlines_and_closure_signals_do_not_invent_open_or_closed_status(self):
        now=datetime(2026,9,12,12,tzinfo=timezone.utc)
        def observe(value):
            return availability({'postings':[{'validThrough':value}]},200,now=now)
        for value in ('2026-09-13','2026-09-12','bad','2026-09-10T10:00:00',None):
            self.assertEqual(observe(value)['state'],'no_closure_observed')
        for value in ('2026-09-10','2026-09-12T11:59:00Z','2026-09-12T13:59:00+02:00'):
            self.assertEqual(observe(value)['state'],'deadline_expired')
        self.assertEqual(availability({'postings':[{'validThrough':'2000-01-01'},{}]},200,now=now)['state'],'no_closure_observed')
        self.assertEqual(availability({'headings':['This job is no longer available.']},200)['state'],'explicit_closure')
        self.assertEqual(availability({'text':'This job is no longer available.','headings':['Example role','Closed-loop operations']},200)['state'],'no_closure_observed')
        self.assertEqual(availability({},404)['state'],'page_unavailable')
        self.assertEqual(availability({},410)['state'],'page_unavailable')
        for code in (None,408,429,500,503):
            self.assertEqual(availability({},code)['queue_status'],'retryable')
        self.assertEqual(availability({},403)['state'],'access_unverified')

    def test_full_description_queue_checks_real_pages_before_any_model_work(self):
        requests=[];model_calls=[]
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                requests.append((self.command,self.path));kind=self.path.strip('/')
                status={'missing':404,'gone':410,'temporary':503}.get(kind,200)
                heading='This position has been filled.' if kind=='closed' else 'Partner Operations Associate'
                posting={'@type':'JobPosting','description':job('unused')['description'],
                    'validThrough':'2000-01-01' if kind=='expired' else '2099-01-01'}
                body='<main><h1>'+heading+'</h1><script type="application/ld+json">'+json.dumps(posting)+'</script></main>'
                self.send_response(status);self.send_header('Content-Type','text/html');self.end_headers();self.wfile.write(body.encode())
        class Model(FixtureModel):
            def generate(self,task,data,schema):
                if data['job']['url'].endswith('/healthy'):
                    self_test.assertEqual(data['job']['description'],job('unused')['description'])
                    self_test.assertNotIn('description_refresh_required',data['job'])
                model_calls.append(data['job']['url']);return super().generate(task,data,schema)
        self_test=self
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store,sync_playwright() as pw:
                data=Path(temp);browser=pw.chromium.launch(channel='chrome',headless=True)
                base=f'http://127.0.0.1:{server.server_port}'
                keys={kind:store.ingest(job(base+'/'+kind)) for kind in ('closed','expired','missing','gone','temporary','healthy','manual')}
                store.ingest({**job(base+'/healthy'),'description':'Earlier posting context requiring a fresh read. '*8,
                    'description_refresh_required':True,'description_retained_from':{'observed_at':'2026-01-01'}})
                store.transition(keys['manual'],'manual_review');before=store.get(keys['manual'])
                with patch('joblazy.discovery.public_url',return_value=True):
                    results=run_queue(store,example_profile(),Model(),browser,data/'applications',limit=10,rank_only=True)
                states={kind:store.get(key)['status'] for kind,key in keys.items()}
                self.assertEqual(states,{'closed':'posting_closed','expired':'posting_expired','missing':'posting_unavailable',
                    'gone':'posting_unavailable','temporary':'retryable','healthy':'ranked','manual':'manual_review'})
                self.assertEqual(model_calls,[base+'/healthy'])
                self.assertEqual(len(results),6);self.assertEqual(store.get(keys['manual']),before)
                self.assertFalse(list(data.rglob('cv.pdf')))
                self.assertTrue(all(method=='GET' for method,path in requests))
                self.assertFalse(any(path=='/manual' for method,path in requests))
                for kind,key in keys.items():
                    if kind=='manual':continue
                    evidence=read_json(data/'applications'/key/'availability.json')
                    self.assertEqual(evidence['requested_url'],base+'/'+kind)
                    self.assertIn('checked_at',evidence)
                    if kind!='healthy':self.assertFalse((data/'applications'/key/'ranking.json').exists())
                report=audit_rows(store.list())
                self.assertEqual(report['summary']['explicit_closed_flags'],1)
                self.assertEqual(report['availability_stops']['posting_expired'],1)
                # Even existing verified CVs must stop before reuse when closed.
                store.transition(keys['closed'],'materials_ready')
                cached={'job':store.get(keys['closed'])['data'],'ranking':{'score':85},'artifact':{'pdf':'existing.pdf'}}
                with patch('joblazy.discovery.public_url',return_value=True),patch('joblazy.pipeline.load_materials',return_value=cached),patch('joblazy.pipeline.apply') as apply:
                    result=run_queue(store,example_profile(),Model(),browser,data/'applications',prepare=True,only=keys['closed'])
                self.assertEqual(result[0]['status'],'posting_closed');apply.assert_not_called()
                self.assertEqual(model_calls,[base+'/healthy'])
                # The normal CLI can explicitly request a fresh check. It does
                # not reclassify a missing page as open or submit an application.
                retry=subprocess.run([sys.executable,'-m','joblazy','--data',str(data),'retry',keys['missing']],
                    capture_output=True,text=True,check=True,timeout=15)
                self.assertEqual(json.loads(retry.stdout)['status'],'retryable')
                with patch('joblazy.discovery.public_url',return_value=True):
                    again=run_queue(store,example_profile(),Model(),browser,data/'applications',rank_only=True,only=keys['missing'])
                self.assertEqual(again[0]['status'],'posting_unavailable')
                self.assertEqual(model_calls,[base+'/healthy'])
                # Navigation failure records a fresh transient observation,
                # replacing any previous successful observation in the sidecar.
                store.transition(keys['healthy'],'retryable')
                page=browser.new_page()
                with patch('joblazy.discovery.public_url',return_value=True),patch.object(browser,'new_page',return_value=page),patch.object(page,'goto',side_effect=BrowserTimeout('fixture timeout')):
                    failure=run_queue(store,example_profile(),Model(),browser,data/'applications',rank_only=True,only=keys['healthy'])
                self.assertEqual(failure[0]['status'],'retryable')
                self.assertEqual(read_json(data/'applications'/keys['healthy']/'availability.json')['state'],'temporary_failure')
                self.assertEqual(model_calls,[base+'/healthy'])
                browser.close()
        finally:
            server.shutdown();server.server_close();thread.join()
