import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright
from joblazy.browser import apply
from joblazy.pipeline import run_queue
from joblazy.common import read_json,NeedsInput
from joblazy.store import Store
from .support import example_profile,FixtureModel,job
from .frame_fixture import replacing_frame_server


class ReplacedFrameTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch(channel='chrome',headless=True)
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()

    def test_cross_origin_replacement_retains_contact_and_verifies_pdf_and_receipt(self):
        self.exercise(False)

    def test_unanswered_question_in_replacement_does_not_submit(self):
        self.exercise(True)

    def test_ambiguous_replacement_frames_stop_before_upload_or_submission(self):
        self.exercise(False,True)

    def test_authentication_in_replacement_stops_before_upload_or_filling(self):
        self.exercise(False,authentication=True)

    def exercise(self,unknown,ambiguous=False,authentication=False):
        with tempfile.TemporaryDirectory() as temp,replacing_frame_server(unknown,ambiguous,authentication) as (origins,saved,received):
            self.assertNotEqual(origins['outer'],origins['frame'])
            store=Store(Path(temp)/'jobs.sqlite');page=self.browser.new_page()
            try:
                posting=job(origins['outer']+'/outer');key=store.ingest(posting);profile=example_profile()
                run_queue(store,profile,FixtureModel(),self.browser,temp,1,fixture_origin=origins['outer'])
                directory=Path(temp)/key;artifact=read_json(directory/'artifact.json')
                # Only the two test servers stand in for validated public hosts.
                def allowed(url):
                    parsed=urlsplit(url)
                    return f'{parsed.scheme}://{parsed.netloc}' in origins.values()
                with patch('joblazy.browser.public_url',side_effect=allowed):
                    if ambiguous or authentication:
                        expected='Multiple visible application forms' if ambiguous else 'authentication or a challenge'
                        with self.assertRaisesRegex(NeedsInput,expected):
                            apply(page,posting,profile,artifact,store,key,directory,submit=True,allow_live=True,verify_seconds=2)
                        self.assertEqual(received,[])
                        frames=[f for f in page.frames if f.url==origins['frame']+'/step2']
                        self.assertEqual(len(frames),2 if ambiguous else 1)
                        for frame in frames:
                            self.assertEqual(frame.locator('[name=resume]').evaluate('e=>e.files.length'),0)
                            self.assertEqual(frame.locator('[name=phone]').input_value(),'')
                        self.assertNotIn(store.get(key)['status'],('submitting','submitted','submission_unknown'))
                        return
                    status=apply(page,posting,profile,artifact,store,key,directory,submit=True,allow_live=True,verify_seconds=2)
                self.assertEqual(saved,{'name':'Alex Example','email':'alex@example.test'})
                self.assertEqual(page.locator('[name=newsletter]').input_value(),'')
                report=read_json(directory/'browser.json')
                self.assertEqual(len(report['steps']),2)
                self.assertEqual(report['steps'][0]['form_url'],origins['frame']+'/step1')
                self.assertEqual(report['steps'][1]['form_url'],origins['frame']+'/step2')
                if unknown:
                    self.assertEqual(status,'needs_input');self.assertEqual(received,[])
                    self.assertTrue(any(q['required'] for q in report['unresolved']))
                else:
                    self.assertEqual(status,'submitted');self.assertEqual(len(received),1)
                    for value in (b'Alex Example',b'alex@example.test',b'+442079460000',Path(artifact['path']).read_bytes()):
                        self.assertIn(value,received[0])
                    confirmation=read_json(directory/'confirmation.json')
                    self.assertEqual(confirmation['application_frame_url'],origins['frame']+'/step2')
                    self.assertEqual(store.get(key)['status'],'submitted')
            finally:page.close();store.close()
