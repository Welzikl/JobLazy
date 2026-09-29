import json
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from playwright.sync_api import sync_playwright

from joblazy.browser import apply
from joblazy.common import digest, read_json
from joblazy.store import Store
from joblazy.uploads import attach_ashby_upload
from .support import example_profile, fixture_server, job


class AshbyUploadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel='chrome', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def test_native_filelist_without_committed_component_is_not_prepared(self):
        self.check_mode('filelist-only', 'needs_input')

    def test_completed_display_and_failed_uploads(self):
        for mode in ('success','pending','wrong-name','failed','removed','wrong-bytes','existing'):
            with self.subTest(mode=mode):
                self.check_mode(mode,'submitted' if mode=='success' else 'needs_input')

    def check_mode(self, mode, expected):
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin, received), closing(Store(Path(temp)/'jobs.sqlite')) as store:
            path = Path(temp)/'cv.pdf'
            path.write_bytes(b'%PDF-1.4\n% Fictional local upload test\n%%EOF')
            artifact = {'path':str(path), 'sha256':digest(path.read_bytes())}
            posting = job(origin+'/ashby-upload-'+mode)
            key = store.ingest(posting);store.transition(key, 'processing')
            page = self.browser.new_page()
            try:
                page.add_init_script('window.mode='+json.dumps(mode))
                def bounded(*args,**kwargs):
                    return attach_ashby_upload(*args,**kwargs,timeout=.8)
                with patch('joblazy.uploads.attach_ashby_upload',side_effect=bounded):
                    status = apply(page, posting, example_profile(), artifact, store, key, temp,
                                   fixture_origin=origin, submit=True, verify_seconds=1)
                self.assertEqual(status, expected)
                report = read_json(Path(temp)/'browser.json')
                self.assertEqual(report['attached'], expected=='submitted')
                self.assertEqual(page.evaluate('window.uploads'), 0 if mode=='existing' else 1)
                submissions = [r for r in received if r['path'].startswith('/submit/')]
                self.assertEqual(len(submissions), int(expected=='submitted'))
                if expected=='submitted':
                    self.assertIn(path.read_bytes(), submissions[0]['body'])
                    self.assertIn(path.read_bytes(),next(r['body'] for r in received if r['path'].startswith('/upload/')))
                else:
                    self.assertEqual(page.locator('input[type=file]').evaluate('e=>e.files.length'), 0 if mode in ('removed','existing') else 1)
            finally:
                page.close()


if __name__ == '__main__':
    unittest.main()
