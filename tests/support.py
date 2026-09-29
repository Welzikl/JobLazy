"""Fictional test fixtures. This model is NOT a runtime inference substitute."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from contextlib import contextmanager
from urllib.parse import urlsplit
from joblazy.common import ROOT, read_json

def example_profile(): return read_json(ROOT/'examples/profile.json')

class FixtureModel:
    def generate(self, task, data, schema):
        if 'Draft a factual application answer' in task:
            return {'answerable':True,'missing_facts':[],'claims':[{
                'text':'I coordinated onboarding for 20 partners and created weekly reporting for the partnerships team.',
                'source_ids':['experience.0.0','experience.0.1']}]}
        if 'Rank this' in task:
            return {'score':85,'reason':'Fixture ranking only',
                'dimensions':{key:{'score':4 if key=='cv_fit' else None,
                    'explanation':'Fictional evidence' if key=='cv_fit' else 'Insufficient information',
                    'job_quotes':['partner onboarding'] if key=='cv_fit' else [],
                    'candidate_source_ids':['experience.0.0'] if key=='cv_fit' else []}
                    for key in ('cv_fit','career_direction','compensation','culture','red_flags')},
                'evidence':[{'quote':'partner onboarding','explanation':'Fixture evidence'}],
                'candidate_source_ids':['experience.0.0'],'missing_facts':[],
                'fit_category':'strong_match',
                'requirements':[{'requirement':'Partner onboarding','job_quote':'partner onboarding',
                    'kind':'responsibility','status':'met','candidate_source_ids':['experience.0.0'],'explanation':'Direct fictional experience'}]}
        if 'Tailor the CV' in task:
            return {'summary':{'text':'Operations specialist experienced in partner onboarding.', 'source_ids':['summary']},
                'experience':[{'index':0,'bullets':[
                    {'text':'Coordinated onboarding for 20 partners.', 'source_ids':['experience.0.0']},
                    {'text':'Created weekly reporting for the partnerships team.', 'source_ids':['experience.0.1']},
                    {'text':'Reduced onboarding handoff delays by 15% using a shared checklist.', 'source_ids':['experience.0.2']}]}], 'project_indices':[]}
        return {'supported':True,'issues':[],**({'missing_facts':[]} if 'missing_facts' in schema['properties'] else {})}

def job(url,title='Partner Operations Associate'):
    return {'url':url,'title':title,'company':'Fictional Software Ltd','location':'London',
        'description':'Help improve partner onboarding and weekly reporting. This role is based in London. Work with the partnerships team to coordinate onboarding, document handoffs, maintain shared checklists, and communicate progress through a weekly reporting cadence.','ats':'fixture'}

@contextmanager
def fixture_server():
    received = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            mode = urlsplit(self.path).path.strip('/')
            if mode == 'redirected':
                body = '<html><body><h1>Another page</h1></body></html>'
            elif mode.startswith('ashby-upload-'):
                body=(ROOT/'tests/fixtures/ashby-upload.html').read_text(encoding='utf-8')
            elif mode.startswith('teamtailor'):
                body=(ROOT/'tests/fixtures/teamtailor.html').read_text(encoding='utf-8')
                if mode.startswith('teamtailor-upload'):
                    body=body.replace('<div><label for="candidate_resume_remote_url">','<div id="upload_resume_field" data-controller="forms--inputs--upload" data-forms--inputs--upload-required-value="true"><label for="candidate_resume_remote_url">')
                    body=body.replace('</body>','<script>'+(ROOT/'tests/fixtures/teamtailor-upload.js').read_text(encoding='utf-8')+'</script></body>')
            elif mode in ('embedded','ambiguous'):
                body = '<html><body><label>Newsletter email<input type="email" name="newsletter"></label><iframe title="Application" src="/success" style="width:900px;height:800px"></iframe>'
                if mode == 'ambiguous': body += '<iframe title="Another application" src="/success" style="width:900px;height:800px"></iframe>'
                body += '</body></html>'
            elif mode=='unrelated_receipt':
                body='<html><body><div role="status" id="unrelated"></div><iframe src="/parent_receipt" style="width:900px;height:800px"></iframe></body></html>'
            elif mode in ('multistep','multistep_unknown'):
                question='<label>Work authorization<select required name="authorization"><option value="">Choose</option><option>Yes</option><option>No</option></select></label>' if mode.endswith('unknown') else '<label>Phone Number<input name="phone" type="tel" required></label>'
                body='''<!doctype html><html><body><h1>Fictional application</h1>
                <form id="application"><label>Full name<input name="name" required></label>
                <label>Email<input name="email" type="email" required></label>
                <button type="button" id="next">Next</button></form><div role="status"></div>
                <script>let saved;
                document.querySelector('#next').onclick=()=>{
                  const form=document.querySelector('form');if(!form.reportValidity())return;
                  saved=new FormData(form);
                  form.innerHTML='''+json.dumps('<label>Resume<input name="resume" type="file" required></label>'+question+'<button type="submit">Submit application</button>')+''';
                };
                document.querySelector('form').onsubmit=async e=>{
                  e.preventDefault();for(const [key,value] of new FormData(e.target))saved.set(key,value);
                  const response=await fetch('/submit/'''+mode+'''',{method:'POST',body:saved});
                  if(response.ok){e.target.remove();document.querySelector('[role=status]').textContent='Application received. Thank you for applying.';}
                };</script></body></html>'''
            elif mode == 'lever':
                body='''<!doctype html><html><body><form id="application-form">
                <label>Full name<input name="name" required></label><label>Email<input name="email" type="email" required></label>
                <li class="application-question resume"><label><div class="application-label">Resume/CV <span class="required">*</span></div>
                <div class="application-field"><input type="file" name="resume"><span>Analyzing resume...</span></div></label></li>
                <li class="application-question"><label><div class="application-label">Current location <span class="required">*</span></div>
                <div class="application-field"><input class="location-input" name="location" required><input type="hidden" name="selectedLocation">
                <div class="dropdown-results"></div></div></label></li>'''
                for name,label in [('authorization','Are you authorized to work here?'),('sponsorship','Do you require sponsorship?')]:
                    body+='<li class="application-question custom-question"><div class="application-label"><div class="text">'+label+'<span class="required">*</span></div></div><div class="application-field"><ul>'
                    for value in ('Yes','No'):
                        body+='<li><label><input type="radio" name="'+name+'" value="'+value+'" required><span>'+value+'</span></label></li>'
                    body+='</ul></div></li>'
                body+='''<button type="submit">Submit application</button></form><div role="status"></div><script>
                document.querySelector('.location-input').oninput=e=>{
                  document.querySelector('[name=selectedLocation]').value='';
                  const choices=document.querySelector('.dropdown-results');choices.innerHTML='<div>London, United Kingdom</div>';
                  choices.firstChild.onclick=()=>{e.target.value='London, United Kingdom';document.querySelector('[name=selectedLocation]').value='provider-location-id';choices.innerHTML='';};
                };
                document.querySelector('form').onsubmit=async e=>{
                  e.preventDefault();const r=await fetch('/submit/lever',{method:'POST',body:new FormData(e.target)});
                  if(r.ok){e.target.remove();document.querySelector('[role=status]').textContent='Application received.';}
                };</script></body></html>'''
            else:
                unknown = '<label>Work authorization<select name="authorization" required><option value="">Choose</option><option>Yes</option><option>No</option></select></label>' if mode in ('unknown','resume','current_authorization','friend') else ''
                if mode=='current_authorization':
                    unknown=unknown.replace('Work authorization','Are you currently legally authorized to work in the country to which you are applying?')
                    unknown+='<label>Will you require sponsorship now or in the future?<select name="sponsorship" required><option value="">Choose</option><option>Yes</option><option>No</option></select></label>'
                body = '''<!doctype html><html><head><title>Fictional application</title></head><body>
                <h1>Partner Operations Associate</h1><form id="application">
                <label>Full name<input name="name" required></label>
                <label>Email<input name="email" type="email" required></label>
                <label>City<select name="city" required><option value="">Choose</option><option>London</option><option>Manchester</option></select></label>
                <label>Resume<input name="resume" type="file" required></label>'''+unknown+'''
                <label>Optional portfolio<input name="portfolio" type="url"></label>
                <button type="submit">Submit application</button></form><div role="status"></div>
                <script nonce="fixture">document.querySelector('form').addEventListener('submit',async e=>{
                  e.preventDefault(); const payload=new FormData(e.target);
                  if('''+json.dumps(mode)+'''==='greenhouse') payload.set('email',document.querySelector('#email').value);
                  const r=await fetch('/submit/'''+mode+'''',{method:'POST',body:payload});
                  if(!r.ok) return;
                  if('''+json.dumps(mode)+'''==='redirect') {location.href='/redirected';return;}
                  if('''+json.dumps(mode)+'''==='disappear') {e.target.remove();return;}
                  if('''+json.dumps(mode)+'''==='parent_receipt') {parent.document.querySelector('#unrelated').textContent='Application received.';e.target.remove();return;}
                  if('''+json.dumps(mode)+'''==='false_confirmation') {document.querySelector('[role=status]').textContent='Application received an error. Please try again.';return;}
                  if('''+json.dumps(mode)+'''==='conflicting_receipts') {document.querySelector('[role=status]').textContent='Application received.';const error=document.createElement('div');error.setAttribute('role','alert');error.textContent='Submission failed.';document.body.appendChild(error);return;}
                  if('''+json.dumps(mode)+'''==='stale_receipt') {document.querySelector('[role=status]').textContent='Application received. Status refreshed.';e.target.remove();return;}
                  document.querySelector('[role=status]').textContent='Application received. Thank you for applying.';
                  e.target.remove();
                });
                if('''+json.dumps(mode)+'''==='dynamic') document.querySelector('[name=city]').addEventListener('change',e=>{
                  if(e.target.dataset.updated) return; e.target.dataset.updated='yes';
                  const email=document.querySelector('[name=email]');
                  const replacement=email.cloneNode();replacement.value='';email.replaceWith(replacement);
                  const label=document.createElement('label');label.textContent='Phone Number';
                  const input=document.createElement('input');input.name='phone';input.type='tel';input.required=true;
                  label.appendChild(input);document.querySelector('form').prepend(label);
                });
                if('''+json.dumps(mode)+'''==='autofill') document.querySelector('[name=resume]').addEventListener('change',()=>{
                  document.querySelector('[name=name]').value='Incorrect Parsed Name';
                  document.querySelector('[name=email]').value='wrong@example.test';
                });</script></body></html>'''
                if mode=='greenhouse':
                    body=body.replace('<body>','<body><button>Apply</button><form id="newsletter"><label>Newsletter email<input type="email" required></label><button>Subscribe</button></form>')
                    body=body.replace('<input name="email" type="email" required>','<input id="email" type="text" required>')
                    body=body.replace('<label>Resume<input name="resume" type="file" required></label>','<span>Resume</span><input id="resume" aria-label="Attach" name="resume" type="file" required>')
                    body=body.replace("document.querySelector('form')","document.querySelector('#application')")
                if mode=='narrative':
                    body=body.replace('<button type="submit">Submit application</button>',
                        '<label>Describe your relevant experience<textarea name="experience" required maxlength="400" aria-describedby="experience-help"></textarea></label><p id="experience-help">Describe relevant partner onboarding work.</p><button type="submit">Submit application</button>')
                if mode=='graduate':
                    body=body.replace('<option>London</option>', '<option>Bristol</option>')
                    body=body.replace('<h1>Partner Operations Associate</h1>', '<h1>Graduate Reporting Assistant</h1>')
                if mode=='resume':
                    body=body.replace('<button type="submit">Submit application</button>',
                        '<label>Phone Number<input name="phone" type="tel"></label><label>Postal code<input name="postal" autocomplete="postal-code"></label><button type="submit">Submit application</button>')
                if mode=='stale_receipt':body=body.replace('<div role="status"></div>','<div role="status">Application received.</div>')
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
            if mode=='friend':body=body.replace('<option>Manchester</option>','<option>Manchester</option><option>Bristol</option>')
            if mode=='csp': self.send_header('Content-Security-Policy',"script-src 'nonce-fixture'; connect-src 'self'")
            self.end_headers(); self.wfile.write(body.encode())
        def do_POST(self):
            received.append({'path':self.path,'body':self.rfile.read(int(self.headers.get('Content-Length','0')))})
            if self.path.startswith('/upload/'):
                self.send_response(500 if self.path.endswith('-failed') else 201)
                self.send_header('Location',f'http://127.0.0.1:{self.server.server_port}/uploaded/cv.pdf')
                self.end_headers();self.wfile.write(b'Uploaded');return
            self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
    server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread = threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    try: yield f'http://127.0.0.1:{server.server_port}', received
    finally: server.shutdown(); server.server_close(); thread.join()
