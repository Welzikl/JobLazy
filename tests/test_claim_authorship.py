import unittest

from joblazy.common import NeedsInput
from joblazy.materials import validate_claims


class ClaimAuthorshipTests(unittest.TestCase):
    def test_using_checklist_does_not_establish_creating_it(self):
        facts = {'experience.0.0': 'Reduced onboarding handoff delays by 15% through a shared checklist.'}
        claim = {'text': 'Reduced onboarding handoff delays by 15% by creating a shared checklist.',
                 'source_ids': ['experience.0.0']}
        with self.assertRaisesRegex(NeedsInput, 'authorship'):
            validate_claims([claim], facts)
        claim['text'] = 'Reduced onboarding handoff delays by 15% using a shared checklist.'
        validate_claims([claim], facts)

    def test_authorship_must_be_in_cited_evidence_not_an_unrelated_fact(self):
        facts = {'experience.0.0': 'Used onboarding checklists.', 'experience.0.1': 'Built weekly reports.'}
        with self.assertRaisesRegex(NeedsInput, 'authorship'):
            validate_claims([{'text': 'Authored onboarding checklists.', 'source_ids': ['experience.0.0']}], facts)
        validate_claims([{'text': 'Created weekly reports.', 'source_ids': ['experience.0.1']}], facts)
