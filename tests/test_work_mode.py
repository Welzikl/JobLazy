import tempfile
import unittest
from pathlib import Path
from contextlib import closing,nullcontext
from unittest.mock import patch
from joblazy.common import write_json,read_json
from joblazy.store import Store
from joblazy.pipeline import run_queue
from joblazy.worker import Worker
from joblazy.assist import run_assisted,prepare_assisted
from joblazy.browser import apply
from joblazy.work_mode import PreparationPaused,require_application_work
from .support import example_profile,FixtureModel,job

class WorkModeTests(unittest.TestCase):
    def test_pause_blocks_application_entries_before_browser_or_queue_actions(self):
        with tempfile.TemporaryDirectory() as tmp,closing(Store(Path(tmp)/'jobs.sqlite')) as store:
            base=Path(tmp);write_json(base/'preparation-policy.json',{'paused':True})
            profile=example_profile();write_json(base/'profile.json',profile)
            key=store.ingest(job('https://example.test/one'));before=store.get(key)
            calls=[lambda:run_queue(store,profile,None,None,base/'applications'),
                lambda:prepare_assisted(store,key,profile,None,None,base),
                lambda:run_assisted(base,key,base/'profile.json'),
                lambda:apply(None,before['data'],profile,None,store,key,base/'applications'/key,allow_live=True)]
            for call in calls:
                with self.assertRaises(PreparationPaused):call()
                self.assertEqual(store.get(key),before)

    def test_paused_worker_can_rank_and_restart_without_cv_or_repeat_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);write_json(base/'preparation-policy.json',{'paused':True})
            write_json(base/'profile.json',example_profile());write_json(base/'boards.json',{'boards':[]})
            calls=[]
            class RankOnly(FixtureModel):
                def generate(self,task,*args):
                    self_task=task.startswith('Rank this')
                    if not self_task:raise AssertionError('Rank-only mode attempted non-ranking inference')
                    calls.append(task);return super().generate(task,*args)
            def scan(boards,store,checkpoint):
                store.ingest(job('https://example.test/one'));return {'discovered':1,'errors':[]}
            options=dict(scanner=scan,browser_factory=lambda:nullcontext(None),model_factory=lambda s:RankOnly())
            with patch('joblazy.discovery.enrich',side_effect=lambda job,*a,**k:job),patch('joblazy.pipeline.tailor') as tailor,patch('joblazy.pipeline.apply') as fill:
                paused=Worker(base,base/'profile.json',base/'boards.json',**options)
                self.assertEqual(paused.tick()['state'],'preparation_paused');self.assertEqual(calls,[])
                worker=Worker(base,base/'profile.json',base/'boards.json',rank_only=True,**options)
                first=worker.tick();self.assertEqual(first['results'][0]['status'],'ranked')
                restarted=Worker(base,base/'profile.json',base/'boards.json',rank_only=True,**options)
                self.assertEqual(restarted.tick()['state'],'idle')
                self.assertEqual(len(calls),1);tailor.assert_not_called();fill.assert_not_called()
                self.assertFalse(list(base.rglob('cv.pdf')))

    def test_pause_arriving_during_ranking_preserves_resumable_queue(self):
        with tempfile.TemporaryDirectory() as tmp,closing(Store(Path(tmp)/'jobs.sqlite')) as store:
            base=Path(tmp);key=store.ingest(job('https://example.test/one'));before=store.get(key)
            class PauseDuringRank(FixtureModel):
                def generate(self,*args):
                    write_json(base/'preparation-policy.json',{'paused':True});return super().generate(*args)
            with patch('joblazy.discovery.enrich',side_effect=lambda job,*a,**k:job),patch('joblazy.pipeline.tailor') as tailor:
                result=run_queue(store,example_profile(),PauseDuringRank(),None,base/'applications')
                self.assertTrue(result[0]['preparation_paused']);tailor.assert_not_called()
                self.assertEqual(store.get(key)['status'],before['status'])
                self.assertEqual(store.get(key)['result'],before['result'])

    def test_conflicting_worker_modes_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):Worker(tmp,'profile.json','boards.json',prepare=True,rank_only=True)

    def test_profile_pause_applies_to_custom_data_and_invalid_policy_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);profile=base/'local'/'profile.json';data=base/'alternate-runtime'
            policy=profile.parent/'preparation-policy.json'
            for value in ({'paused':True},{'paused':'false'},[]):
                write_json(policy,value)
                with self.assertRaises(PreparationPaused):require_application_work(data,profile)
            write_json(policy,{'paused':False});require_application_work(data,profile)
            policy.write_text('{broken',encoding='utf-8')
            with self.assertRaises(PreparationPaused):require_application_work(data,profile)

    def test_worker_reconsiders_user_selected_below_cutoff_role(self):
        class LowScore(FixtureModel):
            def generate(self,*args):
                result=super().generate(*args);result.update(score=65,fit_category='worthwhile_stretch');return result
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);profile=example_profile()
            write_json(base/'profile.json',profile);write_json(base/'boards.json',{'boards':[]})
            write_json(base/'preparation-policy.json',{'paused':True})
            with patch('joblazy.discovery.enrich',side_effect=lambda job,*a,**k:job):
                with closing(Store(base/'jobs.sqlite')) as store:
                    key=store.ingest(job('https://example.test/one'))
                    initial=run_queue(store,profile,LowScore(),None,base/'applications',rank_only=True)
                    self.assertEqual(initial[0]['status'],'not_selected')
                    store.record_choice(key,'pursue','I want this role')
                worker=Worker(base,base/'profile.json',base/'boards.json',rank_only=True,
                    scanner=lambda *a:{},browser_factory=lambda:nullcontext(None),model_factory=lambda s:LowScore())
                self.assertEqual(worker.tick()['results'][0]['status'],'ranked')
                self.assertEqual(worker.tick()['state'],'idle')

    def test_worker_spends_first_slot_on_preferred_role_and_keeps_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);profile=example_profile()
            profile['discovery_preferences']={'title_filter':{'positive':['BDR','Business Operations'],'deprioritized':['BDR']}}
            write_json(base/'profile.json',profile);write_json(base/'boards.json',{'boards':[]})
            with closing(Store(base/'jobs.sqlite')) as store:
                fallback=store.ingest(job('https://example.test/bdr','BDR'))
                preferred=store.ingest(job('https://example.test/ops','Business Operations'))
            with patch('joblazy.discovery.enrich',side_effect=lambda job,*a,**k:job):
                worker=Worker(base,base/'profile.json',base/'boards.json',rank_only=True,batch_size=1,
                    scanner=lambda *a:{},browser_factory=lambda:nullcontext(None),model_factory=lambda s:FixtureModel())
                self.assertEqual(worker.tick()['results'][0]['id'],preferred)
                self.assertEqual(worker.tick()['results'][0]['id'],fallback)
