// Observe the public file component, without reading framework internals.
// A native FileList alone does not establish that the form accepted the file.
async (id) => {
  const picker=document.querySelector(`[data-jpaf-id="${id}"]`);
  const root=picker?.closest('.ashby-application-form-input-file');
  const result={state:'unverified',files:[],selected_files:[],displayed_names:[],item_count:0,
    evidence:'Selected file hash plus completed Ashby file display; submission acceptance not established'};
  if(!root || picker.type!=='file')return result;
  for(const file of [...(picker.files||[])]) {
    const hash=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
    result.selected_files.push({name:file.name,
      sha256:[...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,'0')).join('')});
  }
  const visible=e=>Boolean(e?.getClientRects().length) && getComputedStyle(e).visibility!=='hidden';
  const items=[...root.querySelectorAll('.ashby-application-form-input-file-item')].filter(visible);
  result.item_count=items.length;
  result.displayed_names=items.map(item=>item.querySelector('.ashby-application-form-input-file-item-name')?.innerText.trim()||'');
  const buttons=[...root.querySelectorAll('.ashby-application-form-input-file-dropzone-upload')].filter(visible);
  const enabled=e=>Boolean(e) && !e.disabled && e.getAttribute('aria-disabled')!=='true';
  if(!result.selected_files.length) {
    result.state=items.length ? 'unverified' : 'empty';
    return result;
  }
  result.state='pending';
  if(items.length!==1 || buttons.length!==1)return result;
  const remove=items[0].querySelector('.ashby-application-form-input-file-item-delete');
  if(!visible(remove) || !enabled(remove) || !enabled(buttons[0]) || picker.disabled)return result;
  if(result.selected_files.length!==1 || result.displayed_names[0]!==result.selected_files[0].name ||
     buttons[0].innerText.trim()!=='Replace') {
    result.state='unverified';return result;
  }
  result.state='complete';result.files=result.selected_files;
  return result;
}
