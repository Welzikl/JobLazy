import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from joblazy.answers import questions,save_answer
from joblazy.checkpoints import load_materials
from joblazy.common import NeedsInput,read_json,write_json
from joblazy.inspection import inspect_application
from joblazy.pipeline import run_queue
from joblazy.review import render_review
from joblazy.store import Store
from .support import FixtureModel,example_profile,fixture_server,job


class InspectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(channel='chrome',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name);self.store=Store(self.data/'jobs.sqlite');self.addCleanup(self.store.close)
        self.profile=example_profile();self.profile_path=self.data/'profile.json';write_json(self.profile_path,self.profile)

    def test_ranked_role_can_be_inspected_answered_and_prepared_without_submission(self):
        from joblazy.assist import prepare_assisted
        with fixture_server() as (origin,received):
            key=self.store.ingest(job(origin+'/unknown'));directory=self.data/'applications'/key
            ranked=run_queue(self.store,self.profile,FixtureModel(),self.browser,self.data/'applications',1,rank_only=True,fixture_origin=origin)
            self.assertEqual(ranked[0]['status'],'ranked');self.assertFalse((directory/'cv.pdf').exists())
            inspect_application(self.store,key,self.profile,self.browser,directory,fixture_origin=origin)
            saved=save_answer(self.store,key,directory,self.profile_path,'Work authorization','Yes')
            self.assertEqual(saved['status'],'ranked');self.assertEqual(received,[])
            page,status=prepare_assisted(self.store,key,read_json(self.profile_path),FixtureModel(),self.browser,self.data,fixture_origin=origin)
            try:
                self.assertEqual(status,'prepared');self.assertEqual(self.store.get(key)['status'],'manual_review')
                self.assertEqual(page.locator('select[name=authorization]').input_value(),'Yes')
                self.assertEqual(page.locator('input[type=file]').evaluate('e=>e.files.length'),1)
                self.assertEqual(received,[])
            finally:page.close()

    def test_inspect_answer_and_prepare_reuses_cv_without_early_input_or_upload(self):
        with fixture_server() as (origin,received):
            key=self.store.ingest(job(origin+'/unknown'));directory=self.data/'applications'/key
            run_queue(self.store,self.profile,FixtureModel(),self.browser,self.data/'applications',1,fixture_origin=origin)
            before=self.store.list();original_pdf=(directory/'cv.pdf').read_bytes();page_values=[]
            real_browser=self.browser
            class ObservedBrowser:
                def new_page(inner):
                    page=real_browser.new_page();close=page.close
                    def inspect_then_close():
                        page_values.append(page.locator('input').evaluate_all('es=>es.map(e=>({type:e.type,value:e.value,files:e.files?.length||0}))'))
                        close()
                    page.close=inspect_then_close
                    return page
            report=inspect_application(self.store,key,self.profile,ObservedBrowser(),directory,fixture_origin=origin)
            self.assertEqual(report['inspection'],'inspected');self.assertEqual(self.store.list(),before)
            self.assertEqual(received,[])
            self.assertTrue(page_values)
            self.assertTrue(all(not f['value'] and not f['files'] for page in page_values for f in page))
            self.assertIn('Work authorization',[q['field'] for q in questions(self.store,key,directory,self.profile)['questions']])
            with self.assertRaises(NeedsInput):save_answer(self.store,key,directory,self.profile_path,'Work authorization','Maybe')
            saved=save_answer(self.store,key,directory,self.profile_path,'Work authorization','Yes')
            self.assertEqual(saved['status'],'materials_ready')
            updated=read_json(self.profile_path)
            self.assertNotIn('Work authorization',[q['field'] for q in questions(self.store,key,directory,updated)['questions']])
            self.assertIsNotNone(load_materials(directory,job(origin+'/unknown'),updated))
            class NoModel:
                def generate(self,*args):raise AssertionError('Inspection answers must not regenerate the CV')
            result=run_queue(self.store,updated,NoModel(),self.browser,self.data/'applications',1,prepare=True,submit=True,fixture_origin=origin,verify_seconds=1)
            self.assertEqual(result[0]['status'],'submitted');self.assertEqual((directory/'cv.pdf').read_bytes(),original_pdf)
            self.assertIn(b'Yes',received[0]['body']);self.assertIn(original_pdf,received[0]['body'])

    def test_profile_or_posting_drift_rejects_answer_without_profile_mutation(self):
        with fixture_server() as (origin,received):
            posting=job(origin+'/unknown');key=self.store.ingest(posting);directory=self.data/'applications'/key
            inspect_application(self.store,key,self.profile,self.browser,directory,fixture_origin=origin)
            changed=copy.deepcopy(self.profile);changed['minimum_score']=71;write_json(self.profile_path,changed)
            before=self.profile_path.read_bytes()
            with self.assertRaisesRegex(NeedsInput,'Profile changed'):save_answer(self.store,key,directory,self.profile_path,'Work authorization','Yes')
            self.assertEqual(self.profile_path.read_bytes(),before)
            write_json(self.profile_path,self.profile);self.store.ingest({**posting,'description':posting['description']+' Changed requirements.'})
            before=self.profile_path.read_bytes()
            with self.assertRaisesRegex(NeedsInput,'Posting changed'):save_answer(self.store,key,directory,self.profile_path,'Work authorization','Yes')
            self.assertEqual(self.profile_path.read_bytes(),before);self.assertEqual(received,[])

    def test_cli_show_refreshes_answers_and_explicit_correction_preserves_discovery(self):
        with fixture_server() as (origin,received):
            key=self.store.ingest(job(origin+'/unknown'));directory=self.data/'applications'/key
            inspect_application(self.store,key,self.profile,self.browser,directory,fixture_origin=origin)
            saved=save_answer(self.store,key,directory,self.profile_path,'Work authorization','No')
            self.assertEqual(saved['status'],'discovered')
            saved=save_answer(self.store,key,directory,self.profile_path,'Work authorization','Yes')
            profile=read_json(self.profile_path);self.assertEqual(len(profile['answers']),1);self.assertEqual(profile['answers'][0]['value'],'Yes')
            shown=subprocess.run([sys.executable,'-m','joblazy','--data',str(self.data),'show',key,'--profile',str(self.profile_path)],capture_output=True,text=True,check=True)
            self.assertNotIn('Work authorization',[q['field'] for q in json.loads(shown.stdout)['questions']])
            output=render_review(self.store,self.data,self.data/'review.html',profile=profile)
            html=Path(output['path']).read_text(encoding='utf-8')
            self.assertIn('Read-only form check',html);self.assertNotIn('Work authorization: No unambiguous',html)
            self.assertEqual(received,[])

    def test_protected_application_states_never_open_browser_or_release_ownership(self):
        class NoBrowser:
            def new_page(self):raise AssertionError('Protected job must not open a page')
        for state in ['processing','submitting','submission_unknown','submitted','manual_review']:
            key=self.store.ingest(job('https://example.test/'+state));self.store.transition(key,state)
            with self.assertRaises(NeedsInput):inspect_application(self.store,key,self.profile,NoBrowser(),self.data/'applications'/key)
            self.assertEqual(self.store.get(key)['status'],state)

    def test_failed_reinspection_replaces_old_questions_without_advancing_queue(self):
        with fixture_server() as (origin,received):
            key=self.store.ingest(job(origin+'/unknown'));directory=self.data/'applications'/key
            inspect_application(self.store,key,self.profile,self.browser,directory,fixture_origin=origin)
            with patch.object(self.browser,'new_page',side_effect=NeedsInput('Employer sign-in is required')):
                report=inspect_application(self.store,key,self.profile,self.browser,directory,fixture_origin=origin)
            self.assertEqual(report['inspection'],'needs_input')
            shown=questions(self.store,key,directory,self.profile)
            self.assertEqual(shown['questions'],[]);self.assertIn('sign-in',shown['reason'])
            with self.assertRaises(NeedsInput):save_answer(self.store,key,directory,self.profile_path,'Work authorization','Yes')
            self.assertEqual(self.store.get(key)['status'],'discovered');self.assertEqual(received,[])

if __name__=='__main__':unittest.main()
