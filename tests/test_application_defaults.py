import copy
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from joblazy.browser import scan,fill_plan,verify_fields
from joblazy.mapping import plan_fields
from .test_authorization import profile,posting


def candidate():
    p=profile()
    p['application_defaults']={
        'salary':{'annual_amount':61000,'currency':'GBP'},
        'availability':{'month':'2099-03','exact_day':None,'notice_period':None},
        'sponsorship':{'required':False,'countries':['United Kingdom']},
        'source':{'method':'operator_supplied'}}
    return p


def field(label,kind='text',**kwargs):
    return {'id':label,'label':label,'type':kind,'required':True,**kwargs}


class ApplicationDefaultTests(unittest.TestCase):
    def test_browser_commits_availability_radio_from_exact_date(self):
        p=candidate();p['application_defaults']['availability'].update(month='2099-10',exact_day='2099-10-01')
        with sync_playwright() as pw,patch('joblazy.mapping.datetime') as clock:
            clock.now.return_value=datetime(2099,9,13,tzinfo=timezone.utc)
            browser=pw.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page();page.route('**/*',lambda route:route.abort())
                page.set_content('<form><fieldset><legend>Notice Period/Availiablity</legend>'+''.join(
                    f'<label><input type="radio" name="availability" value="{value}" required>{value}</label>'
                    for value in ['Immediate','2-4 weeks','1-2 months','2+ months'])+'</fieldset></form>')
                plan=plan_fields(scan(page),p,'fixture')
                self.assertFalse(plan['unresolved']);self.assertEqual(len(plan['fields']),1)
                fill_plan(page,plan)
                self.assertEqual(page.locator('input:checked').input_value(),'2-4 weeks')
                self.assertTrue(all(v['ok'] for v in verify_fields(page,plan)))
            finally:browser.close()

    def test_availability_range_is_recalculated_from_confirmed_date(self):
        p=candidate();p['application_defaults']['availability'].update(month='2099-10',exact_day='2099-10-01')
        f=field('Notice Period/Availiablity','radio',options=['Immediate','2-4 weeks','1-2 months','2+ months'])
        before=copy.deepcopy(p)
        for today,wanted in [('2099-09-13','2-4 weeks'),('2099-08-13','1-2 months'),
                             ('2099-07-13','2+ months'),('2099-10-01','Immediate'),
                             ('2099-10-02',None),('2099-09-25',None),('2099-08-01',None)]:
            with self.subTest(today=today),patch('joblazy.mapping.datetime') as clock:
                clock.now.return_value=datetime.fromisoformat(today).replace(tzinfo=timezone.utc)
                plan=plan_fields([f],p,'fixture')
                self.assertEqual([v['value'] for v in plan['fields']],[wanted] if wanted else [])
                if wanted:self.assertEqual(plan['fields'][0]['calculated_on'],today)
        self.assertEqual(p,before)

    def test_availability_does_not_invent_notice_or_resolve_ambiguous_options(self):
        p=candidate();p['application_defaults']['availability'].update(month='2099-02',exact_day='2099-02-28')
        options=['Immediate','2-4 weeks','1-2 months','2+ months']
        with patch('joblazy.mapping.datetime') as clock:
            clock.now.return_value=datetime(2099,1,31,tzinfo=timezone.utc)
            for f in [field('Notice Period/Availability','radio',options=options),
                      field('What is your contractual notice period?','radio',options=options),
                      field('Notice Period/Availability','radio',options=options+['Other']),
                      field('Notice Period/Availability','radio',options=options,description='Also confirm you will relocate.')]:
                self.assertEqual(plan_fields([f],p,'fixture')['fields'],[])
            p['application_defaults']['availability']['month']='2099-03'
            self.assertEqual(plan_fields([field('Notice Period/Availability','radio',options=options)],p,'fixture')['fields'],[])

    def test_local_browser_scan_fill_and_verification_use_defaults(self):
        with sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page()
                page.route('**/*',lambda route:route.abort())
                page.set_content('''<form>
                    <label>What is your desired gross annual salary (local currency)?<input type="number" name="salary" required></label>
                    <label>Next available starting date<input name="start" required></label>
                    <label>Do you require visa sponsorship to work within the UK?<select name="sponsor" required><option value="">Choose</option><option>Yes</option><option>No</option></select></label>
                    <label>I agree to the privacy policy<input type="checkbox" name="consent" required></label>
                    </form>''')
                plan=plan_fields(scan(page),candidate(),'https://example.test/new',job=posting())
                self.assertEqual(len(plan['fields']),3)
                self.assertEqual(len(plan['unresolved']),1)
                fill_plan(page,plan)
                self.assertEqual(page.locator('[name=salary]').input_value(),'61000')
                self.assertEqual(page.locator('[name=start]').input_value(),'Available to start in March 2099.')
                self.assertEqual(page.locator('[name=sponsor]').input_value(),'No')
                self.assertFalse(page.locator('[name=consent]').is_checked())
                self.assertTrue(all(v['ok'] for v in verify_fields(page,plan)))
            finally:browser.close()

    def test_new_application_reuses_confirmed_defaults_without_saved_scope(self):
        p=candidate();before=copy.deepcopy(p)
        fields=[field('What is your desired gross annual salary (local currency)?','number'),
                field('What is the earliest you would want to start?'),
                field('Do you require visa sponsorship to work within the UK?','select-one',options=['Yes','No'])]
        for scope in ('https://example.test/one','https://example.test/two'):
            result=plan_fields(fields,p,scope,job=posting())
            self.assertEqual([r['value'] for r in result['fields']],['61000','Available to start in March 2099.','No'])
            self.assertFalse(result['unresolved'])
            self.assertTrue(all(r['source_ref'].startswith('/application_defaults/') for r in result['fields']))
        self.assertEqual(p,before)

    def test_scoped_answer_wins_and_duplicates_do_not_fall_back(self):
        p=candidate();f=field("What's your annual total comp expectation?")
        p['answers']=[{'question':f['label'],'scope':'scope','value':'GBP 65,000 per year'}]
        self.assertEqual(plan_fields([f],p,'scope',job=posting())['fields'][0]['value'],'GBP 65,000 per year')
        p['answers']*=2
        self.assertEqual(plan_fields([f],p,'scope',job=posting())['fields'],[])

    def test_unknown_context_current_pay_notice_dates_and_options_stay_unresolved(self):
        fields=[field('What is your current salary?'),field('Please, share your yearly compensation'),
                field('What is your notice period?'),field('Next available starting date','date'),
                field('Notice Period/Availiablity','radio',options=['Immediate','2-4 weeks','1-2 months']),
                field('What are your salary expectations in USD?'),
                field("What's your annual total comp expectation?",description='State your current compensation.'),
                field('Do you require visa sponsorship to work within the UK?','select-one',options=['Yes','No'],description='No means you are a citizen.'),
                field('Do you require visa sponsorship to work within the UK and agree to relocate?','select-one',options=['Yes','No'])]
        self.assertEqual(plan_fields(fields,candidate(),'scope',job=posting())['fields'],[])
        for j in (None,{**posting(),'location_evidence':[]},{**posting(),'location':'London, Canada'}):
            self.assertEqual(plan_fields([field('What is your desired gross annual salary (local currency)?','number')],candidate(),'scope',job=j)['fields'],[])

    def test_invalid_or_unconfirmed_defaults_do_not_map(self):
        for defaults in ({},None,{'source':{'method':'generated'}}):
            p=candidate();p['application_defaults']=defaults
            self.assertEqual(plan_fields([field('Next available starting date')],p,'scope',job=posting())['fields'],[])
        for month in ('2020-01','2099-13','March','2099-03-01',None):
            p=candidate();p['application_defaults']['availability']['month']=month
            self.assertEqual(plan_fields([field('Next available starting date')],p,'scope')['fields'],[])
        for amount in (True,-1,'61000',None):
            p=candidate();p['application_defaults']['salary']['annual_amount']=amount
            self.assertEqual(plan_fields([field("What's your annual total comp expectation?")],p,'scope',job=posting())['fields'],[])
