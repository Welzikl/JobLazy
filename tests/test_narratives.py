import copy
import tempfile
import unittest
from pathlib import Path
from joblazy.mapping import plan_fields
from joblazy.narratives import AnswerDrafter, question_evidence
from joblazy.materials import source_facts
from .support import example_profile,job,FixtureModel

class NarrativeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.profile=example_profile()
        self.field={'id':'q','label':'Describe your relevant experience','type':'textarea','required':True,'max_length':400}

    def resolve(self,model,field=None):
        fields=[field or self.field]
        drafter=AnswerDrafter(self.profile,job('https://example.test/job'),model,Path(self.temp.name),'fixture')
        return drafter.extend(plan_fields(fields,self.profile,'fixture'))

    def test_grounded_answer_is_separate_from_profile(self):
        before=copy.deepcopy(self.profile)
        plan=self.resolve(FixtureModel())
        self.assertEqual(len(plan['fields']),1)
        self.assertEqual(plan['fields'][0]['source'],'reviewed_draft')
        self.assertEqual(plan['unresolved'],[])
        self.assertEqual(self.profile,before)

    def test_question_evidence_highlights_existing_client_context_without_inferring_employment(self):
        facts={'summary':'Operations experience with reporting.',
               'employment_identity.4':'Company: Freelance; role: GTM; recorded context: Clients & Startups | 2019-2023',
               'experience.4.0':'Supported client marketing campaigns.',
               'preference.career_rules':'I want startup roles.',
               'job_description':'A startup wants someone with startup experience.'}
        before=copy.deepcopy(facts)
        focused=question_evidence({'label':'Do you have startup experience?','description':''},facts)
        self.assertEqual(next(iter(focused)),'employment_identity.4')
        self.assertEqual(focused['employment_identity.4'],facts['employment_identity.4'])
        self.assertNotIn('preference.career_rules',focused)
        self.assertNotIn('job_description',focused)
        self.assertEqual(facts,before)
        self.assertEqual(question_evidence({'label':'Describe your aerospace work'},{}),{})
        self.assertLessEqual(len(question_evidence({'label':'Describe your startup experience'},
            {f'fact.{i}':'Startup context '+str(i) for i in range(20)})),6)

    def test_saved_career_preferences_support_role_fit_without_becoming_cv_facts(self):
        self.profile['targeting']={'career_preferences':'I prioritise operations roles at software companies.'}
        before=copy.deepcopy(self.profile);calls=[]
        class PreferenceModel(FixtureModel):
            def generate(model,task,data,schema):
                calls.append(data)
                if 'preference.career_rules' not in data['facts']:
                    return {'answerable':False,'claims':[],'missing_facts':['Career interests are absent']}
                if 'Draft a factual' in task:
                    return {'answerable':True,'missing_facts':[],'claims':[{
                        'text':'This software operations role matches the career direction I am targeting.',
                        'source_ids':['preference.career_rules','job_description']}]}
                return {'supported':True,'issues':[],'missing_facts':[]}
        plan=self.resolve(PreferenceModel(),{**self.field,'label':'Why are you interested in this role?'})
        self.assertEqual(len(plan['fields']),1)
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[0]['facts']['preference.career_rules'],self.profile['targeting']['career_preferences'])
        self.assertEqual(calls[0]['facts'],calls[1]['facts'])
        self.assertNotIn('preference.career_rules',source_facts(self.profile))
        self.assertEqual(self.profile,before)

    def test_preferences_cannot_supply_missing_personal_history_or_bypass_review(self):
        self.profile['targeting']={'career_preferences':'I prioritise software companies.'}
        class MissingHistory(FixtureModel):
            def generate(model,task,data,schema):
                if 'Draft a factual' in task:
                    return {'answerable':True,'missing_facts':[],'claims':[{
                        'text':'I have personally worked with the founder.',
                        'source_ids':['preference.career_rules']}]}
                return {'supported':False,'issues':['Career preference does not establish founder contact'],
                        'missing_facts':['Whether the candidate has worked with this founder']}
        plan=self.resolve(MissingHistory(),{**self.field,'label':'Tell me about your prior work with our founder'})
        self.assertEqual(plan['fields'],[])
        self.assertIn('Whether the candidate',plan['unresolved'][0]['reason'])

    def test_tell_me_about_a_time_uses_the_grounded_drafting_flow(self):
        field={**self.field,'label':'Tell me about a time you coordinated onboarding'}
        plan=self.resolve(FixtureModel(),field)
        self.assertEqual(len(plan['fields']),1)
        self.assertEqual(plan['fields'][0]['source'],'reviewed_draft')

    def test_observed_achievement_questions_use_reviewed_drafts_and_keep_safety_checks(self):
        before=copy.deepcopy(self.profile)
        for label in ('What are you most proud of building?', "What is the most impressive thing you've done?"):
            field={**self.field,'label':label}
            self.assertEqual(self.resolve(FixtureModel(),field)['fields'][0]['source'],'reviewed_draft')
            class NoModel:
                def generate(self,*args):raise AssertionError('Consequential context must stay unresolved')
            for change in ({'description':'Include your expected salary and notice period.'},
                           {'options':['Yes','No']},{'type':'checkbox'}):
                self.assertEqual(self.resolve(NoModel(),{**field,**change})['fields'],[])
        self.assertEqual(self.profile,before)

    def test_optional_narrative_is_drafted_but_saved_answers_take_precedence(self):
        field={**self.field,'required':False}
        self.assertEqual(self.resolve(FixtureModel(),field)['fields'][0]['source'],'reviewed_draft')
        self.profile['answers']=[{'question':field['label'],'scope':'fixture','value':'My saved answer.'}]
        class NoModel:
            def generate(self,*args):raise AssertionError('An existing scoped answer must not be rewritten')
        self.assertEqual(self.resolve(NoModel(),field)['fields'][0]['value'],'My saved answer.')

    def test_invented_metric_never_reaches_field_plan(self):
        class Invented(FixtureModel):
            def generate(self,task,data,schema):
                value=super().generate(task,data,schema)
                if 'Draft a factual' in task: value['claims'][0]['text']='I onboarded 2000 partners.'
                return value
        plan=self.resolve(Invented())
        self.assertEqual(plan['fields'],[])
        self.assertIn('metric',plan['unresolved'][0]['reason'])

    def test_unknown_experience_and_failed_review_remain_exceptions(self):
        class Unknown(FixtureModel):
            def generate(self,task,data,schema):
                if 'Draft a factual' in task: return {'answerable':False,'claims':[],'missing_facts':['Engineering sales experience is not documented']}
                return super().generate(task,data,schema)
        class FailedReview(FixtureModel):
            def generate(self,task,data,schema):
                if 'Independently review this application' in task: return {'supported':False,'issues':['Unsupported ownership']}
                return super().generate(task,data,schema)
        for model in (Unknown(),FailedReview()):
            self.assertEqual(self.resolve(model)['fields'],[])

    def test_review_missing_facts_stops_without_rewriting_or_repeated_round_calls(self):
        class MissingAtReview(FixtureModel):
            def __init__(self):self.calls=[]
            def generate(self,task,data,schema):
                self.calls.append(task)
                if len(self.calls)>2:raise AssertionError('A rewrite cannot supply missing personal facts')
                if 'Independently review' in task:
                    return {'supported':False,'issues':['Personal motivation missing'],'missing_facts':['Reason for choosing this company']}
                return super().generate(task,data,schema)
        model=MissingAtReview();before=copy.deepcopy(self.profile)
        drafter=AnswerDrafter(self.profile,job('https://example.test/job'),model,Path(self.temp.name),'fixture')
        for _ in range(3):
            plan=drafter.extend(plan_fields([self.field],self.profile,'fixture'))
            self.assertEqual(plan['fields'],[])
            self.assertIn('Reason for choosing this company',plan['unresolved'][0]['reason'])
        self.assertEqual(len(model.calls),2);self.assertEqual(self.profile,before)
        self.assertTrue(next(iter(drafter.records.values()))['needs_candidate_input'])

    def test_correctable_wording_still_gets_a_bounded_repair(self):
        class Wording(FixtureModel):
            def __init__(self):self.calls=0;self.reviews=0
            def generate(self,task,data,schema):
                self.calls+=1
                if 'Independently review' in task:
                    self.reviews+=1
                    if self.reviews==1:return {'supported':False,'issues':['Rewrite for directness'],'missing_facts':[]}
                return super().generate(task,data,schema)
        model=Wording();plan=self.resolve(model)
        self.assertEqual(len(plan['fields']),1);self.assertEqual(model.calls,4)

    def test_commitments_and_choices_never_invoke_drafting(self):
        class NoModel:
            def generate(self,*args): raise AssertionError('Must require saved explicit answer')
        for field in [
            {**self.field,'label':'Describe when you can start and your availability'},
            {**self.field,'label':'Why do you agree to this policy?'},
            {**self.field,'label':'Describe your salary expectations'},
            {**self.field,'type':'radio','options':['Yes','No']},
        ]:
            self.assertEqual(self.resolve(NoModel(),field)['fields'],[])

    def test_character_limit_is_enforced(self):
        self.assertEqual(self.resolve(FixtureModel(),{**self.field,'max_length':20})['fields'],[])

    def test_message_question_and_opaque_id_are_not_age_questions(self):
        field={**self.field,'label':'Describe your opening message and relevant experience',
            'name':'d9cf43a5-c9bd-4518-8dc2-3f52408962dd'}
        self.assertEqual(len(self.resolve(FixtureModel(),field)['fields']),1)
        class NoModel:
            def generate(self,*args):raise AssertionError('Age and pay still require explicit answers')
        for label in ['Describe your age','Are you 18 years old? Describe your eligibility.', 'Describe your pay expectations']:
            self.assertEqual(self.resolve(NoModel(),{**self.field,'label':label})['fields'],[])
