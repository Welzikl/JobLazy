import base64
import copy
import io
import json
import tempfile
import threading
import unittest
import zipfile
import os
from contextlib import closing
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfWriter
from joblazy.common import digest, read_json
from joblazy.dashboard import make_handler
from joblazy.onboarding import create_draft, confirm_draft, extract_document
from joblazy.profiles import load_profile

CV = ('Morgan Example\nOperations coordinator at Fictional Tools, 2022-2025.\n'
      'Coordinated onboarding for 20 partners.\nBA Business at Example University, 2022.\n'
      'Built a reporting project using SQL.')


def proposal():
    return {'identity': {'full_name': 'Morgan Example', 'first_name': '', 'last_name': '',
                        'email': '', 'phone': '', 'city': '', 'country': ''},
            'summary': 'Operations coordinator.',
            'experience': [{'company': 'Fictional Tools', 'role': 'Operations coordinator',
                            'dates': '2022-2025', 'location': '',
                            'bullets': ['Coordinated onboarding for 20 partners.'],
                            'source_quote': 'Operations coordinator at Fictional Tools, 2022-2025.'}],
            'education': [{'org': 'Example University', 'title': 'BA Business', 'year': '2022',
                           'source_quote': 'BA Business at Example University, 2022.'}],
            'projects': [{'name': 'Reporting', 'description': 'Built a reporting project using SQL.',
                          'source_quote': 'Built a reporting project using SQL.'}],
            'skills': ['SQL'],
            'questions': [{'question': 'What part of partner onboarding did you personally own?',
                           'reason': 'The CV does not specify your responsibilities.'}],
            'uncertainties': ['Name parts and contact details need confirmation.']}


class IntakeModel:
    def generate(self, task, data, schema):
        return proposal()


def upload():
    return [{'name': 'cv.txt', 'content': base64.b64encode(CV.encode()).decode()}]


def confirmation(draft):
    return {'id': draft['id'], 'confirmed': True, 'profile': copy.deepcopy(draft['proposal']),
            'preferences': {'desired_work': 'Move into product research', 'role_families': 'User research',
                            'city': 'Bristol', 'country': 'United Kingdom', 'avoid': 'Outbound sales'},
            'additions': [{'question': 'What else did you do?', 'answer': 'I interviewed partner contacts at Fictional Tools to improve onboarding.'}],
            'links': ['https://example.test/portfolio']}


