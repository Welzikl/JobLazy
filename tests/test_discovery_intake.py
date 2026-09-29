import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from joblazy.common import read_json
from joblazy.pipeline import ingest_discovery_result
from joblazy.store import Store
from .support import job


class DiscoveryIntakeTests(unittest.TestCase):
    def test_sparse_refresh_preserves_description_decision_and_its_provenance(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            old={**job('https://example.test/sparse'),'description_source':'https://example.test/full',
                'description_method':'JobPosting structured data','observed_at':'2026-09-01T00:00:00Z'}
            key=store.ingest(old);store.transition(key,'not_selected',{'score':20})
            store.record_choice(key,'pass','Fictional user decision')
            result_before=store.get(key)['result']
            sparse={**job(old['url']),'title':old['title']+'  ','description':'','observed_at':'2026-09-14T00:00:00Z'}
            ingest_discovery_result({'jobs':[sparse],'errors':[]},store)
            current=store.get(key)
            self.assertEqual(current['data']['description'],old['description'])
            self.assertEqual(current['data']['description_source'],old['description_source'])
            self.assertEqual(current['data']['description_retained_from']['observed_at'],old['observed_at'])
            self.assertEqual(current['status'],'not_selected');self.assertEqual(current['result'],result_before)
            self.assertTrue(store.choice(key)['current'])
            ingest_discovery_result({'jobs':[{**sparse,'observed_at':'2026-09-15T00:00:00Z'}],'errors':[]},store)
            self.assertEqual(store.get(key)['data']['description_retained_from']['observed_at'],old['observed_at'])

    def test_changed_location_retains_old_text_but_requires_a_fresh_description(self):
        from joblazy.materials import rank
        from joblazy.common import NeedsInput
        from .support import example_profile
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            old=job('https://example.test/moved');key=store.ingest(old);store.transition(key,'ranked')
            ingest_discovery_result({'jobs':[{**old,'location':'New York, USA','description':''}],'errors':[]},store)
            current=store.get(key)
            self.assertEqual(current['data']['description'],old['description'])
            self.assertTrue(current['data']['description_refresh_required']);self.assertEqual(current['status'],'discovered')
            with self.assertRaises(NeedsInput):rank(current['data'],example_profile(),None)
            # Another sparse scan cannot clear the unresolved refresh requirement.
            ingest_discovery_result({'jobs':[{**old,'location':'New York, USA','description':''}],'errors':[]},store)
            self.assertTrue(store.get(key)['data']['description_refresh_required'])
            fresh={**old,'location':'New York, USA','description':'New complete posting text.'}
            store.ingest(fresh)
            self.assertEqual(store.get(key)['data']['description'],fresh['description'])
            self.assertNotIn('description_refresh_required',store.get(key)['data'])

    def test_first_intake_records_source_so_exact_replay_preserves_rows_and_events(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            posting=job('https://example.test/role')
            payload={'jobs':[posting],'errors':[]}
            ingest_discovery_result(payload,store)
            before=store.list();events=list(store.db.execute('SELECT * FROM events'))
            self.assertEqual(before[0]['data']['discovery_source_urls'],[posting['url']])
            result=ingest_discovery_result(payload,store)
            self.assertEqual(result['new_unique_jobs'],0)
            self.assertEqual(store.list(),before)
            self.assertEqual(list(store.db.execute('SELECT * FROM events')),events)

    def test_uk_codes_and_east_london_reach_intake_without_foreign_namesakes(self):
        labels=['East London, UK','London, GBR','GB-London','London, U.K.',
            'East London, ZA','London, CAN','London, US','East London','London · GBR']
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            payload={'jobs':[{**job(f'https://example.test/role/{i}'),'location':label} for i,label in enumerate(labels)],'errors':[]}
            result=ingest_discovery_result(payload,store,Path(temp)/'scan.json',['london_uk_explicit'])
            self.assertEqual({r['data']['location'] for r in store.list()},set(labels[:4]))
            self.assertEqual(result['new_unique_jobs'],4)
            self.assertEqual(result['excluded_by_location'],{'other_london':3,'london_country_unverified':2})
            self.assertEqual(len(read_json(Path(temp)/'scan.json')['jobs']),len(labels))
            repeated=ingest_discovery_result(payload,store,None,['london_uk_explicit'])
            self.assertEqual(repeated['new_unique_jobs'],0)

    def test_amazon_locale_slug_and_account_routes_share_only_exact_requisition_ids(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            old=job('https://amazon.jobs/en-gb/jobs/123/old-title');key=store.ingest(old)
            payload={'jobs':[job('https://www.amazon.jobs/en/jobs/123/new-title'),
                job('https://account.amazon.jobs/jobs/123/apply'),job('https://www.amazon.jobs/en/jobs/456/new-title'),
                job('https://unrelated.example.test/en/jobs/123/new-title')],'errors':[]}
            report=ingest_discovery_result(payload,store)
            self.assertEqual(report['new_unique_jobs'],2);self.assertEqual(len(store.list()),3)
            self.assertEqual(len(report['exact_route_joins']),2)
            self.assertEqual(store.get(key)['data']['url'],old['url'])

    def test_observed_employer_route_joins_without_changing_manual_handoff(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            direct='https://job-boards.greenhouse.io/fictional/jobs/123'
            old={**job('https://feed.example.test/role'),'application_url':'https://boards.greenhouse.io/fictional/jobs/123'}
            key=store.ingest(old);store.transition(key,'manual_review',{'reason':'Operator owns the form'})
            before=store.get(key);entry={'name':'Fictional','provider':'greenhouse'}
            payload={'jobs':[job(direct)],'errors':[],'source_runs':[{'entry':entry,'status':'completed','urls':[direct],'finished_at':'2026-09-12T12:00:00Z'}]}
            result=ingest_discovery_result(payload,store,Path(temp)/'scan.json',['london_country_unverified'])
            self.assertEqual(result['new_unique_jobs'],0);self.assertEqual(result['discovered'],1)
            self.assertEqual(result['exact_route_joins'][0]['id'],key)
            self.assertEqual(store.get(key),before);self.assertEqual(len(store.list()),1)
            source=next(iter(read_json(Path(temp)/'source-registry.json')['sources'].values()))
            self.assertEqual(source['last_retained_job_ids'],[key]);self.assertEqual(source['new_unique_jobs_seen'],0)

    def test_filtered_intake_preserves_full_observation_and_keeps_ambiguous_duplicates_separate(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            uuid='00000000-0000-0000-0000-000000000001';direct='https://jobs.ashbyhq.com/fictional/'+uuid
            a=store.ingest(job(direct));b=store.ingest(job(direct+'/application'))
            before=store.list()
            payload={'jobs':[job(direct),{**job('https://other.example.test/us'),'location':'US-Remote'},
                {**job('https://other.example.test/canada'),'location':'London, Ontario, Canada'},
                {**job('https://other.example.test/uk'),'location':'London, England, United Kingdom'}],'errors':[]}
            result=ingest_discovery_result(payload,store,Path(temp)/'scan.json',['london_uk_explicit','london_country_unverified','uk_remote_candidate'])
            self.assertEqual(result['fetched_records'],4);self.assertEqual(result['new_unique_jobs'],1)
            self.assertEqual(sum(result['excluded_by_location'].values()),2)
            self.assertEqual(set(result['ambiguous_route_matches'][0]['existing_ids']),{a,b})
            self.assertEqual(store.get(a),before[0]);self.assertEqual(store.get(b),before[1])
            self.assertEqual(len(read_json(Path(temp)/'scan.json')['jobs']),4)

    def test_matching_titles_are_not_identity_and_mutable_exact_routes_keep_provenance(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            base='https://jobs.ashbyhq.com/fictional/00000000-0000-0000-0000-000000000002'
            key=store.ingest(job(base+'/application'))
            result=ingest_discovery_result({'jobs':[job(base),job('https://different.example.test/role')],'errors':[]},store)
            self.assertEqual(result['new_unique_jobs'],1);self.assertEqual(len(store.list()),2)
            saved=store.get(key)['data'];self.assertEqual(saved['url'],base+'/application')
            self.assertEqual(set(saved['discovery_source_urls']),{base,base+'/application'})


if __name__=='__main__':unittest.main()
