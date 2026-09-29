import subprocess
import unittest
from joblazy.common import ROOT


class WorkdayAndTeamtailorDiscoveryTests(unittest.TestCase):
    def node(self, script):
        subprocess.run(['node','--input-type=module','-e',script],cwd=ROOT,capture_output=True,text=True,check=True,timeout=20)

    def test_workday_paginates_and_constructs_official_urls(self):
        self.node(r'''
        import assert from 'node:assert/strict'; import provider from './scripts/workday.mjs';
        const calls=[]; const entry={name:'Example',provider:'workday',workday:{host:'example.wd1.myworkdayjobs.com',tenant:'example',site:'Careers'}};
        const jobs=await provider.fetch(entry,{fetchJson:async(url,opts)=>{calls.push({url,body:JSON.parse(opts.body)});const offset=JSON.parse(opts.body).offset;
          return {jobPostings:offset ? [{title:'Operations Associate',externalPath:'/job/London/Operations-Associate_R2',locationsText:'London, United Kingdom',postedOn:'Posted Today',jobReqId:'R2'}] : Array.from({length:20},(_,i)=>({title:'Role '+i,externalPath:'/job/London/Role_R'+i,locationsText:'London, United Kingdom',bulletFields:['Own reporting'],jobReqId:'R'+i}))};}});
        assert.equal(calls.length,2); assert.equal(calls[0].url,'https://example.wd1.myworkdayjobs.com/wday/cxs/example/Careers/jobs'); assert.equal(calls[1].body.offset,20);
        assert.equal(jobs.length,21); assert.equal(jobs[0].url,'https://example.wd1.myworkdayjobs.com/en-US/Careers/job/London/Role_R0'); assert.equal(jobs[0].description,'Own reporting');
        await assert.rejects(provider.fetch({name:'Bad',provider:'workday',workday:{host:'example.invalid',tenant:'x',site:'y'}},{fetchJson:async()=>({})}));
        ''')

    def test_teamtailor_reads_only_job_cards_and_preserves_location(self):
        self.node(r'''
        import assert from 'node:assert/strict'; import provider from './scripts/teamtailor.mjs';
        const html=`<ul><li><a href="/jobs/123-strategy-operations"> Strategy &amp; Operations </a><div><span>Operations</span><span>London</span><span>Hybrid</span></div></li><li><a href="https://evil.test/jobs/22-nope">Nope</a></li></ul>`;
        const description='Own commercial systems and improve partner operations across the business. '.repeat(4).trim();
        const detail=`<script type="application/ld+json">${JSON.stringify({"@type":"JobPosting",title:"Strategy and Operations",description:`<p>${description}</p>`})}</script>`;
        const jobs=await provider.fetch({name:'Example',provider:'teamtailor',careers_url:'https://example.teamtailor.com/jobs'},{fetchText:async url=>url.endsWith('/jobs')?html:detail});
        assert.deepEqual(jobs,[{title:'Strategy & Operations',url:'https://example.teamtailor.com/jobs/123-strategy-operations',company:'Example',location:'London, Hybrid',workplace_type:'hybrid',description,description_source:'https://example.teamtailor.com/jobs/123-strategy-operations',description_method:'Teamtailor JobPosting structured data',detail_status:'fetched'}]);
        ''')

    def test_teamtailor_keeps_a_listed_job_when_its_detail_cannot_be_verified(self):
        self.node(r'''
        import assert from 'node:assert/strict'; import provider from './scripts/teamtailor.mjs';
        const list=`<li><a href="/jobs/123-growth">Growth role</a><span>Growth</span><span>London</span></li>`;
        const jobs=await provider.fetch({name:'Example',provider:'teamtailor',careers_url:'https://example.teamtailor.com/jobs'},{fetchText:async url=>url.endsWith('/jobs')?list:'<script type="application/ld+json">{"@type":"JobPosting","title":"Different role","description":"Unrelated"}</script>'});
        assert.equal(jobs.length,1);assert.equal(jobs[0].description,undefined);assert.equal(jobs[0].detail_status,'failed');
        ''')
