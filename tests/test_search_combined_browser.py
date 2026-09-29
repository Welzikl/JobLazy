from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from joblazy.common import digest, write_json
from joblazy.dashboard import make_handler
from joblazy.store import Store
from .support import example_profile, job
from .test_search import PLAN
from .test_shortlist_review import BatchModel


class CombinedSearchBrowserTests(unittest.TestCase):
    def test_one_click_dispatches_search_and_displays_validated_astra_shortlist(self):
        self.exercise_search()

    def test_shortlist_remains_visible_while_feed_is_blocked_and_after_reload(self):
        self.exercise_search(wait_on_feed=True)

    def test_friend_preset_dispatches_six_luna_searches_and_luna_review(self):
        self.exercise_search(preset='friend')

    def exercise_search(self, *, wait_on_feed=False, preset='personal'):
        from playwright.sync_api import sync_playwright
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); profile = example_profile(); path = root / 'profile.json'
            write_json(path, profile)
            write_json(root / 'search/plan.json', {'plan': {**PLAN, 'sources': ['web_search','remotive'] if wait_on_feed else ['web_search']},
                       'profile_hash': digest(profile), 'confirmed': True, 'created_at': 'fixture'})
            requests = []
            feed_started=threading.Event(); release_feed=threading.Event()
            def feed(path,store,checkpoint,**kwargs):
                feed_started.set()
                if not release_feed.wait(20):raise RuntimeError('Fixture feed was not released')
                # A later source failure must preserve the earlier shortlist.
                raise OSError('Fictional supplementary feed unavailable')
            class SearchModel:
                def __init__(inner, cache, **kwargs):
                    self.assertEqual(kwargs['model'], 'gpt-6-luna')
                    inner.reserve = kwargs['before_request']
                def generate(inner, *args):
                    inner.reserve(); requests.append('search')
                    return {'jobs': [{'url': 'https://example.test/role', 'title': 'Partner Operations Associate',
                                      'company': '', 'location': '', 'reason': ''}], 'gaps': []}
            class ReviewModel:
                def __init__(inner, cache, **kwargs):
                    self.assertEqual(kwargs['model'], 'gpt-6-luna' if preset == 'friend' else 'gpt-6-astra')
                    inner.reserve = kwargs['before_request']
                def generate(inner, task, data, schema):
                    inner.reserve(); requests.append('review')
                    return {'results': [{'id': row['id'], 'recommend': True,
                        'reason': 'Relevant documented partner operations work.',
                        'job_quotes': ['partner onboarding'], 'candidate_source_ids': ['experience.0.0'],
                        'caveats': ['Full application assessment remains pending.']} for row in data['jobs']]}
            def verify(url, **kwargs):
                return {'status': 'verified', 'job': {**job(url), 'observed_at': datetime.now(timezone.utc).isoformat()}}
            channel = os.environ.get('JOBLAZY_TEST_BROWSER_CHANNEL', 'chrome')
            with patch('joblazy.search.CodexWebSearch', SearchModel), patch('joblazy.search.CodexModel', ReviewModel), \
                 patch('joblazy.ats_postings.verify_posting', side_effect=verify), \
                 patch('joblazy.search.discover', side_effect=feed), \
                 patch('joblazy.dashboard.CodexModel.status', return_value={'available': True}):
                server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(root, path, 'fixture-token', browser_channel=channel,
                                                                         model_preset_name=preset))
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
                try:
                    with sync_playwright() as pw:
                        browser = pw.chromium.launch(headless=True, **({'channel': channel} if channel != 'chromium' else {}))
                        try:
                            page = browser.new_page(); errors = []; page.on('pageerror', lambda error: errors.append(str(error)))
                            page.goto(f'http://127.0.0.1:{server.server_port}/search')
                            page.get_by_role('button', name='Search and review', exact=True).click()
                            page.locator('#reviewResults').get_by_role('link', name='Partner Operations Associate', exact=False).wait_for(timeout=20000)
                            self.assertIn('Preliminary recommendation', page.locator('#reviewResults').inner_text())
                            self.assertNotIn('Fit ', page.locator('#reviewResults').inner_text())
                            if wait_on_feed:
                                self.assertTrue(feed_started.wait(5))
                                self.assertTrue(page.get_by_role('button',name='Search and review',exact=True).is_disabled())
                                self.assertIn('shortlist is ready',page.locator('#status').inner_text())
                                page.reload()
                                page.locator('#reviewResults').get_by_role('link',name='Partner Operations Associate',exact=False).wait_for(timeout=10000)
                                self.assertTrue(page.get_by_role('button',name='Search and review',exact=True).is_disabled())
                                release_feed.set()
                                page.wait_for_function("!document.getElementById('search').disabled")
                                self.assertIn('coverage gaps',page.locator('#status').inner_text())
                            else:
                                page.wait_for_function("!document.getElementById('search').disabled")
                            self.assertFalse(page.get_by_role('button', name='Resume saved search').is_disabled())
                            self.assertEqual(errors, [])
                        finally: release_feed.set(); browser.close()
                finally: release_feed.set(); server.shutdown(); server.server_close(); thread.join()
            self.assertEqual(requests.count('search'), 6)
            self.assertEqual(requests.count('review'), 1)
            store = Store(root / 'jobs.sqlite')
            try: self.assertEqual([row['status'] for row in store.list()], ['discovered'])
            finally: store.close()
            self.assertFalse(list((root / 'applications').glob('*/artifact.json')))


if __name__ == '__main__': unittest.main()
