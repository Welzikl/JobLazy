import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from joblazy.common import digest
from joblazy.materials import rank
from joblazy.pipeline import run_queue,queue_candidates
from joblazy.store import Store
from joblazy.assessment_state import assessment_stale
from .support import FixtureModel,example_profile,job


class RemoteRankingTests(unittest.TestCase):
    def test_remote_contract_refreshes_only_affected_unprepared_decisions(self):
        profile=example_profile();profile_hash=digest(profile)
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            keys={}
            for label in ('United Kingdom (Remote), Remote','Remote','Remote, United States','London, United Kingdom'):
                posting={**job('https://example.test/'+str(len(keys))),'location':label}
                assessment=rank(posting,profile,FixtureModel())
                if label!='London, United Kingdom':
                    self.assertEqual(assessment.get('remote_scope_version'),1)
                assessment.pop('remote_scope_version',None)
                key=store.ingest(posting);store.transition(key,'not_selected',assessment);keys[label]=key
            candidates=queue_candidates(store,rank_only=True,profile=profile)
            self.assertEqual({r['id'] for r in candidates},set(keys.values())-{keys['London, United Kingdom']})
            protected=keys['Remote'];store.transition(protected,'manual_review')
            self.assertFalse(assessment_stale(store.get(protected),profile_hash))
            with patch('joblazy.discovery.enrich',side_effect=lambda posting,*a,**kw:posting):
                run_queue(store,profile,FixtureModel(),None,Path(temp)/'applications',only=keys['United Kingdom (Remote), Remote'],rank_only=True)
            self.assertFalse(assessment_stale(store.get(keys['United Kingdom (Remote), Remote']),profile_hash))
            self.assertFalse(list(Path(temp).rglob('*.pdf')))

    def test_remote_context_does_not_change_the_nonremote_request(self):
        calls=[]
        class Model(FixtureModel):
            def generate(self,task,data,schema):
                calls.append((task,data,schema));return super().generate(task,data,schema)
        profile=example_profile()
        normal=job('https://example.test/london');remote={**normal,'location':'United Kingdom (Remote)'}
        rank(normal,profile,Model());rank(remote,profile,Model());rank(normal,profile,Model())
        self.assertEqual(calls[0],calls[2])
        self.assertNotEqual(calls[0][0],calls[1][0])
        self.assertEqual(calls[0][2],calls[1][2])
        self.assertNotIn('remote_scope_version',rank(normal,profile,FixtureModel()))
