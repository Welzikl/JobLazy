import copy
import json
import os
import tempfile
import threading
import unittest
from contextlib import closing
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from joblazy.common import digest, read_json, write_json
from joblazy.dashboard import make_handler
from joblazy.locking import LockBusy, run_lock
from joblazy.profile_edit import ProfileEditConflict, edit_profile, profile_form, profile_state
from joblazy.profiles import load_profile
from .support import example_profile


class ProfileEditTests(unittest.TestCase):
    def payload(self, path):
        state = profile_state(path)
        form = copy.deepcopy(state['profile'])
        form['identity'].update(first_name='Morgan', last_name='Example', email='morgan@example.test',
                                phone='+442079460000', city='Bristol', country='United Kingdom')
        form['preferences'].update(desired_work='Product research', city='Bristol', country='United Kingdom')
        return {'revision': state['revision'], 'confirmed': True, 'profile': form}

    def test_confirmed_edit_updates_only_confirmed_values_and_keeps_private_before_after_record(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path = root / 'local/profile.json'; data = root / 'runtime'
            original = example_profile(); write_json(path, original)
            payload = self.payload(path)
            payload['profile'].update(summary='Updated confirmed summary.', skills=['SQL', 'User research'],
                                      facts=['I ran interviews for a student project.'],
                                      links=['https://example.test/portfolio'])
            payload['profile']['experience'][0]['role'] = 'Client Operations Coordinator'
            result = edit_profile(data, path, payload)
            saved = load_profile(path)
            self.assertEqual(saved['resume']['experience'][0]['role'], 'Client Operations Coordinator')
            self.assertEqual(saved['resume']['summary'], 'Updated confirmed summary.')
            self.assertEqual(saved['resume']['skills'][0]['items'], ['SQL', 'User research'])
            self.assertEqual(saved['facts'][0]['source']['method'], 'operator_profile_edit')
            self.assertEqual(saved['supporting_links'], [{'url': 'https://example.test/portfolio', 'status': 'not_read'}])
            audit = data / 'profile-edits' / result['edit_id']
            self.assertEqual(read_json(audit / 'before.json'), original)
            self.assertEqual(read_json(audit / 'after.json'), saved)
            self.assertEqual(read_json(audit / 'receipt.json')['after_revision'], result['revision'])
            self.assertNotEqual(result['revision'], payload['revision'])

    def test_stale_or_unconfirmed_or_unsafe_link_cannot_change_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path = root / 'profile.json'; write_json(path, example_profile())
            payload = self.payload(path); before = path.read_bytes()
            payload['confirmed'] = False
            with self.assertRaisesRegex(ValueError, 'confirmation'): edit_profile(root / 'runtime', path, payload)
            self.assertEqual(path.read_bytes(), before)
            payload['confirmed'] = True; payload['profile']['links'] = ['http://example.test/not-secure']
            with self.assertRaisesRegex(ValueError, 'HTTPS'): edit_profile(root / 'runtime', path, payload)
            self.assertEqual(path.read_bytes(), before)
            payload['profile']['links'] = []
            write_json(path, {**example_profile(), 'minimum_score': 71})
            with self.assertRaises(ProfileEditConflict): edit_profile(root / 'runtime', path, payload)
            self.assertEqual(load_profile(path)['minimum_score'], 71)

    def test_legacy_free_text_targeting_can_be_reviewed_in_the_editor(self):
        legacy = example_profile(); legacy['targeting'] = 'Product research and customer interviews'
        form = profile_form(legacy)
        self.assertEqual(form['preferences']['desired_work'], 'Product research and customer interviews')

    def test_phone_only_edit_preserves_undisplayed_canonical_fields_and_uses_profile_writer_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path = root / 'local/profile.json'; data = root / 'runtime'
            original = example_profile()
            original['targeting']['config'] = {'location': {'authorized_in': ['United Kingdom']},
                                               'target_roles': {'seniority': {'maximum_required_years': 5}}}
            original['resume']['experience'][0].update(hours_per_week='40', employment_type='full-time',
                                                        employer_context='B2B SaaS partner platform')
            original['resume']['projects'] = [{'name': 'Dashboard', 'description': 'Built reporting.',
                                                'bullets': ['Audited data quality.'], 'source_note': 'Portfolio'}]
            original['facts'] = [{'text': 'Confirmed legacy fact.', 'source': {'method': 'operator_confirmed'}}]
            original['supporting_links'] = [{'url': 'https://example.test/portfolio', 'status': 'reviewed',
                                             'review_note': 'Confirmed by applicant'}]
            write_json(path, original)
            state = profile_state(path); payload = {'revision': state['revision'], 'confirmed': True,
                                                     'profile': copy.deepcopy(state['profile'])}
            payload['profile']['identity']['phone'] = '+442079460001'
            payload['profile']['preferences'].update(desired_work='Product research', city='London', country='United Kingdom')
            with run_lock(data / 'run.lock'):
                with self.assertRaises(LockBusy): edit_profile(data, path, payload)
            edit_profile(data, path, payload)
            saved = load_profile(path)
            self.assertEqual(saved['targeting']['config'], original['targeting']['config'])
            self.assertEqual(saved['resume']['experience'][0]['hours_per_week'], '40')
            self.assertEqual(saved['resume']['experience'][0]['employer_context'], 'B2B SaaS partner platform')
            self.assertEqual(saved['resume']['projects'][0]['bullets'], ['Audited data quality.'])
            self.assertEqual(saved['facts'], original['facts'])
            self.assertEqual(saved['supporting_links'], original['supporting_links'])

    def test_browser_edits_existing_profile_without_exposing_api_without_token(self):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); path = root / 'local/profile.json'; data = root / 'runtime'; write_json(path, example_profile())
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(data, path, 'fixture-token'))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                with closing(HTTPConnection('127.0.0.1', server.server_port)) as connection:
                    connection.request('GET', '/api/profile'); response = connection.getresponse(); response.read()
                    self.assertEqual(response.status, 403)
                with sync_playwright() as pw:
                    channel = os.environ.get('JOBLAZY_TEST_BROWSER_CHANNEL', 'chrome')
                    browser = pw.chromium.launch(headless=True, **({'channel': channel} if channel != 'chromium' else {}))
                    try:
                        page = browser.new_page(); errors=[]; page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(f'http://127.0.0.1:{server.server_port}/profile')
                        page.locator('#identity-first_name').fill('Morgan'); page.locator('#identity-last_name').fill('Example')
                        page.locator('#identity-email').fill('morgan@example.test'); page.locator('#identity-phone').fill('+442079460000')
                        page.locator('#identity-city').fill('Bristol'); page.locator('#identity-country').fill('United Kingdom')
                        page.locator('#pref-desired_work').fill('Product research'); page.locator('#pref-city').fill('Bristol'); page.locator('#pref-country').fill('United Kingdom')
                        page.locator('#skills').fill('SQL\nUser research'); page.locator('#links').fill('https://example.test/portfolio')
                        page.locator('#confirmed').check(); page.get_by_role('button', name='Save profile changes').click()
                        page.wait_for_function("document.querySelector('#message').textContent.includes('profile changes are saved')")
                        saved=load_profile(path)
                        self.assertEqual(saved['targeting']['desired_work'], 'Product research')
                        self.assertEqual(saved['supporting_links'][0]['url'], 'https://example.test/portfolio')
                        self.assertEqual(errors, [])
                    finally: browser.close()
            finally: server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
