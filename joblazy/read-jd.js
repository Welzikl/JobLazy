// Visible-content extraction adapted from Career Ops browser-extract.mjs (MIT).
// Prefer complete JobPosting structured data when the page supplies it.
() => {
  const visible=e=>!e.closest('[aria-hidden="true"],[hidden]') && e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
  const title=([...document.querySelectorAll('h1')].find(visible)?.innerText || document.title || '').trim();
  const postings=[];
  function walk(value) {
    if(Array.isArray(value)) {value.forEach(walk);return;}
    if(!value || typeof value!=='object') return;
    if([].concat(value['@type']||[]).includes('JobPosting') && value.description) postings.push(value);
    if(value['@graph']) walk(value['@graph']);
  }
  for(const script of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {walk(JSON.parse(script.textContent));} catch {}
  }
  const root=document.querySelector('main,[role="main"],article') || document.body;
  const clone=root?.cloneNode(true);
  clone?.querySelectorAll('script,style,nav,header,footer,noscript,form').forEach(e=>e.remove());
  const anchors=[...document.querySelectorAll('a[href]')]
    .filter(e=>!e.closest('nav,header,footer') && visible(e))
    .map(e=>({url:e.href,label:e.innerText.trim(),sr_track:e.getAttribute('data-sr-track')}));
  // Read only the current public listing, never the forwarding consent modal.
  const hub=location.hostname==='thehub.io' ? window.__NUXT__?.state?.jobs?.job : null;
  const hub_job=hub ? {id:hub.id,link:hub.link} : null;
  // The Muse renders Apply as a button. Its public page props carry the
  // employer URL; parse serialized JSON only, never evaluate script text.
  const muse_jobs=[];
  if(['www.themuse.com','themuse.com'].includes(location.hostname)) {
    const fragments=[];
    for(const script of document.querySelectorAll('script')) {
      const match=script.textContent.trim().match(/^self\.__next_f\.push\((\[[\s\S]*\])\);?$/);
      if(!match)continue;
      try {const item=JSON.parse(match[1]);if(item[0]===1 && typeof item[1]==='string')fragments.push(item[1]);} catch {}
    }
    function inspect(value) {
      if(Array.isArray(value)){value.forEach(inspect);return;}
      if(!value || typeof value!=='object')return;
      if(value.companyShortName && value.jobShortName && value.job?.type==='external') {
        muse_jobs.push({company_slug:value.companyShortName,job_slug:value.jobShortName,
          short_title:value.job.shortTitle,company_short_name:value.company?.shortName,
          id:value.job.id,link:value.job.applyLink});
      }
      Object.values(value).forEach(inspect);
    }
    // Text records use byte lengths rather than newline boundaries. A complete
    // JSON fragment can follow such a record; inspect it independently too.
    for(const line of [...fragments.flatMap(part=>part.split('\n')),...fragments.join('').split('\n')]) {
      const match=line.match(/^[0-9a-f]+:([\s\S]*)$/i);
      if(match)try {inspect(JSON.parse(match[1]));} catch {}
    }
  }
  const headings=[...document.querySelectorAll('h1,h2,[role="alert"]')]
    .filter(e=>!e.closest('nav,header,footer') && visible(e))
    .map(e=>e.innerText.trim()).filter(Boolean);
  return {title,text:clone?.innerText || clone?.textContent || '',headings,postings,anchors,hub_job,muse_jobs};
}
