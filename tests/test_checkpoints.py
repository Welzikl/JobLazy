import copy
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from playwright.sync_api import sync_playwright
from joblazy.checkpoints import load_materials,save_materials
from joblazy.common import digest,write_json
from joblazy.pipeline import run_queue
from joblazy.store import Store
from .support import example_profile,job,FixtureModel,fixture_server


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.directory=Path(temp.name);self.profile=example_profile();self.job=job('https://example.test/role')
        write_json(self.directory/'material.json',{'job_hash':digest(self.job),'review':{'supported':True,'issues':[]},
            'claims':[{'text':self.profile['resume']['summary'],'source_ids':['summary']}]})
        write_json(self.directory/'ranking.json',{})
        for name in ('cv.json','cv.html','cv.pdf'):(self.directory/name).write_bytes(b'fictional checkpoint bytes')
        artifact={'path':str(self.directory/'cv.pdf'),'pages':1,'sha256':digest((self.directory/'cv.pdf').read_bytes())}
        self.checkpoint=save_materials(self.directory,self.job,self.job,self.profile,{},artifact)

    def load(self,profile):return load_materials(self.directory,self.job,profile)

    def test_saved_reviewer_approval_cannot_bypass_current_claim_checks(self):
        material={'job_hash':digest(self.job),'review':{'supported':True,'issues':[]},
            'claims':[{'text':'Reduced onboarding handoff delays by 15% by creating a shared checklist.',
                       'source_ids':['experience.0.2']}]}
        write_json(self.directory/'material.json',material)
        save_materials(self.directory,self.job,self.job,self.profile,{},self.checkpoint['artifact'])
        self.assertIsNone(self.load(self.profile))
        material['claims']=[]
        write_json(self.directory/'material.json',material)
        save_materials(self.directory,self.job,self.job,self.profile,{},self.checkpoint['artifact'])
        self.assertIsNone(self.load(self.profile))

    def test_discovery_only_changes_preserve_new_checkpoint_without_rewriting_it(self):
        before=(self.directory/'materials-checkpoint.json').read_bytes()
        changed=copy.deepcopy(self.profile)
        changed['discovery_preferences']={'max_posting_age_days':30,
            'title_filter':{'positive':['Operations'],'deprioritized':['SDR']}}
        self.assertIsNotNone(self.load(changed))
        self.assertEqual((self.directory/'materials-checkpoint.json').read_bytes(),before)

    def test_version_two_keeps_original_discovery_binding(self):
        from joblazy.materials import source_facts
        # Reconstruct the historical v2 input independently of today's helper.
        inputs=copy.deepcopy({k:v for k,v in self.profile.items() if k!='answers'})
        applicant=inputs.get('applicant',{})
        for group,keys in (('identity',('full_name','first_name','last_name','email','phone')),
                           ('links',('github','portfolio','website'))):
            if isinstance(applicant.get(group),dict):
                for key in keys:applicant[group].pop(key,None)
                if not applicant[group]:applicant.pop(group)
        inputs['candidate_facts']=source_facts(self.profile)
        old=copy.deepcopy(self.checkpoint);old['version']=2;old['profile_document_hash']=digest(inputs)
        write_json(self.directory/'materials-checkpoint.json',old)
        before=(self.directory/'materials-checkpoint.json').read_bytes()
        self.assertIsNotNone(self.load(self.profile))
        changed=copy.deepcopy(self.profile);changed['discovery_preferences']={'max_posting_age_days':30}
        self.assertIsNone(self.load(changed))
        self.assertEqual((self.directory/'materials-checkpoint.json').read_bytes(),before)

    def test_form_only_links_and_name_parts_reuse_while_identity_conflicts_fail(self):
        changed=copy.deepcopy(self.profile)
        changed['applicant']['links']['github']='https://github.com/fictional'
        changed['applicant']['identity']['first_name']='Alexandra'
        self.assertIsNotNone(self.load(changed))
        changed['applicant']['identity']['email']='someone-else@example.test'
        self.assertIsNone(self.load(changed))

    def test_material_facts_printed_contacts_location_and_unknown_inputs_remain_bound(self):
        changes=[lambda p:p['resume']['candidate'].update(phone='+441234567890'),
            lambda p:p['resume']['experience'][0]['bullets'].append('A new confirmed career fact.'),
            lambda p:p['targeting'].update(new_exclusion='Example sector'),
            lambda p:p['applicant']['address'].update(country='Canada'),
            lambda p:p['applicant'].update(new_constraint='Needs specialist authorization'),
            lambda p:p['applicant']['links'].update(new_material_link='https://example.test/evidence')]
        for change in changes:
            p=copy.deepcopy(self.profile);change(p)
            self.assertIsNone(self.load(p))
        (self.directory/'cv.pdf').write_bytes(b'changed bytes')
        self.assertIsNone(self.load(self.profile))

    def test_legacy_checkpoint_keeps_full_profile_binding_without_silent_upgrade(self):
        old=copy.deepcopy(self.checkpoint);old['version']=1;old.pop('profile_document_hash')
        write_json(self.directory/'materials-checkpoint.json',old)
        original=(self.directory/'materials-checkpoint.json').read_bytes()
        self.assertIsNotNone(self.load(self.profile))
        changed=copy.deepcopy(self.profile);changed['applicant']['links']['github']='https://github.com/fictional'
        self.assertIsNone(self.load(changed))
        self.assertEqual((self.directory/'materials-checkpoint.json').read_bytes(),original)

    def test_connected_preparation_reuses_pdf_after_form_link_update_without_model(self):
        with fixture_server() as (origin,received),sync_playwright() as pw,closing(Store(self.directory/'jobs.sqlite')) as store:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            try:
                key=store.ingest(job(origin+'/success'));directory=self.directory/'applications'/key
                run_queue(store,self.profile,FixtureModel(),browser,directory.parent,1,fixture_origin=origin)
                original=(directory/'cv.pdf').read_bytes()
                changed=copy.deepcopy(self.profile);changed['applicant']['links']['github']='https://github.com/fictional'
                changed['discovery_preferences']={'max_posting_age_days':30,'title_filter':{'positive':['Operations']}}
                class NoModel:
                    def generate(self,*args):raise AssertionError('Form-only update must not regenerate ranking or CV')
                result=run_queue(store,changed,NoModel(),browser,directory.parent,1,prepare=True,fixture_origin=origin)
                self.assertEqual(result[0]['status'],'prepared');self.assertTrue(result[0]['reused_materials'])
                self.assertEqual((directory/'cv.pdf').read_bytes(),original);self.assertEqual(received,[])
            finally:browser.close()
