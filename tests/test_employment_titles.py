import copy
import unittest
import jsonschema
from joblazy.common import NeedsInput
from joblazy.materials import tailor,source_facts,ranking_input
from joblazy.checkpoints import document_profile_hash
from .support import FixtureModel,example_profile,job


class EmploymentTitleTests(unittest.TestCase):
    def profile(self):
        profile=example_profile();e=profile['resume']['experience'][0]
        profile['employment_title_options']=[{'experience_index':0,'company':e['company'],
            'dates':e['dates'],'original_role':e['role'],'allowed_roles':['Client Service Manager'],
            'source':{'method':'operator_confirmed','verbatim':'Both titles were available for this fictional role.'}}]
        return profile

    def model(self,role='Client Service Manager',index=0):
        class Model(FixtureModel):
            def generate(self,task,data,schema):
                result=super().generate(task,data,schema)
                if 'Tailor the CV' in task:
                    result['title_selections']=[{'index':index,'role':role,'reason':'Confirmed client-facing title suits this sales role.'}]
                    if role=='Client Service Manager' and index==0:jsonschema.validate(result,schema)
                return result
        return Model()

    def test_confirmed_title_reaches_cv_without_mutating_original(self):
        profile=self.profile();before=copy.deepcopy(profile)
        result=tailor(job('https://example.test/sales'),profile,self.model())
        self.assertEqual(result['payload']['experience'][0]['role'],'Client Service Manager')
        for key in ('company','dates','location'):
            self.assertEqual(result['payload']['experience'][0][key],profile['resume']['experience'][0][key])
        self.assertEqual(result['title_selections'][0]['source_ref'],'/employment_title_options/0')
        self.assertEqual(profile,before)

    def test_original_title_remains_a_valid_choice(self):
        profile=self.profile();original=profile['resume']['experience'][0]['role']
        result=tailor(job('https://example.test/ops'),profile,self.model(original))
        self.assertEqual(result['payload']['experience'][0]['role'],original)

    def test_unconfirmed_title_and_wrong_employer_are_rejected(self):
        for role,index in [('Sales Director',0),('Client Service Manager',1)]:
            with self.subTest(role=role,index=index),self.assertRaises(NeedsInput):
                tailor(job('https://example.test'),self.profile(),self.model(role,index))

    def test_changed_employer_or_dates_and_missing_confirmation_stop_before_model(self):
        for field in ('company','dates','source'):
            profile=self.profile();profile['employment_title_options'][0][field]={} if field=='source' else 'Different'
            with self.subTest(field=field),self.assertRaises(NeedsInput):
                tailor(job('https://example.test'),profile,None)

    def test_title_options_invalidate_cv_but_not_unchanged_fit_inputs(self):
        before=example_profile();after=self.profile();posting=job('https://example.test')
        self.assertNotEqual(document_profile_hash(before),document_profile_hash(after))
        self.assertEqual(ranking_input(posting,before,source_facts(before)),ranking_input(posting,after,source_facts(after)))

    def test_missing_or_duplicate_selection_cannot_silently_choose(self):
        for selections in ([],[{'index':0,'role':'Client Service Manager','reason':'Relevant'}]*2):
            class Model(FixtureModel):
                def generate(self,task,data,schema):
                    result=super().generate(task,data,schema)
                    if 'Tailor the CV' in task:result['title_selections']=selections
                    return result
            with self.subTest(selections=selections),self.assertRaises(NeedsInput):
                tailor(job('https://example.test'),self.profile(),Model())
