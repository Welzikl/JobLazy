import copy
import html
import json
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from joblazy.common import write_json
from joblazy.model import CodexModel
from joblazy.materials import rank,source_facts
from joblazy.pipeline import plain_text,run_queue
from joblazy.store import Store
from .support import example_profile,FixtureModel,job


class RankOnlyTests(unittest.TestCase):
    def test_sector_exclusion_cites_policy_without_polluting_cv_claim_sources(self):
        profile=example_profile();profile['targeting']={'career_preferences':'Exclude workforce training technology.'}
        posting=job('https://example.test/excluded');posting['description']+=' Enterprise skill development.'
        class PolicyModel(FixtureModel):
            def generate(self,task,data,schema):
                result=super().generate(task,data,schema)
                result.update(score=10,fit_category='poor_fit')
                result['requirements'].append({'requirement':'Saved sector exclusion','job_quote':'Enterprise skill development.',
                    'kind':'hard_constraint','status':'not_met','candidate_source_ids':['preference.career_rules'],
                    'explanation':'This fictional employer matches the saved workforce-training exclusion.'})
                return result
        result=rank(posting,profile,PolicyModel())
        self.assertEqual(result['eligibility_status'],'blocked')
        self.assertEqual(result['candidate_facts']['preference.career_rules'],profile['targeting']['career_preferences'])
        self.assertNotIn('preference.career_rules',source_facts(profile))

    def test_entity_escaped_description_retains_readable_requirements(self):
        text='<div><h2>Requirements</h2><p>SQL &amp; reporting</p><ul><li>Manage 5 &lt; 10 accounts</li></ul></div>'
        expected='Requirements\nSQL & reporting\nManage 5 < 10 accounts'
        for value in (text,html.escape(text)):
            self.assertEqual(plain_text(value),expected)
        self.assertEqual(plain_text('Rates < 5% and revenue > 10,000. R&D.'),'Rates < 5% and revenue > 10,000. R&D.')

    def test_ranking_then_tailoring_reuses_cache_and_changed_profile_is_reassessed(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            data=Path(temp);profile=example_profile();posting=job('https://example.test/role')
            posting['description']=html.escape('<p>'+posting['description']+'</p>')
            key=store.ingest(posting);requests=[]
            model=CodexModel(data/'cache',executable='fictional-codex')
            def fake(args,**kwargs):
                if args[1]=='login':return subprocess.CompletedProcess(args,0,'Logged in','')
                prompt=kwargs['input'];task=prompt.split('TASK: ',1)[1].split('\nINPUT JSON:',1)[0]
                payload=json.loads(prompt.split('\nINPUT JSON:\n',1)[1]);requests.append((task,payload))
                schema=json.loads(Path(args[args.index('--output-schema')+1]).read_text(encoding='utf-8'))
                answer=FixtureModel().generate(task,payload,schema)
                write_json(args[args.index('--output-last-message')+1],answer)
                return subprocess.CompletedProcess(args,0,'','')
            with patch('joblazy.discovery.enrich',side_effect=lambda job,*args,**kwargs:job),patch('joblazy.model.subprocess.run',side_effect=fake),patch('joblazy.pipeline.render',return_value={'pdf':'fixture.pdf'}) as render,patch('joblazy.pipeline.save_materials'):
                first=run_queue(store,profile,model,None,data/'applications',rank_only=True)
                self.assertEqual(first[0]['status'],'ranked');render.assert_not_called()
                self.assertEqual(store.get(key)['data'],posting)
                self.assertNotIn('<p>',requests[0][1]['job']['description'])
                self.assertEqual(run_queue(store,profile,model,None,data/'applications',rank_only=True),[])
                self.assertEqual(run_queue(store,profile,model,None,data/'applications')[0]['status'],'materials_ready')
                self.assertEqual(sum('Rank this' in task for task,_ in requests),1)
                render.assert_called_once()
                # A stale saved rank is never blindly trusted after profile edits.
                store.transition(key,'ranked',{'ranking':{'score':100}})
                changed=copy.deepcopy(profile);changed['resume']['summary']+=' Additional confirmed context.'
                self.assertEqual(run_queue(store,changed,model,None,data/'applications')[0]['status'],'materials_ready')
                self.assertEqual(sum('Rank this' in task for task,_ in requests),2)
            store.transition(key,'ranked');store.ingest({**posting,'description':'Changed role requirements'})
            self.assertEqual(store.get(key)['status'],'discovered')

    def test_rank_only_rejects_preparation_before_recovery_and_preserves_manual_review(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            key=store.ingest(job('https://example.test/handed-off'));store.transition(key,'manual_review')
            before=store.list()
            with self.assertRaises(ValueError):run_queue(store,example_profile(),None,None,temp,rank_only=True,prepare=True)
            self.assertEqual(run_queue(store,example_profile(),None,None,temp,rank_only=True),[])
            self.assertEqual(store.list(),before)
