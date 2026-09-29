// Supplement the reused scanner with Ashby's observed semantic field containers.
// Hash-suffixed CSS class names are never used as selectors.
(fields) => {
  const roots = [...document.querySelectorAll('.ashby-application-form-question-title')]
    .map(label => ({label, root:label.parentElement}));
  for (const {label,root} of roots) {
    if (!root.getClientRects().length) continue;
    const title=label.innerText.trim();
    const required=label.getAttribute('aria-required')==='true' ||
      [...label.classList].some(c=>/^_required_/.test(c));
    const existing=fields.filter(f=> {
      const el=document.querySelector(`[data-jpaf-id="${f.id}"]`);
      return el && root.contains(el);
    });
    for (const f of existing) {
      f.label=title || f.label;
      f.required=f.required || required;
      f.name=root.getAttribute('data-field-path') || f.name;
      if(f.type==='file') f.adapter='ashby_upload';
      if(root.querySelector(`[data-jpaf-id="${f.id}"].ashby-application-form-input-date`)) {
        f.type='date';f.adapter='ashby_date';
      }
    }
    const group=root.querySelector('.ashby-application-form-input-yesno');
    if (group) {
      for(const f of existing) fields.splice(fields.indexOf(f),1);
      const id='jl-choice-'+roots.indexOf(roots.find(x=>x.root===root));
      group.setAttribute('data-jpaf-id',id);
      fields.push({id,label:title,name:root.getAttribute('data-field-path')||'',type:'button_group',required,
        options:[...group.querySelectorAll('button[data-option]')].map(b=>b.innerText.trim())});
    } else if (!existing.length && required) {
      const id='jl-unsupported-'+fields.length;
      root.setAttribute('data-jpaf-id',id);
      fields.push({id,label:title,type:'unsupported',required:true,options:null});
    }
  }
  return fields;
}
