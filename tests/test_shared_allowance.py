from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from joblazy.assist import prepare_assisted
from joblazy.common import DailyJobLimit, DailyModelLimit
from joblazy.limits import account_model
from joblazy.store import Store
from .support import example_profile, job


class SharedAllowanceTests(unittest.TestCase):
    def test_changed_reviewed_cv_cannot_trigger_regeneration_or_upload(self):
        from joblazy.common import NeedsInput
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp)/'jobs.sqlite')) as store:
            key=store.ingest(job('https://example.test/reviewed'))
            with self.assertRaisesRegex(NeedsInput,'reviewed CV changed'):
                prepare_assisted(store,key,example_profile(),None,None,Path(temp),
                                 fixture_origin='http://127.0.0.1:1',reviewed_cv_sha256='old-confirmed-hash')
            self.assertEqual(store.get(key)['status'],'discovered')
            self.assertEqual(store.daily_usage(datetime.now(timezone.utc).date().isoformat())['job_attempts'],0)

    def test_exhausted_attempts_block_assisted_generation_without_changing_target(self):
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp)/'jobs.sqlite')) as store:
            for index in range(25):
                key=store.ingest(job(f'https://example.test/used-{index}'))
                store.transition(key,'processing')
                store.transition(key,'ranked',{'fixture':True})
            key=store.ingest(job('https://example.test/next'))
            before=store.get(key)
            with self.assertRaises(DailyJobLimit):
                prepare_assisted(store,key,example_profile(),None,None,Path(temp),fixture_origin='http://127.0.0.1:1')
            self.assertEqual(store.get(key),before)
            self.assertFalse((Path(temp)/'applications'/key/'cv.pdf').exists())

    def test_attempt_reservation_checks_shared_database_inside_transaction(self):
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp)/'jobs.sqlite')) as first, \
             closing(Store(Path(temp)/'jobs.sqlite')) as second:
            key=first.ingest(job('https://example.test/role'))
            for index in range(25):
                first.transition(key,'processing')
                first.transition(key,'ranked')
            with self.assertRaises(DailyJobLimit):
                second.transition(key,'processing')
            self.assertEqual(second.get(key)['status'],'ranked')

    def test_assisted_model_reserves_requests_and_cannot_raise_global_ceiling(self):
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp)/'jobs.sqlite')) as store:
            day=datetime.now(timezone.utc).date().isoformat()
            model=account_model(temp,store,'gpt-6-luna')
            for _ in range(50): model.before_request()
            with self.assertRaises(DailyModelLimit): model.before_request()
            with self.assertRaises(DailyModelLimit): store.reserve_model_request(day,999)
            self.assertEqual(store.daily_usage(day)['model_requests'],50)
