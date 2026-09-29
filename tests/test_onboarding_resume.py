"""Fresh-person intake recovery and project-led CVs; no real candidate or employer."""
import io
import json
import os
import tempfile
import threading
import unittest
import zipfile
from contextlib import closing
from html import escape
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from pypdf import PdfReader

from joblazy.common import NeedsInput, read_json
from joblazy.dashboard import make_handler
from joblazy.materials import source_facts, tailor
from joblazy.onboarding import DraftConflict, confirm_draft, create_draft, onboarding_state, save_draft
from joblazy.pipeline import run_queue
from joblazy.profiles import load_profile
from joblazy.store import Store
from .support import FixtureModel, example_profile, fixture_server, job
from .test_onboarding import IntakeModel, confirmation, upload


STUDENT_CV = ('Morgan Example\nBA Business at Example University, 2026.\n'
              'Built weekly reporting using SQL for a university project.\n'
              'Skills: SQL.\nSeeking a graduate operations role.')


def student_proposal():
    return {'identity': dict.fromkeys(('first_name', 'last_name', 'email', 'phone', 'city', 'country'), '')
            | {'full_name': 'Morgan Example'},
            'summary': 'Business graduate with a university reporting project.', 'experience': [],
            'education': [{'org': 'Example University', 'title': 'BA Business', 'year': '2026',
                           'source_quote': 'BA Business at Example University, 2026.'}],
            'projects': [{'name': 'University reporting project',
                          'description': 'Built weekly reporting using SQL for a university project.',
                          'source_quote': 'Built weekly reporting using SQL for a university project.'}],
            'skills': ['SQL'], 'questions': [], 'uncertainties': []}


class StudentModel(FixtureModel):
    def generate(self, task, data, schema):
        if 'Extract a DRAFT' in task:
            if 'Built weekly reporting using SQL' not in data['documents'][0]['text']:
                raise AssertionError('The uploaded document was not extracted')
            return student_proposal()
        if 'Tailor the CV' in task:
            return {'summary': {'text': 'Business graduate with a university reporting project.',
                                'source_ids': ['education.0', 'project.0.description']},
                    'experience': [], 'project_indices': [0]}
        value = super().generate(task, data, schema)
        if 'Rank this' in task:
            value['candidate_source_ids'] = ['project.0.description']
            value['evidence'] = [{'quote': 'weekly reporting', 'explanation': 'Fictional project evidence'}]
            value['dimensions']['cv_fit'].update(job_quotes=['weekly reporting'], candidate_source_ids=['project.0.description'])
            value['requirements'] = [{'requirement': 'Reporting', 'job_quote': 'weekly reporting',
                'kind': 'responsibility', 'status': 'met', 'candidate_source_ids': ['project.0.description'],
                'explanation': 'Confirmed university reporting project, not employment.'}]
        return value


