// Read Teamtailor/Dropzone's native File, completed XHR and submitted URL carrier.
async id => {
  const root=document.querySelector(`[data-jpaf-id="${id}"]`);
  if(!root?.dropzone) return {state:'unsupported',files:[],reason:'Upload controller unavailable'};
  const files=root.dropzone.files || [];
  if(!files.length) return {state:'empty',files:[]};
  if(files.length!==1) return {state:'invalid',files:[],reason:'Multiple uploaded files'};
  const file=files[0];
  if(!(file instanceof File)) return {state:'invalid',files:[],reason:'Existing remote attachment has no verifiable local File'};
  if(file.status==='error' || file.status==='canceled') return {state:'failed',files:[],reason:'Upload failed or was canceled'};
  if(file.status!=='success') return {state:'pending',files:[]};
  const xhr=file.xhr,preview=file.previewElement;
  if(!xhr || xhr.readyState!==4 || xhr.status<200 || xhr.status>=300 || !preview?.isConnected || !root.contains(preview))
    return {state:'invalid',files:[],reason:'Missing successful upload response or preview'};
  let remote=xhr.getResponseHeader('Location');
  if(remote) {try{remote=decodeURIComponent(remote);}catch{return {state:'invalid',files:[],reason:'Invalid upload response URL'};}}
  else remote=xhr.responseText?.match(/<Location>(.*?)<\/Location>/i)?.[1];
  const carrier=preview.querySelector('[data-forms--inputs--upload-preview-target="urlInput"]');
  if(!remote || preview.getAttribute('data-forms--inputs--upload-preview-url-value')!==remote ||
      !carrier?.name || carrier.disabled || carrier.value!==remote || carrier.form!==root.closest('form'))
    return {state:'invalid',files:[],reason:'Uploaded file URL does not match the application form'};
  const entries=new FormData(carrier.form).getAll(carrier.name);
  if(entries.length!==1 || entries[0]!==remote) return {state:'invalid',files:[],reason:'Ambiguous submitted attachment reference'};
  const hash=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
  return {state:'complete',files:[{name:file.name,sha256:[...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,'0')).join(''),remote_url:remote,
    upload_status:xhr.status,form_field:carrier.name}],verification:'native File hash, successful XHR and matching form reference'};
}
