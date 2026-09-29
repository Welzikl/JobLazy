// Add full posting content around the unchanged upstream list provider.
export function smartRecruitersIdentity(value, api=false) {
  try {
    const url=new URL(value);
    if(url.protocol!=='https:' || url.username || url.password || url.port || url.search || url.hash) return null;
    if(url.hostname!==(api?'api.smartrecruiters.com':'jobs.smartrecruiters.com'))return null;
    const match=url.pathname.match(api ? /^\/v1\/companies\/([^/]+)\/postings\/([\w-]+)\/?$/ : /^\/([^/]+)\/(\d+)(?:-[^/]*)?\/?$/);
    return match ? {company:match[1],id:match[2]} : null;
  } catch {return null;}
}

export function sameSmartRecruitersPosting(jobUrl,source) {
  const job=smartRecruitersIdentity(jobUrl),ref=smartRecruitersIdentity(source?.ref,true);
  return !!(job && ref && job.company===ref.company && job.id===ref.id && String(source.id)===ref.id);
}

export async function smartRecruitersDetails(jobs,raw,fetchJson,warn) {
  const seen=new Set();
  for(const job of jobs) {
    const source=raw.find(row=>sameSmartRecruitersPosting(job.url,row));
    if(!source){warn(`SmartRecruiters has no exact detail reference for ${job.url}`);continue;}
    if(seen.has(source.ref))continue;
    seen.add(source.ref);
    try {
      const detail=await fetchJson(source.ref,{redirect:'error',timeoutMs:30000});
      const identity=smartRecruitersIdentity(source.ref,true);
      if(String(detail?.id)!==identity.id || detail?.company?.identifier!==identity.company)
        throw new Error('Posting detail identity does not match the listing');
      if(!detail.jobAd?.sections?.jobDescription?.text?.trim())throw new Error('Posting detail has no job description');
      Object.assign(source,detail,{ref:source.ref,detail_status:'fetched',detail_observed_at:new Date().toISOString()});
    } catch(error) {
      source.detail_status='failed';source.detail_error=error.message;
      warn(`SmartRecruiters detail failed for ${source.ref}: ${error.message}`);
    }
  }
}
