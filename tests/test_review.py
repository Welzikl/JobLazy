import copy
import tempfile
import unittest
from pathlib import Path
from joblazy.common import digest,write_json
from joblazy.review import render_review
from joblazy.store import Store
from .support import job,example_profile


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name);self.store=Store(self.data/'jobs.sqlite');self.addCleanup(self.store.close)

    def material(self):
        from joblazy.checkpoints import save_materials
        posting=job('https://example.test/saved');profile=example_profile();key=self.store.ingest(posting)
        directory=self.data/'applications'/key;directory.mkdir(parents=True)
        for name in ('cv.pdf','cv.html','cv.json'):(directory/name).write_bytes(b'Fictional saved document')
        ranking={'score':80,'reason':'Fictional fit','missing_facts':[]}
        write_json(directory/'ranking.json',ranking)
        write_json(directory/'material.json',{'job_hash':digest(posting),'review':{'supported':True,'issues':[]},
            'claims':[{'text':profile['resume']['summary'],'source_ids':['summary']}]})
        artifact={'path':str(directory/'cv.pdf'),'pages':1,'sha256':digest((directory/'cv.pdf').read_bytes())}
        write_json(directory/'artifact.json',artifact)
        save_materials(directory,posting,posting,profile,ranking,artifact)
        self.store.transition(key,'manual_review',{'ranking':ranking})
        return key,directory,profile

    def test_stale_cv_remains_available_for_history_without_appearing_current(self):
        key,directory,profile=self.material()
        changed=copy.deepcopy(profile);changed['resume']['summary']+=' Another confirmed fact.'
        before=self.store.get(key);files={p.name:p.read_bytes() for p in directory.iterdir()}
        html=Path(render_review(self.store,self.data,profile=changed)['path']).read_text(encoding='utf-8')
        self.assertIn('>Saved CV (review required)</a>',html)
        self.assertIn('not verified for the current profile and posting',html)
        self.assertIn((directory/'cv.pdf').as_uri(),html)
        self.assertNotIn('>Tailored CV</a>',html)
        self.assertEqual(self.store.get(key),before)
        self.assertEqual({p.name:p.read_bytes() for p in directory.iterdir()},files)

    def test_current_checkpoint_and_discovery_edit_keep_current_cv_label(self):
        key,directory,profile=self.material()
        profile['discovery_preferences']={'max_posting_age_days':30}
        html=Path(render_review(self.store,self.data,profile=profile)['path']).read_text(encoding='utf-8')
        self.assertIn('>Tailored CV</a>',html)
        self.assertNotIn('Saved CV (review required)',html)
        # A changed checkpoint component must not be hidden by unchanged PDF bytes.
        (directory/'cv.html').write_text('Changed document component',encoding='utf-8')
        html=Path(render_review(self.store,self.data,profile=profile)['path']).read_text(encoding='utf-8')
        self.assertIn('>Saved CV (review required)</a>',html)

    def test_review_without_profile_does_not_claim_current_material_validation(self):
        key,directory,profile=self.material()
        html=Path(render_review(self.store,self.data)['path']).read_text(encoding='utf-8')
        self.assertIn('>Saved CV (profile not checked)</a>',html)
        self.assertIn('No candidate profile was supplied',html)
        self.assertNotIn('>Tailored CV</a>',html)

    def test_ranked_role_retains_failed_inspection_reason_without_changing_fit_or_state(self):
        posting=job('https://example.test/job');key=self.store.ingest(posting)
        self.store.transition(key,'ranked',{'ranking':{'score':72,'reason':'Worthwhile stretch','missing_facts':[]}})
        before=self.store.get(key);directory=self.data/'applications'/key
        write_json(directory/'form-inventory.json',{'version':1,'source_job_hash':digest(posting),
            'method':'read_only_inventory','state':'needs_input','reason':'Application destination is unavailable (HTTP 403)',
            'fields':[],'unresolved':[]})
        html=Path(render_review(self.store,self.data)['path']).read_text(encoding='utf-8')
        self.assertIn('Application destination is unavailable (HTTP 403)',html)
        self.assertIn('Worthwhile stretch',html)
        self.assertEqual(self.store.get(key),before)

    def test_lower_interest_titles_do_not_jump_ahead_of_target_roles_on_score_alone(self):
        from joblazy.assessment_state import FULL_ASSESSMENT_VERSION,assessment_profile_hash
        profile=example_profile()
        profile['discovery_preferences']={'title_filter':{'deprioritized':['BDR']}}
        target=self.store.ingest(job('https://example.test/target','Strategy & Operations Associate'))
        fallback=self.store.ingest(job('https://example.test/fallback','BDR (Business Development Representative)'))
        current={'assessment_version':FULL_ASSESSMENT_VERSION,'assessment_profile_hash':assessment_profile_hash(profile)}
        self.store.transition(target,'ranked',{'ranking':{**current,'score':71,'reason':'Target track','missing_facts':[]}})
        self.store.transition(fallback,'ranked',{'ranking':{**current,'score':95,'reason':'Lower-interest fallback','missing_facts':[]}})
        html=Path(render_review(self.store,self.data,profile=profile)['path']).read_text(encoding='utf-8')
        self.assertLess(html.index('Strategy &amp; Operations Associate'),html.index('BDR (Business Development Representative)'))

    def test_source_text_is_escaped_and_changed_cv_is_not_linked(self):
        posting=job('javascript:alert(1)',title='<script>alert(1)</script>')
        key=self.store.ingest(posting);directory=self.data/'applications'/key
        directory.mkdir(parents=True);pdf=directory/'cv.pdf';pdf.write_bytes(b'fictional PDF fixture')
        write_json(directory/'artifact.json',{'path':str(pdf),'sha256':digest(pdf.read_bytes())})
        self.store.transition(key,'materials_ready',{'ranking':{'score':80,'reason':'Strong <fit>','missing_facts':[]}})
        output=Path(render_review(self.store,self.data)['path']);html=output.read_text(encoding='utf-8')
        self.assertNotIn('<script>',html);self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('href="javascript:',html);self.assertIn('Saved CV (profile not checked)',html)
        pdf.write_bytes(b'changed after rendering')
        render_review(self.store,self.data)
        html=output.read_text(encoding='utf-8')
        self.assertNotIn('Tailored CV</a>',html);self.assertIn('could not be verified',html)

    def test_questions_and_drafts_are_reviewable_without_application_actions(self):
        key=self.store.ingest(job('https://example.test/job'));directory=self.data/'applications'/key
        self.store.transition(key,'needs_input',{'reason':'Missing saved answer'})
        write_json(directory/'browser.json',{'unresolved':[{'field':'Start date','reason':'No saved answer','required':True}]})
        write_json(directory/'answer-drafts.json',{'drafts':{'q':{'question':{'label':'Why this role?'},'text':'Grounded answer.'}}})
        output=Path(render_review(self.store,self.data)['path']);html=output.read_text(encoding='utf-8')
        for text in ('Start date','No saved answer','Why this role?','Grounded answer.',key):self.assertIn(text,html)
        self.assertNotIn('<form',html);self.assertNotIn('<script',html);self.assertNotIn('<button',html)
