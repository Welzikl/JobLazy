import unittest
from joblazy.experience_policy import mandatory_years
from joblazy.materials import rank
from .support import FixtureModel,example_profile,job

class ExperiencePolicyTests(unittest.TestCase):
    def test_repeated_false_exclusion_stops_after_one_correction(self):
        from joblazy.materials import AssessmentFailed
        profile=example_profile()
        profile['targeting']={'config':{'target_roles':{'seniority':{'mode':'required_experience_range','maximum_required_years':5}}}}
        posting=job('https://example.test/repeat');quote='5-7 years of experience'
        posting['description']+=' '+quote;calls=[]
        class Model(FixtureModel):
            def generate(self,task,data,schema):
                calls.append(data);result=super().generate(task,data,schema)
                result['requirements'].append({'requirement':'Search ceiling','job_quote':quote,
                    'kind':'hard_constraint','status':'not_met','candidate_source_ids':['preference.experience_range'],
                    'explanation':'The upper end is seven.'})
                return result
        with self.assertRaises(AssessmentFailed):rank(posting,profile,Model())
        self.assertEqual(len(calls),2)

    def test_old_full_ceiling_exclusions_require_revalidation_without_staling_other_decisions(self):
        from joblazy.assessment_state import assessment_stale,assessment_profile_hash
        from joblazy.common import digest
        profile=example_profile()
        result=self.assess('6–11 years of experience')
        full_profile={**profile,'targeting':{'config':{'target_roles':{'seniority':{'mode':'required_experience_range','maximum_required_years':5}}}}}
        row={'status':'not_selected','data':job('https://example.test/old'),'result':result}
        hashes=(digest(full_profile),assessment_profile_hash(full_profile))
        self.assertFalse(assessment_stale(row,*hashes))
        result.pop('experience_policy_version',None)
        self.assertTrue(assessment_stale(row,*hashes))
        row['status']='materials_ready'
        self.assertFalse(assessment_stale(row,*hashes))
        positive=self.assess('3–6 years of experience');positive.pop('experience_policy_version',None)
        self.assertFalse(assessment_stale({'status':'ranked','data':row['data'],'result':positive},*hashes))

    def test_upper_end_of_range_cannot_create_a_false_search_policy_exclusion(self):
        for quote in ('5-7 years in operations','3–6 years in consulting','5+ years of experience'):
            with self.subTest(quote=quote):
                profile=example_profile()
                profile['targeting']={'config':{'target_roles':{'seniority':{'mode':'required_experience_range','maximum_required_years':5}}}}
                posting=job('https://example.test/range');posting['description']+=' '+quote
                calls=[]
                class Model(FixtureModel):
                    def generate(self,task,data,schema):
                        calls.append(data)
                        result=super().generate(task,data,schema)
                        if len(calls)==1:
                            result['requirements'].append({'requirement':'Experience search policy','job_quote':quote,
                                'kind':'hard_constraint','status':'not_met','candidate_source_ids':['preference.experience_range'],
                                'explanation':'The top end exceeds five years.'})
                        else:
                            result['requirements'].append({'requirement':'Qualifying experience','job_quote':quote,
                                'kind':'required_experience','status':'unverified','candidate_source_ids':[],
                                'explanation':'The candidate may lack the specified background; duration is unconfirmed.'})
                        return result
                result=rank(posting,profile,Model())
                self.assertTrue(result['eligible'])
                self.assertEqual(len(calls),2)
                self.assertEqual(result['validation']['correction_attempts'],1)
                self.assertIn('lower bound',calls[1]['validation_error'])

    def assess(self,quote,kind='required_experience'):
        profile=example_profile()
        profile['targeting']={'config':{'target_roles':{'seniority':{'mode':'required_experience_range','maximum_required_years':5}}}}
        posting=job('https://example.test/range');posting['description']+=' '+quote
        class Model(FixtureModel):
            def generate(self,task,data,schema):
                result=super().generate(task,data,schema)
                result['requirements'].append({'requirement':'Experience','job_quote':quote,'kind':kind,
                    'status':'unverified','candidate_source_ids':[],'explanation':'Years not established by fixture candidate.'})
                return result
        return rank(posting,profile,Model())

    def test_high_score_cannot_override_six_to_eleven_year_minimum(self):
        result=self.assess('6–11 years in consulting or operating roles')
        self.assertEqual(result['score'],85)
        self.assertEqual(result['dimensions']['cv_fit']['score'],4)
        self.assertFalse(result['eligible']);self.assertEqual(result['fit_category'],'poor_fit')
        self.assertEqual(result['eligibility_status'],'blocked')
        self.assertIn('preference.experience_range',result['candidate_facts'])

    def test_required_numeric_and_word_minimums(self):
        for quote in ('6+ years of experience','At least six years of experience','7 to 10 years of experience'):
            with self.subTest(quote=quote):self.assertFalse(self.assess(quote)['eligible'])

    def test_five_plus_and_lower_bound_within_target_remain_allowed(self):
        for quote in ('1-5 years of experience','3–6 years in partnerships','5+ years in operations'):
            with self.subTest(quote=quote):self.assertTrue(self.assess(quote)['eligible'])

    def test_preferred_years_are_not_mandatory(self):
        self.assertTrue(self.assess('8 years in operations','preferred')['eligible'])
        self.assertTrue(self.assess('8 years preferred')['eligible'])

    def test_preferred_domain_does_not_erase_required_years(self):
        for quote in ('Requires 6 years of experience, ideally in SaaS.',
                      'At least six years in operations ideally within a technology company.'):
            with self.subTest(quote=quote):self.assertFalse(self.assess(quote)['eligible'])
        for quote in ('Ideally 6 years of experience in SaaS.', '6 years of experience would be ideal.'):
            with self.subTest(quote=quote):self.assertTrue(self.assess(quote,'preferred')['eligible'])
        self.assertTrue(self.assess('Ideally 6 years of experience in SaaS.')['eligible'])

    def test_ambiguous_alternatives_and_missing_years_are_not_guessed(self):
        for quote in ('3 years with a masters or 6 years with a bachelors','Lead the operations team','Up to 8 years of experience'):
            self.assertIsNone(mandatory_years({'kind':'required_experience','job_quote':quote}))

    def test_parenthetical_preference_for_an_example_does_not_erase_required_duration(self):
        quote='Required: 6+ years in a demanding role such as advisory (large firms preferred) or startup operations.'
        self.assertEqual(mandatory_years({'kind':'required_experience','job_quote':quote}),6)
        self.assertFalse(self.assess(quote)['eligible'])
        for uncertain in (
            'Ideally '+quote,
            '6 years preferred in fields such as advisory (large firms preferred).',
            '6 years in advisory (experience preferred).',
            '6 years in fields such as advisory (relevant experience preferred).',
            '6 years in fields such as advisory (large firms preferred), or 3 years with a masters.',
            '6 years (preferred) in fields such as advisory (large firms preferred).',
        ):
            with self.subTest(quote=uncertain):
                self.assertIsNone(mandatory_years({'kind':'required_experience','job_quote':uncertain}))
        self.assertTrue(self.assess(quote.replace('6+','3-6'))['eligible'])
        self.assertTrue(self.assess(quote,'preferred')['eligible'])
