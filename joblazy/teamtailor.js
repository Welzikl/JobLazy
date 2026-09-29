// Metadata observed on Teamtailor's public application overlay.
(fields) => {
  const clean=node=>{
    const copy=node.cloneNode(true);
    copy.querySelectorAll('[data-asterisk],.sr-only,input,select,textarea,button').forEach(e=>e.remove());
    return copy.textContent.trim().replace(/\s+/g,' ');
  };
  // The uploader replaces/disables its picker after accepting a file. Keep one
  // stable upload field rooted at its visible controller, including while busy.
  document.querySelectorAll('form[data-controller~="careersite--form"] [data-controller~="forms--inputs--upload"]').forEach((root,index)=>{
    if(!root.getClientRects().length) return;
    fields=fields.filter(f=>document.querySelector(`[data-jpaf-id="${f.id}"]`)?.closest('[data-controller~="forms--inputs--upload"]')!==root);
    let id=root.getAttribute('data-jpaf-id');
    if(!id) {id=`tt-upload-${index}`;while(document.querySelector(`[data-jpaf-id="${id}"]`))id=`tt-upload-${++index}`;}
    root.setAttribute('data-jpaf-id',id);
    const label=root.querySelector('label');
    fields.push({id,label:label ? clean(label) : '',name:root.id,type:'file',adapter:'teamtailor_upload',
      required:root.getAttribute('data-forms--inputs--upload-required-value')==='true',options:null});
  });
  for(const f of fields) {
    const e=document.querySelector(`[data-jpaf-id="${f.id}"]`);
    if(!e?.closest('form[data-controller~="careersite--form"]')) continue;
    const legend=['radio','checkbox'].includes(e.type) ? e.closest('fieldset')?.querySelector('legend') : null;
    const label=legend?.querySelector(':scope > span') || legend || e.labels?.[0];
    if(label) {
      f.label=clean(label);
      f.required=Boolean(f.required || label.querySelector('[data-asterisk="true"]') ||
        [...label.querySelectorAll('.sr-only')].some(x=>/^required\.?$/i.test(x.textContent.trim())));
    }
    if(legend) {
      const help=legend.querySelector(':scope > div');
      if(help) f.description=clean(help);
    }
    if(['radio','checkbox'].includes(e.type)) {
      const group=[...e.form.elements].filter(x=>x.type===e.type && x.name===e.name);
      f.adapter='teamtailor_choice';
      f.option_values=group.map(x=>({label:x.labels?.[0] ? clean(x.labels[0]) : x.value,value:x.value}));
      f.options=f.option_values.map(x=>x.label);
    }
  }
  return fields;
}
