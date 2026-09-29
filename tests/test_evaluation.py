import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from joblazy.common import read_json,write_json
from joblazy.evaluation import evaluate,evaluate_files
from joblazy.store import choice_job_hash

def case(key,*,worthwhile=None,split='development'):
    posting={'url':'https://example.test/jobs/'+key,'company':'Fictional '+key,'title':'Operations Associate',
        'description':'Coordinate operational projects for '+key,'location':'London, UK'}
    result={'id':key,'job':posting,'split':split,'category':'adjacent'}
    if worthwhile is not None:
        result['judgment']={'worthwhile':worthwhile,'job_hash':choice_job_hash(posting),
            'source':{'kind':'user','quote':'Fictional test judgment','recorded_at':'2026-01-01','basis':'fixture'}}
    return result

def prediction(c,score=85):
    return {'id':c['id'],'job_hash':choice_job_hash(c['job']),'profile_hash':'fictional-profile',
        'assessment':{'score':score,'eligible':True,'fit_category':'worthwhile_stretch','assessment_version':5}}

def report(cases,predictions,**options):
    return evaluate({'version':1,'cases':cases},{'version':1,'name':'fixture','predictions':predictions},**options)

class EvaluationTests(unittest.TestCase):
    def test_unlabeled_recommendations_do_not_become_false_or_perfect_precision(self):
        a=case('a',worthwhile=True);b=case('b')
        r=report([a,b],[prediction(a),prediction(b)])['splits']['development']
        self.assertIsNone(r['precision_at_available_top_k']);self.assertIsNone(r['observed_80_percent'])
        self.assertEqual(r['top_label_coverage'],0.5);self.assertEqual(r['precision_bounds_from_missing_labels'],[0.5,1])

    def test_cutoff_comparison_finds_missed_interest_without_changing_score(self):
        a=case('a',worthwhile=True);b=case('b',worthwhile=False);p=[prediction(a,65),prediction(b,80)]
        high=report([a,b],p)['splits']['development']
        self.assertEqual(high['worthwhile_not_recommended_ids'],['a']);self.assertEqual(high['precision_at_available_top_k'],0)
        low=report([a,b],p,minimum_score=60)['splits']['development']
        self.assertEqual(low['worthwhile_not_recommended_ids'],[]);self.assertEqual(low['precision_at_available_top_k'],0.5)
        self.assertEqual(p[0]['assessment']['score'],65)

    def test_independent_constraint_detects_high_scoring_policy_violation(self):
        c=case('a',worthwhile=True);c['job']['description']+=' Requires 6 years of experience.'
        c['judgment']['job_hash']=choice_job_hash(c['job'])
        c['known_block']={'policy_reason':'Fictional user ceiling is five required years',
            'source':{'kind':'reviewed_posting','quote':'Requires 6 years of experience.'}}
        r=report([c],[prediction(c,99)])['splits']['development']
        self.assertEqual(r['known_block_violation_ids'],['a'])
        c['known_block']['source']['quote']='Invented quote'
        with self.assertRaises(ValueError):report([c],[prediction(c)])

    def test_splits_stay_separate_and_equivalent_application_routes_cannot_leak(self):
        a=case('a',worthwhile=True);b=case('b',worthwhile=False,split='holdout')
        r=report([a,b],[prediction(a),prediction(b)])['splits']
        self.assertEqual(r['development']['precision_at_available_top_k'],1)
        self.assertEqual(r['holdout']['precision_at_available_top_k'],0)
        a['job']['url']='https://jobs.ashbyhq.com/example/00000000-0000-0000-0000-000000000001'
        b['job']['url']=a['job']['url']+'/application'
        with self.assertRaises(ValueError):report([a,b],[])

    def test_stale_labels_and_stale_predictions_are_reported_not_reused(self):
        c=case('a',worthwhile=True);p=prediction(c);c['job']['description']+=' Changed responsibilities.'
        r=report([c],[p]);split=r['splits']['development']
        self.assertEqual(split['stale_judgment_ids'],['a']);self.assertEqual(split['missing_assessment_ids'],['a'])
        self.assertEqual(len(r['prediction_errors']),1)
        p=prediction(c);split=report([c],[p])['splits']['development']
        self.assertEqual(split['top_judged'],0);self.assertIsNone(split['precision_at_available_top_k'])

    def test_model_generated_judgments_are_rejected(self):
        c=case('a',worthwhile=True);c['judgment']['source']['kind']='model'
        with self.assertRaises(ValueError):report([c],[prediction(c)])

    def test_cli_does_not_open_database_or_overwrite_inputs(self):
        c=case('a',worthwhile=True)
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);dataset=base/'cases.json';predictions=base/'run.json';output=base/'report.json'
            write_json(dataset,{'version':1,'cases':[c]});write_json(predictions,{'version':1,'predictions':[prediction(c)]})
            before=dataset.read_bytes()
            subprocess.run([sys.executable,'-m','joblazy','--data',str(base/'unused-data'),'evaluate',str(dataset),
                '--predictions',str(predictions),'--output',str(output)],capture_output=True,check=True,timeout=15)
            self.assertFalse((base/'unused-data').exists());self.assertEqual(dataset.read_bytes(),before)
            self.assertEqual(read_json(output)['splits']['development']['top_worthwhile'],1)
            with self.assertRaises(ValueError):evaluate_files(dataset,predictions,dataset)
