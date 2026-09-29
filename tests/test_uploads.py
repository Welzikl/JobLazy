import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from joblazy.browser import apply
from joblazy.materials import tailor,render
from joblazy.store import Store
from joblazy.common import read_json
from joblazy.uploads import attach_upload
from .support import fixture_server,example_profile,FixtureModel,job


class UploadTests(unittest.TestCase):
    def test_upload_completion_failure_and_reference_checks(self):
        with tempfile.TemporaryDirectory() as temp,fixture_server() as (origin,received),sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True);store=Store(Path(temp)/'jobs.sqlite')
            profile=example_profile();artifact=render(tailor(job(origin),profile,FixtureModel()),Path(temp)/'cv',browser)
            try:
                for suffix in ('success','failed','mismatch','pending','stale','wrong-bytes'):
                    with self.subTest(suffix=suffix):
                        url=origin+'/teamtailor-upload-'+suffix;posting=job(url);key=store.ingest(posting)
                        directory=Path(temp)/key;page=browser.new_page()
                        profile['answers']=[{'scope':url,'question':q,'value':v}for q,v in
                            [('Gender Identity','Prefer not to say'),('I agree to the application privacy policy.','I agree to the application privacy policy.')]]
                        store.transition(key,'materials_ready')
                        def bounded(*args,**kwargs):return attach_upload(*args,**kwargs,timeout=.3)
                        with patch('joblazy.uploads.attach_upload',side_effect=bounded):
                            status=apply(page,posting,profile,artifact,store,key,directory,submit=True,fixture_origin=origin,verify_seconds=1)
                        expected='submitted' if suffix=='success' else 'needs_input'
                        self.assertEqual(status,expected)
                        audit=read_json(directory/'browser.json')['file_audit'][0]
                        self.assertEqual(audit['state'],{'success':'complete','failed':'empty','mismatch':'invalid','pending':'pending','stale':'invalid','wrong-bytes':'complete'}[suffix])
                        uploads=[r for r in received if r['path']=='/upload/teamtailor-upload-'+suffix]
                        submits=[r for r in received if r['path']=='/submit/teamtailor-upload-'+suffix]
                        self.assertEqual(len(uploads),1 if suffix in ('success','failed','mismatch','wrong-bytes') else 0)
                        self.assertEqual(len(submits),1 if suffix=='success' else 0)
                        if suffix=='success':
                            self.assertIn(Path(artifact['path']).read_bytes(),uploads[0]['body'])
                            self.assertIn(b'candidate[resume_remote_url]',submits[0]['body'])
                            self.assertIn((origin+'/uploaded/cv.pdf').encode(),submits[0]['body'])
                            self.assertEqual(audit['files'][0]['sha256'],artifact['sha256'])
                        else:self.assertFalse(read_json(directory/'browser.json')['attached'])
                        page.close()
            finally:browser.close();store.close()