class OnboardingTests(unittest.TestCase):
    def test_browser_upload_review_followups_and_confirmation_without_configuration_edits(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); data=root/'runtime'; profile=root/'local/profile.json'
            server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(data,profile,'fixture-token'))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with patch('joblazy.dashboard.CodexModel',return_value=IntakeModel()), sync_playwright() as pw:
                    channel=os.environ.get('JOBLAZY_TEST_BROWSER_CHANNEL','chrome')
                    options={'headless':True}
                    if channel!='chromium':options['channel']=channel
                    browser=pw.chromium.launch(**options)
                    try:
                        page=browser.new_page(); errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                        page.goto(f'http://127.0.0.1:{server.server_port}/')
                        page.locator('#cv').set_input_files({'name':'cv.txt','mimeType':'text/plain','buffer':CV.encode()})
                        page.get_by_role('button',name='Extract a draft with Codex').click()
                        page.locator('#review').wait_for(state='visible')
                        self.assertFalse(profile.exists())
                        page.locator('#experience-0-role').fill('Partner Operations Coordinator')
                        page.locator('#identity-first_name').fill('Morgan');page.locator('#identity-last_name').fill('Example')
                        page.locator('#answer-0').fill('I coordinated schedules and checked onboarding documents at Fictional Tools.')
                        page.locator('#pref-desired_work').fill('User research and customer interviews')
                        page.locator('#pref-city').fill('Bristol');page.locator('#pref-country').fill('United Kingdom')
                        page.locator('#confirmed').check()
                        page.get_by_role('button',name='Save my reviewed profile').click()
                        page.locator('#finished').wait_for(state='visible')
                        saved=load_profile(profile)
                        self.assertEqual(saved['resume']['experience'][0]['role'],'Partner Operations Coordinator')
                        self.assertEqual(saved['targeting']['desired_work'],'User research and customer interviews')
                        self.assertEqual(saved['facts'][0]['text'],'I coordinated schedules and checked onboarding documents at Fictional Tools.')
                        self.assertNotIn('What part',saved['facts'][0]['text'])
                        self.assertEqual(errors,[])
                    finally:browser.close()
            finally:server.shutdown();server.server_close();thread.join()

    def test_sources_are_preserved_draft_is_not_profile_and_review_is_required(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); data=root/'runtime'; profile=root/'local/profile.json'
            draft=create_draft(data, upload(), IntakeModel())
            self.assertFalse(profile.exists())
            source=draft['sources'][0]
            self.assertEqual((data/'onboarding'/draft['id']/source['file']).read_bytes(), CV.encode())
            self.assertEqual(source['sha256'], digest(CV.encode()))
            payload=confirmation(draft); payload['confirmed']=False
            with self.assertRaisesRegex(ValueError, 'confirm'):confirm_draft(data,profile,payload)
            self.assertFalse(profile.exists())
            payload['confirmed']=True
            payload['profile']['identity'].update(first_name='Morgan',last_name='Example',city='Bath',country='United Kingdom')
            payload['profile']['experience'][0]['role']='Partner Operations Coordinator'
            confirm_draft(data,profile,payload)
            saved=load_profile(profile)
            self.assertEqual(saved['resume']['experience'][0]['role'],'Partner Operations Coordinator')
            self.assertEqual(saved['resume']['skills'],[{'category':'Skills','items':['SQL']}])
            self.assertEqual(saved['applicant']['address']['city'],'Bath')
            self.assertEqual(saved['search_location']['city'],'Bristol')
            self.assertEqual(saved['targeting']['desired_work'],'Move into product research')
            self.assertNotIn('London',json.dumps(saved))
            self.assertEqual(saved['facts'][0]['source']['method'],'operator_confirmed')
            self.assertEqual(saved['supporting_links'][0]['status'],'not_read')
            self.assertEqual(saved['answers'],[])
            before=profile.read_bytes()
            with self.assertRaisesRegex(ValueError,'already exists'):confirm_draft(data,profile,payload)
            self.assertEqual(profile.read_bytes(),before)

    def test_bad_source_quote_cannot_become_a_reviewable_draft(self):
        class WrongQuote:
            def generate(self,*args):
                value=proposal();value['experience'][0]['source_quote']='Invented experience';return value
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError,'unverifiable'):create_draft(temp,upload(),WrongQuote())
            self.assertEqual(list(Path(temp).rglob('draft.json')),[])
            self.assertEqual(len(list(Path(temp).rglob('sources.json'))),1)

    def test_terse_extraction_still_asks_about_missing_work_in_the_actual_role(self):
        class NoQuestions:
            def generate(self,*args):
                value=proposal();value['questions']=[];return value
        with tempfile.TemporaryDirectory() as temp:
            draft=create_draft(temp,upload(),NoQuestions())
            question=draft['proposal']['questions'][0]['question']
            self.assertIn('Fictional Tools',question)
            self.assertIn('Operations coordinator',question)
            self.assertIn('does not describe',question)

    def test_docx_extracts_text_and_image_only_pdf_is_reported(self):
        body=io.BytesIO()
        with zipfile.ZipFile(body,'w') as z:
            z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+CV+'</w:t></w:r></w:p></w:body></w:document>')
        self.assertIn('Morgan Example',extract_document('CV.docx',body.getvalue()))
        pdf=io.BytesIO(); writer=PdfWriter();writer.add_blank_page(612,792);writer.write(pdf)
        with self.assertRaisesRegex(ValueError,'readable text'):extract_document('scan.pdf',pdf.getvalue())
        with self.assertRaisesRegex(ValueError,'Upload a PDF'):extract_document('cv.exe',CV.encode())

    def test_source_filename_does_not_escape_private_intake(self):
        with tempfile.TemporaryDirectory() as temp:
            files=upload();files[0]['name']='../../escape.txt'
            draft=create_draft(temp,files,IntakeModel())
            self.assertEqual(draft['sources'][0]['name'],'escape.txt')
            self.assertFalse((Path(temp)/'escape.txt').exists())

    def test_empty_workspace_http_intake_confirm_and_existing_profile_protection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); data=root/'runtime'; profile=root/'local/profile.json'
            server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(data,profile,'fixture-token'))
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            try:
                with closing(HTTPConnection('127.0.0.1',server.server_port,timeout=10)) as connection:
                    connection.request('GET','/');r=connection.getresponse();page=r.read().decode()
                    self.assertEqual(r.status,200);self.assertIn('Upload your CV',page)
                    self.assertFalse(profile.exists())
                    connection.request('POST','/api/onboarding/draft',body=json.dumps({'files':upload()}))
                    r=connection.getresponse();r.read();self.assertEqual(r.status,403)
                    headers={'Content-Type':'application/json','X-JobLazy-Token':'fixture-token'}
                    with patch('joblazy.dashboard.CodexModel',return_value=IntakeModel()):
                        connection.request('POST','/api/onboarding/draft',body=json.dumps({'files':upload()}),headers=headers)
                        r=connection.getresponse();draft=json.loads(r.read());self.assertEqual(r.status,200,draft)
                    connection.request('POST','/api/onboarding/confirm',body=json.dumps(confirmation(draft)),headers=headers)
                    r=connection.getresponse();result=json.loads(r.read());self.assertEqual(r.status,200,result)
                    self.assertEqual(load_profile(profile)['resume']['candidate']['name'],'Morgan Example')
                    connection.request('POST','/api/onboarding/draft',body=json.dumps({'files':upload()}),headers=headers)
                    r=connection.getresponse();r.read();self.assertEqual(r.status,409)
            finally:server.shutdown();server.server_close();thread.join()
