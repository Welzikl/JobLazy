import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from playwright.sync_api import sync_playwright
from joblazy.browser import prepare_step, apply
from joblazy.common import digest
from joblazy.store import Store
from joblazy.answers import questions
from .support import example_profile, fixture_server, job


class UploadRejectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(channel='chrome', headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name)/'cv.pdf'
        path.write_bytes(b'%PDF-1.4\n% Fictional upload fixture\n%%EOF')
        self.artifact = {'path':str(path), 'sha256':digest(path.read_bytes())}
        self.page = self.browser.new_page()
        self.addCleanup(self.page.close)
        # A trustworthy local origin gives the fixture Web Crypto for file hashing.
        self.page.route('http://localhost/**', lambda r:r.fulfill(body='<html></html>', content_type='text/html'))
        self.page.goto('http://localhost/upload')
        self.page.set_content('''<form><label>Full name<input name="name"></label>
          <label>Email<input type="email" name="email"></label>
          <label>Resume<input id="resume" type="file" required></label>
          <button type="button">Submit Application</button></form><div id="notice"></div>
          <script>window.uploads=0;document.querySelector('#resume').addEventListener('change',()=>window.uploads++);</script>''')

    def prepare(self):
        return prepare_step(self.page, self.page.main_frame, example_profile(),
                            'http://localhost/upload', self.artifact)

    def test_failed_remote_upload_is_not_attached_even_when_filelist_survives(self):
        self.page.evaluate('''() => document.querySelector('#resume').addEventListener('change',()=>{
          setTimeout(()=>document.querySelector('#notice').textContent='cv.pdf failed to upload',350);
        })''')
        report = self.prepare()
        self.assertEqual(self.page.locator('#resume').evaluate('e=>e.files.length'),1)
        self.assertFalse(report['attached'])
        self.assertEqual(report['application_blockers'][0]['kind'],'upload_failed')
        self.assertEqual(self.page.evaluate('window.uploads'),1)

    def test_existing_spam_warning_stops_entry_and_upload(self):
        self.page.locator('#notice').evaluate("e=>e.textContent='This has been marked as potential spam. Please apply again.'")
        report = self.prepare()
        self.assertFalse(report['attached'])
        self.assertEqual(self.page.evaluate('window.uploads'),0)
        self.assertEqual(self.page.locator('[name=email]').input_value(),'')
        self.assertEqual(report['application_blockers'][0]['kind'],'spam_rejection')

    def test_removed_file_is_not_reuploaded_in_later_passes(self):
        self.page.evaluate("""() => document.querySelector('#resume').addEventListener('change',e=>{
          setTimeout(()=>e.target.value='',20);
        })""")
        report=self.prepare()
        self.assertFalse(report['attached'])
        self.assertEqual(self.page.evaluate('window.uploads'),1)

    def test_normal_attachment_and_general_spam_description_are_not_blocked(self):
        self.page.locator('#notice').evaluate("e=>e.textContent='Help customers prevent spam and investigate failed uploads.'")
        report=self.prepare()
        self.assertTrue(report['attached'])
        self.assertEqual(report['application_blockers'],[])

    def test_role_filename_reaches_browser_without_changing_pdf_bytes(self):
        posting={'company':'Example Labs','title':'Operations Associate'}
        report=prepare_step(self.page,self.page.main_frame,example_profile(),
                            'http://localhost/upload',self.artifact,job=posting)
        self.assertEqual(self.page.locator('#resume').evaluate('e=>e.files[0].name'),
                         'Alex_Example_Example_Labs_Operations_Associate_CV.pdf')
        self.assertEqual(report['file_audit'][0]['files'][0]['sha256'],self.artifact['sha256'])

    def test_connected_rejection_is_reported_and_never_submitted(self):
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin,received), closing(Store(Path(temp)/'jobs.sqlite')) as store:
            directory=Path(temp)
            posting=job(origin+'/success');key=store.ingest(posting)
            store.transition(key,'processing')
            self.page.add_init_script('''document.addEventListener('change',e=>{
              if(e.target.type==='file') {
                const error=document.createElement('div');
                error.textContent='cv.pdf failed to upload';document.body.append(error);
              }
            });''')
            status=apply(self.page,posting,example_profile(),self.artifact,store,key,directory,
                         submit=True,fixture_origin=origin)
            self.assertEqual(status,'needs_input')
            self.assertEqual(received,[])
            self.assertIn({'field':'Application','reason':'cv.pdf failed to upload'},
                          questions(store,key,directory)['verification_issues'])


if __name__ == '__main__':
    unittest.main()
