import copy
import tempfile
import unittest
from pathlib import Path

from joblazy.common import DailyModelLimit, ModelUnavailable, read_json
from joblazy.search_shortlist import review_shortlist
from .support import example_profile, job


def _payload(data):
    return data.get('original_input',data)


class ShortlistModel:
    def __init__(self, mutate=None):
        self.calls=[];self.mutate=mutate

    def generate(self, task, data, schema):
        self.calls.append({'task':task,'data':copy.deepcopy(data),'schema':copy.deepcopy(schema)})
        jobs=_payload(data)['jobs']
        response={'results':[{
            'id':entry['id'],'recommend':True,
            'reason':'The role has relevant duties supported by documented experience.',
            'job_quotes':['partner onboarding'],
            'candidate_source_ids':['experience.0.0'],'caveats':['Company details remain unverified.']
        } for entry in jobs]}
        if self.mutate:self.mutate(response,len(self.calls))
        return response


class SearchShortlistTests(unittest.TestCase):
    def setUp(self):
        self.profile=example_profile()
        self.rows=[{'id':key,'data':job('https://example.test/'+key)} for key in ('one','two')]

    def test_shared_canonical_context_and_full_job_descriptions(self):
        before=copy.deepcopy(self.rows);model=ShortlistModel()
        result=review_shortlist(self.rows,self.profile,model)
        self.assertEqual(result['errors'],{});self.assertEqual(result['model_calls'],1)
        payload=model.calls[0]['data']
        self.assertIn('candidate_facts',payload);self.assertIn('employment_calendar',payload)
        self.assertEqual(len(payload['jobs']),2)
        self.assertEqual([entry['job']['description'] for entry in payload['jobs']],
                         [row['data']['description'] for row in self.rows])
        self.assertTrue(all('assessment' not in entry for entry in payload['jobs']))
        self.assertTrue(all(result['results'][key]['assessment_stage']=='search_shortlist'
                            for key in ('one','two')))
        self.assertEqual(self.rows,before)

    def test_malicious_identity_envelopes_get_one_correction_then_error(self):
        for alter in ('omitted','duplicate','foreign'):
            with self.subTest(alter=alter):
                def mutate(response,attempt):
                    if attempt==1:
                        if alter=='omitted':response['results'].pop()
                        elif alter=='duplicate':response['results'][1]['id']='one'
                        else:response['results'][1]['id']='foreign'
                model=ShortlistModel(mutate)
                result=review_shortlist(self.rows,self.profile,model)
                self.assertEqual(result['model_calls'],2)
                self.assertEqual(set(result['results']),{'one','two'})
                self.assertEqual(result['errors'],{})

    def test_invalid_quote_and_candidate_reference_only_correct_bad_sibling(self):
        def mutate(response,attempt):
            if attempt==1:
                response['results'][1]['job_quotes']=['phrase from another role']
                response['results'][1]['candidate_source_ids']=['invented.source']
        model=ShortlistModel(mutate)
        with tempfile.TemporaryDirectory() as tmp:
            result=review_shortlist(self.rows,self.profile,model,directory=tmp)
            audit=read_json(Path(tmp)/'shortlist-validation.json')
        self.assertEqual(result['model_calls'],2)
        self.assertEqual(set(result['results']),{'one','two'})
        self.assertEqual(result['results']['two']['job_quotes'],['partner onboarding'])
        self.assertEqual(model.calls[1]['data']['original_input']['jobs'][0]['id'],'two')
        self.assertEqual(audit['profile_hash'],result['results']['one']['assessment_profile_hash'])

    def test_cross_job_quote_is_rejected_even_if_valid_for_sibling(self):
        self.rows[0]['data']['description']+=' Exclusive phrase for first role.'
        def mutate(response,attempt):
            if attempt==1:response['results'][1]['job_quotes']=['Exclusive phrase for first role.']
        model=ShortlistModel(mutate)
        result=review_shortlist(self.rows,self.profile,model)
        self.assertEqual(set(result['results']),{'one','two'})
        self.assertEqual(_payload(model.calls[1]['data'])['jobs'][0]['id'],'two')
        self.assertEqual(result['errors'],{})

    def test_positive_recommendation_needs_posting_quote_and_nonpreference_fact(self):
        def mutate(response,attempt):
            response['results'][0]['candidate_source_ids']=['preference.targeting']
        result=review_shortlist(self.rows[:1],self.profile,ShortlistModel(mutate))
        self.assertFalse(result['results'])
        self.assertIn('one',result['errors'])

    def test_interrupt_during_correction_preserves_valid_sibling(self):
        class Interrupted(ShortlistModel):
            def generate(self,task,data,schema):
                if self.calls:
                    raise ModelUnavailable('Fixture provider interruption')
                response=super().generate(task,data,schema)
                response['results'][1]['job_quotes']=['not present']
                return response
        with self.assertRaises(ModelUnavailable) as caught:
            review_shortlist(self.rows,self.profile,Interrupted())
        self.assertEqual(set(caught.exception.batch_results),{'one'})
        self.assertEqual(caught.exception.batch_pending,['two'])

    def test_duplicate_or_invalid_input_ids_never_call_model(self):
        model=ShortlistModel()
        with self.assertRaises(ValueError):
            review_shortlist([self.rows[0],self.rows[0]],self.profile,model)
        with self.assertRaises(ValueError):
            review_shortlist([{'id':' ','data':self.rows[0]['data']}],self.profile,model)
        self.assertEqual(model.calls,[])

    def test_empty_input_is_a_noop(self):
        model=ShortlistModel()
        self.assertEqual(review_shortlist([],self.profile,model),
                         {'results':{},'errors':{},'model_calls':0})
        self.assertEqual(model.calls,[])


if __name__=='__main__':unittest.main()

