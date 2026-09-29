import tempfile
import unittest
from pathlib import Path
from joblazy.assist import ManualPreparation
from joblazy.browser import apply
from joblazy.common import NeedsInput
from joblazy.discovery_intake import ingest_jobs
from joblazy.pipeline import run_queue
from joblazy.store import Store
from .support import example_profile,job


URL='https://jobs.ashbyhq.com/example/01234567-89ab-cdef-0123-456789abcdef'


class NoExternalWork:
    def __getattr__(self,name):raise AssertionError('No model or browser work should occur: '+name)


class PriorApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.store=Store(self.root/'jobs.sqlite');self.addCleanup(self.store.close)

    def history(self,status='submitted'):
        key=self.store.ingest({**job(URL),'historical_application':True})
        self.store.transition(key,status,{'method':'imported_history','source':'fictional tracker'})
        return key

    def test_future_discovery_joins_imported_history_without_reopening_it(self):
        key=self.history();before=self.store.get(key)
        result=ingest_jobs(self.store,[job(URL+'/application')])
        self.assertEqual(result['ids'],[key]);self.assertEqual(self.store.get(key),before)
        self.assertEqual(len(self.store.list()),1)

    def test_known_broker_route_stops_before_ranking_and_keeps_historical_outcome(self):
        prior=self.history();before=self.store.get(prior)
        key=self.store.ingest({**job('https://example.test/broker'),'application_url':URL+'/application'})
        result=run_queue(self.store,example_profile(),NoExternalWork(),NoExternalWork(),self.root/'applications',only=key)
        self.assertEqual(result,[{'id':key,'status':'needs_input'}])
        self.assertEqual(self.store.get(key)['result']['prior_job_id'],prior)
        self.assertEqual(self.store.get(prior),before)
        self.assertFalse((self.root/'applications').exists())

    def test_newly_resolved_route_stops_before_filling_in_both_preparation_modes(self):
        prior=self.history('submission_unknown');before=self.store.get(prior)
        key=self.store.ingest(job('https://example.test/unresolved-broker'))
        resolved={**self.store.get(key)['data'],'application_url':URL+'/application'}
        for store in (self.store,ManualPreparation(self.store)):
            with self.assertRaisesRegex(NeedsInput,'already has application history'):
                apply(NoExternalWork(),resolved,example_profile(),{},store,key,self.root/'application')
        self.assertEqual(self.store.get(prior),before)
        self.assertFalse((self.root/'application').exists())

    def test_exact_route_match_does_not_block_another_requisition_or_its_own_resume(self):
        key=self.history('manual_review')
        self.assertIsNone(self.store.prior_application(job(URL),exclude_id=key))
        different=job(URL.replace('456789abcdef','456789abcdee'))
        self.assertIsNone(self.store.prior_application(different))
        self.assertEqual(self.store.prior_application(job(URL+'/application'))['id'],key)
