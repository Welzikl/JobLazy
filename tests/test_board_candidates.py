import unittest

from joblazy.board_candidates import location_matches, select_board_candidates, title_matches
from .support import example_profile, job


class BoardCandidateSelectionTests(unittest.TestCase):
    def test_explicit_london_uk_search_drops_other_cities_and_london_ontario(self):
        target = 'London, United Kingdom'
        for location in ('Berlin, Germany', 'Pune, India', 'New York, NY, United States',
                         'London, Ontario, Canada', 'London, ON'):
            with self.subTest(location=location):
                self.assertFalse(location_matches(location, target))
        self.assertTrue(location_matches('London, UK', target))
        self.assertTrue(location_matches('London, GB', target))
        self.assertTrue(location_matches('London', target))
        self.assertTrue(location_matches('London, on-site', target))
        self.assertTrue(location_matches('London (On site)', target))

    def test_observed_ats_location_labels_are_interpreted_conservatively(self):
        target = 'London, United Kingdom'
        for location in ('UK - London (London Wall), United Kingdom',
                         'London (Hybrid) | MTUK', 'Location unverified',
                         'United Kingdom', 'TBD', 'Mystery Region, MTUK'):
            with self.subTest(location=location):
                self.assertTrue(location_matches(location, target))
        self.assertFalse(location_matches('London, Ontario (Hybrid)', target))
        self.assertFalse(location_matches('Berlin, Germany', target))

    def test_remote_unknown_and_multilocation_observations_are_kept(self):
        target = 'London, United Kingdom'
        for location in ('Remote', 'United Kingdom (Remote)', '', 'Hybrid: location unspecified', 'Hybrid London, UK',
                         'Berlin, Germany / London, UK', 'Bristol, UK or London, UK'):
            with self.subTest(location=location):
                self.assertTrue(location_matches(location, target))

    def test_remote_country_restrictions_and_internal_codes_do_not_override_conflicts(self):
        for location in ('Remote - US eligible', 'India (Remote)', 'Remote | India', 'Pune, India | MTIN'):
            with self.subTest(location=location):
                self.assertFalse(location_matches(location, 'London, United Kingdom'))
        self.assertTrue(location_matches('Berlin, Germany | London', 'London, United Kingdom'))

    def test_observed_region_and_city_labels_exclude_overseas_roles_without_inventing_code_meanings(self):
        target = 'London, United Kingdom'
        self.assertFalse(location_matches('AU - HQ - NSW', target))
        self.assertFalse(location_matches('Amsterdam or Rotterdam | DTNL', target))
        self.assertTrue(location_matches('London, Manchester | DTNL', target))
        self.assertTrue(location_matches('DTNL', target))

    def test_location_country_disambiguation_works_for_london_ontario_target(self):
        target = 'London, Ontario, Canada'
        self.assertTrue(location_matches('London, Canada', target))
        self.assertTrue(location_matches('London, ON', target))
        self.assertFalse(location_matches('London, UK', target))

    def test_title_requires_all_requested_meaningful_terms(self):
        self.assertTrue(title_matches('Strategy Analyst', ['strategy']))
        self.assertFalse(title_matches('HR Business Partner', ['strategy']))
        self.assertFalse(title_matches('HR Business Partner', ['business strategy']))
        self.assertTrue(title_matches('Business Strategy Analyst', ['business strategy']))
        self.assertFalse(title_matches('HR Business Partner', ['strategy operations']))
        self.assertTrue(title_matches('Strategy and Operations Manager', ['strategy operations']))
        self.assertTrue(title_matches('Partner Operations Manager', ['partner operations']))
        self.assertTrue(title_matches('AI Consultant', ['AI consulting']))

    def test_equivalent_role_abbreviations_match_without_expanding_to_unrelated_families(self):
        self.assertTrue(title_matches('SDR EMEA', ['sales development representative']))
        self.assertTrue(title_matches('Sales Development Representative', ['SDR']))
        self.assertTrue(title_matches('BDR', ['business development']))
        self.assertTrue(title_matches('BizOps Lead', ['business operations']))
        self.assertTrue(title_matches('GTM Strategy Manager', ['go to market strategy']))
        self.assertFalse(title_matches('Sales Operations Analyst', ['SDR']))

    def test_selector_combines_location_and_title_then_keeps_processing_priority(self):
        profile = example_profile()
        roles = [
            {**job('https://example.test/uk'), 'title': 'Strategy and Operations Manager', 'location': 'London, UK'},
            {**job('https://example.test/de'), 'title': 'Strategy and Operations Manager', 'location': 'Berlin, Germany'},
            {**job('https://example.test/hr'), 'title': 'HR Business Partner', 'location': 'London, UK'},
            {**job('https://example.test/unknown'), 'title': 'Partner Operations Manager', 'location': ''},
        ]
        selected = select_board_candidates(roles, ['strategy operations', 'partner operations'],
                                          'London, United Kingdom', profile)
        self.assertEqual({role['url'] for role in selected}, {
            'https://example.test/uk', 'https://example.test/unknown'})


if __name__ == '__main__':
    unittest.main()
