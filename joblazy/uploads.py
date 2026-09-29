"""Bounded completion checks for an asynchronous application upload."""
import time
import re
import unicodedata
from pathlib import Path
from .common import ROOT, NeedsInput, digest


def cv_filename(profile, job):
    """Human-readable basename; posting text can never supply a path."""
    def part(value, limit, fallback):
        text=unicodedata.normalize('NFKD',str(value or '')).encode('ascii','ignore').decode()
        return re.sub(r'[^A-Za-z0-9]+','_',text).strip('_')[:limit].rstrip('_') or fallback
    candidate=profile.get('applicant',{}).get('identity',{}).get('full_name') or profile.get('resume',{}).get('candidate',{}).get('name')
    return '_'.join((part(candidate,36,'Candidate'),part(job.get('company'),36,'Company'),
                     part(job.get('title'),64,'Role'),'CV'))+'.pdf'


def cv_upload(artifact, filename):
    raw=Path(artifact['path']).read_bytes()
    if digest(raw)!=artifact['sha256']:raise NeedsInput('CV changed before upload')
    return {'name':filename,'mimeType':'application/pdf','buffer':raw}


def application_feedback(form):
    """Recognize observed rejection messages, not general mentions of spam."""
    text = form.locator('body').inner_text()
    rules = (
        ('spam_rejection', r'^(?:(?:this|your|the)\s+)?(?:application\s+)?(?:has been|was|is)\s+(?:marked|flagged)\s+as\s+(?:potential\s+)?spam\b[^\n]*$'),
        ('upload_failed', r'^.{1,180}\.(?:pdf|docx?|rtf)\s+failed to upload[.!]?$'),
        ('application_unavailable', r'^Application submission is unavailable at this time, please try again later\.$'),
    )
    return [{'kind':kind, 'message':line.strip()} for line in text.splitlines()
            for kind, pattern in rules if re.fullmatch(pattern,line.strip(),re.I)]


def upload_state(form,field):
    return form.evaluate((ROOT/'joblazy/upload-state.js').read_text(encoding='utf-8'),field['id'])


def ashby_upload_state(form,field):
    return form.evaluate((ROOT/'joblazy/ashby-upload-state.js').read_text(encoding='utf-8'),field['id'])


def attach_ashby_upload(page,form,field,artifact,attempted,timeout=15,filename=None):
    # Use the stable employer field path, not a scan index which may change.
    key=('ashby',field.get('name') or field['id'])
    first=key not in attempted
    attempted.add(key)
    state=ashby_upload_state(form,field)
    if first and state['state']=='empty':
        picker=form.locator(f'[data-jpaf-id="{field["id"]}"]')
        if picker.count()!=1 or picker.is_disabled():return state
        picker.set_input_files(cv_upload(artifact,filename or Path(artifact['path']).name))
        state=ashby_upload_state(form,field)
    deadline=time.monotonic()+(timeout if first else 0)
    while state['state']=='pending' and time.monotonic()<deadline:
        if application_feedback(form):break
        page.wait_for_timeout(200)
        state=ashby_upload_state(form,field)
    return state


def attach_upload(page,form,field,artifact,attempted,timeout=15,filename=None):
    state=upload_state(form,field)
    first=field['id'] not in attempted
    attempted.add(field['id'])
    if state['state']=='empty' and first:
        # Record before setting the file; replacement/error must not cause another
        # upload in the three form-filling passes of this same preparation.
        root=form.locator(f'[data-jpaf-id="{field["id"]}"]')
        picker=root.locator('input[type=file]')
        if picker.count()!=1 or picker.is_disabled():return state
        picker.set_input_files(cv_upload(artifact,filename or Path(artifact['path']).name))
        state=upload_state(form,field)
    deadline=time.monotonic()+(timeout if first else 0)
    while state['state']=='pending' and time.monotonic()<deadline:
        page.wait_for_timeout(200);state=upload_state(form,field)
    return state
