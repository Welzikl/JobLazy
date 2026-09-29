"""A new fictional person completes the visible intake-to-shortlist journey."""
import copy
import os
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from joblazy.common import read_json, write_json
from joblazy.dashboard import make_handler
from joblazy.pipeline import ingest_discovery_result, run_queue
from joblazy.store import Store
from .support import FixtureModel, fixture_server, job
from .test_onboarding import CV, IntakeModel
from .test_search import PLAN


class DashboardIntakeModel(IntakeModel):
    """One harmless model double for both the dashboard status and CV draft."""

    def status(self):
        return {'available': True, 'detail': 'Fixture'}


class FirstRunJourneyTests(unittest.TestCase):
    def test_new_person_uses_only_browser_controls_from_cv_to_explained_shortlist(self):
        self.exercise_journey('personal')

    def test_friend_intake_and_full_ranking_use_luna(self):
        self.exercise_journey('friend')

    def exercise_journey(self, preset):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin, received):
            root = Path(temp); data = root / 'runtime'; profile = root / 'local/profile.json'; launched = []
            channel = os.environ.get('JOBLAZY_TEST_BROWSER_CHANNEL', 'chrome')
            def scan(path, store, checkpoint, *, timeout=45):
                entry = read_json(path)['boards'][0]
                return ingest_discovery_result({'jobs': [job(origin + '/success', 'Partner Operations Associate')], 'errors': [],
                    'source_runs': [{'entry': entry, 'status': 'completed', 'urls': [origin + '/success'], 'warnings': []}]}, store, checkpoint)
            def fixture_rank(*args, **kwargs):
                return run_queue(*args, **kwargs, fixture_origin=origin)
            def intake_model(*args, **kwargs):
                if 'model' in kwargs:
                    self.assertEqual(kwargs['model'], 'gpt-6-luna' if preset == 'friend' else 'gpt-5.6-terra')
                return DashboardIntakeModel()
            selected_models = []
            def ranking_model(*args, **kwargs):
                expected = {'gpt-6-luna'} if preset == 'friend' else {'gpt-6-luna', 'gpt-6-astra'}
                self.assertIn(kwargs['model'], expected)
                selected_models.append(kwargs['model'])
                return FixtureModel()
            server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(data, profile, 'fixture-token',
                                       assist_launcher=launched.append, browser_channel=channel, model_preset_name=preset))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                with patch('joblazy.dashboard.CodexModel', side_effect=intake_model), \
                     patch('joblazy.search.generate_plan', return_value=copy.deepcopy(PLAN)), \
                     patch('joblazy.search.discover', side_effect=scan), \
                     patch('joblazy.search.CodexModel', side_effect=ranking_model), \
                     patch('joblazy.search.run_queue', side_effect=fixture_rank), sync_playwright() as pw:
                    browser = pw.chromium.launch(headless=True, **({'channel': channel} if channel != 'chromium' else {}))
                    try:
                        page = browser.new_page(); errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                        page.goto(f'http://127.0.0.1:{server.server_port}/')
                        page.locator('#cv').set_input_files({'name': 'cv.txt', 'mimeType': 'text/plain', 'buffer': CV.encode()})
                        page.get_by_role('button', name='Extract a draft with Codex').click(); page.locator('#review').wait_for(state='visible')
                        for field, value in {'first_name': 'Morgan', 'last_name': 'Example', 'email': 'morgan@example.test',
                            'phone': '+442079460000', 'city': 'Bristol', 'country': 'United Kingdom'}.items():
                            page.locator('#identity-' + field).fill(value)
                        page.locator('#answer-0').fill('I coordinated schedules and onboarding documents for partner contacts.')
                        page.locator('#extra').fill('I volunteered to run a student event series and tracked attendance.')
                        page.locator('#pref-desired_work').fill('Partner operations and customer experience')
                        page.locator('#pref-city').fill('Bristol'); page.locator('#pref-country').fill('United Kingdom')
                        page.locator('#pref-experience_level').fill('Early-career roles with room to grow')
                        page.locator('#pref-avoid').fill('Outbound sales')
                        page.locator('#confirmed').check(); page.get_by_role('button', name='Save my reviewed profile').click()
                        page.locator('#finished').wait_for(state='visible'); self.assertTrue(profile.exists())
                        page.get_by_role('link', name='Build my search').click(); page.get_by_role('button', name='Suggest search plan').click()
                        page.locator('#planSection').wait_for(state='visible'); page.get_by_role('button', name='Save search plan', exact=True).click()
                        page.wait_for_function("!document.querySelector('#scan').disabled")
                        page.get_by_role('button', name='Fetch vacancies', exact=True).click()
                        page.wait_for_function("document.querySelector('#counts').textContent.includes('1 saved roles')")
                        page.get_by_role('button', name='Rank matching roles', exact=True).click()
                        page.wait_for_function("document.querySelector('#status').textContent.includes('Ranking finished')", timeout=20000)
                        page.get_by_role('link', name='Review fit scores', exact=True).click()
                        page.get_by_role('heading', name='Partner Operations Associate', exact=True).wait_for()
                        self.assertIn('85', page.locator('#jobs').inner_text())
                        page.get_by_role('link', name='Review applications', exact=True).click()
                        page.get_by_role('heading', name='Your JobLazy shortlist', exact=True).wait_for()
                        self.assertIn('Fixture ranking only', page.locator('main').inner_text())
                        self.assertEqual(received, [])
                        self.assertEqual(launched, [])
                        self.assertEqual(errors, [])
                        self.assertIn('gpt-6-luna' if preset == 'friend' else 'gpt-6-astra', selected_models)
                    finally: browser.close()
            finally: server.shutdown(); server.server_close(); thread.join()


if __name__ == '__main__': unittest.main()
