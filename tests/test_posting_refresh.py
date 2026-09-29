import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import Mock, patch

from joblazy.common import PostingUnavailable
from joblazy.pipeline import ingest_discovery_result, queue_candidates, run_queue
from joblazy.store import Store
from .support import FixtureModel, example_profile, job


class PostingRefreshTests(unittest.TestCase):
    def test_description_persistence_preserves_history_and_detects_changed_source(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            original={**job('https://example.test/description'),'description':''}
            observed={**original,'description':job('unused')['description'],
                'description_source':original['url'],'description_method':'Visible posting text'}
            key=store.ingest(original)
            changed={**original,'title':'Another role'}
            store.ingest(changed)
            with self.assertRaisesRegex(ValueError,'Source posting changed'):
                store.record_description(key,original,observed)
            self.assertEqual(store.get(key)['data'],changed)
            store.ingest(original)
            for history in ('materials_ready','prepared','manual_review','submitting','submitted','submission_unknown'):
                with self.subTest(history=history):
                    with store.db:
                        store.db.execute('DELETE FROM events WHERE job_id=?',(key,))
                        store.db.execute("UPDATE jobs SET status='discovered' WHERE id=?",(key,))
                    store.transition(key,history)
                    with store.db:store.db.execute("UPDATE jobs SET status='processing' WHERE id=?",(key,))
                    before=store.get(key);events=list(store.db.execute('SELECT * FROM events'))
                    self.assertEqual(store.record_description(key,original,observed),original)
                    self.assertEqual(store.get(key),before)
                    self.assertEqual(list(store.db.execute('SELECT * FROM events')),events)

    def test_recovered_description_survives_model_limit_and_restart(self):
        from joblazy.common import DailyModelLimit
        with tempfile.TemporaryDirectory() as temp:
            database=Path(temp)/'jobs.sqlite';output=Path(temp)/'applications'
            original={**job('https://example.test/recovered'),'description':''}
            extracted={**original,'description':job('unused')['description'],
                'description_source':original['url'],'description_method':'JobPosting structured data'}
            with closing(Store(database)) as store:
                key=store.ingest(original)
                model=Mock();model.generate.side_effect=DailyModelLimit('Daily limit')
                with patch('joblazy.discovery.enrich',return_value=extracted):
                    run_queue(store,example_profile(),model,None,output,rank_only=True)
                self.assertEqual(store.get(key)['status'],'retryable')
                self.assertEqual(store.get(key)['data']['description'],extracted['description'])
            with closing(Store(database)) as store:
                def check(posting,*args,**kwargs):
                    self.assertTrue(kwargs['check_only'])
                    self.assertEqual(posting['description'],extracted['description'])
                    return posting
                with patch('joblazy.discovery.enrich',side_effect=check):
                    run_queue(store,example_profile(),FixtureModel(),None,output,rank_only=True)
                self.assertEqual(store.get(key)['status'],'ranked')
                self.assertEqual(queue_candidates(store,rank_only=True,profile=example_profile()),[])
                self.assertFalse(list(output.rglob('*.pdf')))

    def test_refreshed_source_still_requires_public_check_before_ranking(self):
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp)/'jobs.sqlite')) as store:
            old=job('https://example.test/recheck');key=store.ingest(old)
            store.transition(key,'posting_unavailable')
            changed={**old,'description':old['description']+' Updated responsibilities.'}
            ingest_discovery_result({'jobs':[changed],'errors':[]},store)
            model=Mock()
            with patch('joblazy.discovery.enrich',side_effect=PostingUnavailable({
                'queue_status':'posting_unavailable','reason':'Public page still missing'})) as check:
                run_queue(store,example_profile(),model,None,Path(temp)/'applications',rank_only=True)
            check.assert_called_once();model.generate.assert_not_called()
            self.assertEqual(store.get(key)['status'],'posting_unavailable')
            ingest_discovery_result({'jobs':[changed],'errors':[]},store)
            self.assertEqual(queue_candidates(store,rank_only=True),[])
            changed['description']+=' Another substantive revision.'
            ingest_discovery_result({'jobs':[changed],'errors':[]},store)
            with patch('joblazy.discovery.enrich',side_effect=lambda posting,*a,**kw:posting):
                run_queue(store,example_profile(),FixtureModel(),None,Path(temp)/'applications',rank_only=True)
            self.assertEqual(store.get(key)['status'],'ranked')
            self.assertFalse(list(Path(temp).rglob('cv.pdf')))

    def test_changed_unavailable_posting_returns_to_queue_once(self):
        for status in ('posting_unavailable', 'posting_expired', 'posting_closed'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp)/'jobs.sqlite')) as store:
                old=job('https://example.test/refresh');key=store.ingest(old)
                store.transition(key,status,{'reason':'Previous public check failed'})
                changed={**old,'description':old['description']+' Updated responsibilities.'}
                ingest_discovery_result({'jobs':[changed],'errors':[]},store)
                self.assertEqual(store.get(key)['status'],'discovered')
                self.assertEqual(store.get(key)['data']['description'],changed['description'])
                self.assertIn(key,[r['id'] for r in queue_candidates(store,rank_only=True)])
                events=list(store.db.execute('SELECT * FROM events'))
                ingest_discovery_result({'jobs':[changed],'errors':[]},store)
                self.assertEqual(list(store.db.execute('SELECT * FROM events')),events)

    def test_observation_timestamp_and_sparse_feed_do_not_reopen(self):
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp)/'jobs.sqlite')) as store:
            old=job('https://example.test/unchanged');key=store.ingest(old)
            store.transition(key,'posting_unavailable',{'reason':'No longer advertised'})
            for delta in ({'observed_at':'2026-09-14T12:00:00Z'}, {'description':''}, {'postedAt':1789387200000}):
                ingest_discovery_result({'jobs':[{**old,**delta}],'errors':[]},store)
                self.assertEqual(store.get(key)['status'],'posting_unavailable')
                self.assertEqual(store.get(key)['data']['description'],old['description'])
            self.assertEqual(queue_candidates(store,rank_only=True),[])

    def test_previous_artifacts_and_application_history_remain_immutable(self):
        for history in ('materials_ready','prepared','manual_review','submitting','submitted','submission_unknown'):
            with self.subTest(history=history), tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp)/'jobs.sqlite')) as store:
                old=job('https://example.test/protected');key=store.ingest(old)
                store.transition(key,history,{'reason':'Historical application work'})
                # Imported/interrupted history can outlive the current availability state.
                with store.db:
                    store.db.execute("UPDATE jobs SET status='posting_unavailable' WHERE id=?",(key,))
                before=store.get(key);events=list(store.db.execute('SELECT * FROM events'))
                ingest_discovery_result({'jobs':[{**old,'description':'A changed posting'}],'errors':[]},store)
                self.assertEqual(store.get(key),before)
                self.assertEqual(list(store.db.execute('SELECT * FROM events')),events)
