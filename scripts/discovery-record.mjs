// Preserve fields omitted by the reused providers' minimal normalized records.
import {sameSmartRecruitersPosting} from './smartrecruiters-details.mjs';
export function responseRecords(data) {
  if (Array.isArray(data)) return data;
  for (const key of ['jobs', 'data', 'results', 'content']) if (Array.isArray(data?.[key])) return data[key];
  return [];
}

export function discoveryRecord(job, raw, provider, observedAt=new Date().toISOString()) {
  const source=raw.find(x=>x && (provider==='smartrecruiters' ? sameSmartRecruitersPosting(job.url,x) :
    [x.jobUrl,x.absolute_url,x.hostedUrl,x.url,x.refs?.landing_page,
    provider==='amazon' && x.job_path ? new URL(x.job_path,'https://www.amazon.jobs').href : null,
    provider==='thehub' && x.id ? `https://thehub.io/jobs/${encodeURIComponent(x.id)}` : null].includes(job.url)));
  const firstText=(values)=>values.find(v=>typeof v==='string' && v.trim()) || '';
  const description=firstText([source?.descriptionPlain,source?.descriptionHtml,source?.content,
    source?.description,source?.contents,job.description]);
  const extra=(Array.isArray(source?.lists) ? source.lists : []).map(x=>[x?.text,x?.content].filter(v=>typeof v==='string').join('\n')).join('\n');
  const result={...job,description:[description,extra].filter(Boolean).join('\n'),ats:provider,
    url:source?.applyUrl || job.url,observed_at:observedAt};
  if (description && source) result.description_source=job.url;
  if(provider==='smartrecruiters' && source) {
    // A configured source name can describe a query, not the employer.
    if(typeof source.company?.name==='string' && source.company.name.trim())result.company=source.company.name.trim();
    const sections=source.jobAd?.sections;
    if(sections && typeof sections==='object' && !Array.isArray(sections)) {
      result.description=Object.values(sections).filter(s=>typeof s?.text==='string' && s.text.trim())
        .map(s=>[typeof s.title==='string'?s.title:'',s.text].filter(Boolean).join('\n')).join('\n\n');
      if(result.description)result.description_source=source.ref;
    }
    const loc=source.location||{},countries={GB:'United Kingdom',UK:'United Kingdom',CA:'Canada',US:'United States',ZA:'South Africa'};
    const code=typeof loc.country==='string'?loc.country.toUpperCase():null;
    if(loc.city)result.location=[loc.city,loc.region,countries[code]||code,loc.remote===true?'Remote':null].filter(Boolean).join(', ');
    result.location_evidence=loc;
    result.workplace_type=loc.hybrid===true?'hybrid':loc.remote===true?'remote':'unspecified';
    result.source_job_id=source.id;
    const posted=Date.parse(source.releasedDate);
    if(Number.isFinite(posted))result.postedAt=posted;
    result.detail_status=source.detail_status||'not_fetched';
    if(source.detail_error)result.detail_error=source.detail_error;
    if(source.detail_observed_at)result.detail_observed_at=source.detail_observed_at;
    result.url=job.url;
  }
  if (provider==='lever' && source) {
    // Lever exposes a primary location plus allLocations. A country on the
    // posting cannot be copied to secondary locations in another country.
    const primary=typeof source.categories?.location==='string' ? source.categories.location.trim() : '';
    const labels=[...new Set([primary,...(Array.isArray(source.categories?.allLocations)?source.categories.allLocations:[])]
      .filter(x=>typeof x==='string' && x.trim()).map(x=>x.trim()))];
    const countries={GB:'United Kingdom',UK:'United Kingdom',CA:'Canada',US:'United States',SE:'Sweden',ZA:'South Africa'};
    const code=typeof source.country==='string' && /^[A-Z]{2}$/.test(source.country) ? source.country : null;
    const country=countries[code]||code;
    const singlePrimary=primary && !/[|/;]/.test(primary);
    result.location_evidence=labels.map(label=>({label,primary:label===primary,
      country:label===primary && singlePrimary ? country : null}));
    if(labels.length)result.location=result.location_evidence.map(x=>[x.label,x.country].filter(Boolean).join(', ')).join(' | ');
    result.description=[description,extra,firstText([source.additionalPlain,source.additional])].filter(Boolean).join('\n');
    if(typeof source.workplaceType==='string')result.workplace_type=source.workplaceType;
  }
  if(provider==='amazon' && source) {
    // The search payload separates mandatory/preferred qualifications from the
    // role description, and can put London among secondary locations.
    result.description=[description,
      source.basic_qualifications ? 'Basic qualifications\n'+source.basic_qualifications : '',
      source.preferred_qualifications ? 'Preferred qualifications\n'+source.preferred_qualifications : ''].filter(Boolean).join('\n\n');
    const countries={GBR:'United Kingdom',GB:'United Kingdom',USA:'United States',US:'United States',CAN:'Canada',CA:'Canada'};
    const parsed=(Array.isArray(source.locations)?source.locations:[]).flatMap(value=>{
      try { const row=typeof value==='string'?JSON.parse(value):value;return row && typeof row==='object' && !Array.isArray(row)?[row]:[]; }
      catch {return [];}
    });
    const locations=parsed.map(row=>[row.normalizedCityName||row.city,row.normalizedStateName,
      row.normalizedCountryName||countries[row.countryIso3a||row.normalizedCountryCode]||row.countryIso3a||row.normalizedCountryCode]
      .filter(value=>typeof value==='string' && value.trim()).join(', ')).filter(Boolean);
    if(!locations.length && source.city && source.country_code)locations.push([source.city,source.state,countries[source.country_code]||source.country_code].filter(Boolean).join(', '));
    if(locations.length)result.location=[...new Set(locations)].join(' | ');
    result.location_evidence=parsed;
    result.source_job_id=source.id_icims;
    // This source supplies a calendar date, not a posting time. Normalize at
    // UTC midnight so the host timezone cannot shift it to the previous day.
    if(typeof source.posted_date==='string') {
      const date=Date.parse(source.posted_date.replace(/\s+/g,' ').trim()+' UTC');
      if(Number.isFinite(date)){result.postedAt=date;result.posted_date_precision='day';result.posted_date_raw=source.posted_date;}
    }
    if(source.url_next_step)result.application_url=source.url_next_step;
  }
  if (provider==='ashby' && source) {
    const countries={GB:'United Kingdom',UK:'United Kingdom',CA:'Canada',US:'United States',USA:'United States',ZA:'South Africa'};
    const sourceLocations=[source,...(Array.isArray(source.secondaryLocations)?source.secondaryLocations:[])];
    const locations=sourceLocations.map(x=>{
      const pa=x?.address?.postalAddress||{};
      const country=countries[pa.addressCountry]||pa.addressCountry;
      return [...new Set([x?.location,pa.addressLocality,pa.addressRegion,country]
        .filter(v=>typeof v==='string' && v.trim()).map(v=>v.trim()))].join(', ');
    }).filter(Boolean);
    if(locations.length)result.location=[...new Set(locations)].join(' | ');
    result.location_evidence=sourceLocations.map(x=>({label:x?.location,postal_address:x?.address?.postalAddress}));
  }
  // Preserve all explicit Muse locations rather than only locations[0].
  if (provider==='themuse' && Array.isArray(source?.locations)) {
    const names=[...new Set(source.locations.map(x=>x?.name).filter(x=>typeof x==='string' && x.trim()))];
    if(names.length) result.location=names.join(' | ');
    const posted=Date.parse(source.publication_date);
    if(Number.isFinite(posted)) result.postedAt=posted;
  }
  // The Hub's address label can omit its separately supplied locality/country.
  if (provider==='thehub' && source?.location?.locality && source?.location?.country) {
    result.location=[source.location.locality,source.location.country,source.isRemote===true?'Remote':null].filter(Boolean).join(', ');
  }
  return result;
}
