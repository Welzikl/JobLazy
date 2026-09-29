import tempfile
import threading
import unittest
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from joblazy.assist import prepare_assisted,resume_assisted,operator_prompt
from joblazy.answers import save_answer,questions
from joblazy.common import NeedsInput,read_json,write_json,digest
from joblazy.routes import resolve_application
from joblazy.store import Store
from .support import fixture_server,example_profile,FixtureModel,job


class AssistTests(unittest.TestCase):
    def test_live_resume_uses_saved_answers_preserves_edits_and_retains_original_upload(self):
        with tempfile.TemporaryDirectory() as temp,fixture_server() as (origin,received),sync_playwright() as pw:
            data=Path(temp);browser=pw.chromium.launch(channel='chrome',headless=True);context=browser.new_context()
            store=Store(data/'jobs.sqlite');key=store.ingest(job(origin+'/resume'));profile=example_profile();profile_path=data/'profile.json'
            profile['resume']['candidate']['phone']=''
            write_json(profile_path,profile)
            class NoModel:
                def generate(self,*args):raise AssertionError('Deterministic live resume requested a model')
            try:
                page,status=prepare_assisted(store,key,profile,FixtureModel(),context,data,fixture_origin=origin)
                self.assertEqual(status,'needs_input');directory=data/'applications'/key
                before={name:digest((directory/name).read_bytes()) for name in ('cv.pdf','materials-checkpoint.json')}
                page.evaluate('''()=>{window.keptFile=document.querySelector('[name=resume]').files[0];window.uploadChanges=0;
                  document.querySelector('[name=resume]').addEventListener('change',()=>window.uploadChanges++);}''')
                page.locator('[name=portfolio]').fill('https://portfolio.example.test/custom')
                page.locator('[name=email]').fill('operator-edit@example.test')
                command=subprocess.run([sys.executable,'-m','joblazy','--data',str(data),'answer',key,
                    '--profile',str(profile_path),'--question','Work authorization','--value','Yes'],
                    capture_output=True,text=True,check=True,timeout=15)
                saved=json.loads(command.stdout)
                self.assertEqual(saved['status'],'manual_review')
                self.assertEqual(page.locator('[name=authorization]').input_value(),'')
                updated=read_json(profile_path)
                # A form-only international number and postcode do not modify the CV.
                updated['applicant']['identity']['phone']='+447700900321'
                updated['discovery_preferences']={'max_posting_age_days':30,'title_filter':{'positive':['Operations']}}
                updated['applicant']['address']['postal_code']='SW1A 1AA';write_json(profile_path,updated)
                self.assertEqual(questions(store,key,directory,updated)['questions'][0]['field'],'Optional portfolio')
                self.assertEqual(updated['answers'][-1]['source']['method'],'operator_supplied')
                for _ in range(2):
                    self.assertEqual(resume_assisted(store,key,profile_path,NoModel(),page,data),'needs_input')
                    self.assertEqual(page.locator('[name=email]').input_value(),'operator-edit@example.test')
                    self.assertEqual(page.locator('[name=portfolio]').input_value(),'https://portfolio.example.test/custom')
                    self.assertEqual(page.locator('[name=authorization]').input_value(),'Yes')
                    self.assertEqual(page.locator('[name=phone]').input_value(),'+447700900321')
                    self.assertEqual(page.locator('[name=postal]').input_value(),'SW1A 1AA')
                    self.assertTrue(page.evaluate('window.keptFile===document.querySelector("[name=resume]").files[0]'))
                    self.assertEqual(page.evaluate('window.uploadChanges'),0)
                    issues=questions(store,key,directory,read_json(profile_path))['verification_issues']
                    self.assertIn({'field':'Email','reason':'Browser edit differs from the saved answer; left unchanged'},issues)
                    self.assertEqual(store.get(key)['status'],'manual_review');self.assertEqual(received,[])
                # Correct the conflicting browser edit ourselves; resume may verify it.
                page.locator('[name=email]').fill(profile['applicant']['identity']['email'])
                self.assertEqual(resume_assisted(store,key,profile_path,NoModel(),page,data),'prepared')
                self.assertEqual(before,{name:digest((directory/name).read_bytes()) for name in before})
                # Removing the attachment is an operator edit, not an invitation to reupload.
                page.locator('[name=resume]').set_input_files([])
                changes=page.evaluate('window.uploadChanges')
                self.assertEqual(resume_assisted(store,key,profile_path,NoModel(),page,data),'needs_input')
                self.assertEqual(page.evaluate('window.uploadChanges'),changes)
                self.assertEqual(page.locator('[name=resume]').evaluate('e=>e.files.length'),0)
                self.assertEqual(received,[])
            finally:browser.close();store.close()

    def test_resume_keeps_the_current_multistep_form_and_its_attachment(self):
        with tempfile.TemporaryDirectory() as temp,fixture_server() as (origin,received),sync_playwright() as pw:
            data=Path(temp);browser=pw.chromium.launch(channel='chrome',headless=True);store=Store(data/'jobs.sqlite')
            key=store.ingest(job(origin+'/multistep_unknown'));profile=example_profile();path=data/'profile.json';write_json(path,profile)
            class NoModel:
                def generate(self,*args):raise AssertionError('Saved answer needed no model')
            try:
                page,status=prepare_assisted(store,key,profile,FixtureModel(),browser,data,fixture_origin=origin)
                self.assertEqual(status,'needs_input');self.assertEqual(page.locator('[name=email]').count(),0)
                page.evaluate('window.keptFile=document.querySelector("[name=resume]").files[0]')
                save_answer(store,key,data/'applications'/key,path,'Work authorization','Yes')
                self.assertEqual(resume_assisted(store,key,path,NoModel(),page,data),'prepared')
                self.assertEqual(page.locator('[name=email]').count(),0)
                self.assertTrue(page.evaluate('window.keptFile===document.querySelector("[name=resume]").files[0]'))
                self.assertEqual(len(read_json(data/'applications'/key/'browser.json')['steps']),2)
                self.assertEqual(store.get(key)['status'],'manual_review');self.assertEqual(received,[])
            finally:browser.close();store.close()

    def test_resume_rejects_changed_profile_artifact_document_and_wrong_job_without_navigation(self):
        with tempfile.TemporaryDirectory() as temp,fixture_server() as (origin,received),sync_playwright() as pw:
            data=Path(temp);browser=pw.chromium.launch(channel='chrome',headless=True);store=Store(data/'jobs.sqlite')
            key=store.ingest(job(origin+'/unknown'));profile=example_profile();path=data/'profile.json';write_json(path,profile)
            try:
                page,_=prepare_assisted(store,key,profile,FixtureModel(),browser,data,fixture_origin=origin)
                with self.assertRaises(NeedsInput):resume_assisted(store,'other-job',path,None,page,data)
                changed=example_profile();changed['resume']['summary']='A different career claim';write_json(path,changed)
                with self.assertRaisesRegex(NeedsInput,'Career facts'):resume_assisted(store,key,path,None,page,data)
                write_json(path,profile);pdf=data/'applications'/key/'cv.pdf';original=pdf.read_bytes();pdf.write_bytes(original+b'changed')
                with self.assertRaisesRegex(NeedsInput,'checkpoint'):resume_assisted(store,key,path,None,page,data)
                pdf.write_bytes(original)
                page.reload()
                with self.assertRaisesRegex(NeedsInput,'document or step'):resume_assisted(store,key,path,None,page,data)
                self.assertEqual(page.locator('[name=email]').input_value(),'')
                self.assertEqual(page.locator('[name=resume]').evaluate('e=>e.files.length'),0)
                self.assertEqual(store.get(key)['status'],'manual_review');self.assertEqual(received,[])
            finally:browser.close();store.close()

    def test_prepared_page_stays_open_and_manual_outcome_survives_restart(self):
        with tempfile.TemporaryDirectory() as temp,fixture_server() as (origin,received),sync_playwright() as pw:
            data=Path(temp);profile_dir=data/'browser-profile'
            context=pw.chromium.launch_persistent_context(str(profile_dir),channel='chrome',headless=True)
            store=Store(data/'jobs.sqlite')
            key=store.ingest(job(origin+'/unknown'))
            page,status=prepare_assisted(store,key,example_profile(),FixtureModel(),context,data,fixture_origin=origin)
            self.assertEqual(status,'needs_input')
            self.assertFalse(page.is_closed())
            self.assertEqual(store.get(key)['status'],'manual_review')
            self.assertEqual(received,[])
            self.assertEqual(page.locator('[name=email]').input_value(),'alex@example.test')
            self.assertEqual(page.locator('[name=resume]').evaluate('e=>e.files.length'),1)
            # Closing without submitting, recording that fact, and explicitly
            # reopening reuses the same reviewed CV without inference.
            pdf=data/'applications'/key/'cv.pdf';modified=pdf.stat().st_mtime_ns
            page.close();store.reconcile(key,'not-submitted','Closed the fixture before submitting')
            class NoModel:
                def generate(self,*args):raise AssertionError('Assisted resume regenerated cached materials')
            page,status=prepare_assisted(store,key,example_profile(),NoModel(),context,data,fixture_origin=origin)
            self.assertEqual(pdf.stat().st_mtime_ns,modified)
            # Simulated operator action occurs only AFTER the preparation returns.
            page.locator('[name=authorization]').select_option(label='Yes')
            page.get_by_role('button',name='Submit application',exact=True).click()
            page.get_by_role('status').get_by_text('Application received.',exact=False).wait_for()
            self.assertEqual(len(received),1)
            self.assertEqual(store.get(key)['status'],'manual_review')
            context.add_cookies([{'name':'fictional-login','value':'persisted','url':origin,'expires':2000000000}])
            context.close();store.close()
            context=pw.chromium.launch_persistent_context(str(profile_dir),channel='chrome',headless=True)
            store=Store(data/'jobs.sqlite')
            try:
                self.assertTrue(any(c['name']=='fictional-login' for c in context.cookies(origin)))
                store.recover()
                self.assertEqual(store.get(key)['status'],'manual_review')
                with self.assertRaises(ValueError):store.transition(key,'retryable')
                with self.assertRaises(NeedsInput):
                    prepare_assisted(store,key,example_profile(),FixtureModel(),context,data,fixture_origin=origin)
                store.reconcile(key,'submitted','Verified the fictional local receipt')
                self.assertEqual(store.get(key)['status'],'submitted')
                self.assertEqual(len(received),1)
            finally:context.close();store.close()

    def test_read_only_routing_preserves_supplied_login_page(self):
        with tempfile.TemporaryDirectory() as temp,sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            context=browser.new_context()
            context.route('**/*',lambda r:r.fulfill(status=200,content_type='text/html',body='<h1>Login</h1><input type="password">'))
            page=context.new_page()
            with patch('joblazy.routes.public_url',return_value=True),self.assertRaises(NeedsInput):
                resolve_application({'url':'https://employer.test/login'},context,Path(temp),page=page)
            self.assertFalse(page.is_closed())
            self.assertEqual(page.url,'https://employer.test/login')
            self.assertEqual(read_json(Path(temp)/'application-route.json')['observations'][-1]['boundary'],'employer_sign_in')
            browser.close()

    def test_terminal_wait_keeps_browser_network_working(self):
        with sync_playwright() as pw,fixture_server() as (origin,received):
            browser=pw.chromium.launch(channel='chrome',headless=True);page=browser.new_page()
            page.goto(origin+'/success');hit=threading.Event()
            def route(r):
                r.fulfill(status=200,body='done');hit.set()
            page.route('**/prompt-probe',route)
            page.evaluate('setTimeout(()=>fetch("/prompt-probe"),200)')
            def terminal_input(message):
                hit.wait(timeout=5);return 'done'
            with patch('builtins.input',side_effect=terminal_input):
                self.assertEqual(operator_prompt(page,'Fixture wait'),'done')
            self.assertTrue(hit.is_set())
            browser.close()

    def test_terminal_eof_keeps_visible_review_open_until_operator_closes_it(self):
        closed=threading.Event()
        class Page:
            context=object()
            def is_closed(self):return closed.is_set()
            def wait_for_timeout(self,milliseconds):closed.wait(milliseconds/1000)
        timer=threading.Timer(.05,closed.set)
        timer.start()
        try:
            with patch('builtins.input',side_effect=EOFError):
                self.assertEqual(operator_prompt(Page(),'Fixture review'),'done')
            self.assertTrue(closed.is_set())
        finally:timer.cancel()

    def test_reconciled_outcome_releases_a_terminal_eof_review(self):
        class Page:
            context=object()
            def is_closed(self):return False
            def wait_for_timeout(self,milliseconds):pass
        reconciled=threading.Event()
        reconciled.set()
        with patch('builtins.input',side_effect=EOFError):
            self.assertEqual(operator_prompt(Page(),'Fixture review',stop_when=reconciled.is_set),'done')

    def test_batch_review_survives_closed_selected_tab_and_services_sibling(self):
        with sync_playwright() as pw,fixture_server() as (origin,received):
            browser=pw.chromium.launch(channel='chrome',headless=True)
            context=browser.new_context();first=context.new_page();second=context.new_page()
            hit=threading.Event()
            try:
                second.goto(origin+'/success')
                second.locator('[name=email]').fill('operator-edit@example.test')
                def route(r):
                    r.fulfill(status=200,body='done');hit.set()
                second.route('**/prompt-probe',route)
                second.evaluate('setTimeout(()=>fetch("/prompt-probe"),200)')
                first.close()
                def terminal_input(message):
                    hit.wait(timeout=5);return 'resume 2'
                with patch('builtins.input',side_effect=terminal_input):
                    command=operator_prompt(first,'Batch review',review_pages=[first,second])
                self.assertEqual(command,'resume 2')
                self.assertTrue(hit.is_set());self.assertFalse(second.is_closed())
                self.assertEqual(second.locator('[name=email]').input_value(),'operator-edit@example.test')
                self.assertEqual(received,[])
            finally:hit.set();browser.close()

    def test_batch_review_finishes_when_all_selected_pages_are_closed(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            context=browser.new_context();first=context.new_page();second=context.new_page()
            first.close();second.close();release=threading.Event()
            def terminal_input(message):
                release.wait(timeout=5);return 'resume 2'
            try:
                with patch('builtins.input',side_effect=terminal_input):
                    self.assertEqual(operator_prompt(first,'Batch review',review_pages=[first,second]),'done')
            finally:release.set();browser.close()

    def test_sign_in_can_resume_preparation_in_the_same_context(self):
        from joblazy.common import write_json
        with tempfile.TemporaryDirectory() as temp,fixture_server() as (origin,received),sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True);context=browser.new_context()
            data=Path(temp);store=Store(data/'jobs.sqlite');key=store.ingest(job(origin+'/unknown'));calls=[]
            def resolve(posting,ctx,directory,*,page):
                self.assertIs(ctx,context);calls.append(page)
                if len(calls)==1:
                    page.goto(origin+'/success')
                    write_json(directory/'application-route.json',{'observations':[{'boundary':'employer_sign_in'}]})
                    raise NeedsInput('Fixture sign-in required')
                self.assertTrue(any(c['name']=='signed-in' for c in ctx.cookies(origin)))
                return posting
            def prompt(page,message):
                self.assertEqual(store.get(key)['status'],'manual_review')
                context.add_cookies([{'name':'signed-in','value':'yes','url':origin}])
                return 'prepare'
            try:
                with patch('joblazy.discovery.public_url',return_value=True),patch('joblazy.assist.resolve_application',side_effect=resolve),patch('joblazy.browser.public_url',return_value=True):
                    page,status=prepare_assisted(store,key,example_profile(),FixtureModel(),context,data,prompt=prompt,emit=lambda _:None)
                self.assertEqual(status,'needs_input')
                self.assertEqual(len(calls),2)
                self.assertIs(calls[0],calls[1])
                self.assertFalse(page.is_closed())
                self.assertEqual(received,[])
            finally:browser.close();store.close()

    def test_not_submitted_handoff_requires_separate_retry(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'jobs.sqlite')
            try:
                key=store.ingest(job('https://example.test/job'))
                store.transition(key,'manual_review')
                result=store.reconcile(key,'not-submitted','Operator closed the form without submitting')
                self.assertEqual(result['status'],'needs_input')
                self.assertEqual(result['previous_status'],'manual_review')
            finally:store.close()
