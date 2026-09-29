"""One fictional new person uses only visible controls through outcome recording."""
from contextlib import closing
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
import copy
import os
import tempfile
import threading
import unittest
from unittest.mock import patch

from joblazy.application_ui import ApplicationController
from joblazy.assist import prepare_assisted, resume_assisted
from joblazy.assist_bridge import BrowserBridge
from joblazy.common import read_json
from joblazy.dashboard import make_handler
from joblazy.store import Store
from .support import FixtureModel, fixture_server, job
from .test_first_run_e2e import DashboardIntakeModel
from .test_onboarding import CV
from .test_search import PLAN


class FriendJourneyTests(unittest.TestCase):
    def test_fresh_intake_six_luna_searches_selected_cv_questions_resume_and_outcome(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin, received):
            data=Path(temp)/'runtime'; profile=Path(temp)/'local/profile.json'
            channel=os.environ.get('JOBLAZY_TEST_BROWSER_CHANNEL','chrome')
            calls=[]; errors=[]; workers=[]; stop=threading.Event();resumed=threading.Event()

            class CandidateModel(FixtureModel):
                def generate(inner, task, payload, schema):
                    if 'Tailor the CV' in task:
                        return {'summary':{'text':'Operations coordinator.','source_ids':['summary']},
                                'experience':[{'index':0,'bullets':[{'text':'Coordinated onboarding for 20 partners.',
                                                                  'source_ids':['experience.0.0']}]}], 'project_indices':[]}
                    return super().generate(task,payload,schema)

            class Scout:
                def __init__(inner, cache, **kwargs):
                    self.assertEqual(kwargs['model'],'gpt-6-luna'); inner.reserve=kwargs['before_request']
                def generate(inner,*args):
                    inner.reserve();calls.append('scout')
                    return {'jobs':[{'url':'https://example.test/fictional-role','title':'Partner Operations Associate',
                                     'company':'','location':'','reason':''}], 'gaps':[]}

            class Reviewer:
                def __init__(inner, cache, **kwargs):
                    self.assertEqual(kwargs['model'],'gpt-6-luna');inner.reserve=kwargs['before_request']
                def generate(inner,task,payload,schema):
                    inner.reserve();calls.append('shortlist')
                    return {'results':[{'id':row['id'],'recommend':True,'reason':'Documented partner onboarding experience.',
                            'job_quotes':['partner onboarding'],'candidate_source_ids':['experience.0.0'],
                            'caveats':['Full assessment still required.']} for row in payload['jobs']]}

            def application_model(data,store,name):
                self.assertEqual(name,'gpt-6-luna');calls.append('application_model')
                return CandidateModel()

            def controller(*args,**kwargs):
                return ApplicationController(*args,**kwargs,fixture_origin=origin)

            def verify(url,**kwargs):
                return {'status':'verified','job':{**job(origin+'/friend'), 'location':'Bristol, United Kingdom',
                                                   'observed_at':datetime.now(timezone.utc).isoformat()}}

            def launcher(command):
                self.assertEqual(command[command.index('--model')+1],'gpt-6-luna')
                self.assertIn('--ui-session',command)
                key=command[command.index('assist')+1]
                def run():
                    try:
                        with closing(Store(data/'jobs.sqlite')) as store, sync_playwright() as pw:
                            browser=pw.chromium.launch(headless=True,**({'channel':channel} if channel!='chromium' else {}))
                            context=browser.new_context();bridge=BrowserBridge(store,key)
                            try:
                                page,status=prepare_assisted(store,key,read_json(profile),CandidateModel(),context,data,
                                                            fixture_origin=origin,prompt=bridge.wait,
                                                            reviewed_cv_sha256=command[command.index('--reviewed-cv-sha256')+1],
                                                            profile_path=profile)
                                page.evaluate('window.originalCV=document.querySelector("[name=resume]").files[0]')
                                while not stop.is_set() and not page.is_closed():
                                    response=bridge.wait(page,'Fixture preparation',stop_when=lambda:stop.is_set())
                                    if response!='resume':break
                                    status=resume_assisted(store,key,profile,CandidateModel(),page,data)
                                    self.assertEqual(page.locator('[name=authorization]').input_value(),'Yes')
                                    self.assertTrue(page.evaluate('window.originalCV===document.querySelector("[name=resume]").files[0]'))
                                    self.assertEqual(status,'prepared')
                                    resumed.set()
                            finally:bridge.close();context.close();browser.close()
                    except Exception as error:errors.append(repr(error))
                worker=threading.Thread(target=run,daemon=True);workers.append(worker);worker.start()

            plan={**copy.deepcopy(PLAN),'sources':['web_search']}
            with patch('joblazy.dashboard.CodexModel',return_value=DashboardIntakeModel()), \
                 patch('joblazy.search.generate_plan',return_value=plan), \
                 patch('joblazy.search.CodexWebSearch',Scout), patch('joblazy.search.CodexModel',Reviewer), \
                 patch('joblazy.ats_postings.verify_posting',side_effect=verify), \
                 patch('joblazy.application_ui.ApplicationController',side_effect=controller), \
                 patch('joblazy.application_ui.account_model',side_effect=application_model):
                server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(data,profile,'fixture-token',
                                          assist_launcher=launcher,browser_channel=channel,model_preset_name='friend'))
                thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
                try:
                    with sync_playwright() as pw:
                        browser=pw.chromium.launch(headless=True,**({'channel':channel} if channel!='chromium' else {}))
                        try:
                            page=browser.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                            page.goto(f'http://127.0.0.1:{server.server_port}/')
                            self.assertIn('gpt-6-luna',page.locator('body').inner_text())
                            page.locator('#cv').set_input_files({'name':'cv.txt','mimeType':'text/plain','buffer':CV.encode()})
                            page.get_by_role('button',name='Extract a draft with Codex').click();page.locator('#review').wait_for(state='visible')
                            for field,value in {'first_name':'Morgan','last_name':'Example','email':'morgan@example.test',
                                                'phone':'+442079460000','city':'Bristol','country':'United Kingdom'}.items():
                                page.locator('#identity-'+field).fill(value)
                            page.locator('#answer-0').fill('I coordinated partner onboarding documents.')
                            page.locator('#pref-desired_work').fill('Partner operations')
                            page.locator('#pref-city').fill('Bristol');page.locator('#pref-country').fill('United Kingdom')
                            page.locator('#confirmed').check();page.get_by_role('button',name='Save my reviewed profile').click()
                            page.locator('#finished').wait_for(state='visible')
                            page.get_by_role('link',name='Build my search').click()
                            page.get_by_role('button',name='Suggest search plan').click();page.locator('#planSection').wait_for(state='visible')
                            page.get_by_role('button',name='Save search plan',exact=True).click()
                            page.wait_for_function("!document.getElementById('search').disabled")
                            page.get_by_role('button',name='Search and review',exact=True).click()
                            page.get_by_role('link',name='Review this application',exact=True).wait_for(timeout=20000)
                            self.assertEqual(calls.count('scout'),6);self.assertEqual(calls.count('shortlist'),1)
                            screenshots=os.environ.get('JOBLAZY_TEST_SCREENSHOT_DIR')
                            if screenshots:
                                Path(screenshots).mkdir(parents=True,exist_ok=True)
                                page.screenshot(path=str(Path(screenshots)/'fictional-shortlist.png'),full_page=True)
                            page.get_by_role('link',name='Review this application',exact=True).click()
                            page.get_by_role('button',name='Select and assess this role').click()
                            page.wait_for_function("document.getElementById('state').textContent.includes('Status: ranked')",timeout=30000)
                            self.assertFalse(list((data/'applications').glob('*/cv.pdf')))
                            page.get_by_role('button',name='Create tailored CV').click()
                            page.locator('#pdf').wait_for(state='visible',timeout=30000)
                            with page.expect_popup() as preview:page.locator('#pdf').click()
                            preview.value.close()
                            page.locator('#cvReviewed').check();page.get_by_role('button',name='Prepare employer form').click()
                            page.get_by_label('Work authorization',exact=True).wait_for(timeout=30000)
                            if screenshots:page.screenshot(path=str(Path(screenshots)/'fictional-application.png'),full_page=True)
                            for label,value in [('Work authorization','Yes'),('Optional portfolio','https://example.test/portfolio')]:
                                control=page.get_by_label(label,exact=True)
                                if not control.count():continue
                                form=page.locator('form').filter(has=control)
                                if label=='Work authorization':control.select_option(label=value)
                                else:control.fill(value)
                                form.get_by_role('checkbox').check();form.get_by_role('button',name='Save answer').click()
                                control.wait_for(state='detached')
                            page.get_by_role('button',name='Continue in the open form').click()
                            self.assertTrue(resumed.wait(10),repr(errors))
                            page.wait_for_function("document.getElementById('session').textContent.includes('Review the employer browser')")
                            page.locator('#outcome').select_option('not-submitted')
                            page.locator('#note').fill('Reviewed the fictional form and deliberately did not submit.')
                            page.locator('#outcomeConfirmed').check();page.get_by_role('button',name='Save outcome').click()
                            page.wait_for_function("document.getElementById('state').textContent.includes('Status: needs input')")
                            self.assertEqual(received,[])
                        except Exception as error:
                            raise AssertionError('Visible journey stopped: '+page.locator('body').inner_text()[:7000]+' Worker errors: '+repr(errors)) from error
                        finally:browser.close()
                finally:
                    stop.set();server.shutdown();server.server_close();thread.join()
                    for worker in workers:worker.join(timeout=10)
                self.assertFalse(any(worker.is_alive() for worker in workers))
                self.assertEqual(errors,[])
                with closing(Store(data/'jobs.sqlite')) as store:
                    self.assertEqual(store.list()[0]['status'],'needs_input')
                    report=read_json(data/'applications'/store.list()[0]['id']/'browser.json')
                    self.assertTrue(report.get('artifact'))
