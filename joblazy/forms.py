"""Locate one visible application frame without assuming the outer page owns it."""
import time
import re
from urllib.parse import urlsplit,urlunsplit
from .common import NeedsInput

EMAIL_SELECTOR='input[type=email]:visible,input[name*=email i]:visible,input[id=email]:visible,input[autocomplete=email]:visible'

def application_root(frame):
    root=frame.locator('[data-joblazy-form-root]')
    return root if root.count()==1 else frame

def is_application(root):
    # A styled upload input can itself be hidden, but its parent must be visible.
    # Otherwise a closed application overlay plus an unrelated login email looks
    # like an application frame before the actual form has opened.
    files=root.locator('input[type=file]').evaluate_all('es=>es.filter(e=>e.getClientRects().length || e.parentElement?.getClientRects().length).length')
    emails=root.locator(EMAIL_SELECTOR).count()
    next_buttons=root.get_by_role('button',name=re.compile(r'^(next|continue|next step|save and continue)$',re.I)).filter(visible=True).count()
    return (files and emails) or (next_buttons and (files or emails))

def application_url(url):
    parsed=urlsplit(url)
    path=parsed.path.rstrip('/')
    suffix={'jobs.ashbyhq.com':'/application','jobs.lever.co':'/apply'}.get(parsed.hostname)
    if suffix and len(path.split('/'))==3: path+=suffix
    return urlunsplit((parsed.scheme,parsed.netloc,path,parsed.query,parsed.fragment))

def visible_frames(page):
    for frame in page.frames:
        if frame.is_detached(): continue
        try:
            if frame==page.main_frame or frame.frame_element().is_visible(): yield frame
        except Exception: continue


def open_application_form(page,timeout=8):
    """Open the observed Teamtailor overlay; never click generic Apply controls."""
    entry=page.locator('button[data-careersite--jobs--form-overlay-target="coverButton"][data-action*="careersite--jobs--form-overlay#showFormOverlay"]').filter(visible=True)
    if entry.count():
        if entry.count()!=1: raise NeedsInput('Multiple Teamtailor application entry controls')
        decline=page.locator('button[data-action="click->common--cookies--alert#disableAll"]').filter(visible=True)
        if decline.count()==1: decline.click(timeout=5000)
        if not entry.is_enabled(): raise NeedsInput('Teamtailor application entry is disabled')
        entry.click(timeout=10000)
    return locate_form(page,timeout=timeout)

def locate_form(page,timeout=8):
    deadline=time.monotonic()+timeout
    while True:
        candidates=[]
        for frame in visible_frames(page):
            try:
                if is_application(frame): candidates.append(frame)
            except Exception: continue
        if len(candidates)==1:
            frame=candidates[0]
            forms=[f for f in frame.locator('form').all() if is_application(f)]
            if len(forms)>1: raise NeedsInput('Multiple visible application forms in the same frame')
            if forms: forms[0].evaluate("e=>e.setAttribute('data-joblazy-form-root','true')")
            return frame
        if len(candidates)>1:raise NeedsInput('Multiple visible application forms; cannot choose an exact target')
        if time.monotonic()>=deadline:raise NeedsInput('No visible application form with résumé/contact fields and application controls found')
        page.wait_for_timeout(200)
