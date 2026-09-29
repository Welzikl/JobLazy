import subprocess
import unittest
from joblazy.common import ROOT


class SmartRecruitersDiscoveryTests(unittest.TestCase):
    def node(self, script):
        subprocess.run(['node', '--input-type=module', '-e', script], cwd=ROOT,
                       capture_output=True, text=True, check=True, timeout=20)

    def test_reused_provider_paginates_with_filters_and_keeps_full_postings(self):
        self.node(r'''
        import assert from 'node:assert/strict';
        import provider from './vendor/career-ops/providers/smartrecruiters.mjs';
        import {discoveryRequest} from './scripts/discovery-request.mjs';
        import {responseRecords,discoveryRecord} from './scripts/discovery-record.mjs';
        import {smartRecruitersDetails} from './scripts/smartrecruiters-details.mjs';
        const entry={name:'Example',provider:'smartrecruiters',careers_url:'https://jobs.smartrecruiters.com/Example',
          smartrecruiters:{city:'London',country:'gb'}};
        const calls=[],raw=[];
        const jobs=await provider.fetch(entry,{fetchJson:async(url,opts)=>{
          const u=new URL(discoveryRequest(url,entry));calls.push(Number(u.searchParams.get('offset')));
          assert.equal(u.searchParams.get('city'),'London');assert.equal(u.searchParams.get('country'),'gb');
          assert.equal(opts.redirect,'error');
          const start=Number(u.searchParams.get('offset'));
          const data={content:Array.from({length:start===0?100:1},(_,i)=>({id:String(start+i+1),name:'Operations '+(start+i+1),
            ref:'https://api.smartrecruiters.com/v1/companies/Example/postings/'+(start+i+1),
            location:{city:'London',country:'gb',hybrid:true},releasedDate:'2026-09-10T12:00:00Z'}))};
          raw.push(...responseRecords(data));return data;
        }});
        assert.deepEqual(calls,[0,100]);
        for(const filters of [null,[],{offset:'0'},{country:''}])
          assert.throws(()=>discoveryRequest('https://api.smartrecruiters.com/v1/companies/Example/postings',{...entry,smartrecruiters:filters}));
        let details=0;
        await smartRecruitersDetails(jobs,raw,async(url,opts)=>{
          details++;assert.equal(opts.redirect,'error');
          return {id:url.split('/').at(-1),company:{identifier:'Example'},jobAd:{sections:{
            jobDescription:{title:'Responsibilities',text:'Run commercial analysis.'},
            qualifications:{title:'Qualifications',text:'Five years required.'},
            additionalInformation:{text:'No relocation support.'}}}};
        },message=>assert.fail(message));
        assert.equal(details,101);
        const result=discoveryRecord(jobs[0],raw,'smartrecruiters');
        assert.equal(result.location,'London, United Kingdom');assert.equal(result.workplace_type,'hybrid');
        assert.equal(result.postedAt,1789041600000);assert.equal(result.detail_status,'fetched');
        assert.match(result.description,/Five years required/);assert.match(result.description,/No relocation support/);
        assert.equal(result.description_source,raw[0].ref);assert.equal(result.url,jobs[0].url);
        ''')

    def test_failed_or_mismatched_details_stay_visible_without_borrowing_content(self):
        self.node(r'''
        import assert from 'node:assert/strict';
        import {smartRecruitersDetails} from './scripts/smartrecruiters-details.mjs';
        import {discoveryRecord} from './scripts/discovery-record.mjs';
        const raw=[1,2,3,4].map(id=>({id:String(id),ref:'https://api.smartrecruiters.com/v1/companies/Example/postings/'+id,
          location:{city:'London',country:id===4?'ca':'gb'}}));
        const jobs=raw.map(r=>({url:'https://jobs.smartrecruiters.com/Example/'+r.id+'-role',title:'Role'}));
        const warnings=[];
        await smartRecruitersDetails(jobs,raw,async(url)=>{
          const id=url.split('/').at(-1);
          if(id==='1')throw new Error('HTTP 429');
          if(id==='2')return {id:'2',company:{identifier:'Other'},jobAd:{sections:{jobDescription:{text:'Unrelated facts'}}}};
          if(id==='3')return {id:'3',company:{identifier:'Example'},jobAd:{sections:{}}};
          return {id:'4',company:{identifier:'Example'},jobAd:{sections:{jobDescription:{text:'Canadian posting'}}}};
        },message=>warnings.push(message));
        assert.equal(warnings.length,3);
        for(let i=0;i<3;i++) {
          const row=discoveryRecord(jobs[i],raw,'smartrecruiters');
          assert.equal(row.description,'');assert.equal(row.detail_status,'failed');assert.ok(row.detail_error);
        }
        assert.equal(discoveryRecord(jobs[3],raw,'smartrecruiters').location,'London, Canada');
        ''')

    def test_reference_identity_is_exact_and_untrusted_urls_are_never_fetched(self):
        self.node(r'''
        import assert from 'node:assert/strict';
        import {sameSmartRecruitersPosting,smartRecruitersDetails} from './scripts/smartrecruiters-details.mjs';
        import {discoveryRecord} from './scripts/discovery-record.mjs';
        const job={url:'https://jobs.smartrecruiters.com/Example/123-role'};
        const base='https://api.smartrecruiters.com/v1/companies/Example/postings/123';
        for(const ref of [base+'/extra',base+'?next=abc',base.replace('Example','Other'),
          base.replace('https:','http:'),base.replace('api.smartrecruiters.com','evil.example'),
          base.replace('https://','https://user:pass@')]) {
          assert.equal(sameSmartRecruitersPosting(job.url,{ref,id:'123'}),false);
          await smartRecruitersDetails([job],[{ref,id:'123'}],()=>assert.fail('Unexpected fetch'),()=>{});
        }
        assert.equal(sameSmartRecruitersPosting(job.url,{ref:base,id:'124'}),false);
        assert.equal(sameSmartRecruitersPosting(job.url,{ref:base,id:'123'}),true);
        const wrong={ref:base,id:'124',url:job.url,description:'Unrelated description'};
        assert.equal(discoveryRecord(job,[wrong],'smartrecruiters').description,'');
        ''')
