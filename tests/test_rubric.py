import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from joblazy.common import NeedsInput
from joblazy.materials import rank
from joblazy.review import render_review
from joblazy.store import Store
from .support import FixtureModel,example_profile,job


class RubricTests(unittest.TestCase):
    def run_change(self,change):
        class Changed(FixtureModel):
            def generate(self,*args):
                result=super().generate(*args);change(result);return result
        return rank(job('https://example.test/one'),example_profile(),Changed())

    def test_missing_or_unsupported_dimensions_do_not_pass(self):
        changes=[lambda r:r.pop('dimensions'),
            lambda r:r['dimensions']['cv_fit'].update(job_quotes=['An invented requirement']),
            lambda r:r['dimensions']['cv_fit'].update(candidate_source_ids=['invented']),
            lambda r:r['dimensions']['cv_fit'].update(candidate_source_ids=[]),
            lambda r:r['dimensions']['compensation'].update(score=3,job_quotes=[])]
        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(NeedsInput):self.run_change(change)

    def test_dimension_evidence_and_unknowns_survive_rendering(self):
        result=self.run_change(lambda r:r['dimensions']['culture'].update(explanation='<script>unknown</script>'))
        self.assertIsNone(result['dimensions']['compensation']['score'])
        self.assertEqual(result['score'],85) # No arithmetic conversion from the 4/5 CV rating.
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            key=store.ingest(job('https://example.test/one'));store.transition(key,'ranked',{'ranking':result})
            output=render_review(store,Path(temp));html=Path(output['path']).read_text(encoding='utf-8')
            self.assertIn('Career Ops scoring dimensions',html)
            self.assertIn('Unknown',html)
            self.assertIn('&lt;script&gt;unknown&lt;/script&gt;',html)
            self.assertNotIn('<script>unknown</script>',html)
