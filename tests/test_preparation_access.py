import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from joblazy.common import read_json
from joblazy.checkpoints import load_materials
from joblazy.pipeline import run_queue
from joblazy.store import Store
from .support import example_profile,job,FixtureModel,fixture_server


class CountingModel(FixtureModel):
    def __init__(self):self.tasks=[]
    def generate(self,task,data,schema):
        self.tasks.append(task)
        return super().generate(task,data,schema)


class PreparationAccessTests(unittest.TestCase):
    def test_accessible_preparation_still_renders_attaches_and_saves_reusable_materials(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store,fixture_server() as (origin,received),sync_playwright() as pw:
            root=Path(temp);profile=example_profile();profile['example_only']=False
            posting=job(origin+'/success');key=store.ingest(posting);model=CountingModel()
            browser=pw.chromium.launch(channel='chrome',headless=True)
            allowed=lambda url:url.startswith(origin+'/')
            try:
                with patch('joblazy.routes.public_url',side_effect=allowed),patch('joblazy.discovery.public_url',side_effect=allowed),patch('joblazy.browser.public_url',side_effect=allowed):
                    result=run_queue(store,profile,model,browser,root/'applications',only=key,prepare=True,allow_live=True)
                self.assertEqual(result[0]['status'],'prepared',result)
                checkpoint=load_materials(root/'applications'/key,posting,profile)
                self.assertIsNotNone(checkpoint)
                self.assertEqual(checkpoint['job']['application_url'],origin+'/success')
                self.assertEqual(len(model.tasks),3)
                self.assertEqual(received,[])
            finally:browser.close()

    def test_inaccessible_employer_stops_after_fit_before_cv_calls_or_rendering(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store,fixture_server() as (origin,received),sync_playwright() as pw:
            root=Path(temp);profile=example_profile();profile['example_only']=False
            key=store.ingest({**job(origin+'/success'),'application_url':'https://employer.test/apply'});model=CountingModel()
            browser=pw.chromium.launch(channel='chrome',headless=True);context=browser.new_context();requests=[]
            def serve(route):
                requests.append((route.request.method,route.request.url))
                route.fulfill(status=403,content_type='text/html',body='<h1>Access check</h1>')
            context.route('https://employer.test/**',serve)
            try:
                with patch('joblazy.routes.public_url',return_value=True),patch('joblazy.discovery.public_url',return_value=True),patch('joblazy.pipeline.render',side_effect=AssertionError('CV rendering attempted before employer access check')):
                    result=run_queue(store,profile,model,context,root/'applications',only=key,prepare=True,allow_live=True)
                self.assertEqual(result[0]['status'],'needs_input',result)
                self.assertIn('HTTP 403',result[0]['reason'])
                self.assertEqual(len(model.tasks),1,'Only the fit assessment should use the model before inaccessible preparation pauses')
                self.assertTrue(model.tasks[0].startswith('Rank this'))
                self.assertFalse((root/'applications'/key/'cv.pdf').exists())
                self.assertEqual(read_json(root/'applications'/key/'ranking.json')['score'],85)
                self.assertTrue(all(method=='GET' for method,url in requests))
                self.assertEqual(received,[])
            finally:browser.close()
