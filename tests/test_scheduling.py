import tempfile
import unittest
from contextlib import closing
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from joblazy.pipeline import run_queue,schedule_candidates,processing_priority
from joblazy.store import Store
from .support import example_profile,job,FixtureModel


class SchedulingTests(unittest.TestCase):
    def test_invalid_or_ambiguous_rotation_groups_are_rejected(self):
        for groups in ([],{'Alpha':[]},{'Alpha':['']},{'Alpha':[42]},
                {'Alpha':['One'],'Beta':[' ONE ']},{'Alpha':['One'],' alpha ':['Two']}):
            with self.subTest(groups=groups):
                profile=example_profile();profile['discovery_preferences']={'employer_rotation_groups':groups}
                with self.assertRaises(ValueError):schedule_candidates([],profile)

    def test_explicit_employer_groups_rotate_across_a_connected_batch(self):
        profile=example_profile();profile['discovery_preferences']={
            'employer_rotation_groups':{'Alpha family':['Alpha Europe','Alpha UK']}}
        seen=[]
        class Model(FixtureModel):
            def generate(self,task,data,schema):
                seen.append(data['job']['url']);return super().generate(task,data,schema)
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            keys=[]
            for name,company in [('eu','Alpha Europe'),('uk',' ALPHA UK '),('beta','Beta'),('vendor','Alpha Vendors')]:
                keys.append(store.ingest({**job('https://example.test/'+name),'company':company}))
            rows=store.list();before={r['id']:r['data'].copy() for r in rows}
            # Feed order is explicit here; database timestamps are not relevant.
            rows=[store.get(key) for key in keys]
            ordered=schedule_candidates(rows,profile)
            self.assertEqual([r['id'] for r in ordered],[keys[0],keys[2],keys[3],keys[1]])
            priority=schedule_candidates(rows,profile,prioritized_ids={keys[1]})
            self.assertEqual([r['id'] for r in priority],[keys[1],keys[0],keys[2],keys[3]])
            with patch('joblazy.pipeline.queue_candidates',return_value=rows),patch('joblazy.discovery.enrich',side_effect=lambda p,*a,**k:p):
                run_queue(store,profile,Model(),None,temp,limit=3,rank_only=True)
            self.assertEqual(seen,['https://example.test/eu','https://example.test/beta','https://example.test/vendor'])
            self.assertEqual(store.get(keys[1])['status'],'discovered')
            self.assertEqual({r['id']:r['data'] for r in store.list()},before)

    def test_priority_moves_only_selected_rows_without_reordering_the_remaining_queue(self):
        now=datetime(2026,9,14,tzinfo=timezone.utc);profile=example_profile()
        profile['discovery_preferences']={'max_posting_age_days':45}
        rows=[{'id':key,'data':{**job('https://example.test/'+key),'company':company,
            'postedAt':(now-timedelta(days=age)).isoformat()}}
            for key,company,age in [('a1','Alpha',1),('a2','Alpha',4),('a3','Alpha',6),('b1','Beta',2),('b2','Beta',5),('c1','Gamma',3)]]
        original=schedule_candidates(rows,profile,now=now)
        priority=schedule_candidates(rows,profile,now=now,prioritized_ids={'a2'})
        self.assertEqual(priority[0]['id'],'a2')
        self.assertEqual([r['id'] for r in priority[1:]],[r['id'] for r in original if r['id']!='a2'])

    def test_uk_remote_candidates_share_london_priority_but_other_remote_scopes_do_not(self):
        profile=example_profile();profile['search_location']={'city':'London','country':'United Kingdom'}
        profile['discovery_preferences']={'title_filter':{'positive':['Strategy'],'deprioritized':['BDR']}}
        make=lambda location,title='Strategy Manager':{**job('https://example.test/role',title),'location':location}
        london=processing_priority(make('London, UK'),profile)
        remote=processing_priority(make('United Kingdom (Remote)'),profile)
        self.assertEqual(london,remote)
        self.assertGreater(remote,processing_priority(make('London, UK','BDR'),profile))
        for label in ('Remote','Remote, United States','London, Canada','United Kingdom','London'):
            self.assertGreater(remote,processing_priority(make(label),profile))
        rows=[{'id':str(i),'data':make(label)} for i,label in enumerate(('London, UK','United Kingdom (Remote)','Remote'))]
        self.assertEqual({r['id'] for r in schedule_candidates(rows,profile)},{'0','1','2'})

    def test_obvious_senior_titles_wait_behind_equivalent_target_track_roles(self):
        profile=example_profile();profile['search_location']={'city':'London','country':'United Kingdom'}
        profile['discovery_preferences']={'title_filter':{'positive':['Business Development']}}
        senior={'id':'senior','data':{**job('https://example.test/senior','Senior Business Development Manager'),'location':'London, UK'}}
        junior={'id':'junior','data':{**job('https://example.test/junior','Business Development Associate'),'location':'London, UK'}}
        self.assertGreater(processing_priority(junior['data'],profile),processing_priority(senior['data'],profile))
        self.assertEqual([row['id'] for row in schedule_candidates([senior,junior],profile)],['junior','senior'])
        # Title wording is only a scheduling hint; it cannot reject the role.
        self.assertEqual({row['id'] for row in schedule_candidates([senior,junior],profile)}, {'junior','senior'})

    def test_internship_titles_wait_behind_equivalent_target_track_roles(self):
        profile=example_profile();profile['search_location']={'city':'London','country':'United Kingdom'}
        profile['discovery_preferences']={'title_filter':{'positive':['Product Operations']}}
        intern={'id':'intern','data':{**job('https://example.test/intern','Product Operations Intern'),'location':'London, UK'}}
        associate={'id':'associate','data':{**job('https://example.test/associate','Product Operations Associate'),'location':'London, UK'}}
        self.assertGreater(processing_priority(associate['data'],profile),processing_priority(intern['data'],profile))
        self.assertEqual([row['id'] for row in schedule_candidates([intern,associate],profile)],['associate','intern'])
        self.assertEqual({row['id'] for row in schedule_candidates([intern,associate],profile)}, {'associate','intern'})

    def test_dates_do_not_override_location_or_interest_and_unknown_dates_stay_unknown(self):
        now=datetime(2026,9,14,tzinfo=timezone.utc);profile=example_profile()
        profile['search_location']={'city':'London','country':'United Kingdom'}
        profile['discovery_preferences']={'max_posting_age_days':45,'title_filter':{'positive':['Operations'],'deprioritized':['BDR']}}
        rows=[]
        for key,location,title,date in [
                ('canada','London, Canada','Operations Associate',now),
                ('bdr','London, UK','BDR',now),
                ('old','London, UK','Operations Associate',now-timedelta(days=60)),
                ('future','London, UK','Operations Associate',now+timedelta(days=30)),
                ('unknown','London, UK','Operations Associate',None),
                ('recent','London, UK','Operations Associate',now-timedelta(days=2))]:
            posting={**job('https://example.test/'+key,title),'company':key,'location':location,
                'observed_at':now.isoformat(),'postedAt':date.isoformat() if date else 'invalid'}
            rows.append({'id':key,'data':posting})
        self.assertEqual([r['id'] for r in schedule_candidates(rows,profile,now=now)],
            ['recent','future','unknown','old','bdr','canada'])
        self.assertEqual(len(rows),6)

    def test_no_age_preference_does_not_introduce_a_default_date_cutoff(self):
        profile=example_profile();profile['discovery_preferences']={}
        rows=[{'id':name,'data':{**job('https://example.test/'+name),'company':name,'postedAt':date}}
            for name,date in [('older','2020-01-01'),('recent','2026-09-14')]]
        self.assertEqual([r['id'] for r in schedule_candidates(rows,profile)],['older','recent'])

    def test_batch_prefers_recent_postings_and_rotates_equivalent_employers(self):
        now=datetime.now(timezone.utc)
        profile=example_profile();profile['discovery_preferences']={'max_posting_age_days':45}
        seen=[]
        class Model(FixtureModel):
            def generate(self,task,data,schema):
                seen.append(data['job']['url']);return super().generate(task,data,schema)
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            for name,company,age in [('old','Old Co',90),('unknown','Unknown Co',None),
                    ('alpha1','Alpha',2),('alpha2',' ALPHA ',3),('beta','Beta',4),('gamma','Gamma',5)]:
                posting={**job('https://example.test/'+name),'company':company}
                if age is not None:posting['postedAt']=int((now-timedelta(days=age)).timestamp()*1000)
                store.ingest(posting)
            with patch('joblazy.discovery.enrich',side_effect=lambda j,*a,**k:j):
                first=run_queue(store,profile,Model(),None,temp,limit=3,rank_only=True)
                self.assertEqual([url.rsplit('/',1)[-1] for url in seen],['alpha1','beta','gamma'])
                run_queue(store,profile,Model(),None,temp,limit=10,rank_only=True)
            self.assertEqual(len(first),3)
            self.assertEqual(set(url.rsplit('/',1)[-1] for url in seen),{'old','unknown','alpha1','alpha2','beta','gamma'})
            self.assertEqual(len(seen),6)
