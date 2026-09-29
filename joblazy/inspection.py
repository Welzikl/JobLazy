"""Observe public application questions without entering or uploading candidate data."""
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit
from .browser import scan,public_url
from .checkpoints import load_materials,material_profile_hash
from .common import NeedsInput,digest,write_json
from .forms import application_url,open_application_form
from .mapping import plan_fields
from .profiles import require_profile
from .routes import resolve_application


def inspect_application(store,key,profile,browser,directory,*,fixture_origin=None):
    require_profile(profile)
    row=store.get(key);directory=Path(directory)
    if row['status'] in {'processing','submitting','submitted','submission_unknown','manual_review'}:
        raise NeedsInput('Inspect an unsubmitted job outside an active processing or manual-review session')
    checkpoint=load_materials(directory,row['data'],profile)
    job=checkpoint['job'] if checkpoint else row['data']
    report={'version':1,'method':'read_only_inventory','source_job_hash':digest(row['data']),
        'profile_material_hash':material_profile_hash(profile),'observed_at':datetime.now(timezone.utc).isoformat(),
        'candidate_data_entered':False,'files_uploaded':False,'submitted':False,
        'scope':None,'fields':[],'unresolved':[],'missing_files':[]}
    page=None
    try:
        if fixture_origin is None:job=resolve_application(job,browser,directory)
        scope=job.get('application_url') or job['url'];url=application_url(scope)
        if fixture_origin is not None:
            parsed=urlsplit(url)
            if parsed.hostname not in {'127.0.0.1','localhost'} or f'{parsed.scheme}://{parsed.netloc}'!=fixture_origin:
                raise NeedsInput('Fictional inspection must stay on its exact local origin')
        elif not public_url(url):raise NeedsInput('Application URL must be public HTTPS')
        page=browser.new_page()
        checked={}
        def guard(route):
            parsed=urlsplit(route.request.url);origin=f'{parsed.scheme}://{parsed.netloc}'
            if fixture_origin is not None:allowed=origin==fixture_origin
            else:
                if origin not in checked:checked[origin]=public_url(route.request.url)
                allowed=checked[origin]
            route.continue_() if allowed else route.abort()
        page.route('**/*',guard)
        response=page.goto(url,wait_until='domcontentloaded',timeout=45000)
        if not response or not response.ok:raise NeedsInput('Application page is unavailable')
        if page.locator('input[type=password]:visible').count():raise NeedsInput('Employer sign-in is required')
        form=open_application_form(page,timeout=12)
        fields=scan(form)
        # The profile is used only by the local mapper, never passed to the page.
        plan=plan_fields(fields,profile,scope,job=job)
        report.update({'state':'inspected','scope':scope,'url':page.url,'form_url':form.url,
            'fields':fields,'unresolved':plan['unresolved'],
            'mapped_fields':[{k:f[k] for k in ('id','source_ref','job_source_ref') if k in f} for f in plan['fields']]})
    except NeedsInput as error:report.update({'state':'needs_input','reason':str(error)})
    except Exception as error:report.update({'state':'needs_input','reason':type(error).__name__+': '+str(error)})
    finally:
        try:
            if page:page.close()
        finally:write_json(directory/'form-inventory.json',report)
    return {'id':key,'status':row['status'],'inspection':report['state'],'scope':report.get('scope'),
        'fields':len(report['fields']),'required_unresolved':sum(bool(q.get('required')) for q in report['unresolved']),
        'reason':report.get('reason'),'path':str((directory/'form-inventory.json').resolve()),
        'candidate_data_entered':False,'files_uploaded':False,'submitted':False}
