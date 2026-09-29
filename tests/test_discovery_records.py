import json
import subprocess
import unittest
from joblazy.common import ROOT
from joblazy.coverage import location_class


class DiscoveryRecordTests(unittest.TestCase):
    def test_ashby_preserves_nested_salary_component(self):
        script=r'''
        import assert from 'node:assert/strict';
        import ashby,{parseCompensation} from './scripts/ashby.mjs';
        const current={compensation:{summaryComponents:[
          {compensationType:'EquityPercentage',interval:'NONE',currencyCode:null,minValue:null,maxValue:null},
          {compensationType:'Salary',interval:'1 YEAR',currencyCode:'GBP',minValue:60000,maxValue:120000}
        ]}};
        assert.deepEqual(parseCompensation(current),{min:60000,max:120000,currency:'GBP'});
        assert.equal(parseCompensation({compensation:{summaryComponents:[current.compensation.summaryComponents[0]]}}),null);
        assert.deepEqual(parseCompensation({compensation:{interval:'1 YEAR',currency:'GBP',minValue:50000,maxValue:70000}}),
          {min:50000,max:70000,currency:'GBP'});
        const fetched=await ashby.fetch({name:'Example',api:'https://api.ashbyhq.com/posting-api/job-board/example?includeCompensation=true'},
          {fetchJson:async()=>({jobs:[{title:'Role',jobUrl:'https://jobs.ashbyhq.com/example/one',location:'London',compensation:current.compensation}]})});
        assert.deepEqual(fetched[0].salary,{min:60000,max:120000,currency:'GBP'});
        '''
        result=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_smartrecruiters_uses_bound_employer_name_instead_of_query_label(self):
        script=r'''
        import assert from 'node:assert/strict';
        import {discoveryRecord} from './scripts/discovery-record.mjs';
        const job={title:'Fictional role',url:'https://jobs.smartrecruiters.com/Fictional/123-fictional-role',
          company:'Fictional — London strategy query',location:'London'};
        const source={id:'123',ref:'https://api.smartrecruiters.com/v1/companies/Fictional/postings/123',
          company:{identifier:'Fictional',name:' Fictional Payments '}};
        assert.equal(discoveryRecord(job,[source],'smartrecruiters').company,'Fictional Payments');
        for(const company of [null,{}, {name:''},{name:42}])
          assert.equal(discoveryRecord(job,[{...source,company}],'smartrecruiters').company,job.company);
        const unrelated={...source,id:'456',ref:source.ref.replace('/123','/456')};
        assert.equal(discoveryRecord(job,[unrelated],'smartrecruiters').company,job.company);
        '''
        result=subprocess.run(['node','--input-type=module','-e',script],capture_output=True,text=True,cwd=ROOT)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_lever_keeps_secondary_locations_primary_country_and_closing_conditions(self):
        script=r'''
        import lever from './vendor/career-ops/providers/lever.mjs';
        import {discoveryRecord} from './scripts/discovery-record.mjs';
        const raw=[
          {text:'London primary',hostedUrl:'https://jobs.lever.co/example/one',country:'GB',
           categories:{location:'London',allLocations:['London','Stockholm']},descriptionPlain:'Opening and body.',
           lists:[{text:'Requirements',content:'<li>Analysis experience</li>'}],additionalPlain:'No relocation support.',workplaceType:'hybrid'},
          {text:'London secondary',hostedUrl:'https://jobs.lever.co/example/two',country:'CA',
           categories:{location:'Toronto',allLocations:['Toronto','London','London']},descriptionPlain:'Body.'},
          {text:'Canadian London',hostedUrl:'https://jobs.lever.co/example/three',country:'CA',
           categories:{location:'London',allLocations:['London']},descriptionPlain:'Body.'},
          {text:'No country',hostedUrl:'https://jobs.lever.co/example/four',country:null,
           categories:{location:'London',allLocations:['London']},descriptionPlain:'Body.'}];
        const jobs=await lever.fetch({name:'Example',careers_url:'https://jobs.lever.co/example'}, {fetchJson:async()=>raw});
        console.log(JSON.stringify(jobs.map(j=>discoveryRecord(j,raw,'lever'))));
        '''
        result=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,capture_output=True,text=True,check=True,timeout=15)
        primary,secondary,canadian,unknown=json.loads(result.stdout)
        self.assertEqual(primary['location'],'London, United Kingdom | Stockholm')
        self.assertEqual(location_class(primary['location']),'london_uk_explicit')
        self.assertEqual(primary['workplace_type'],'hybrid')
        self.assertIn('No relocation support.',primary['description'])
        self.assertIn('Analysis experience',primary['description'])
        self.assertEqual(secondary['location'],'Toronto, Canada | London')
        self.assertEqual(location_class(secondary['location']),'london_country_unverified')
        self.assertIsNone(secondary['location_evidence'][1]['country'])
        self.assertEqual(location_class(canadian['location']),'other_london')
        self.assertEqual(location_class(unknown['location']),'london_country_unverified')

    def test_muse_filters_follow_every_upstream_page_and_preserve_description_and_date(self):
        script=r'''
        import assert from 'node:assert/strict';
        import muse from './vendor/career-ops/providers/themuse.mjs';
        import {discoveryRequest} from './scripts/discovery-request.mjs';
        import {discoveryRecord} from './scripts/discovery-record.mjs';
        const entry={provider:'themuse',themuse:{company:'Example & Co',location:'London, United Kingdom'}};
        const calls=[],raw=[];
        const jobs=await muse.fetch(entry,{sleep:async()=>{},fetchJson:async url=>{
          const u=new URL(discoveryRequest(url,entry));calls.push(u.href);
          assert.equal(u.searchParams.get('company'),'Example & Co');
          assert.equal(u.searchParams.get('location'),'London, United Kingdom');
          const page=Number(u.searchParams.get('page'));
          const row={name:'Fictional role '+page,company:{name:'Example & Co'},
            refs:{landing_page:'https://www.themuse.com/jobs/fictional/'+page},
            locations:[{name:'London, United Kingdom'}],contents:'Full fictional description.',publication_date:'2026-09-10T12:00:00Z'};
          raw.push(row);return {page,page_count:2,total:2,results:[row]};
        }});
        assert.deepEqual(calls.map(url=>new URL(url).searchParams.get('page')),['0','1']);
        for(const filter of [{company:''},{page:'99'},[],null])assert.throws(()=>discoveryRequest(calls[0],{provider:'themuse',themuse:filter}));
        const gh=new URL(discoveryRequest('https://boards-api.greenhouse.io/v1/boards/example/jobs',{provider:'greenhouse'}));
        assert.equal(gh.searchParams.get('content'),'true');
        console.log(JSON.stringify(jobs.map(job=>discoveryRecord(job,raw,'themuse'))));
        '''
        result=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,capture_output=True,text=True,check=True,timeout=15)
        records=json.loads(result.stdout);self.assertEqual(len(records),2)
        self.assertTrue(all(row['description']=='Full fictional description.' for row in records))
        self.assertTrue(all(row['postedAt']==1789041600000 for row in records))

    def test_reused_amazon_provider_preserves_qualifications_secondary_countries_and_posting_date(self):
        script=r'''
        import amazon from './vendor/career-ops/providers/amazon.mjs';
        import {discoveryRecord} from './scripts/discovery-record.mjs';
        const raw=[{title:'Fictional operations role',job_path:'/en/jobs/123/operations',id_icims:'123',
          country_code:'GBR',city:'Manchester',normalized_location:'Manchester, England, GBR',posted_date:'September 10, 2026',updated_time:'1 minute',
          description:'Coordinate operations.',basic_qualifications:'SQL and analytics.',preferred_qualifications:'Commercial experience.',
          url_next_step:'https://account.amazon.jobs/jobs/123/apply',locations:[
            JSON.stringify({normalizedCityName:'London',normalizedCountryName:'Canada'}),
            JSON.stringify({normalizedCityName:'London',normalizedCountryName:'United Kingdom'}),'invalid JSON']}];
        const calls=[];
        const jobs=await amazon.fetch({name:'Fictional Amazon query',amazon:{normalized_country_code:['GBR'],normalized_city_name:['London']}},
          {fetchJson:async url=>{calls.push(url);return {jobs:raw};}});
        console.log(JSON.stringify({calls,record:discoveryRecord(jobs[0],raw,'amazon')}));
        '''
        result=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,capture_output=True,text=True,check=True,timeout=15)
        value=json.loads(result.stdout);record=value['record']
        self.assertIn('normalized_city_name%5B%5D=London',value['calls'][0])
        self.assertIn('normalized_country_code%5B%5D=GBR',value['calls'][0])
        self.assertIn('Basic qualifications\nSQL and analytics.',record['description'])
        self.assertIn('Preferred qualifications\nCommercial experience.',record['description'])
        self.assertEqual(record['source_job_id'],'123')
        self.assertEqual(record['application_url'],'https://account.amazon.jobs/jobs/123/apply')
        self.assertEqual(location_class(record['location'].split(' | ')[0]),'other_london')
        self.assertEqual(location_class(record['location']),'london_uk_explicit')
        self.assertEqual(record['postedAt'],1788998400000)

    def test_ashby_primary_postal_country_and_secondary_locations_stay_associated(self):
        script=r'''
        import {discoveryRecord} from './scripts/discovery-record.mjs';
        const source={jobUrl:'https://jobs.ashbyhq.com/fictional/one',location:'London',
          address:{postalAddress:{addressLocality:'London',addressCountry:'CA',addressRegion:'Ontario'}},
          secondaryLocations:[{location:'London',address:{postalAddress:{addressLocality:'London',addressCountry:'GB'}}}]};
        console.log(JSON.stringify(discoveryRecord({url:source.jobUrl,location:'London'},[source],'ashby')));
        '''
        result=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,capture_output=True,text=True,check=True,timeout=15)
        value=json.loads(result.stdout)
        primary,secondary=value['location'].split(' | ')
        self.assertEqual(location_class(primary),'other_london')
        self.assertEqual(location_class(secondary),'london_uk_explicit')
        self.assertEqual(location_class(value['location']),'london_uk_explicit')
        self.assertEqual(value['location_evidence'][0]['postal_address']['addressCountry'],'CA')

    def test_reused_provider_payloads_retain_descriptions_dates_and_all_locations(self):
        script=r'''
        import {responseRecords,discoveryRecord} from './scripts/discovery-record.mjs';
        import {normalizeMuseJob} from './vendor/career-ops/providers/themuse.mjs';
        import {normalizeSpeedrunJob} from './vendor/career-ops/providers/a16z-speedrun-talent.mjs';
        const muse={name:'Operations Associate',refs:{landing_page:'https://www.themuse.com/jobs/fictional/operations'},
          company:{name:'Fictional'},locations:[{name:'New York, NY'},{name:'London, United Kingdom'}],
          contents:'<p>Full source description retained.</p>',publication_date:'2026-09-12T00:00:00Z'};
        const speedrun={title:'Partner Operations',url:'https://speedrun-talent-network.com/jobs/fictional-partner',
          company:'Fictional',location:'London, UK',description:'Full partner operations description.'};
        const records=[discoveryRecord(normalizeMuseJob(muse),responseRecords({results:[muse]}),'themuse'),
          discoveryRecord(normalizeSpeedrunJob(speedrun),responseRecords({jobs:[speedrun]}),'a16z-speedrun-talent'),
          discoveryRecord({title:'Other',url:'https://example.test/other'},[muse],'themuse'),
          discoveryRecord({url:'https://thehub.io/jobs/fake',location:'Street address'},responseRecords({jobs:[{
            id:'fake',location:{locality:'London',country:'United Kingdom'},description:'Hub content'}]}),'thehub')];
        console.log(JSON.stringify({records,arbeitnow:responseRecords({data:[{description:'Preserved'}]})}));
        '''
        result=subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        result=json.loads(result.stdout);muse,speedrun,other,hub=result['records']
        self.assertEqual(location_class(muse['location']),'london_uk_explicit')
        self.assertIn('Full source description',muse['description']);self.assertIsInstance(muse['postedAt'],int)
        self.assertEqual(speedrun['description'],'Full partner operations description.')
        self.assertEqual(other['description'],'');self.assertNotIn('postedAt',other)
        self.assertEqual(location_class(hub['location']),'london_uk_explicit');self.assertEqual(hub['description'],'Hub content')
        self.assertEqual(result['arbeitnow'],[{'description':'Preserved'}])


if __name__=='__main__':unittest.main()
