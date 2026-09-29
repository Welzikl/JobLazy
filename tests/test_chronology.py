import copy
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from joblazy.materials import rank,AssessmentFailed
from .support import example_profile,job,FixtureModel


class ChronologyTests(unittest.TestCase):
    def profile(self):
        profile=example_profile()
        profile['resume']['experience'][0]['dates']='April 2021 – February 2023'
        return profile

    def test_impossible_employer_tenure_is_rejected_after_bounded_correction(self):
        class Wrong(FixtureModel):
            def generate(self,*args):
                result=super().generate(*args)
                result['dimensions']['cv_fit']['explanation']='The documented tenure is about 2 years 4 months at Fictional Software Ltd.'
                return result
        with self.assertRaises(AssessmentFailed):rank(job('https://example.test/tenure'),self.profile(),Wrong())

    def test_calendar_bounds_and_overlaps_preserve_unknown_work_patterns(self):
        from joblazy.chronology import employment_calendar
        profile=self.profile();entries=profile['resume']['experience']
        entries.extend([
            {'company':'Second Example','dates':'February 2023 – July 2023','role':'Intern','hours_per_week':12},
            {'company':'Third Example','dates':'2022-01 – 2022-06'},
            {'company':'Freelance','dates':'Clients | 2019–2023'},
            {'company':'Current Example','dates':'January 2024 – Present'},
            {'company':'Invalid Example','dates':'July 2024 – March 2024'},
        ])
        before=copy.deepcopy(profile);report=employment_calendar(profile)
        first,second,third,*unknown=report['entries']
        self.assertEqual(first['month_distance'],22)
        self.assertEqual(first['calendar_months_touched'],23)
        self.assertEqual(first['overlapping_source_ids'],['employment.1','employment.2'])
        self.assertEqual(second['calendar_months_touched'],6)
        self.assertEqual(third['calendar_months_touched'],6)
        self.assertEqual(report['calendar_months_touched_union'],28)
        self.assertTrue(all(e['status']=='unquantified' for e in unknown))
        self.assertNotIn('worked_months',str(report));self.assertEqual(profile,before)

    def test_correction_receives_calculation_and_preserves_raw_dates(self):
        self_test=self;calls=[]
        class Corrected(FixtureModel):
            def generate(self,task,data,schema):
                calls.append(data)
                payload=data.get('original_input',data)
                self_test.assertEqual(payload['employment_calendar']['entries'][0]['month_distance'],22)
                self_test.assertEqual(payload['resume']['experience'][0]['dates'],'April 2021 – February 2023')
                result=super().generate(task,data,schema)
                result['dimensions']['cv_fit']['explanation']=(
                    'The candidate has 28 months at Fictional Software Ltd.' if len(calls)==1 else
                    'The source dates are April 2021–February 2023; actual full-time relevant experience remains uncertain.')
                return result
        result=rank(job('https://example.test/correct'),self.profile(),Corrected())
        self.assertEqual(len(calls),2);self.assertIn('calendar',calls[1]['validation_error'])
        self.assertEqual(result['validation']['status'],'corrected')
        from joblazy.store import Store
        from joblazy.review import render_review
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            key=store.ingest(job('https://example.test/correct'))
            store.transition(key,'ranked',{'ranking':result})
            render_review(store,temp,profile=self.profile())
            html=(Path(temp)/'review.html').read_text(encoding='utf-8')
            self.assertIn('Employment calendar evidence',html)
            self.assertIn('23 calendar months touched',html)
            self.assertIn('full-time equivalence',html)
            self.assertIn('April 2021',html)

    def test_bound_check_distinguishes_uncertainty_and_ambiguous_employers(self):
        from joblazy.chronology import chronology_errors
        profile=self.profile()
        def errors(text):
            return chronology_errors({'dimensions':{'cv_fit':{'explanation':text,'candidate_source_ids':['employment.0']}}},profile)
        for text in ('The candidate has 28 months at Fictional Software Ltd.',
                     'Two years and four months at Fictional Software Ltd are documented.',
                     'The candidate has 2 years 4 months at Fictional.'):
            self.assertTrue(errors(text),text)
        for text in ('Three years at Another Employer is required.',
                     'The evidence does not establish 28 months at Fictional Software Ltd.',
                     'It is unverified whether the candidate has 28 months at Fictional Software Ltd.',
                     'About two years at Fictional Software Ltd supports transferable experience.',
                     'The range touches 23 months at Fictional Software Ltd.'):
            self.assertEqual(errors(text),[],text)
        profile['resume']['experience'].append({'company':'Fictional Software Ltd','dates':'2010–2013'})
        self.assertEqual(errors('The candidate has 28 months at Fictional Software Ltd.'),[])


if __name__=='__main__':unittest.main()
