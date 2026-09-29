import tempfile,unittest
from contextlib import closing,nullcontext
from pathlib import Path
from unittest.mock import patch
from joblazy.common import write_json
from joblazy.materials import rank
from joblazy.store import Store
from joblazy.worker import Worker
from joblazy.review import render_review
from .support import example_profile,job,FixtureModel


class RefreshTests(unittest.TestCase):
    def test_worker_refreshes_stale_decisions_once_and_keeps_handoffs_untouched(self):
        for status,change in [('ranked','profile'),('not_selected','profile'),('ranked','version')]:
            with self.subTest(status=status,change=change),tempfile.TemporaryDirectory() as temp:
                data=Path(temp);posting=job('https://example.test/role');profile=example_profile()
                assessment=rank(posting,profile,FixtureModel())
                if status=='not_selected':assessment.update(score=20,fit_category='poor_fit')
                if change=='version':assessment['assessment_version']=2
                else:profile['resume']['summary']+=' Further confirmed fictional context.'
                write_json(data/'profile.json',profile);write_json(data/'boards.json',{'boards':[]})
                with closing(Store(data/'jobs.sqlite')) as store:
                    key=store.ingest(posting);store.transition(key,status,{'ranking':assessment} if status=='ranked' else assessment)
                    other=store.ingest(job('https://example.test/handed-off'));store.transition(other,'manual_review',{'ranking':assessment})
                    protected=store.get(other)
                calls=[]
                class Model(FixtureModel):
                    def generate(self,*args):calls.append(1);return super().generate(*args)
                def worker():return Worker(data,data/'profile.json',data/'boards.json',rank_only=True,
                    scanner=lambda *a:{'discovered':0},browser_factory=lambda:nullcontext(None),model_factory=lambda s:Model())
                with patch('joblazy.discovery.enrich',side_effect=lambda j,*a,**k:j):
                    first=worker().tick();second=worker().tick()
                self.assertEqual([r['id'] for r in first['results']],[key])
                self.assertEqual(first['results'][0]['status'],'ranked');self.assertEqual(second['results'],[])
                self.assertEqual(len(calls),1)
                with closing(Store(data/'jobs.sqlite')) as store:self.assertEqual(store.get(other),protected)

    def test_review_marks_stale_score_and_current_user_pass_does_not_loop(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            data=Path(temp);posting=job('https://example.test/role');profile=example_profile()
            assessment=rank(posting,profile,FixtureModel());key=store.ingest(posting)
            store.transition(key,'ranked',{'ranking':assessment});write_json(data/'applications'/key/'ranking.json',assessment)
            profile['resume']['summary']+=' New confirmed context.'
            render_review(store,data,profile=profile);text=(data/'review.html').read_text(encoding='utf-8')
            self.assertIn('Stale assessment',text);self.assertNotIn('Fit score 85',text)
            from joblazy.status import summary
            report=summary(store,profile=profile)
            self.assertTrue(report['assessment_profile_checked'])
            self.assertIsNone(report['recent_results'][0]['score'])
            self.assertTrue(report['recent_results'][0]['assessment_stale'])
            store.record_choice(key,'pass','No longer interested')
            from joblazy.pipeline import run_queue
            with patch('joblazy.discovery.enrich') as read:
                first=run_queue(store,profile,FixtureModel(),None,data/'applications',rank_only=True)
                second=run_queue(store,profile,FixtureModel(),None,data/'applications',rank_only=True)
            self.assertEqual(first[0]['status'],'not_selected');self.assertEqual(second,[]);read.assert_not_called()
