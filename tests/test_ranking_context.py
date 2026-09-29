import copy
import json
import tempfile
import unittest
from joblazy.materials import ranking_input,rank,source_facts
from joblazy.model import CodexModel
from .support import example_profile,job,FixtureModel


def expand(value,facts):
    if isinstance(value,dict):
        if set(value)=={'candidate_fact_ref'}:return facts[value['candidate_fact_ref']]
        return {key:expand(item,facts) for key,item in value.items()}
    if isinstance(value,list):return [expand(item,facts) for item in value]
    return value


class RankingContextTests(unittest.TestCase):
    def test_employment_context_is_citable_with_its_own_duties_and_exact_dates(self):
        profile=example_profile()
        profile['resume']['experience'][0].update(dates='January 2021 – December 2022',
            employment_type='Part-time internship',hours_per_week=12)
        before=copy.deepcopy(profile);posting=job('https://example.test/duration')
        posting['description']+=' Four years of relevant operations experience required.'
        class ContextModel(FixtureModel):
            def generate(worker,task,data,schema):
                context=json.loads(data['candidate_facts']['employment.0'])
                self.assertEqual(context,{k:v for k,v in before['resume']['experience'][0].items() if k!='bullets'})
                result=super(ContextModel,worker).generate(task,data,schema)
                result['requirements'].append({'requirement':'Four years of relevant operations experience',
                    'job_quote':'Four years of relevant operations experience required.',
                    'kind':'required_experience','status':'unverified','candidate_source_ids':['employment.0','experience.0.0'],
                    'explanation':'The saved part-time internship dates do not establish four years of relevant full-time work.'})
                return result
        result=rank(posting,profile,ContextModel())
        self.assertEqual(result['candidate_facts']['employment.0'],json.dumps({k:v for k,v in before['resume']['experience'][0].items() if k!='bullets'},ensure_ascii=False))
        self.assertEqual(profile,before)
        self.assertEqual(result['requirements'][-1]['status'],'unverified')
        self.assertNotIn('employment.0',source_facts(profile))

    def test_missing_and_year_only_employment_dates_are_not_completed_or_invented(self):
        profile=example_profile();profile['resume']['experience'][0].pop('dates',None)
        profile['resume']['experience'].append({'company':'Freelance','role':'Operations projects',
            'dates':'Clients A and B | 2019–2023','work_pattern':'Intermittent projects; hours unknown',
            'bullets':['Documented fictional project work.']})
        profile['generated_cv']={'experience':[{'dates':'January 2019 – December 2023','years':5}]}
        class ContextModel(FixtureModel):
            def generate(worker,task,data,schema):
                self.assertNotIn('dates',json.loads(data['candidate_facts']['employment.0']))
                context=json.loads(data['candidate_facts']['employment.1'])
                self.assertEqual(context['dates'],'Clients A and B | 2019–2023')
                self.assertEqual(context['work_pattern'],'Intermittent projects; hours unknown')
                self.assertNotIn('years',context)
                return super(ContextModel,worker).generate(task,data,schema)
        rank(job('https://example.test/dates'),profile,ContextModel())

    def test_identical_text_under_different_employers_keeps_its_original_context(self):
        profile=example_profile();text='Coordinated partner onboarding and weekly reporting within the documented scope of this role.'
        profile['resume']['experience']=[{'company':company,'role':'Associate','bullets':[text]} for company in ('Company A','Company B')]
        data=ranking_input(job('https://example.test/role'),profile,source_facts(profile))
        self.assertEqual(data['resume']['experience'],profile['resume']['experience'])

    def test_location_evidence_is_literal_and_attributed_without_loosening_other_quotes(self):
        from joblazy.common import NeedsInput
        posting={**job('https://example.test/location'),'location':'London, England, United Kingdom'}
        class LocationModel(FixtureModel):
            def generate(self,task,data,schema):
                result=super().generate(task,data,schema)
                result['requirements'].append({'requirement':'Location','job_quote':'London, England, United Kingdom',
                    'kind':'hard_constraint','status':'unverified','candidate_source_ids':[],
                    'explanation':'Exact posting location, practical candidate availability unconfirmed.'})
                return result
        result=rank(posting,example_profile(),LocationModel())
        self.assertEqual(result['requirements'][-1]['job_quote_source'],'location')
        self.assertEqual(result['requirements'][0]['job_quote_source'],'description')
        self.assertEqual(result['eligibility_status'],'uncertain')
        # A claimed country cannot be borrowed from the candidate profile.
        with self.assertRaises(NeedsInput):rank({**posting,'location':'London'},example_profile(),LocationModel())

    def test_every_profile_value_is_recoverable_and_only_observation_metadata_is_removed(self):
        profile=example_profile()
        profile['targeting']={'career_preferences':'Consider transferable operations experience and keep every saved restriction. '*4,
            'config':{'location':{'visa_status':'Fictional authorization statement','city':'London'}}}
        profile['resume']['experience'][0]['dates']='2025-2026'
        profile['resume']['experience'][0]['extra_context']={'confirmed':False,'uncertainty':'Award status not established'}
        profile['resume']['projects']=[{'name':'Fictional proposal','description':'This was a documented proposal, not an implemented production system. '*3,
            'bullets':['Research-only work; no shipped product or production ownership is established.']}]
        posting={**job('https://example.test/role'),'observed_at':'2026-09-01',
            'salary':{'min':40000,'currency':'GBP'},'employment_type':'Contract','new_condition':'French is required',
            'description_source':'https://example.test/source','description_method':'Feed','discovery_source_urls':['https://example.test/source']}
        before=copy.deepcopy((profile,posting));facts=source_facts(profile)
        facts['preference.career_rules']=profile['targeting']['career_preferences']
        data=ranking_input(posting,profile,facts)
        self.assertEqual(expand(data['resume'],facts),profile['resume'])
        self.assertEqual(expand(data['targeting'],facts),profile['targeting'])
        self.assertEqual(data['candidate_facts'],facts)
        self.assertEqual(data['job'],{k:v for k,v in posting.items() if k not in ('observed_at','description_source','description_method','discovery_source_urls')})
        self.assertEqual((profile,posting),before)
        original={'job':posting,'resume':profile['resume'],'targeting':profile['targeting'],'candidate_facts':facts}
        self.assertLess(len(json.dumps(data)),len(json.dumps(original)))

    def test_observation_only_refresh_reuses_real_model_cache_but_fact_and_job_changes_do_not(self):
        # Populate the actual cache path through generate(), with a fictional
        # transport. A metadata refresh must never request a second inference.
        import subprocess
        from pathlib import Path
        from unittest.mock import patch
        from joblazy.common import write_json
        calls=[]
        def transport(args,**kwargs):
            if args[1]=='login':return subprocess.CompletedProcess(args,0,'Logged in','')
            prompt=kwargs['input'];task=prompt.split('TASK: ',1)[1].split('\nINPUT JSON:',1)[0]
            data=json.loads(prompt.split('\nINPUT JSON:\n',1)[1]);calls.append(data)
            write_json(args[args.index('--output-last-message')+1],FixtureModel().generate(task,data,{}))
            return subprocess.CompletedProcess(args,0,'','')
        with tempfile.TemporaryDirectory() as temp,patch('joblazy.model.subprocess.run',side_effect=transport):
            profile=example_profile();posting=job('https://example.test/role');model=CodexModel(Path(temp),executable='fixture-codex')
            first=rank(posting,profile,model)
            refreshed={**posting,'observed_at':'2099-01-01','description_source':'https://example.test/new-source',
                'description_retained_from':{'observed_at':'2026-01-01'}}
            self.assertEqual(rank(refreshed,profile,model),first);self.assertEqual(len(calls),1)
            rank({**posting,'description':posting['description']+' Additional required experience.'},profile,model)
            changed=copy.deepcopy(profile);changed['resume']['experience'][0]['dates']='Changed dates'
            rank(posting,changed,model)
            self.assertEqual(len(calls),3)
            self.assertEqual(first['ranking_context_version'],3)
