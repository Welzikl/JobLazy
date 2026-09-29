import copy
import tempfile
import unittest
from pathlib import Path

from joblazy.common import DailyModelLimit, InvalidModelOutput, ModelUnavailable, read_json
from joblazy.materials import rank
from joblazy.shortlist_review import rank_batch
from .support import FixtureModel, example_profile, job


class BatchModel:
    def __init__(self, mutate=None):
        self.calls=[];self.mutate=mutate

    def generate(self,task,data,schema):
        self.calls.append(copy.deepcopy(data))
        payload=data.get('original_input',data)
        result={'results':[{'id':entry['id'],'assessment':FixtureModel().generate('Rank this',{}, {})}
                           for entry in payload['jobs']]}
        if self.mutate:self.mutate(result,len(self.calls))
        return result


class BatchRankingTests(unittest.TestCase):
    def setUp(self):
        self.profile=example_profile()
        self.rows=[{'id':key,'data':job('https://example.test/'+key)} for key in ('one','two')]

    def test_full_assessments_match_single_role_and_share_canonical_context(self):
        before=copy.deepcopy(self.rows);model=BatchModel()
        outcome=rank_batch(self.rows,self.profile,model)
        self.assertEqual(outcome['errors'],{});self.assertEqual(outcome['model_calls'],1)
        for row in self.rows:
            self.assertEqual(outcome['results'][row['id']],rank(row['data'],self.profile,FixtureModel()))
        payload=model.calls[0]
        self.assertIn('candidate_facts',payload);self.assertIn('employment_calendar',payload)
        self.assertTrue(all('resume' not in entry and 'candidate_facts' not in entry for entry in payload['jobs']))
        self.assertEqual([entry['job']['description'] for entry in payload['jobs']],
                         [row['data']['description'] for row in self.rows])
        self.assertEqual(self.rows,before)

    def test_reordered_response_uses_ids_and_preserves_hard_conflicts(self):
        def change(response,attempt):
            response['results'][1]['assessment']['requirements'][0].update(kind='hard_constraint',status='not_met')
            response['results'].reverse()
        outcome=rank_batch(self.rows,self.profile,BatchModel(change))
        self.assertEqual(outcome['results']['two']['eligibility_status'],'blocked')
        self.assertFalse(outcome['results']['two']['eligible'])
        self.assertTrue(outcome['results']['one']['eligible'])

    def test_correct_only_invalid_sibling_with_full_original_evidence(self):
        def change(response,attempt):
            if attempt==1:response['results'][1]['assessment']['evidence'][0]['quote']='Invented phrase'
        model=BatchModel(change)
        with tempfile.TemporaryDirectory() as tmp:
            outcome=rank_batch(self.rows,self.profile,model,directory=tmp)
            audit=read_json(Path(tmp)/'batch-ranking-validation.json')
        self.assertEqual(outcome['model_calls'],2);self.assertEqual(outcome['errors'],{})
        self.assertEqual(outcome['results']['one']['validation']['status'],'valid')
        self.assertEqual(outcome['results']['two']['validation']['status'],'corrected')
        self.assertEqual([row['id'] for row in model.calls[1]['original_input']['jobs']],['two'])
        self.assertIn('candidate_facts',model.calls[1]['original_input'])
        self.assertEqual(audit['attempts'][0]['rejected']['two']['response']['assessment']['evidence'][0]['quote'],'Invented phrase')

    def test_omitted_duplicate_and_unexpected_ids_reject_whole_envelope(self):
        def omitted(result):result['results'].pop()
        def duplicate(result):result['results'][1]['id']='one'
        def unexpected(result):result['results'][1]['id']='foreign'
        for mutation in (omitted,duplicate,unexpected):
            with self.subTest(mutation=mutation.__name__):
                model=BatchModel(lambda response,attempt:mutation(response))
                outcome=rank_batch(self.rows,self.profile,model)
                self.assertEqual(outcome['results'],{});self.assertEqual(set(outcome['errors']),{'one','two'})
                self.assertEqual(outcome['model_calls'],2)

    def test_cross_job_quotes_unknown_candidate_refs_and_weak_schema_fail(self):
        self.rows[0]['data']['description']+=' Exclusive statement for role one.'
        def cross_quote(assessment):assessment['evidence'][0]['quote']='Exclusive statement for role one.'
        def unknown_ref(assessment):assessment['requirements'][0]['candidate_source_ids']=['invented.99']
        def weak_schema(assessment):assessment.pop('dimensions')
        for mutation in (cross_quote,unknown_ref,weak_schema):
            with self.subTest(mutation=mutation.__name__):
                def change(response,attempt):
                    for entry in response['results']:
                        if entry['id']=='two':mutation(entry['assessment'])
                outcome=rank_batch(self.rows,self.profile,BatchModel(change))
                self.assertEqual(set(outcome['results']),{'one'});self.assertEqual(set(outcome['errors']),{'two'})

    def test_model_output_and_source_failures_share_one_correction(self):
        class Broken(BatchModel):
            def generate(self,task,data,schema):
                if not self.calls:
                    self.calls.append(data)
                    raise InvalidModelOutput('Malformed JSON','fictional-failure.json')
                result=super().generate(task,data,schema)
                result['results'][0]['assessment']['evidence'][0]['quote']='Invented phrase'
                return result
        model=Broken();outcome=rank_batch(self.rows,self.profile,model)
        self.assertEqual(len(model.calls),2);self.assertEqual(set(outcome['errors']),{'one'})
        self.assertEqual(set(outcome['results']),{'two'})

    def test_global_interruption_propagates_and_exposes_valid_siblings(self):
        for error_type in (ModelUnavailable,DailyModelLimit):
            class Interrupted(BatchModel):
                def generate(self,task,data,schema):
                    if self.calls:raise error_type('Fictional provider limit')
                    result=super().generate(task,data,schema)
                    result['results'][1]['assessment']['evidence'][0]['quote']='Invalid'
                    return result
            with self.assertRaises(error_type) as caught:rank_batch(self.rows,self.profile,Interrupted())
            self.assertEqual(set(caught.exception.batch_results),{'one'})
            self.assertEqual(caught.exception.batch_pending,['two'])

    def test_experience_policy_and_chronology_validators_remain_active(self):
        self.profile['targeting']={'config':{'target_roles':{'seniority':{
            'mode':'required_experience_range','maximum_required_years':5}}}}
        quote='6-11 years of experience'
        self.rows[0]['data']['description']+=' '+quote
        self.profile['resume']['experience'][0]['dates']='April 2021 – February 2023'
        def change(response,attempt):
            for entry in response['results']:
                assessment=entry['assessment']
                if entry['id']=='one':
                    assessment['requirements'].append({'requirement':'Experience','job_quote':quote,
                        'kind':'required_experience','status':'unverified','candidate_source_ids':[],
                        'explanation':'Required experience is not established.'})
                else:
                    assessment['dimensions']['cv_fit']['explanation']='The candidate has 28 months at Fictional Software Ltd.'
        outcome=rank_batch(self.rows,self.profile,BatchModel(change))
        self.assertFalse(outcome['results']['one']['eligible'])
        self.assertEqual(outcome['results']['one']['fit_category'],'poor_fit')
        self.assertIn('preference.experience_range',outcome['results']['one']['candidate_facts'])
        self.assertIn('two',outcome['errors'])

    def test_remote_scope_and_compacted_candidate_references_keep_full_sources(self):
        long_fact='Coordinated partner onboarding and weekly reporting for the documented fictional software partner programme.'
        self.profile['resume']['experience'][0]['bullets'][0]=long_fact
        self.rows[1]['data']['location']='United Kingdom (Remote)'
        model=BatchModel();outcome=rank_batch(self.rows,self.profile,model)
        payload=model.calls[0]
        self.assertEqual(payload['resume']['experience'][0]['bullets'][0],{'candidate_fact_ref':'experience.0.0'})
        self.assertEqual(payload['candidate_facts']['experience.0.0'],long_fact)
        self.assertEqual(outcome['results']['two']['candidate_facts']['experience.0.0'],long_fact)
        self.assertIn('remote_scope_version',outcome['results']['two'])
        self.assertNotIn('remote_scope_version',outcome['results']['one'])
        self.assertIn('For remote-location postings',payload['jobs'][1]['assessment_instructions'])

    def test_invalid_posting_never_enters_model_and_duplicate_input_never_runs(self):
        self.rows[1]['data']['description_refresh_required']=True
        model=BatchModel();outcome=rank_batch(self.rows,self.profile,model)
        self.assertEqual(set(outcome['errors']),{'two'})
        self.assertEqual([entry['id'] for entry in model.calls[0]['jobs']],['one'])
        model=BatchModel()
        with self.assertRaises(ValueError):rank_batch([self.rows[0],self.rows[0]],self.profile,model)
        self.assertEqual(model.calls,[])
        self.assertEqual(rank_batch([],self.profile,model),{'results':{},'errors':{},'model_calls':0})


if __name__=='__main__':unittest.main()
