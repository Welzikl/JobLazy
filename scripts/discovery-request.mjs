// Add supported query filters around the retained upstream HTTP transport.
export function discoveryRequest(url, entry) {
  const result=new URL(url);
  if(entry.provider==='greenhouse' && result.pathname.endsWith('/jobs')) result.searchParams.set('content','true');
  if(entry.provider==='smartrecruiters' && entry.smartrecruiters!==undefined) {
    if(!entry.smartrecruiters || typeof entry.smartrecruiters!=='object' || Array.isArray(entry.smartrecruiters)) throw new Error('smartrecruiters filters must be an object');
    for(const [key,value] of Object.entries(entry.smartrecruiters)) {
      if(!['city','country'].includes(key) || typeof value!=='string' || !value.trim()) throw new Error('Unsupported or empty smartrecruiters filter');
      result.searchParams.set(key,value.trim());
    }
  }
  if(entry.provider==='themuse' && entry.themuse!==undefined) {
    if(!entry.themuse || typeof entry.themuse!=='object' || Array.isArray(entry.themuse)) throw new Error('themuse filters must be an object');
    for(const [key,value] of Object.entries(entry.themuse)) {
      if(!['company','location','category'].includes(key) || typeof value!=='string' || !value.trim()) throw new Error('Unsupported or empty themuse filter');
      result.searchParams.set(key,value.trim());
    }
  }
  return result.toString();
}
