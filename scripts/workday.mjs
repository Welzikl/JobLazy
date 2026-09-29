const WORKDAY_HOST = /^[a-z0-9-]+\.wd[1-9]\.myworkdayjobs\.com$/i;

function config(entry) {
  const value=entry.workday;
  if (!value || typeof value!=='object' || Array.isArray(value)) throw new Error('workday requires a workday configuration object');
  const {host,tenant,site}=value;
  if (typeof host!=='string' || !WORKDAY_HOST.test(host) || ![tenant,site].every(item=>typeof item==='string' && /^[A-Za-z0-9_-]+$/.test(item)))
    throw new Error('workday host, tenant and site must be nonempty safe identifiers');
  if (!WORKDAY_HOST.test(host)) throw new Error('workday host must be a direct *.wdN.myworkdayjobs.com host');
  return {host,tenant,site,locale:typeof value.locale==='string' && /^[a-z]{2}-[A-Z]{2}$/.test(value.locale) ? value.locale : 'en-US'};
}

function description(posting) {
  const fields=Array.isArray(posting?.bulletFields) ? posting.bulletFields : [];
  return fields.map(field=>typeof field==='string' ? field.trim() : '').filter(Boolean).join('\n');
}

export default {
  id:'workday',
  async fetch(entry,ctx) {
    const {host,tenant,site,locale}=config(entry);
    const endpoint=`https://${host}/wday/cxs/${tenant}/${site}/jobs`;
    const limit=20, maxPages=Number.isInteger(entry.max_pages) && entry.max_pages>0 ? entry.max_pages : 10;
    const jobs=[];
    for(let page=0;page<maxPages;page++) {
      const data=await ctx.fetchJson(endpoint,{method:'POST',redirect:'error',timeoutMs:30000,
        headers:{'content-type':'application/json','accept':'application/json'},body:JSON.stringify({appliedFacets:{},limit,offset:page*limit,searchText:''})});
      const listings=Array.isArray(data?.jobPostings) ? data.jobPostings : [];
      for(const posting of listings) {
        const path=typeof posting?.externalPath==='string' && posting.externalPath.startsWith('/') ? posting.externalPath : null;
        if(!path) continue;
        jobs.push({title:typeof posting.title==='string'?posting.title:'',company:entry.name,
          url:`https://${host}/${locale}/${site}${path}`,location:typeof posting.locationsText==='string'?posting.locationsText:'',
          description:description(posting),postedAt:Date.parse(posting.postedOn)||undefined,source_job_id:posting.jobReqId});
      }
      if(listings.length<limit) break;
      if(page===maxPages-1) console.error(`Workday stopped at the configured ${maxPages}-page cap; the board may have additional jobs.`);
    }
    return jobs;
  }
};