class OnboardingResumeTests(unittest.TestCase):
    def test_draft_edits_survive_restart_and_stale_pages_cannot_replace_or_confirm_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path = root / 'profile.json'
            draft = create_draft(root, upload(), IntakeModel())
            other_draft = create_draft(root, upload(), IntakeModel())
            self.assertNotEqual(draft['id'], other_draft['id'])
            original = (root / 'onboarding' / draft['id'] / 'draft.json').read_bytes()
            payload = confirmation(draft)
            payload['preferences'] = {}  # Incomplete preferences may be saved, not confirmed.
            payload['profile']['identity']['first_name'] = 'Corrected name'
            saved = save_draft(root, payload)
            resumed = onboarding_state(Path(str(root)), path)['draft']
            self.assertEqual(resumed['revision'], saved['revision'])
            self.assertEqual(resumed['id'], draft['id'])
            self.assertEqual(onboarding_state(root, path, other_draft['id'])['draft']['revision'], 0)
            self.assertEqual(resumed['proposal']['identity']['first_name'], 'Corrected name')
            self.assertEqual(resumed['additions'], payload['additions'])
            self.assertEqual(resumed['links'], payload['links'])
            self.assertFalse(path.exists())
            self.assertEqual((root / 'onboarding' / draft['id'] / 'draft.json').read_bytes(), original)
            with self.assertRaises(DraftConflict): save_draft(root, payload)
            stale = confirmation(draft)
            with self.assertRaises(DraftConflict): confirm_draft(root, path, stale)
            self.assertFalse(path.exists())
            payload.update(revision=resumed['revision'], preferences=stale['preferences'])
            confirm_draft(root, path, payload)
            self.assertEqual(load_profile(path)['applicant']['identity']['first_name'], 'Corrected name')
            self.assertEqual(onboarding_state(root, path), {'profile_exists': True, 'draft': None})
            with self.assertRaises(DraftConflict): save_draft(root, payload)

    def test_resume_requires_local_token_and_preserves_saved_data_in_private_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            draft = create_draft(root, upload(), IntakeModel())
            create_draft(root, upload(), IntakeModel())  # A second tab changes the default.
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(root, root / 'profile.json', 'fixture-token'))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                with closing(HTTPConnection('127.0.0.1', server.server_port)) as connection:
                    connection.request('GET', '/api/onboarding')
                    response = connection.getresponse(); body = response.read().decode()
                    self.assertEqual(response.status, 403); self.assertNotIn('Morgan', body)
                    connection.request('GET', '/api/onboarding?draft=' + draft['id'], headers={'X-JobLazy-Token': 'fixture-token'})
                    response = connection.getresponse()
                    self.assertEqual(response.getheader('Cache-Control'), 'no-store')
                    self.assertEqual(json.loads(response.read())['draft']['id'], draft['id'])
                    connection.request('GET', '/api/onboarding?draft=../outside', headers={'X-JobLazy-Token': 'fixture-token'})
                    response = connection.getresponse(); response.read()
                    self.assertEqual(response.status, 409)
            finally: server.shutdown(); server.server_close(); thread.join()

    def test_pdf_and_docx_browser_intake_resume_then_project_led_cv_preparation(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            channel = os.environ.get('JOBLAZY_TEST_BROWSER_CHANNEL', 'chrome')
            browser = pw.chromium.launch(headless=True, **({'channel': channel} if channel != 'chromium' else {}))
            try:
                source_page = browser.new_page()
                source_page.set_content('<pre>' + escape(STUDENT_CV) + '</pre>')
                pdf = source_page.pdf(format='A4'); source_page.close()
                docx = io.BytesIO()
                with zipfile.ZipFile(docx, 'w') as archive:
                    archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                        + ''.join('<w:p><w:r><w:t>' + escape(line) + '</w:t></w:r></w:p>' for line in STUDENT_CV.splitlines()) + '</w:body></w:document>')
                for name, raw in [('cv.pdf', pdf), ('cv.docx', docx.getvalue())]:
                    with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                        root = Path(temp); data = root / 'runtime'; profile = root / 'local/profile.json'
                        server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(data, profile, 'fixture-token'))
                        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                        page = browser.new_page(); errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
                        try:
                            with patch('joblazy.dashboard.CodexModel', return_value=StudentModel()) as extraction:
                                page.goto(f'http://127.0.0.1:{server.server_port}/')
                                page.locator('#cv').set_input_files({'name': name, 'mimeType': 'application/octet-stream', 'buffer': raw})
                                page.get_by_role('button', name='Extract a draft with Codex').click()
                                page.locator('#review').wait_for(state='visible')
                                self.assertIn('/onboarding?draft=', page.url)
                                self.assertEqual(page.locator('#experience .entry').count(), 0)
                                for field, value in {'first_name': 'Morgan', 'last_name': 'Example', 'email': 'morgan@example.test',
                                    'phone': '+442079460000', 'city': 'Bristol', 'country': 'United Kingdom'}.items():
                                    page.locator('#identity-' + field).fill(value)
                                page.locator('#answer-0').fill('I organised a volunteer rota for a campus group.')
                                page.locator('#pref-desired_work').fill('Graduate operations and reporting')
                                page.locator('#pref-city').fill('Bristol'); page.locator('#pref-country').fill('United Kingdom')
                                page.locator('#links').fill('https://example.test/my-project')
                                page.wait_for_function("document.querySelector('#draftStatus').textContent.includes('resume later')")
                                self.assertFalse(profile.exists())
                                # Restart the actual HTTP app, not just a browser refresh.
                                server.shutdown(); server.server_close(); thread.join()
                                server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(data, profile, 'next-token'))
                                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                                page.goto(f'http://127.0.0.1:{server.server_port}/')
                                page.locator('#review').wait_for(state='visible')
                                self.assertEqual(page.locator('#answer-0').input_value(), 'I organised a volunteer rota for a campus group.')
                                self.assertEqual(page.locator('#pref-desired_work').input_value(), 'Graduate operations and reporting')
                                self.assertEqual(page.locator('#links').input_value(), 'https://example.test/my-project')
                                self.assertFalse(page.locator('#confirmed').is_checked())
                                self.assertEqual(extraction.call_count, 1)
                                page.locator('#confirmed').check()
                                page.get_by_role('button', name='Save my reviewed profile').click()
                                page.locator('#finished').wait_for(state='visible')
                            candidate = load_profile(profile)
                            self.assertEqual(candidate['resume']['experience'], [])
                            self.assertEqual(source_facts(candidate)['skills.0.0'], 'SQL')
                            with fixture_server() as (origin, received), closing(Store(data / 'jobs.sqlite')) as store:
                                key = store.ingest({**job(origin + '/graduate', 'Graduate Reporting Assistant'), 'location': 'Bristol'})
                                result = run_queue(store, candidate, StudentModel(), browser, data / 'applications',
                                                   limit=1, prepare=True, fixture_origin=origin, profile_path=profile)
                                self.assertEqual(result[0]['status'], 'prepared', result)
                                self.assertEqual(received, [])
                                directory = data / 'applications' / key
                                output = read_json(directory / 'cv.json')
                                self.assertEqual(output['experience'], [])
                                self.assertEqual(output['projects'][0]['name'], 'University reporting project')
                                pdf_text = PdfReader(directory / 'cv.pdf').pages[0].extract_text()
                                self.assertIn('BA Business', pdf_text)
                                self.assertIn('SQL', pdf_text)
                                self.assertNotIn('Work Experience', pdf_text)
                                self.assertNotIn('Fictional Software', pdf_text)
                            self.assertEqual(errors, [])
                        finally:
                            page.close(); server.shutdown(); server.server_close(); thread.join()
            finally: browser.close()

    def test_no_employment_does_not_authorize_inventing_an_employer_or_a_blank_cv(self):
        profile = example_profile(); profile['resume']['experience'] = []
        class InventedEmployment(StudentModel):
            def generate(self, task, data, schema):
                value = super().generate(task, data, schema)
                if 'Tailor the CV' in task:
                    value['experience'] = [{'index': 0, 'bullets': []}]
                return value
        with self.assertRaisesRegex(NeedsInput, 'employment identity'):
            tailor(job('https://example.test/role'), profile, InventedEmployment())
        for field in ('summary', 'skills', 'competencies', 'certifications', 'education', 'projects'):
            profile['resume'][field] = '' if field == 'summary' else []
        profile['facts'] = []
        with self.assertRaisesRegex(NeedsInput, 'Add confirmed'):
            tailor(job('https://example.test/role'), profile, object())


if __name__ == '__main__': unittest.main()
