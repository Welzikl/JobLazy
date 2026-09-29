import unittest
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from joblazy.outcomes import receipt_messages
from joblazy.store import Store
from .support import job


class OutcomeTests(unittest.TestCase):
    def test_positive_receipts_are_explicit(self):
        for message in ['Application received.','Your application has been successfully submitted!',
            "We've received your application.",'Thank you for applying to Fictional Ltd.',
            'Thank you for your application.','Your application was submitted successfully.']:
            self.assertTrue(receipt_messages([message]),message)

    def test_errors_negation_and_ambiguous_acknowledgements_are_not_receipts(self):
        for message in ['Application received an error.','Your application was not submitted.',
            'We have not received your application.','Submission pending.','Application already submitted.',
            'Thanks for visiting.','If successful, your application will be received.']:
            self.assertEqual(receipt_messages([message]),[],message)
        self.assertEqual(receipt_messages(['Application received.','Submission failed.']),[])

    def test_changed_surrounding_text_does_not_make_a_stale_receipt_fresh(self):
        self.assertEqual(receipt_messages(['Application received.']),
            receipt_messages(['Application received. Status refreshed.']))

    def test_reconcile_cli_records_operator_evidence_without_a_new_attempt(self):
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'jobs.sqlite')
            key=store.ingest(job('https://example.test/outcome'));store.transition(key,'submission_unknown');store.close()
            result=subprocess.run([sys.executable,'-m','joblazy','--data',temp,'reconcile',key,
                '--outcome','submitted','--note','Checked the employer portal receipt.'],
                capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(result.stdout)['method'],'operator_report')
            store=Store(Path(temp)/'jobs.sqlite')
            try:
                self.assertEqual(store.get(key)['status'],'submitted')
                self.assertEqual(store.db.execute("SELECT count(*) FROM events WHERE status='processing'").fetchone()[0],0)
            finally:store.close()
            self.assertTrue((Path(temp)/'applications'/key/'manual-outcome.json').is_file())
            self.assertIn('operator reported',(Path(temp)/'review.html').read_text(encoding='utf-8'))
