// Fictional reproduction of the public controller's upload/preview contract.
const root=document.querySelector('#upload_resume_field');
root.dropzone={files:[]};
if(location.pathname.endsWith('-stale')) root.dropzone.files=[{name:'cv.pdf',url:'/existing-unverified.pdf'}];
root.querySelector('input[type=file]').onchange=e=>{
  let file=e.target.files[0];
  if(location.pathname.endsWith('-wrong-bytes'))file=new File(['Not the verified CV'],file.name,{type:'application/pdf'});
  root.dataset.uploadAttempts=String(Number(root.dataset.uploadAttempts||0)+1);
  file.status='uploading';root.dropzone.files=[file];
  const replacement=e.target.cloneNode();replacement.value='';replacement.disabled=true;e.target.replaceWith(replacement);
  const preview=document.createElement('div');file.previewElement=preview;
  preview.innerHTML='<span>cv.pdf</span><input type="hidden" name="candidate[resume_remote_url]" disabled data-forms--inputs--upload-preview-target="urlInput">';
  root.append(preview);
  const xhr=new XMLHttpRequest();file.xhr=xhr;
  xhr.open('POST','/upload'+location.pathname);
  xhr.onload=()=>{
    if(xhr.status>=200 && xhr.status<300){
      file.status='success';const url=xhr.getResponseHeader('Location');
      preview.setAttribute('data-forms--inputs--upload-preview-url-value',url);
      const input=preview.querySelector('input');input.disabled=false;
      input.value=location.pathname.endsWith('-mismatch') ? url+'-wrong' : url;
    }else{file.status='error';root.dropzone.files=[];replacement.disabled=false;}
  };
  if(location.pathname.endsWith('-pending'))return;
  const body=new FormData();body.append('file',file);xhr.send(body);
};
