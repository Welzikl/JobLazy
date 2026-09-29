import copy
import json
import unittest

from joblazy.search_missions import build_search_missions, discovery_brief, SEARCH_MODEL, REVIEW_MODEL


class SearchMissionTests(unittest.TestCase):
    def test_six_deterministic_complementary_missions_preserve_requested_preferences(self):
        plan = {'queries': ['Business Operations', 'Growth Associate', 'Product Operations',
                            'Investment Analyst', 'Strategic Partnerships', 'Founder Associate'],
                'location': 'London, United Kingdom'}
        brief = {'primary_tracks': ['strategy', 'growth'], 'exclusions': ['accounting'],
                 'experience_level': '1-5 years', 'lower_interest_roles': ['SDR']}
        before = copy.deepcopy((plan, brief))
        missions = build_search_missions(plan, brief, known_board_ids=['lever:fictional'], seen_ids=['job:1'])
        self.assertEqual(missions, build_search_missions(plan, brief, known_board_ids=['lever:fictional'], seen_ids=['job:1']))
        self.assertEqual(len(missions), 6)
        self.assertEqual(len({m['id'] for m in missions}), 6)
        self.assertEqual(len({m['scope'] for m in missions}), 3)
        role_queries = [q for m in missions[:4] for q in m['queries']]
        self.assertTrue(set(plan['queries']).issubset(role_queries))
        self.assertEqual(len(role_queries), len(set(role_queries)))
        for mission in missions:
            self.assertEqual(mission['brief'], brief)
            self.assertEqual(mission['location'], plan['location'])
            self.assertEqual(mission['max_search_calls'], 1)
            self.assertEqual(mission['max_queries'], 3)
            self.assertEqual(mission['max_leads'], 8)
            self.assertTrue(0 < len(mission['queries']) <= 3)
            self.assertIn('lever:fictional', mission['known_board_ids'])
            self.assertIn('job:1', mission['seen_ids'])
        self.assertEqual((plan, brief), before)
        json.dumps(missions)

    def test_sparse_unrelated_profession_does_not_acquire_hardcoded_career_preferences(self):
        missions = build_search_missions({'queries': ['Registered nurse'], 'location': 'Bristol, UK'},
                                         {'desired_work': 'Nursing', 'avoid': 'Management'})
        self.assertEqual(len({q for m in missions for q in m['queries']}), 6)
        self.assertTrue(all('Registered nurse' in q for m in missions for q in m['queries']))
        self.assertTrue(all(m['name'].startswith('Preferred roles') for m in missions[:4]))
        self.assertTrue(all(m['brief']['avoid'] == 'Management' for m in missions))

    def test_large_homogeneous_plan_balances_and_reports_unsearched_phrases(self):
        queries = [f'Operations specialty {i}' for i in range(15)]
        missions = build_search_missions({'queries': queries, 'location': 'London, UK'})
        covered = {q for m in missions[:4] + missions[5:] for q in m['queries']}
        self.assertEqual(covered, set(queries))
        self.assertEqual(missions[-1]['deferred_queries'], [])
        bounded = build_search_missions({'queries': queries, 'location': 'London, UK'}, max_queries=1)
        covered = {q for m in bounded[:4] + bounded[5:] for q in m['queries']}
        self.assertEqual(covered | set(bounded[-1]['deferred_queries']), set(queries))

    def test_case_and_spacing_duplicates_share_one_primary_owner(self):
        missions = build_search_missions({'queries': ['  Product   manager', 'product manager', 'Growth'],
                                          'location': 'London, UK'})
        all_queries = [q.casefold() for m in missions for q in m['queries']]
        self.assertEqual(len(all_queries), len(set(all_queries)))

    def test_profile_envelope_never_sends_identity_cv_facts_or_salary(self):
        profile = {'targeting': {'desired_work': 'Design', 'salary': 'private', 'email': 'private'},
                   'applicant': {'email': 'private'}, 'resume': {'text': 'private'}, 'facts': ['private']}
        brief = discovery_brief(profile)
        self.assertEqual(brief, {'desired_work': 'Design'})
        self.assertEqual(discovery_brief('Design'), brief)
        self.assertEqual(discovery_brief(None), {})

    def test_mission_briefs_are_independent_and_routing_defaults_are_explicit(self):
        brief = {'exclusions': ['banking']}
        missions = build_search_missions({'queries': ['Designer'], 'location': 'London'}, brief)
        missions[0]['brief']['exclusions'].append('new')
        self.assertEqual(missions[1]['brief'], brief)
        self.assertEqual(SEARCH_MODEL, 'gpt-6-luna')
        self.assertEqual(REVIEW_MODEL, 'gpt-6-astra')

    def test_imported_preferences_keep_exclusions_seniority_and_fallback_without_candidate_config(self):
        config = {'candidate': {'full_name': 'Private Name', 'email': 'private@example.test'},
                  'target_roles': {'primary': ['Strategy & Operations'],
                    'archetypes': [{'name': 'BDR / SDR', 'fit': 'fallback', 'source': {'verbatim': 'private'}}],
                    'seniority': {'mode': 'required_experience_range', 'minimum_target_years': 1,
                                  'maximum_required_years': 5, 'rule': 'Exclude mandatory 6+ years.',
                                  'source': {'verbatim': 'private'}}},
                  'location': {'city': 'London', 'country': 'United Kingdom', 'working_arrangement': 'Any',
                               'visa_status': 'private'},
                  'compensation': {'minimum_annual_gbp': 50000},
                  'narrative': {'strategy_operations': 'private candidate experience'}, 'cv': {'template': 'private'}}
        prose = ('## Target Career Tracks\nStrategy primary; BDR / SDR fallback.\n'
                 '## Sector Exclusions\nExclude workforce training and banking.\n'
                 '## Adaptive Professional Narrative\nprivate candidate experience\n'
                 '### Strategy & Operations\nprivate achievements\n'
                 '## Search Treatment\nRequire 1-5 years; ignore compensation in discovery.\n'
                 '## Confirmed Compensation\nprivate salary details\n'
                 '## Confirmed BDR / SDR Preference\nFallback only. Email private@example.test')
        for envelope in ('config', 'context'):
            with self.subTest(envelope=envelope):
                brief = discovery_brief({'targeting': {envelope: config, 'career_preferences': prose}})
                self.assertEqual(brief['primary_tracks'], ['Strategy & Operations'])
                self.assertEqual(brief['role_archetypes'], [{'name': 'BDR / SDR', 'fit': 'fallback'}])
                self.assertEqual(brief['experience_policy']['maximum_required_years'], 5)
                self.assertEqual(brief['city'], 'London')
                self.assertEqual(brief['work_arrangement'], 'Any')
                self.assertIn('Exclude workforce training and banking.', brief['career_preferences'])
                self.assertIn('Require 1-5 years', brief['career_preferences'])
                self.assertIn('Fallback only.', brief['career_preferences'])
                self.assertNotIn('private', json.dumps(brief).lower())
                self.assertEqual(discovery_brief(brief), brief)

    def test_bad_plans_and_non_integer_budgets_fail_before_dispatch(self):
        valid = {'queries': ['Designer'], 'location': 'London'}
        for plan in (None, {}, {**valid, 'queries': []}, {**valid, 'queries': ['']},
                     {**valid, 'queries': 'Designer'}, {**valid, 'location': ''}):
            with self.subTest(plan=plan), self.assertRaises(ValueError): build_search_missions(plan)
        for key in ('max_queries', 'max_search_calls', 'max_leads'):
            for value in (0, -1, True, 1.5, '3'):
                with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                    build_search_missions(valid, **{key: value})
