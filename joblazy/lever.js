// Semantic containers observed on Lever's public application forms.
(fields) => {
  for(const f of fields) {
    const e=document.querySelector(`[data-jpaf-id="${f.id}"]`);
    const root=e?.closest('.application-question');
    const label=root?.querySelector('.application-label');
    if(!root || !label) continue;
    const copy=label.cloneNode(true);
    copy.querySelectorAll('.required,[aria-hidden=true]').forEach(x=>x.remove());
    const title=copy.textContent.trim().replace(/\s+/g,' ');
    if(title) f.label=title;
    f.required=Boolean(f.required || label.querySelector('.required'));
    if(e.matches('input.location-input') && root.querySelector('input[name=selectedLocation]')) {
      f.adapter='lever_location'; f.combo=true;
      const results=root.querySelector('.dropdown-results');
      const options=[...(results?.children||[])].filter(x=>x.getClientRects().length).map(x=>x.innerText.trim()).filter(Boolean);
      if(options.length) f.options=options;
    }
  }
  return fields;
}
