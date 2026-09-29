from contextlib import closing
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import patch

from joblazy.application_ui import ApplicationController
from joblazy.assist_bridge import BrowserBridge, request_resume, session_state
from joblazy.common import NeedsInput, digest, write_json
from joblazy.dashboard import make_handler
from joblazy.model_presets import model_preset
from joblazy.store import Store
from .support import example_profile, job


class ApplicationUITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name);self.profile=self.data/'profile.json'
        write_json(self.profile,example_profile())
        with closing(Store(self.data/'jobs.sqlite')) as store:
            self.key=store.ingest(job('https://example.test/role'))
        self.controller=ApplicationController(self.data,self.profile,model_preset('friend'))

    def test_explicit_assessment_can_retry_unprepared_failure_but_not_handoff(self):
        def queued(store, *args, **kwargs):
            self.assertEqual(store.get(self.key)['status'], 'retryable')
            return []
        with patch('joblazy.application_ui.run_queue', side_effect=queued) as run:
            for status in ('materials_ready', 'needs_input', 'model_failed', 'processing_failed'):
                with closing(Store(self.data/'jobs.sqlite')) as store: store.transition(self.key, status, {'reason': 'Saved fixture work'})
                self.controller._work(self.key, 'assess')
                self.assertEqual(self.controller.operation['state'], 'complete')
            self.assertEqual(run.call_count, 4)
            with closing(Store(self.data/'jobs.sqlite')) as store: store.transition(self.key, 'manual_review')
            self.controller._work(self.key, 'assess')
            self.assertEqual(self.controller.operation['state'], 'needs_attention')
            self.assertEqual(run.call_count, 4)
            with closing(Store(self.data/'jobs.sqlite')) as store: self.assertEqual(store.get(self.key)['status'], 'manual_review')

    def test_scoped_answer_requires_confirmation_current_profile_and_observed_question(self):
        directory=self.data/'applications'/self.key
        write_json(directory/'browser.json',{'scope':'https://example.test','unresolved':[
            {'id':'auth','field':'Work authorization','reason':'Unconfirmed','options':['Yes','No']}],
            'fields':[{'id':'auth','label':'Work authorization','options':['Yes','No']}]})
        with closing(Store(self.data/'jobs.sqlite')) as store:store.transition(self.key,'manual_review')
        payload={'question':'Work authorization','value':'Yes','confirmed':True,'profile_revision':digest(example_profile())}
        with self.assertRaises(ValueError):self.controller.answer(self.key,{**payload,'confirmed':False})
        with self.assertRaises(NeedsInput):self.controller.answer(self.key,{**payload,'profile_revision':'stale'})
        with self.assertRaises(NeedsInput):self.controller.answer(self.key,{**payload,'question':'Unobserved claim'})
        result=self.controller.answer(self.key,payload)
        self.assertEqual(result['status'],'manual_review')
        self.assertEqual(self.controller.state(self.key)['status'],'manual_review')

    def test_outcome_is_explicit_and_uncertainty_never_allows_an_automatic_retry(self):
        with closing(Store(self.data/'jobs.sqlite')) as store:store.transition(self.key,'manual_review')
        payload={'confirmed':True,'outcome':'uncertain','note':'Closed page; could not verify receipt.'}
        self.assertEqual(self.controller.outcome(self.key,payload)['status'],'submission_unknown')
        with closing(Store(self.data/'jobs.sqlite')) as store:
            with self.assertRaises(ValueError):store.transition(self.key,'processing')
        self.assertEqual(self.controller.outcome(self.key,{**payload,'outcome':'not-submitted','note':'Checked employer portal: draft only.'})['status'],'needs_input')

    def test_resume_is_bound_to_one_live_session_and_only_consumed_once(self):
        with closing(Store(self.data/'jobs.sqlite')) as store:
            store.transition(self.key,'manual_review'); bridge=BrowserBridge(store,self.key)
            with store.db:store.db.execute("UPDATE assist_sessions SET status='waiting'")
            with self.assertRaises(NeedsInput):request_resume(store,self.key,'old-session')
            request_resume(store,self.key,bridge.id)
            with self.assertRaises(NeedsInput):request_resume(store,self.key,bridge.id)
            class Page:
                def is_closed(self):return False
                def wait_for_timeout(self,_):raise AssertionError('Pending command should be consumed immediately')
            self.assertEqual(bridge.wait(Page(),'Fixture'),'resume')
            self.assertFalse(session_state(store,self.key)['active'])
            bridge.close()
            with self.assertRaises(NeedsInput):request_resume(store,self.key,bridge.id)

    def test_http_actions_require_token_and_preparation_requires_verified_cv(self):
        launched=[]
        server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(self.data,self.profile,'fixture-token',
                                   assist_launcher=launched.append,model_preset_name='friend'))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            for token,expected in [('',403),('fixture-token',409)]:
                connection=HTTPConnection('127.0.0.1',server.server_port)
                connection.request('POST',f'/api/application/{self.key}/prepare',body=json.dumps({'confirmed':True,'cv_sha256':'wrong'}),
                                   headers={'X-JobLazy-Token':token,'Content-Type':'application/json'})
                response=connection.getresponse();self.assertEqual(response.status,expected);response.read();connection.close()
            self.assertEqual(launched,[])
            connection=HTTPConnection('127.0.0.1',server.server_port)
            connection.request('GET',f'/application/{self.key}',headers={'Host':'untrusted.example'})
            response=connection.getresponse();self.assertEqual(response.status,403);response.read();connection.close()
            connection=HTTPConnection('127.0.0.1',server.server_port)
            connection.request('POST',f'/api/application/{self.key}/assess',body='{}',
                               headers={'X-JobLazy-Token':'fixture-token','Origin':'https://untrusted.example'})
            response=connection.getresponse();self.assertEqual(response.status,403);response.read();connection.close()
        finally:server.shutdown();server.server_close();thread.join()
