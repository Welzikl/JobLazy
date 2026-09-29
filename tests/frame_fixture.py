"""Fictional two-origin application with server-saved contact data and a replaced iframe."""
import json
import threading
from contextlib import contextmanager
from html import escape
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlsplit


@contextmanager
def replacing_frame_server(unknown=False,ambiguous=False,authentication=False):
    origins={};saved={};received=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,body,kind='text/html'):
            self.send_response(200);self.send_header('Content-Type',kind+'; charset=utf-8')
            self.end_headers();self.wfile.write(body.encode())
        def do_GET(self):
            path=urlsplit(self.path).path
            if path=='/outer':
                body='''<html><body><form><label>Newsletter email<input type="email" required name="newsletter"></label>
                <button>Subscribe</button></form><div role="status">Application received.</div>
                <iframe id="application" style="width:950px;height:750px" src="'''+origins['frame']+'''/step1"></iframe>
                <script>window.addEventListener('message',e=>{
                    const old=document.querySelector('#application');
                    if(e.origin!=='''+json.dumps(origins['frame'])+'''||e.source!==old.contentWindow||e.data!=='next')return;
                    const next=old.cloneNode();next.src='''+json.dumps(origins['frame']+'/step2')+''';old.replaceWith(next);
                    '''+('const other=next.cloneNode();other.id="other-application";next.after(other);' if ambiguous else '')+'''
                });</script></body></html>'''
            elif path=='/step1':
                body='''<html><body><form><label>Full name<input required name="name"></label>
                <label>Email<input type="email" required name="email"></label><button type="submit">Next</button></form>
                <script>document.querySelector('form').onsubmit=async e=>{
                    e.preventDefault();const r=await fetch('/save',{method:'POST',body:JSON.stringify(Object.fromEntries(new FormData(e.target)))});
                    if(r.ok)parent.postMessage('next','''+json.dumps(origins['outer'])+''');
                };</script></body></html>'''
            elif path=='/step2':
                question='<label>Work authorization<select name="authorization" required><option value="">Choose</option><option>Yes</option><option>No</option></select></label>' if unknown else ''
                if authentication:question+='<label>Password<input type="password" name="password" required></label>'
                body='''<html><body><form><label>Full name<input readonly name="name" value="'''+escape(saved.get('name',''),quote=True)+'''"></label>
                <label>Email<input type="email" readonly name="email" value="'''+escape(saved.get('email',''),quote=True)+'''"></label>
                <label>Resume<input type="file" name="resume" required></label><label>Phone Number<input type="tel" name="phone" required></label>
                '''+question+'''<button type="submit">Submit application</button></form><div role="status"></div>
                <script>document.querySelector('form').onsubmit=async e=>{
                    e.preventDefault();const r=await fetch('/submit',{method:'POST',body:new FormData(e.target)});
                    if(r.ok){e.target.remove();document.querySelector('[role=status]').textContent='Application received. Thank you for applying.';}
                };</script></body></html>'''
            else:body='<html><body>Not an application</body></html>'
            self.respond(body)
        def do_POST(self):
            body=self.rfile.read(int(self.headers.get('Content-Length','0')))
            if self.path=='/save':saved.update(json.loads(body))
            elif self.path=='/submit':received.append(body)
            self.respond('{}','application/json')
    servers=[ThreadingHTTPServer(('127.0.0.1',0),Handler) for _ in range(2)]
    origins.update(dict(zip(('outer','frame'),[f'http://127.0.0.1:{s.server_port}' for s in servers])))
    threads=[threading.Thread(target=s.serve_forever,daemon=True) for s in servers]
    for thread in threads:thread.start()
    try:yield origins,saved,received
    finally:
        for server in servers:server.shutdown();server.server_close()
        for thread in threads:thread.join()
