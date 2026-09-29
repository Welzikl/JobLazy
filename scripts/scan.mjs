import {readFile} from 'node:fs/promises';
import {saveCheckpoint} from './scan-checkpoint.mjs';
import {responseRecords,discoveryRecord} from './discovery-record.mjs';
import {discoveryRequest} from './discovery-request.mjs';
import {smartRecruitersDetails} from './smartrecruiters-details.mjs';
import workday from './workday.mjs';
import teamtailor from './teamtailor.mjs';
import smartrecruiters from '../vendor/career-ops/providers/smartrecruiters.mjs';
import ashby from './ashby.mjs';
import greenhouse from '../vendor/career-ops/providers/greenhouse.mjs';
import lever from '../vendor/career-ops/providers/lever.mjs';
import {fetchJson,fetchText} from '../vendor/career-ops/providers/_http.mjs';
const entries = JSON.parse(await readFile(process.argv[2], 'utf8')).boards;
const providers = {ashby,greenhouse,lever,smartrecruiters,workday,teamtailor};
for (const id of ['amazon','a16z-speedrun-talent','thehub','arbeitnow','himalayas','remoteok','remotive','weworkremotely','workingnomads','jobicy','echojobs','landingjobs','themuse','hackernews']) {
  providers[id] = (await import(`../vendor/career-ops/providers/${id}.mjs`)).default;
}
const jobs = [], errors = [], source_runs=[];
const checkpoint=process.argv[3];
async function save() { if(checkpoint) await saveCheckpoint(checkpoint,{jobs,errors,source_runs}); }
for (const entry of entries) {
  if (entry.enabled === false) continue;
  const run={entry,started_at:new Date().toISOString(),status:'in_progress',urls:[],warnings:[]};source_runs.push(run);
  await save();
  const provider = providers[entry.provider];
  if (!provider) { run.status='failed';run.error='Unsupported discovery provider';run.finished_at=new Date().toISOString();errors.push({board:entry.name,error:run.error}); await save(); continue; }
  const raw = [];
  let reportedTotal=0;
  const originalError=console.error;
  console.error=(...args)=>{run.warnings.push(args.map(String).join(' '));originalError(...args);};
  try {
    const found = await provider.fetch(entry, {fetchText,fetchJson:async (url,opts) => {
      const data = await fetchJson(discoveryRequest(url,entry), {...opts,timeoutMs:30000});
      if(entry.provider==='amazon' && Number.isFinite(data?.hits))reportedTotal=Math.max(reportedTotal,data.hits);
      if(entry.provider==='themuse' && Number.isFinite(data?.total))reportedTotal=Math.max(reportedTotal,data.total);
      if(entry.provider==='smartrecruiters' && Number.isFinite(data?.totalFound))reportedTotal=Math.max(reportedTotal,data.totalFound);
      raw.push(...responseRecords(data));
      if(entry.provider==='themuse' && entry.max_pages!==undefined) {
        if(!Number.isInteger(entry.max_pages) || entry.max_pages<1 || entry.max_pages>100) throw new Error('max_pages must be between 1 and 100');
        if(Number.isInteger(data.page_count) && data.page_count>entry.max_pages) {
          if(data.page===0) console.error(`The Muse has ${data.page_count} pages; this search samples at most ${entry.max_pages}. Broaden or adjust the location if needed; this is not complete market coverage.`);
          return {...data,page_count:Math.min(data.page_count,entry.max_pages)};
        }
      }
      return data;
    }});
    if(entry.provider==='amazon' && reportedTotal>found.length)console.error(`Amazon returned ${found.length} distinct records against ${reportedTotal} reported matches; snapshot may be incomplete or changed during pagination.`);
    if(entry.provider==='themuse' && reportedTotal>new Set(found.map(job=>job.url)).size)console.error(`The Muse returned ${new Set(found.map(job=>job.url)).size} distinct records against ${reportedTotal} reported matches; snapshot may be incomplete or changed during pagination.`);
    if(entry.provider==='smartrecruiters') {
      run.reported_total=reportedTotal;
      if(reportedTotal>new Set(found.map(job=>job.url)).size)console.error(`SmartRecruiters returned fewer distinct postings than ${reportedTotal} reported matches; snapshot may be incomplete.`);
      await smartRecruitersDetails(found,raw,fetchJson,(message)=>console.error(message));
    }
    for (const job of found) {
      const record=discoveryRecord(job,raw,entry.provider);jobs.push(record);run.urls.push(record.url);
    }
    run.status=run.warnings.length?'completed_with_warnings':'completed';
    // The retained Muse adapter returns gathered records on a later-page
    // failure. Preserve those records, but distinguish retryable truncation
    // from our deliberate page cap so it does not receive a success cache.
    const partialFailure=entry.provider==='themuse' && run.warnings.find(message=>/themuse: truncated at page/i.test(message));
    if(partialFailure) {
      run.error=partialFailure;
      errors.push({board:entry.name,error:partialFailure});
    }
  } catch(e) { run.status='failed';run.error=e.message;errors.push({board:entry.name,error:e.message}); }
  finally {console.error=originalError;run.finished_at=new Date().toISOString();}
  await save();
}
console.log(JSON.stringify({jobs,errors,source_runs}));
