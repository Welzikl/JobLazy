import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from joblazy.materials import original_quote,rank,AssessmentFailed
from joblazy.pipeline import run_queue
from joblazy.review import render_review
from joblazy.store import Store
from .support import FixtureModel,example_profile,job


class QuoteRecoveryTests(unittest.TestCase):
    def test_symbol_spacing_recovers_the_literal_source_without_merging_words_or_numbers(self):
        source='UK Remote | 💰£62,000 - £73,000 + Benefits'
        self.assertEqual(original_quote('💰 £62,000 - £73,000 + Benefits',source),'💰£62,000 - £73,000 + Benefits')
        self.assertEqual(original_quote('£ 62,000','£62,000'),'£62,000')
        for quote,text in [('£62,000','£63,000'),('$62,000','£62,000'),('£6 2,000','£62,000'),
                           ('partner ship','partnership'),('five years','six years'),('SQL and Python','SQL or Python')]:
            with self.subTest(quote=quote):self.assertIsNone(original_quote(quote,text))

    def test_valid_location_evidence_keeps_its_source_and_does_not_rerank(self):
        calls=[];posting={**job('https://example.test/location'),'location':'United Kingdom (Remote)'}
        class Model(FixtureModel):
            def generate(self,task,data,schema):
                calls.append(task);result=super().generate(task,data,schema)
                result['evidence'].insert(0,{'quote':posting['location'],'explanation':'Advertised work location.'})
                return result
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            key=store.ingest(posting)
            with patch('joblazy.discovery.enrich',side_effect=lambda j,*a,**kw:j):
                run_queue(store,example_profile(),Model(),None,Path(temp)/'applications',rank_only=True)
            result=store.get(key)['result']['ranking']
            self.assertEqual(len(calls),1);self.assertEqual(result['score'],85)
            self.assertEqual(result['validation']['correction_attempts'],0)
            self.assertEqual(result['evidence'][0]['quote_source'],'location')
            self.assertEqual(result['evidence'][0]['quote'],posting['location'])
            rendered=Path(render_review(store,Path(temp))['path']).read_text(encoding='utf-8')
            self.assertIn('Source: posting location',rendered)
            self.assertFalse(list(Path(temp).rglob('cv.pdf')))

    def test_summary_evidence_still_rejects_title_only_and_invented_or_candidate_quotes(self):
        for quote in ('Unique title text','Invented qualification','Operations specialist experienced in partner onboarding.'):
            calls=[]
            class Model(FixtureModel):
                def generate(self,task,data,schema):
                    calls.append(task);result=super().generate(task,data,schema)
                    result['evidence']=[{'quote':quote,'explanation':'Unsupported quote.'}];return result
            with self.subTest(quote=quote),self.assertRaises(AssessmentFailed):
                rank(job('https://example.test/invalid','Unique title text'),example_profile(),Model())
            self.assertEqual(len(calls),2)

    def test_location_alone_cannot_supply_role_fit_evidence(self):
        class Model(FixtureModel):
            def generate(self,task,data,schema):
                result=super().generate(task,data,schema)
                result['evidence']=[{'quote':'London','explanation':'Only location supplied.'}]
                return result
        posting={**job('https://example.test/no-role-evidence'),'location':'London'}
        posting['description']=posting['description'].replace('London','the office')
        with self.assertRaises(AssessmentFailed):rank(posting,example_profile(),Model())
