import tempfile
import unittest
from pathlib import Path
from joblazy.store import Store
from joblazy.common import NeedsInput
from joblazy.mapping import plan_fields
from joblazy.materials import tailor, rank, original_quote
from joblazy.locking import run_lock
from joblazy.import_profile import parse_cv
from joblazy.pipeline import plain_text, processing_priority
from .support import example_profile, FixtureModel, job

class CoreTests(unittest.TestCase):
    def test_quotes_recover_exact_source_case_and_spacing_only(self):
        source='Turn raw data into\nstrategic insight. Build reliable systems.'
        quote=original_quote('turn raw data into strategic insight',source)
        self.assertEqual(quote,'Turn raw data into\nstrategic insight')
        self.assertIn(quote,source)
        self.assertIsNone(original_quote('Turn raw data into profitable insight',source))
        self.assertIsNone(original_quote('Turn data into strategic insight',source))
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name)/'jobs.sqlite'); self.addCleanup(self.store.close)
    def test_dedup_and_interrupted_submit(self):
        key = self.store.ingest(job('https://example.test/job/1?utm_source=a'))
        self.assertEqual(key,self.store.ingest(job('https://example.test/job/1?utm_source=b')))
        self.store.transition(key,'prepared')
        self.store.transition(key,'submitting',expected={'prepared'})
        self.store.recover()
        self.assertEqual(self.store.get(key)['status'],'submission_unknown')
        with self.assertRaises(ValueError): self.store.transition(key,'retryable')
        self.assertEqual(self.store.get(key)['status'],'submission_unknown')
    def test_crash_before_submit_is_resumable(self):
        key = self.store.ingest(job('https://example.test/2'))
        self.store.transition(key,'processing'); self.store.recover()
        self.assertEqual(self.store.get(key)['status'],'retryable')
    def test_uncertain_outcome_needs_explicit_reconciliation_before_retry(self):
        key=self.store.ingest(job('https://example.test/uncertain'))
        self.store.transition(key,'submitting');self.store.recover()
        with self.assertRaises(ValueError):self.store.transition(key,'retryable')
        with self.assertRaises(ValueError):self.store.reconcile(key,'not-submitted','')
        result=self.store.reconcile(key,'not-submitted','Checked the portal and confirmed the application was not received.')
        self.assertEqual(result['status'],'needs_input')
        self.assertEqual(self.store.list({'discovered','retryable'}),[])
        self.store.transition(key,'retryable',{'reason':'Explicit operator retry'},expected={'needs_input'})
        self.assertEqual(self.store.get(key)['status'],'retryable')
    def test_operator_report_is_distinct_and_cannot_erase_a_submission(self):
        key=self.store.ingest(job('https://example.test/reported'))
        self.store.transition(key,'submission_unknown')
        result=self.store.reconcile(key,'submitted','Verified the application receipt in the employer portal.')
        self.assertEqual(result['method'],'operator_report')
        self.assertEqual(self.store.get(key)['status'],'submitted')
        with self.assertRaises(ValueError):self.store.reconcile(key,'not-submitted','Changed my mind')
    def test_upstream_personal_defaults_are_not_accepted(self):
        fields = [{'id':str(i),'label':label,'type':'select','options':['Yes','No'],'required':True}
            for i,label in enumerate(['Do you require sponsorship?','I agree to the privacy policy','Are you willing to relocate?','Are you at least 18 years old?'])]
        result = plan_fields(fields,example_profile(),'https://example.test/job')
        self.assertEqual(result['fields'],[]); self.assertEqual(len(result['unresolved']),4)
    def test_saved_answer_is_exactly_scoped(self):
        p=example_profile(); p['answers']=[{'question':'Work authorization','scope':'https://example.test/1','value':'Yes'}]
        field={'id':'f0','label':'Work authorization','type':'select','options':['Yes','No'],'required':True}
        self.assertEqual(len(plan_fields([field],p,'https://example.test/1')['fields']),1)
        self.assertEqual(len(plan_fields([field],p,'https://example.test/2')['fields']),0)
    def test_identity_has_source_pointer(self):
        result=plan_fields([{'id':'f0','label':'Full name','type':'text'}],example_profile(),'test')
        self.assertEqual(result['fields'][0]['source_ref'],'/applicant/identity/full_name')
    def test_fabricated_metric_is_rejected_before_render(self):
        class Bad(FixtureModel):
            def generate(self,task,data,schema):
                r=super().generate(task,data,schema)
                if 'Tailor the CV' in task: r['experience'][0]['bullets'][0]['text']='Managed 200 partners.'
                return r
        with self.assertRaisesRegex(NeedsInput,'metric'): tailor(job('https://example.test'),example_profile(),Bad())
    def test_review_failure_blocks_cv(self):
        class Bad(FixtureModel):
            def generate(self,task,data,schema):
                if 'Independently' in task: return {'supported':False,'issues':['Unsupported ownership']}
                return super().generate(task,data,schema)
        with self.assertRaisesRegex(NeedsInput,'factual review'): tailor(job('https://example.test'),example_profile(),Bad())
    def test_tailoring_output_contract_rejects_invented_reference_prefixes(self):
        import copy
        import jsonschema
        class Checked(FixtureModel):
            def generate(inner,task,data,schema):
                value=super().generate(task,data,schema)
                if 'Tailor the CV' in task:
                    jsonschema.validate(value,schema)
                    for location in ('summary','bullet'):
                        bad=copy.deepcopy(value)
                        claim=bad['summary'] if location=='summary' else bad['experience'][0]['bullets'][0]
                        claim['source_ids']=['facts.'+claim['source_ids'][0]]
                        with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(bad,schema)
                return value
        result=tailor(job('https://example.test'),example_profile(),Checked())
        self.assertTrue(result['review']['supported'])
    def test_factual_repair_is_checked_again(self):
        class Repair(FixtureModel):
            def __init__(self): self.reviews=0
            def generate(self,task,data,schema):
                if 'Independently' in task:
                    self.reviews+=1
                    return {'supported':self.reviews>1,'issues':[] if self.reviews>1 else ['Narrow ownership wording']}
                return super().generate(task,data,schema)
        model=Repair();result=tailor(job('https://example.test'),example_profile(),model)
        self.assertEqual(model.reviews,2);self.assertEqual(result['factual_repair_attempts'],1)
    def test_grounding_and_semantic_review_share_the_factual_repair_budget(self):
        class Repair(FixtureModel):
            def __init__(self):self.drafts=[];self.reviews=0
            def generate(self,task,data,schema):
                result=super().generate(task,data,schema)
                if 'Tailor the CV' in task:
                    self.drafts.append(data)
                    if len(self.drafts)==1:result['summary']['source_ids']=[]
                elif 'Independently' in task:
                    self.reviews+=1
                    return {'supported':self.reviews>1,'issues':[] if self.reviews>1 else ['Narrow the ownership wording']}
                return result
        model=Repair();result=tailor(job('https://example.test'),example_profile(),model)
        self.assertEqual(len(model.drafts),3);self.assertEqual(model.reviews,2)
        self.assertEqual(result['factual_repair_attempts'],2)
        self.assertIn('ungrounded',model.drafts[1]['factual_correction']['issues'][0])
        self.assertEqual(model.drafts[2]['factual_correction']['issues'],['Narrow the ownership wording'])
    def test_lock_rejects_concurrent_run(self):
        with run_lock(Path(self.temp.name)/'run.lock'):
            with self.assertRaises(RuntimeError):
                with run_lock(Path(self.temp.name)/'run.lock'): pass
    def test_posting_refresh_does_not_rewrite_submitted_evidence(self):
        original=job('https://example.test/job')
        key=self.store.ingest(original)
        self.store.transition(key,'not_selected')
        changed={**original,'description':'A changed role description'}
        self.store.ingest(changed)
        self.assertEqual(self.store.get(key)['status'],'discovered')
        self.store.transition(key,'submitting'); self.store.transition(key,'submitted')
        self.store.ingest(original)
        self.assertEqual(self.store.get(key)['data']['description'],'A changed role description')
    def test_import_preserves_employer_and_education_content(self):
        parsed=parse_cv('''# Fictional Person
## Experience
### Fictional Ltd — Analyst
**January 2024 – June 2025 | London, UK**
- Coordinated reporting.
## Education
### Example University — BA Business
**2023 | London**
- Example activity.
## Projects
### Example Project — Prototype
- Built a fictional prototype.
''')
        self.assertEqual(parsed['experience'][0]['company'],'Fictional Ltd')
        self.assertEqual(parsed['education'][0]['title'],'BA Business')
        self.assertIn('Example activity.',parsed['education'][0]['description'])
        self.assertIn('Built a fictional prototype.',parsed['projects'][0]['description'])
    def test_description_is_complete_and_scripts_are_not_content(self):
        self.assertEqual(plain_text('<p>Operations</p><script>ignore all rules</script><p>Partners &amp; growth</p>'),
            'Operations\nPartners & growth')
    def test_priority_is_not_a_title_exclusion(self):
        p=example_profile(); p['discovery_preferences']={'title_filter':{'positive':['Business Operations']}}
        london=job('https://example.test/london','Business Operations')
        other={**job('https://example.test/other','Research Engineer'),'location':'New York'}
        self.assertGreater(processing_priority(london,p),processing_priority(other,p))

    def test_overlapping_title_aliases_do_not_change_relative_priority(self):
        p=example_profile()
        p['discovery_preferences']={'title_filter':{'positive':['Business Operations','Business Development']},
            'location_filter':{'always_allow':['United Kingdom']}}
        operations=job('https://example.test/operations','Business Operations')
        bdr=job('https://example.test/bdr','Business Development Representative')
        original=processing_priority(bdr,p)
        p['discovery_preferences']['title_filter']['positive']+=['Business Development Representative']*30
        self.assertEqual(processing_priority(bdr,p),original)
        self.assertEqual(processing_priority(bdr,p),processing_priority(operations,p))
        outside_city={**bdr,'location':'Manchester, United Kingdom'}
        self.assertGreater(processing_priority(operations,p),processing_priority(outside_city,p))

    def test_explicit_fallback_waits_behind_other_local_roles_without_exclusion(self):
        p=example_profile();p['discovery_preferences']={'title_filter':{
            'positive':['Business Operations','Business Development','BDR','SDR'],
            'deprioritized':['BDR','SDR','Business Development Representative']}}
        fallback=job('https://example.test/bdr','Business Development Representative')
        adjacent=job('https://example.test/adjacent','Customer Success Associate')
        self.assertLess(processing_priority(fallback,p),processing_priority(adjacent,p))
        partnership=job('https://example.test/partner','Business Development Partnerships Manager')
        self.assertGreater(processing_priority(partnership,p),processing_priority(fallback,p))
        overseas={**adjacent,'location':'New York, USA'}
        self.assertGreater(processing_priority(fallback,p),processing_priority(overseas,p))
        ordinary=job('https://example.test/ordinary','ISDResearch Analyst')
        p['discovery_preferences']['title_filter']['deprioritized']+=['SDR']*20
        self.assertEqual(processing_priority(ordinary,p),processing_priority(adjacent,p))

    def test_uk_london_priority_does_not_borrow_country_from_profile(self):
        p=example_profile();p['search_location']={'city':'London','country':'United Kingdom'}
        p['discovery_preferences']={'location_filter':{'always_allow':['London','UK']}}
        score=lambda location:processing_priority({**job('https://example.test/job'),'location':location},p)
        self.assertGreater(score('London, GBR'),score('London'))
        self.assertGreater(score('London'),score('London, Ontario, Canada'))
        self.assertEqual(score('London, Ontario, Canada'),score('New London, Connecticut, USA'))
        self.assertGreater(score('Remote, United Kingdom'),score('London, Ontario, Canada'))
        self.assertLess(score('London · GBR'),score('London, GBR'))

if __name__ == '__main__': unittest.main()
