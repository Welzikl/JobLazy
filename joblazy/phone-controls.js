(() => {
  const norm=s=>String(s??'').trim().replace(/\s+/g,' ').toLowerCase();
  window.__joblazyPhoneControl=({id,info,mode})=>{
    const e=document.querySelector(`[data-jpaf-id="${CSS.escape(id)}"]`);
    if(!e)return {ok:false,actual:[],count:0,search:''};
    const region=info.region;
    const name=region ? new Intl.DisplayNames(['en'],{type:'region'}).of(region) : '';
    const names=new Set([name,region].filter(Boolean).map(norm));
    if(region==='US')for(const alias of ['United States of America','USA'])names.add(norm(alias));
    if(region==='GB')names.add('uk');
    const matches=(label,value='')=>{
      const text=norm(label);const codes=text.match(/\+\d+/g)||[];
      if(codes.some(code=>code!==info.calling_code))return false;
      if(/^[a-z]{2}$/i.test(value) && (!region || value.toUpperCase()!==region))return false;
      if(/^\+[0-9]+$/.test(text))return text===info.calling_code;
      if(!region)return false;
      const bare=text.replace(/\(?\+\d+\)?/g,'').replace(/^[\s–—-]+|[\s–—-]+$/g,'').trim();
      return names.has(bare);
    };
    const native=e.tagName==='SELECT';
    if(mode==='read') {
      let actual=[];let ok=false;
      if(info.control==='calling_code') {
        actual=[e.value||''];ok=norm(actual[0])===info.calling_code;
      } else if(native) {
        const selected=[...e.selectedOptions];actual=selected.map(o=>o.textContent.trim());
        ok=selected.length===1 && matches(actual[0],selected[0].value);
      } else {
        const shell=e.closest('.select-shell,.select__container,.select__control');
        actual=[...(shell?.querySelectorAll('.select__single-value,[class*="single-value"],[class*="selectedItem"]')||[])]
          .filter(x=>x.getClientRects().length).map(x=>x.textContent.trim());
        // Typed combobox text is not proof that a country was selected.
        ok=actual.length===1 && matches(actual[0]);
      }
      return {ok:ok && e.getAttribute('aria-invalid')!=='true',actual};
    }
    let options=[];
    if(native)options=[...e.options];
    else {
      for(const control of (e.getAttribute('aria-controls')||e.getAttribute('aria-owns')||'').split(/\s+/).filter(Boolean))
        options.push(...(document.getElementById(control)?.querySelectorAll('[role=option]')||[]));
      if(!options.length && e.id)options=[...document.querySelectorAll(`[id^="react-select-${CSS.escape(e.id)}-option"]`)];
      if(!options.length)options=[...(e.closest('.select-shell,.select__container')?.querySelectorAll('[role=listbox] [role=option]')||[])];
    }
    options=[...new Set(options)].filter(o=>!o.disabled && o.getAttribute('aria-disabled')!=='true' && (native || o.getClientRects().length));
    for(const option of options)option.removeAttribute('data-joblazy-phone-option');
    const found=options.filter(o=>matches(o.textContent,o.value||''));
    if(found.length===1)found[0].setAttribute('data-joblazy-phone-option',id);
    return {count:found.length,index:native && found.length===1 ? found[0].index : null,search:name||info.calling_code};
  };
})()
