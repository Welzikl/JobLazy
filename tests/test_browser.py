import tempfile
import unittest
import os
import json
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from joblazy.store import Store
from joblazy.pipeline import run_queue
from joblazy.browser import scan, fill_plan, verify_fields
from joblazy.mapping import plan_fields
from joblazy.answers import save_answer
from joblazy.checkpoints import load_materials
from joblazy.common import NeedsInput, write_json, read_json
from joblazy.worker import Worker
from joblazy.forms import open_application_form,is_application
from .support import FixtureModel, example_profile, fixture_server, job

class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start()
        channel=os.environ.get('JOBLAZY_TEST_BROWSER_CHANNEL','chrome')
        cls.browser=cls.pw.chromium.launch(headless=True,**({} if channel=='chromium' else {'channel':channel}))
    @classmethod
    def tearDownClass(cls): cls.browser.close(); cls.pw.stop()
    def test_interrupt_after_materials_does_not_claim_completed_preparation_timing(self):
        from contextlib import closing
        from joblazy.usage import summarize
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            key=store.ingest(job('http://fictional.test/interrupted'))
            with patch('joblazy.pipeline.apply',side_effect=KeyboardInterrupt),self.assertRaises(KeyboardInterrupt):
                run_queue(store,example_profile(),FixtureModel(),self.browser,Path(temp)/'applications',
                    prepare=True,fixture_origin='http://fictional.test')
            self.assertEqual(store.get(key)['status'],'materials_ready')
            report=summarize(Path(temp)/'model-cache',job_id=key)['workflow']
            self.assertEqual(report['completed_attempts'],0)
            self.assertEqual(report['incomplete_attempts'],1)
            self.assertIsNone(report['completed_attempt_seconds'])

    def test_ungrounded_draft_is_a_bounded_model_failure_and_other_jobs_continue(self):
        from contextlib import closing
        class BrokenDraft(FixtureModel):
            def __init__(self):self.bad_drafts=0
            def generate(self,task,data,schema):
                result=super().generate(task,data,schema)
                if 'Tailor the CV' in task and data['job']['url'].endswith('/bad'):
                    self.bad_drafts+=1;result['summary']['source_ids']=[]
                return result
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            from datetime import datetime,timezone,timedelta
            profile=example_profile();profile['discovery_preferences']={'max_posting_age_days':45}
            now=datetime.now(timezone.utc)
            keys=[store.ingest({**job('http://fictional.test/'+name),'postedAt':(now-timedelta(days=i)).isoformat()}) for i,name in enumerate(('bad','good'))]
            model=BrokenDraft()
            result=run_queue(store,profile,model,self.browser,temp,limit=2,fixture_origin='http://fictional.test')
            self.assertEqual([r['id'] for r in result],keys)
            bad=store.get(keys[0]);good=store.get(keys[1])
            self.assertEqual(bad['status'],'model_failed',result)
            self.assertFalse(bad['result']['requires_user_input'])
            self.assertEqual(bad['result']['failure_kind'],'tailoring_validation')
            self.assertEqual(model.bad_drafts,3)
            self.assertFalse((Path(temp)/keys[0]/'cv.pdf').exists())
            evidence=read_json(bad['result']['evidence_path'])
            self.assertEqual(evidence['rejected_draft']['summary']['source_ids'],[])
            self.assertEqual(good['status'],'materials_ready')
            self.assertTrue((Path(temp)/keys[1]/'cv.pdf').exists())
            self.assertEqual(run_queue(store,profile,model,self.browser,temp,fixture_origin='http://fictional.test'),[])
    def test_connected_workflow_and_unknowns_do_not_starve_queue(self):
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin,received):
            store=Store(Path(temp)/'queue.sqlite')
            try:
                keys=[store.ingest(job(origin+'/'+mode)) for mode in ('unknown','success')]
                results=run_queue(store,example_profile(),FixtureModel(),self.browser,temp,10,
                    prepare=True,submit=True,fixture_origin=origin,verify_seconds=1)
                self.assertEqual(store.get(keys[0])['status'],'needs_input',results)
                self.assertEqual(store.get(keys[1])['status'],'submitted',results)
                self.assertEqual(len(received),1)
                self.assertIn(b'%PDF-',received[0]['body'])
                self.assertIn(b'Alex Example',received[0]['body'])
                self.assertIn(b'London',received[0]['body'])
                # A second run must neither reprocess an exception nor duplicate a submission.
                self.assertEqual(run_queue(store,example_profile(),FixtureModel(),self.browser,temp,10,
                    prepare=True,submit=True,fixture_origin=origin),[])
                self.assertEqual(len(received),1)
            finally: store.close()
    def test_redirect_and_disappearing_form_are_not_success(self):
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin,received):
            store=Store(Path(temp)/'queue.sqlite')
            try:
                keys=[store.ingest(job(origin+'/'+mode)) for mode in ('redirect','disappear')]
                results=run_queue(store,example_profile(),FixtureModel(),self.browser,temp,10,
                    prepare=True,submit=True,fixture_origin=origin,verify_seconds=1)
                for key in keys: self.assertEqual(store.get(key)['status'],'submission_unknown',results)
                self.assertEqual(len(received),2)
            finally: store.close()
    def test_csp_and_dynamic_fields(self):
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin,received):
            store=Store(Path(temp)/'queue.sqlite')
            try:
                keys=[store.ingest(job(origin+'/'+mode)) for mode in ('csp','dynamic')]
                results=run_queue(store,example_profile(),FixtureModel(),self.browser,temp,10,
                    prepare=True,submit=True,fixture_origin=origin,verify_seconds=1)
                for key in keys: self.assertEqual(store.get(key)['status'],'submitted',results)
                dynamic=next(r for r in received if r['path']=='/submit/dynamic')
                self.assertIn(b'+442079460000',dynamic['body'])
                self.assertIn(b'alex@example.test',dynamic['body'])
            finally: store.close()
    def test_ashby_question_containers_and_button_groups(self):
        page=self.browser.new_page()
        try:
            page.set_content('''<div class="ashby-application-form-field-entry" data-field-path="location">
              <label class="ashby-application-form-question-title _required_xyz">Where are you currently located?</label>
              <input role="combobox" placeholder="Start typing..."></div>
              <div class="ashby-application-form-field-entry" data-field-path="work_auth">
              <label class="ashby-application-form-question-title _required_xyz">Are you authorized to work here?</label>
              <div class="ashby-application-form-input-yesno">
              <button type="button" data-option="yes" aria-pressed="false" onclick="this.setAttribute('aria-pressed','true')">Yes</button>
              <button type="button" data-option="no" aria-pressed="false">No</button>
              <input type="checkbox" style="display:none"></div></div>''')
            fields=scan(page)
            location=next(f for f in fields if 'located' in f['label'])
            self.assertTrue(location['required'])
            group=next(f for f in fields if f['type']=='button_group')
            self.assertTrue(group['required']); self.assertEqual(group['options'],['Yes','No'])
            p=example_profile()
            p['answers']=[{'question':group['label'],'scope':'fixture','value':'Yes'}]
            plan=plan_fields([group],p,'fixture')
            fill_plan(page,plan)
            self.assertEqual(page.get_by_role('button',name='Yes').get_attribute('aria-pressed'),'true')
        finally: page.close()

    def test_embedded_form_and_resume_parser_corrections(self):
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin,received):
            store=Store(Path(temp)/'queue.sqlite')
            try:
                keys=[store.ingest(job(origin+'/'+mode)) for mode in ('embedded','autofill','ambiguous')]
                results=run_queue(store,example_profile(),FixtureModel(),self.browser,temp,10,
                    prepare=True,submit=True,fixture_origin=origin,verify_seconds=1)
                self.assertEqual([store.get(k)['status'] for k in keys],['submitted','submitted','needs_input'],results)
                self.assertEqual(len(received),2)
                for receipt in received:
                    self.assertIn(b'%PDF-',receipt['body'])
                    self.assertIn(b'alex@example.test',receipt['body'])
                    self.assertNotIn(b'wrong@example.test',receipt['body'])
                    self.assertNotIn(b'Incorrect Parsed Name',receipt['body'])
                    self.assertNotIn(b'newsletter',receipt['body'])
            finally: store.close()

    def test_actual_values_override_stale_verified_markers(self):
        page=self.browser.new_page()
        try:
            page.set_content('''<label>Full name<input name="name"></label>
              <label>City<select name="city"><option value="">Choose</option><option value="LDN">London</option></select></label>''')
            plan=plan_fields(scan(page),example_profile(),'fixture')
            fill_plan(page,plan)
            self.assertEqual(page.locator('[name=city]').input_value(),'LDN')
            self.assertTrue(all(v['ok'] for v in verify_fields(page,plan)))
            page.locator('[name=name]').evaluate("e=>{e.value='Wrong Person';e.setAttribute('data-jpaf-state','verified')}")
            self.assertFalse(all(v['ok'] for v in verify_fields(page,plan)))
            fill_plan(page,plan)
            self.assertTrue(all(v['ok'] for v in verify_fields(page,plan)))
        finally: page.close()

    def test_wrong_combobox_chip_cannot_pass_as_verified(self):
        page=self.browser.new_page()
        try:
            page.set_content('''<div class="select__container"><label>City<input role="combobox" class="select__input" data-jpaf-id="city" data-jpaf-state="verified"></label><div class="select__single-value">Manchester</div></div>''')
            plan={'fields':[{'id':'city','value':'London','source_ref':'/applicant/location/city'}],
                '_scanMeta':[{'id':'city','type':'text','combo':True}]}
            self.assertFalse(verify_fields(page,plan)[0]['ok'])
            page.locator('.select__single-value').evaluate("e=>e.textContent='London'")
            self.assertTrue(verify_fields(page,plan)[0]['ok'])
        finally: page.close()

    def test_multistep_validates_each_page_before_submission(self):
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin,received):
            store=Store(Path(temp)/'queue.sqlite')
            try:
                keys=[store.ingest(job(origin+'/'+mode)) for mode in ('multistep_unknown','multistep')]
                results=run_queue(store,example_profile(),FixtureModel(),self.browser,temp,10,
                    prepare=True,submit=True,fixture_origin=origin,verify_seconds=1)
                self.assertEqual([store.get(k)['status'] for k in keys],['needs_input','submitted'],results)
                self.assertEqual(len(received),1)
                for expected in (b'%PDF-',b'Alex Example',b'alex@example.test',b'+442079460000'):
                    self.assertIn(expected,received[0]['body'])
                report=json.loads((Path(temp)/keys[1]/'browser.json').read_text())
                self.assertEqual(len(report['steps']),2)
                self.assertFalse(report['steps'][0]['attached'])
                self.assertTrue(report['steps'][1]['attached'])
            finally: store.close()

    def test_ready_materials_resume_without_model_or_rerender(self):
        class NoModel:
            def generate(self,*args): raise AssertionError('Resume must not request model inference')
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin,received):
            store=Store(Path(temp)/'queue.sqlite')
            try:
                posting=job(origin+'/success'); profile=example_profile()
                key=store.ingest(posting); directory=Path(temp)/key
                run_queue(store,profile,FixtureModel(),self.browser,temp,1,fixture_origin=origin)
                self.assertEqual(store.get(key)['status'],'materials_ready')
                pdf=directory/'cv.pdf'; modified=pdf.stat().st_mtime_ns; original=pdf.read_bytes()
                self.assertIsNotNone(load_materials(directory,posting,profile))
                pdf.write_bytes(original+b'changed')
                self.assertIsNone(load_materials(directory,posting,profile))
                pdf.write_bytes(original); modified=pdf.stat().st_mtime_ns
                changed={**profile,'minimum_score':99}
                self.assertIsNone(load_materials(directory,posting,changed))
                self.assertIsNone(load_materials(directory,{**posting,'description':'Changed job'},profile))
                other=store.ingest(job(origin+'/another-job'))
                result=run_queue(store,profile,NoModel(),self.browser,temp,1,prepare=True,submit=True,
                    fixture_origin=origin,verify_seconds=1,only=key)
                self.assertEqual(result[0]['status'],'submitted',result)
                self.assertTrue(result[0]['reused_materials'])
                self.assertEqual(pdf.stat().st_mtime_ns,modified)
                self.assertEqual(len(received),1)
                self.assertEqual(store.get(other)['status'],'discovered')
            finally: store.close()

    def test_cached_materials_resolve_route_before_preparation(self):
        class NoModel:
            def generate(self,*args): raise AssertionError('Routing must not regenerate materials')
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'queue.sqlite')
            try:
                posting=job('https://listing.test/jobs/123');profile=example_profile()
                key=store.ingest(posting);directory=Path(temp)/key
                with patch('joblazy.discovery.enrich',side_effect=lambda job,*args,**kwargs:job):
                    run_queue(store,profile,FixtureModel(),self.browser,temp,1)
                pdf=directory/'cv.pdf';modified=pdf.stat().st_mtime_ns
                routed={**posting,'application_url':'https://employer.test/jobs/123/apply'}
                def prepare(page,observed,*args,**kwargs):
                    self.assertEqual(observed['application_url'],routed['application_url'])
                    self.assertEqual(observed['url'],posting['url'])
                    return 'prepared'
                with patch('joblazy.discovery.enrich',side_effect=lambda job,*args,**kwargs:job),patch('joblazy.routes.resolve_application',return_value=routed) as resolver,patch('joblazy.pipeline.apply',side_effect=prepare):
                    result=run_queue(store,profile,NoModel(),self.browser,temp,1,prepare=True,allow_live=True)
                resolver.assert_called_once()
                self.assertTrue(result[0]['reused_materials'],result)
                self.assertEqual(result[0]['status'],'prepared')
                self.assertEqual(pdf.stat().st_mtime_ns,modified)
                self.assertIsNotNone(load_materials(directory,posting,profile))
            finally:store.close()

    def test_recovered_description_keeps_new_checkpoint_reusable(self):
        class NoModel:
            def generate(self,*args):raise AssertionError('A saved CV must be reused')
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'jobs.sqlite')
            try:
                original={**job('https://example.test/recovered'),'description':''}
                observed={**original,'description':job('unused')['description'],
                    'description_source':original['url'],'description_method':'Visible posting text'}
                key=store.ingest(original);directory=Path(temp)/key;profile=example_profile()
                with patch('joblazy.discovery.enrich',return_value=observed):
                    result=run_queue(store,profile,FixtureModel(),self.browser,temp,1)
                self.assertEqual(result[0]['status'],'materials_ready',result)
                saved=store.get(key)['data'];pdf=(directory/'cv.pdf').read_bytes()
                self.assertIsNotNone(load_materials(directory,saved,profile))
                with patch('joblazy.discovery.enrich',side_effect=lambda posting,*a,**k:posting):
                    # Force only the fictional queue state back to resumable;
                    # the completed material event and checkpoint stay intact.
                    store.transition(key,'retryable')
                    result=run_queue(store,profile,NoModel(),self.browser,temp,1)
                self.assertTrue(result[0]['reused_materials'],result)
                self.assertEqual((directory/'cv.pdf').read_bytes(),pdf)
            finally:store.close()

    def test_scoped_answer_resumes_exception_with_existing_cv(self):
        class NoModel:
            def generate(self,*args): raise AssertionError('An application answer must not regenerate the CV')
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin,received):
            store=Store(Path(temp)/'jobs.sqlite')
            try:
                profile=example_profile(); profile_path=Path(temp)/'profile.json'; write_json(profile_path,profile)
                output=Path(temp)/'applications'
                key=store.ingest(job(origin+'/unknown')); directory=output/key
                run_queue(store,profile,FixtureModel(),self.browser,output,1,prepare=True,submit=True,
                    fixture_origin=origin,verify_seconds=1)
                self.assertEqual(store.get(key)['status'],'needs_input')
                with self.assertRaises(NeedsInput):
                    save_answer(store,key,directory,profile_path,'Question not observed','Yes')
                with self.assertRaises(NeedsInput):
                    save_answer(store,key,directory,profile_path,'Work authorization','Maybe')
                command=[sys.executable,'-m','joblazy','--data',temp]
                shown=subprocess.run(command+['show',key],capture_output=True,text=True,check=True)
                self.assertIn('Work authorization',[q['field'] for q in json.loads(shown.stdout)['questions']])
                answered=subprocess.run(command+['answer',key,'--profile',str(profile_path),
                    '--question','Work authorization','--value','Yes'],capture_output=True,text=True,check=True)
                self.assertEqual(json.loads(answered.stdout)['status'],'retryable')
                profile=read_json(profile_path)
                self.assertEqual(profile['answers'][-1]['scope'],origin+'/unknown')
                shown=subprocess.run(command+['show',key,'--profile',str(profile_path)],capture_output=True,text=True,check=True)
                self.assertNotIn('Work authorization',[q['field'] for q in json.loads(shown.stdout)['questions']])
                self.assertNotIn('Work authorization: No unambiguous', (Path(temp)/'review.html').read_text(encoding='utf-8'))
                save_answer(store,key,directory,profile_path,'Work authorization','No')
                save_answer(store,key,directory,profile_path,'Work authorization','Yes')
                profile=read_json(profile_path)
                result=run_queue(store,profile,NoModel(),self.browser,output,1,prepare=True,submit=True,
                    fixture_origin=origin,verify_seconds=1)
                self.assertEqual(result[0]['status'],'submitted',result)
                self.assertTrue(result[0]['reused_materials'])
                self.assertIn(b'Yes',received[0]['body'])
                with self.assertRaises(NeedsInput):
                    save_answer(store,key,directory,profile_path,'Work authorization','No')
            finally: store.close()

    def test_greenhouse_form_scope_and_lever_semantic_questions(self):
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin,received):
            store=Store(Path(temp)/'jobs.sqlite')
            try:
                profile=example_profile()
                profile['answers']=[{'question':question,'scope':origin+'/lever','value':value} for question,value in
                    [('Are you authorized to work here?','Yes'),('Do you require sponsorship?','No')]]
                keys=[store.ingest(job(origin+'/'+mode)) for mode in ('greenhouse','lever')]
                results=run_queue(store,profile,FixtureModel(),self.browser,temp,10,prepare=True,submit=True,
                    fixture_origin=origin,verify_seconds=1)
                self.assertEqual([store.get(k)['status'] for k in keys],['submitted','submitted'],results)
                self.assertEqual(len(received),2)
                for receipt in received:
                    self.assertIn(b'%PDF-',receipt['body'])
                    self.assertIn(b'alex@example.test',receipt['body'])
                lever=next(x for x in received if x['path']=='/submit/lever')['body']
                self.assertIn(b'name="authorization"\r\n\r\nYes',lever)
                self.assertIn(b'name="sponsorship"\r\n\r\nNo',lever)
                self.assertIn(b'provider-location-id',lever)
            finally: store.close()

    def test_teamtailor_overlay_metadata_and_scoped_choices(self):
        with tempfile.TemporaryDirectory() as temp,fixture_server() as (origin,received):
            page=self.browser.new_page()
            try:
                page.goto(origin+'/teamtailor')
                self.assertFalse(is_application(page))
                form=open_application_form(page)
                fields=scan(form);by_label={f['label']:f for f in fields}
                self.assertEqual(len(fields),8)
                for label in ('Gender Identity','First name','Last name','Email','Phone','Upload CV','I agree to the application privacy policy.'):
                    self.assertTrue(by_label[label]['required'],label)
                self.assertFalse(by_label['Cover letter']['required'])
                self.assertEqual(by_label['Gender Identity']['options'],['Female','Male','Prefer not to say'])
                self.assertEqual(by_label['I agree to the application privacy policy.']['options'],['I agree to the application privacy policy.'])
                self.assertEqual(page.locator('#employee-login input').input_value(),'')
            finally:page.close()
            store=Store(Path(temp)/'jobs.sqlite')
            try:
                missing=store.ingest(job(origin+'/teamtailor-missing'))
                complete=store.ingest(job(origin+'/teamtailor'))
                profile=example_profile()
                profile['answers']=[{'scope':origin+'/teamtailor','question':q,'value':v} for q,v in
                    [('Gender Identity','Prefer not to say'),('I agree to the application privacy policy.','I agree to the application privacy policy.')]]
                results=run_queue(store,profile,FixtureModel(),self.browser,temp,2,prepare=True,submit=True,fixture_origin=origin,verify_seconds=1)
                self.assertEqual(store.get(missing)['status'],'needs_input',results)
                self.assertEqual(store.get(complete)['status'],'submitted',results)
                report=read_json(Path(temp)/missing/'browser.json')
                self.assertEqual({q['field'] for q in report['unresolved'] if q['required']},{'Gender Identity','I agree to the application privacy policy.'})
                self.assertEqual(len(received),1)
                self.assertEqual(received[0]['path'],'/submit/teamtailor')
                self.assertIn(b'%PDF-',received[0]['body'])
                self.assertIn(b'name="candidate[answers_attributes][0][choice]"\r\n\r\n4',received[0]['body'])
                self.assertIn(b'name="candidate[consent_given]"\r\n\r\n1',received[0]['body'])
            finally:store.close()

    def test_lever_location_requires_committed_selection(self):
        page=self.browser.new_page()
        try:
            page.set_content('''<li class="application-question"><div class="application-label">Current location</div>
              <input class="location-input" name="location" value="London, United Kingdom" data-jpaf-state="verified">
              <input type="hidden" name="selectedLocation" value="stale-id"><div class="dropdown-results"></div></li>''')
            plan=plan_fields(scan(page),example_profile(),'fixture')
            self.assertEqual(len(plan['fields']),1)
            self.assertFalse(verify_fields(page,plan)[0]['ok'])
            page.locator('.location-input').evaluate("e=>e.setAttribute('data-joblazy-selection',JSON.stringify({value:'London, United Kingdom',token:'stale-id'}))")
            self.assertTrue(verify_fields(page,plan)[0]['ok'])
            page.locator('[name=selectedLocation]').evaluate("e=>e.value='different-id'")
            self.assertFalse(verify_fields(page,plan)[0]['ok'])
        finally: page.close()

    def test_reviewed_narrative_reaches_local_application(self):
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin,received):
            store=Store(Path(temp)/'jobs.sqlite')
            try:
                profile=example_profile(); before=json.dumps(profile,sort_keys=True)
                key=store.ingest(job(origin+'/narrative'))
                results=run_queue(store,profile,FixtureModel(),self.browser,temp,1,prepare=True,submit=True,
                    fixture_origin=origin,verify_seconds=1)
                self.assertEqual(store.get(key)['status'],'submitted',results)
                self.assertIn(b'I coordinated onboarding for 20 partners',received[0]['body'])
                self.assertEqual(json.dumps(profile,sort_keys=True),before)
                record=read_json(Path(temp)/key/'answer-drafts.json')
                draft=next(iter(record['drafts'].values()))
                self.assertTrue(draft['review']['supported'])
                self.assertEqual(draft['question']['max_length'],400)
                self.assertIn('partner onboarding',draft['question']['description'])
            finally: store.close()

    def test_continuous_runner_caps_work_across_cycles_and_restart(self):
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin,received):
            data=Path(temp);profile=data/'profile.json';boards=data/'boards.json'
            write_json(profile,example_profile());write_json(boards,[]);scans=[]
            def scanner(boards,store,checkpoint):
                scans.append(1)
                for mode in ('success','autofill'):store.ingest(job(origin+'/'+mode))
                return {'discovered':2,'errors':[]}
            options={'scanner':scanner,'browser_factory':lambda:nullcontext(self.browser),
                'model_factory':lambda store:FixtureModel(),'prepare':True,'daily_jobs':1,'interval':.01,
                'run_options':{'submit':True,'fixture_origin':origin,'verify_seconds':1}}
            reports=[]
            result=Worker(data,profile,boards,**options).run(max_cycles=2,emit=reports.append)
            self.assertEqual(result['cycles'],2)
            self.assertEqual([r['state'] for r in reports],['processed','daily_limit'])
            self.assertEqual(len(received),1);self.assertIn(b'%PDF-',received[0]['body'])
            self.assertEqual(Worker(data,profile,boards,**options).tick()['state'],'daily_limit')
            self.assertEqual(len(scans),1);self.assertEqual(len(received),1)

    def test_misleading_conflicting_and_unrelated_receipts_stay_unknown(self):
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin,received):
            store=Store(Path(temp)/'jobs.sqlite')
            try:
                modes=('false_confirmation','conflicting_receipts','stale_receipt','unrelated_receipt')
                keys=[store.ingest(job(origin+'/'+mode)) for mode in modes]
                results=run_queue(store,example_profile(),FixtureModel(),self.browser,temp,10,prepare=True,submit=True,
                    fixture_origin=origin,verify_seconds=1)
                self.assertEqual([store.get(k)['status'] for k in keys],['submission_unknown']*4,results)
                self.assertEqual(len(received),4)
                self.assertEqual(run_queue(store,example_profile(),FixtureModel(),self.browser,temp,10,
                    prepare=True,submit=True,fixture_origin=origin,verify_seconds=1),[])
                self.assertEqual(len(received),4)
            finally:store.close()

if __name__ == '__main__': unittest.main()
