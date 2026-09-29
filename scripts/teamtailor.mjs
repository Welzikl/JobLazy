function decode(value) {
  return value.replace(/&(?:nbsp|middot|amp|lt|gt|quot|#39|#x27);/gi, entity => ({'&nbsp;':' ','&middot;':'·','&amp;':'&','&lt;':'<','&gt;':'>','&quot;':'"','&#39;':"'",'&#x27;':"'"}[entity.toLowerCase()]));
}
function text(value) { return decode(decode(value)).replace(/<[^>]*>/g,' ').replace(/\s+/g,' ').trim(); }
function absolute(href, base) { try { const url=new URL(href,base); return url.protocol==='https:' ? url.href : null; } catch { return null; } }
function normalized(value) { return text(value).toLowerCase().replace(/&/g,' and ').replace(/[^a-z0-9]+/g,' ').trim(); }
function jobPosting(value) {
  if(Array.isArray(value)) return value.flatMap(jobPosting);
  if(!value || typeof value!=='object') return [];
  const children=Array.isArray(value['@graph']) ? value['@graph'].flatMap(jobPosting) : [];
  const types=Array.isArray(value['@type']) ? value['@type'] : [value['@type']];
  return types.includes('JobPosting') ? [value,...children] : children;
}
function structuredPosting(html,title) {
  for(const match of html.matchAll(/<script\b[^>]*type=["']application\/ld\+json["'][^>]*>([\s\S]*?)<\/script>/gi)) {
    try {
      for(const posting of jobPosting(JSON.parse(match[1]))) {
        if(normalized(posting.title)===normalized(title) && typeof posting.description==='string') return text(posting.description);
      }
    } catch { /* Ignore malformed unrelated structured data. */ }
  }
  return '';
}

export default {
  id:'teamtailor',
  async fetch(entry,ctx) {
    if(typeof entry.careers_url!=='string' || !entry.careers_url.startsWith('https://')) throw new Error('teamtailor requires an HTTPS careers_url');
    const listUrl=new URL(entry.careers_url); if(!listUrl.pathname.endsWith('/jobs')) listUrl.pathname=listUrl.pathname.replace(/\/$/,'')+'/jobs';
    const html=await ctx.fetchText(listUrl.href,{redirect:'error',timeoutMs:30000});
    const jobs=[];
    for(const item of html.matchAll(/<li\b[^>]*>([\s\S]*?)<\/li>/gi)) {
      const block=item[1]; const match=block.match(/<a\b[^>]*href=["']([^"']*\/jobs\/\d+-[^"']+)["'][^>]*>([\s\S]*?)<\/a>/i);
      if(!match) continue;
      const url=absolute(match[1],listUrl); if(!url || new URL(url).origin!==listUrl.origin) continue;
      const title=text(match[2]); const meta=[...block.matchAll(/<span\b[^>]*>([\s\S]*?)<\/span>/gi)].map(match=>text(match[1])).filter(Boolean);
      const location=meta.length>1 ? meta.slice(1).filter(value=>value!=='·').join(', ') : '';
      if(title) jobs.push({title,url,company:entry.name,location,workplace_type:/\bhybrid\b/i.test(location)?'hybrid':/\bremote\b/i.test(location)?'remote':'unspecified'});
    }
    if(!jobs.length && /\/jobs\/\d+-/i.test(html)) throw new Error('teamtailor found job links but could not parse safe job cards');
    const limit=100;
    for(const job of jobs.slice(0,limit)) {
      try {
        const detail=await ctx.fetchText(job.url,{redirect:'error',timeoutMs:30000});
        const description=structuredPosting(detail,job.title);
        if(description.length>=200) Object.assign(job,{description,description_source:job.url,description_method:'Teamtailor JobPosting structured data',detail_status:'fetched'});
        else { job.detail_status='failed';job.detail_error='No matching structured job description'; console.error(`Teamtailor detail unavailable for ${job.title}`); }
      } catch(error) { job.detail_status='failed';job.detail_error=`${error?.message || 'Detail request failed'}`; console.error(`Teamtailor detail request failed for ${job.title}`); }
    }
    if(jobs.length>limit) console.error(`Teamtailor stopped detail reads at the ${limit}-job cap; remaining roles are list-only.`);
    return jobs;
  }
};
