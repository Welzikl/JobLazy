import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from joblazy.store import Store
from joblazy.status import summary
from .support import job


class StatusTests(unittest.TestCase):
    def test_summary_counts_entire_queue_but_limits_results_without_mutating(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'jobs.sqlite')
            try:
                keys=[store.ingest(job('https://example.test/job/'+str(i))) for i in range(30)]
                store.transition(keys[0],'not_selected',{'score':25,'reason':'Missing required experience'})
                store.transition(keys[1],'materials_ready',{'ranking':{'score':80,'reason':'Relevant evidence'},'artifact':{'private':'omitted'}})
                store.transition(keys[2],'needs_input',{'reason':'Phone required'})
                store.transition(keys[3],'submission_unknown',{'reason':'Outcome needs reconciliation'})
                before=store.list();report=summary(store,3)
                self.assertEqual(report['total'],30)
                self.assertEqual(report['counts']['discovered'],26)
                self.assertEqual(len(report['recent_results']),3)
                self.assertEqual(report['more_results'],1)
                self.assertEqual(report['recent_results'][0]['status'],'submission_unknown')
                self.assertEqual(next(r for r in report['recent_results'] if r['status']=='materials_ready')['score'],80)
                self.assertNotIn('artifact',json.dumps(report))
                self.assertEqual(store.list(),before)
                self.assertEqual(report['usage'],{'job_attempts':0,'model_requests':0})
                # An active transition persists JSON null before any result exists.
                store.transition(keys[4],'processing')
                current=summary(store,1)['recent_results'][0]
                self.assertEqual(current['status'],'processing')
                self.assertIsNone(current['score']);self.assertIsNone(current['reason'])
            finally:store.close()

    def test_cli_default_is_bounded_and_all_preserves_full_listing(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'jobs.sqlite')
            for i in range(25):store.ingest(job('https://example.test/job/'+str(i)))
            store.close()
            def run(*args):
                return subprocess.run([sys.executable,'-m','joblazy','--data',temp,'status',*args],capture_output=True,text=True,timeout=10)
            result=run();self.assertEqual(result.returncode,0)
            report=json.loads(result.stdout);self.assertEqual(report['total'],25)
            self.assertEqual(report['recent_results'],[])
            result=run('--all');self.assertEqual(result.returncode,0)
            self.assertEqual(len(json.loads(result.stdout)),25)
            self.assertNotEqual(run('--limit','0').returncode,0)
