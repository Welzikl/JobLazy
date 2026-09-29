// Read actual control values. A previous "verified" marker is never evidence.
(plan) => {
  const norm=s=>String(s??'').trim().replace(/\s+/g,' ').toLocaleLowerCase();
  const same=(a,b)=>norm(a)===norm(b);
  const metas=new Map(plan._scanMeta.map(f=>[f.id,f]));
  return plan.fields.map(f=>{
    const e=document.querySelector(`[data-jpaf-id="${f.id}"]`);
    const meta=metas.get(f.id)||{};
    let actual=[],kind=meta.type,ok=false;
    if(!e) return {id:f.id,ok:false,reason:'Control disappeared',actual};
    const wanted=f.exact_location && meta.adapter!=='lever_location' &&
      same(e.getAttribute('data-joblazy-location-choice-value'),f.value)
      ? e.getAttribute('data-joblazy-location-choice-label') || f.value : f.value;
    const group=e.name ? [...document.getElementsByName(e.name)] : [e];
    if(f.phone_country) {
      const state=window.__joblazyPhoneControl({id:f.id,info:f.phone_country,mode:'read'});
      actual=state.actual;ok=state.ok;
    } else if(f.phone_number) {
      actual=[e.value||''];
      ok=window.__joblazyPhoneControl({id:f.phone_number.country_field,info:f.phone_number,mode:'read'}).ok;
      // Python validates the formatted number with libphonenumber metadata.
    } else if(meta.adapter==='ashby_date') {
      let selected;try {selected=JSON.parse(e.getAttribute('data-joblazy-date-choice'));} catch {}
      actual=[e.value||''];
      ok=Boolean(selected && selected.iso===f.value && selected.value===e.value && e.value.trim());
    } else if(meta.adapter==='teamtailor_choice') {
      const selected=[...e.form.elements].filter(x=>x.type===e.type && x.name===e.name && x.checked);
      const wanted=meta.option_values.filter(x=>x.label===f.value);
      actual=selected.map(x=>x.value);
      ok=wanted.length===1 && actual.length===1 && actual[0]===wanted[0].value;
    } else if(meta.adapter==='lever_location') {
      const selected=e.closest('.application-question')?.querySelector('input[name=selectedLocation]');
      let recorded;try {recorded=JSON.parse(e.getAttribute('data-joblazy-selection'));} catch {}
      actual=[e.value||''];
      ok=Boolean(recorded && selected?.value && recorded.token===selected.value &&
        same(recorded.value,f.value) && same(e.value,f.value));
    } else if(kind==='button_group') {
      actual=[...e.querySelectorAll('button[aria-pressed=true]')].map(x=>x.innerText.trim());
      ok=actual.length===1 && same(actual[0],f.value);
    } else if(e.type==='radio'||e.type==='checkbox') {
      actual=group.filter(x=>x.checked).map(x=>(x.labels?.[0]?.innerText||x.value).trim());
      const wanted=String(f.value).split(';').map(x=>x.trim());
      ok=actual.length===wanted.length && wanted.every(x=>actual.some(y=>same(x,y)));
    } else if(e.tagName==='SELECT') {
      actual=[...e.selectedOptions].map(x=>x.text.trim());
      ok=actual.length===1 && same(actual[0],f.value);
    } else if(meta.combo || kind==='aria_select') {
      let parent=e.parentElement;
      for(let hops=0;parent && hops<5;hops++,parent=parent.parentElement) {
        actual=[...parent.querySelectorAll('.select__single-value,.select__multi-value,[class*="single-value"],[class*="multi-value"],[class*="selectedItem"]')]
          .filter(x=>x.getClientRects().length).map(x=>x.innerText.trim());
        if(actual.length || parent.matches('form,.select-shell,.select__container,.ashby-application-form-field-entry')) break;
      }
      if(actual.length) ok=actual.length===1 && same(actual[0],wanted);
      else if(kind==='aria_select') {actual=[e.innerText.trim()];ok=same(actual[0],wanted);}
      else if(!String(e.className).includes('select__input')) {
        actual=[e.value||''];ok=e.getAttribute('aria-expanded')!=='true' && same(actual[0],wanted);
      }
    } else {
      actual=[e.value??''];ok=same(actual[0],f.value);
    }
    if(e.getAttribute('aria-invalid')==='true') ok=false;
    if(f.exact_location && meta.adapter!=='lever_location' && !same(e.getAttribute('data-joblazy-location-choice-value'),f.value)) ok=false;
    return {id:f.id,ok,actual,source_ref:f.source_ref};
  });
}
