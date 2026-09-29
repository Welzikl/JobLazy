import json
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from joblazy.common import read_json
from joblazy.pipeline import run_queue, queue_candidates
from joblazy.store import Store
from .support import FixtureModel, example_profile, job


class DescriptionIdentityTests(unittest.TestCase):
    def test_only_formatting_or_exact_employer_prefix_can_explain_a_title_difference(self):
        from joblazy.discovery import description_identity
        from joblazy.common import PostingDescriptionError
        posting={'title':'Strategy & Operations','company':'Fictional'}
        with tempfile.TemporaryDirectory() as temp:
            for title in ('Strategy and Operations','Fictional - Strategy & Operations','Strategy & Operations | Fictional'):
                self.assertTrue(description_identity(posting,{'title':title,'postings':[]},Path(temp))['matched'])
            for title in ('Senior Strategy & Operations','Another Company - Strategy & Operations','Strategy & Operations Careers'):
                with self.assertRaises(PostingDescriptionError):description_identity(posting,{'title':title,'postings':[]},Path(temp))
            with self.assertRaises(PostingDescriptionError):
                description_identity(posting,{'title':posting['title'],'postings':[{'title':posting['title']},{}]},Path(temp))

    def test_homepage_and_wrong_posting_stop_before_inference_while_real_role_continues(self):
        calls=[]
        expected=job('unused')['title']
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                if self.path=='/redirect':
                    self.send_response(302);self.send_header('Location','/');self.end_headers();return
                title='Curious minds. Complex problems.' if self.path=='/' else expected
                description=job('unused')['description']
                if self.path=='/':
                    body='<h1>'+title+'</h1><p>'+('We combine research and technology to serve our customers. '*10)+'</p><h2>'+expected+'</h2><a href="/healthy">View vacancies</a>'
                elif self.path in ('/wrong-schema','/structured'):
                    posting={'@type':'JobPosting','title':'Finance Director' if self.path=='/wrong-schema' else expected,'description':description}
                    body='<h1>'+('We are hiring' if self.path=='/structured' else title)+'</h1><script type="application/ld+json">'+json.dumps(posting)+'</script>'
                else:body='<h1>'+title+'</h1><p>'+description+'</p>'
                self.send_response(200);self.send_header('Content-Type','text/html');self.end_headers()
                self.wfile.write(('<main>'+body+'</main>').encode())
        class Model(FixtureModel):
            def generate(self,task,data,schema):
                calls.append(data['job']['url']);return super().generate(task,data,schema)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store,sync_playwright() as pw:
                browser=pw.chromium.launch(channel='chrome',headless=True)
                base=f'http://127.0.0.1:{server.server_port}'
                paths=['/','/redirect','/wrong-schema','/healthy','/structured']
                keys={path:store.ingest({**job(base+path),'description':job('unused')['description'] if path=='/redirect' else ''}) for path in paths}
                with patch('joblazy.discovery.public_url',return_value=True):
                    run_queue(store,example_profile(),Model(),browser,Path(temp)/'applications',limit=10,rank_only=True)
                for path in paths[:3]:
                    row=store.get(keys[path]);self.assertEqual(row['status'],'processing_failed',path)
                    self.assertEqual(row['result']['failure_kind'],'posting_description')
                    self.assertFalse(row['result']['requires_user_input'])
                    self.assertTrue((Path(temp)/'applications'/keys[path]/'description-check.json').exists())
                    self.assertNotIn(base+path,calls)
                self.assertEqual(store.get(keys['/healthy'])['status'],'ranked')
                self.assertEqual(store.get(keys['/structured'])['status'],'ranked')
                for path in ('/healthy','/structured'):
                    saved=store.get(keys[path])['data']
                    self.assertIn('description_source',saved)
                    self.assertIn(job('unused')['description'],saved['description'])
                    # A later summary-only scan must not erase recovered evidence
                    # or restart a current assessment merely because it was saved.
                    store.ingest({**job(base+path),'description':''})
                    self.assertEqual(store.get(keys[path])['status'],'ranked')
                    self.assertEqual(store.get(keys[path])['data']['description'],saved['description'])
                self.assertEqual(set(calls),{base+'/healthy',base+'/structured'})
                self.assertEqual(queue_candidates(store,rank_only=True,profile=example_profile()),[])
                self.assertFalse(list(Path(temp).rglob('*.pdf')))
                browser.close()
        finally:server.shutdown();server.server_close()
