import copy
import tempfile
import unittest
from contextlib import ExitStack,closing
from pathlib import Path
from playwright.sync_api import sync_playwright
from joblazy.answers import questions
from joblazy.common import read_json
from joblazy.inspection import inspect_application
from joblazy.mapping import plan_fields
from joblazy.pipeline import run_queue
from joblazy.store import Store
from .support import example_profile,fixture_server,FixtureModel,job


QUESTION='Are you currently legally authorized to work in the country to which you are applying?'


def posting(url='https://example.test/job'):
    return {**job(url),'location':'GB-London, London, United Kingdom',
        'location_evidence':[{'label':'GB-London','postal_address':{
            'addressLocality':'London','addressCountry':'United Kingdom'}}]}


def profile():
    value=example_profile()
    value['targeting']['config']={'location':{'authorized_in':['United Kingdom']}}
    return value


def field(label=QUESTION):
    return {'id':'authorization','label':label,'type':'select-one',
        'options':['Choose','Yes','No'],'required':True}


class AuthorizationTests(unittest.TestCase):
    def test_named_country_comes_from_question_without_guessing_posting_country(self):
        question='Do you have the legal right to work in the UK?'
        p=profile();before=copy.deepcopy(p)
        for j in (None,{**posting(),'location':'London','location_evidence':[]}):
            result=plan_fields([field(question)],p,'scope',job=j)['fields'][0]
            self.assertEqual(result['value'],'Yes')
            self.assertEqual(result['source_ref'],'/targeting/config/location/authorized_in/0')
            self.assertEqual(result['question_source_ref'],'label')
            self.assertEqual(result['question_country'],'United Kingdom')
            self.assertNotIn('job_source_ref',result)
            self.assertEqual(plan_fields([field()],p,'scope',job=j)['fields'],[])
        for question in ('Do you have the legal right to work in the UK without sponsorship now or in the future?',
            'Do you have the legal right to work in the UK and agree to relocate?',
            'Do you have the legal right to work in the US?',
            'Do you not have the legal right to work in the UK?'):
            self.assertEqual(plan_fields([field(question)],p,'scope')['fields'],[])
        self.assertEqual(p,before)
        p['targeting']['config']['location']['authorized_in']=[]
        self.assertEqual(plan_fields([field('Do you have the legal right to work in the UK?')],p,'scope')['fields'],[])
        self.assertEqual(before['targeting']['config']['location']['authorized_in'],['United Kingdom'])

    def test_positive_fact_has_candidate_and_posting_sources_without_mutation(self):
        p=profile();before=copy.deepcopy(p);j=posting()
        for label in (QUESTION,QUESTION.replace('authorized','authorised'),
            'For Example Inc. to anticipate possible immigration timelines and obligations, could you confirm you are currently authorized to work in the country to which you are applying?'):
            result=plan_fields([field(label)],p,j['url'],job=j)['fields'][0]
            self.assertEqual(result['value'],'Yes')
            self.assertEqual(result['source_ref'],'/targeting/config/location/authorized_in/0')
            self.assertEqual(result['job_source_ref'],'/location_evidence')
        self.assertEqual(p,before)

    def test_sponsorship_consent_citizenship_negative_and_compound_questions_stay_unknown(self):
        for label in ('Will you require sponsorship now or in the future?',
            'Are you a United Kingdom citizen?', 'I agree to the privacy policy',
            'Are you currently not authorized to work in the United Kingdom?',
            'Are you currently authorized to work in the United Kingdom without sponsorship now or in the future?',
            'Are you currently authorized to work in the United Kingdom and willing to relocate?',
            'Are you currently authorized to work in the United States?'):
            with self.subTest(label=label):
                self.assertEqual(plan_fields([field(label)],profile(),'scope',job=posting())['fields'],[])

    def test_country_ambiguity_and_missing_facts_do_not_produce_yes_or_no(self):
        mixed=posting();mixed['location_evidence'].append({'label':'Toronto','postal_address':{'addressCountry':'Canada'}})
        for j in (None,{**posting(),'location_evidence':[]},mixed,
            {**posting(),'location':'London, Canada'},
            {**posting(),'location':'GB-London, London, United Kingdom | Paris'},
            {**posting(),'location_evidence':[{'label':'London','postal_address':{}}]}):
            with self.subTest(job=j):self.assertEqual(plan_fields([field()],profile(),'scope',job=j)['fields'],[])
        for countries in ([],['United States'],['United Kingdom','UK'],'United Kingdom',None):
            p=profile();p['targeting']['config']['location']['authorized_in']=countries
            self.assertEqual(plan_fields([field()],p,'scope',job=posting())['fields'],[])
        for targeting in ('London only',{}, {'config':{'location':{'visa_status':'No sponsorship required'}}}):
            p=profile();p['targeting']=targeting
            self.assertEqual(plan_fields([field()],p,'scope',job=posting())['fields'],[])

    def test_explicit_scoped_answer_wins_and_duplicate_answers_remain_unresolved(self):
        p=profile();p['answers']=[{'question':QUESTION,'scope':'scope','value':'No'}]
        self.assertEqual(plan_fields([field()],p,'scope',job=posting())['fields'][0]['value'],'No')
        p['answers'].append(dict(p['answers'][0]))
        self.assertEqual(plan_fields([field()],p,'scope',job=posting())['fields'],[])

    def test_additional_instructions_and_non_binary_options_need_an_answer(self):
        for change in ({'description':'Select Yes only if you will never require sponsorship.'},
            {'options':['Yes','No','Only with sponsorship']},{'type':'checkbox'},
            {'options':None}):
            self.assertEqual(plan_fields([{**field(),**change}],profile(),'scope',job=posting())['fields'],[])

    def test_inspection_question_refresh_and_browser_preparation_share_the_fact(self):
        with tempfile.TemporaryDirectory() as temp,fixture_server() as (origin,received),sync_playwright() as pw,ExitStack() as stack:
            browser=stack.enter_context(closing(pw.chromium.launch(channel='chrome',headless=True)))
            store=stack.enter_context(closing(Store(Path(temp)/'jobs.sqlite')))
            p=profile();before=copy.deepcopy(p);key=store.ingest(posting(origin+'/current_authorization'))
            directory=Path(temp)/'applications'/key
            run_queue(store,p,FixtureModel(),browser,directory.parent,1,fixture_origin=origin)
            cv=(directory/'cv.pdf').read_bytes();rows=store.list()
            inspected=inspect_application(store,key,p,browser,directory,fixture_origin=origin)
            self.assertEqual(inspected['required_unresolved'],1,read_json(directory/'form-inventory.json'))
            self.assertEqual(store.list(),rows)
            pending=questions(store,key,directory,p)['questions']
            self.assertEqual([q['field'] for q in pending if q.get('required')],['Will you require sponsorship now or in the future?'])
            class NoModel:
                def generate(self,*args):raise AssertionError('Valid CV must be reused')
            result=run_queue(store,p,NoModel(),browser,directory.parent,1,prepare=True,fixture_origin=origin)
            self.assertEqual(result[0]['status'],'needs_input')
            report=read_json(directory/'browser.json')
            auth=next(f for f in report['fields'] if f.get('name')=='authorization')
            actual=next(v for v in report['values'] if v['id']==auth['id'])
            self.assertTrue(actual['ok']);self.assertEqual(actual['actual'],['Yes'])
            self.assertTrue(report['attached']);self.assertFalse(report['unverified'])
            self.assertEqual(sum(bool(q.get('required')) for q in report['unresolved']),1)
            self.assertEqual((directory/'cv.pdf').read_bytes(),cv)
            self.assertEqual(p,before);self.assertEqual(received,[])
