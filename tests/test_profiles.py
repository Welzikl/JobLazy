import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from joblazy.common import write_json
from joblazy.profiles import check_profile,InvalidProfile
from joblazy.pipeline import run_queue
from joblazy.assist import prepare_assisted
from joblazy.browser import apply
from joblazy.store import Store
from joblazy.worker import Worker,utc_day
from .support import example_profile,job


class ProfileTests(unittest.TestCase):
    def test_contact_conflicts_stop_before_queue_model_or_browser_actions(self):
        class Forbidden:
            def __getattr__(self,name):raise AssertionError('Invalid profile reached '+name)
        for field,cv_field in [('full_name','name'),('email','email'),('phone','phone')]:
            with self.subTest(field=field),tempfile.TemporaryDirectory() as temp:
                profile=example_profile();profile['resume']['candidate'][cv_field]='Different supplied value'
                before=copy.deepcopy(profile);store=Store(Path(temp)/'jobs.sqlite');key=store.ingest(job('https://example.test/job'))
                try:
                    with self.assertRaises(InvalidProfile):run_queue(store,profile,Forbidden(),Forbidden(),temp)
                    with self.assertRaises(InvalidProfile):prepare_assisted(store,key,profile,Forbidden(),Forbidden(),temp)
                    with self.assertRaises(InvalidProfile):apply(Forbidden(),job('https://example.test'),profile,{},store,key,temp)
                    self.assertEqual(store.get(key)['status'],'discovered')
                    self.assertEqual(store.daily_usage(utc_day()),{'job_attempts':0,'model_requests':0})
                    self.assertEqual(profile,before)
                finally:store.close()

    def test_missing_name_parts_and_phone_are_warnings_without_inference(self):
        profile=example_profile();identity=profile['applicant']['identity']
        for key in ('first_name','last_name','phone'):identity.pop(key)
        profile['resume']['candidate']['phone']=''
        before=copy.deepcopy(profile);report=check_profile(profile)
        self.assertTrue(report['valid'])
        self.assertTrue({'applicant.identity.'+key for key in ('first_name','last_name','phone')}.issubset({x['path'] for x in report['warnings']}))
        self.assertEqual(profile,before)
        profile['applicant']['identity']['phone']='+44 (20) 7946 0000';profile['resume']['candidate']['phone']='+442079460000'
        self.assertTrue(check_profile(profile)['valid'])

    def test_structure_errors_do_not_echo_supplied_values(self):
        profile=example_profile();profile['applicant']['identity']['phone']={'private':'not a string'}
        report=check_profile(profile)
        self.assertFalse(report['valid']);self.assertNotIn('not a string',json.dumps(report))
        for value in (None,[],{}, {'resume':[]}):self.assertFalse(check_profile(value)['valid'])

    def test_worker_resumes_after_profile_correction_without_provider_penalty(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);profile=root/'profile.json';boards=root/'boards.json'
            profile.write_text('{unfinished',encoding='utf-8');write_json(boards,{'boards':[]})
            scans=[];reports=[]
            def scan(*args):scans.append(1);return {'discovered':0,'errors':[]}
            worker=Worker(root,profile,boards,interval=.01,scanner=scan)
            def emit(report):
                reports.append(report)
                if report['state']=='profile_input':write_json(profile,example_profile())
            worker.run(max_cycles=2,emit=emit)
            self.assertEqual([r['state'] for r in reports],['profile_input','idle'])
            self.assertEqual(len(scans),1);self.assertNotIn('next_run',worker.state)

    def test_doctor_reports_profile_errors_with_nonzero_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            profile=Path(temp)/'profile.json';data=example_profile();data['resume']['candidate']['email']='different@example.test';write_json(profile,data)
            result=subprocess.run([sys.executable,'-m','joblazy','--data',temp,'doctor','--profile',str(profile)],capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,1)
            report=json.loads(result.stdout)['profile'];self.assertFalse(report['valid'])
            self.assertNotIn('different@example.test',result.stdout)
