"""Resolve an observed application question with an explicit operator answer."""
from pathlib import Path
from datetime import datetime,timezone
from .common import NeedsInput, read_json, write_json,digest
from .checkpoints import material_profile_hash
from .mapping import plan_fields,CREDENTIAL
from .profiles import load_profile


def observed_fields(report):
    if 'fields' in report:return report['fields']
    # Older preparation reports retain the scan in their last fill round.
    rounds=report.get('rounds',[])
    return rounds[-1].get('plan',{}).get('_scanMeta',[]) if rounds else []


def questions(store, key, directory,profile=None):
    row=store.get(key)
    directory=Path(directory);browser=directory/'browser.json';inventory=directory/'form-inventory.json'
    use_inventory=inventory.exists() and (not browser.exists() or inventory.stat().st_mtime_ns>browser.stat().st_mtime_ns)
    try: report=read_json(inventory if use_inventory else browser)
    except (OSError,ValueError): report={}
    if use_inventory:
        if report.get('version')!=1 or report.get('source_job_hash')!=digest(row['data']):
            report={'method':'read_only_inventory','reason':'Posting changed since inspection; inspect this application again'}
        elif profile is not None and report.get('profile_material_hash')!=material_profile_hash(profile):
            report={'method':'read_only_inventory','reason':'Profile changed since inspection; inspect this application again'}
        elif profile is not None and report.get('scope'):
            report={**report,'unresolved':plan_fields(report.get('fields',[]),profile,report['scope'],job=row['data'])['unresolved']}
    elif profile is not None and report.get('scope'):
        resolved={f['id'] for f in plan_fields(observed_fields(report),profile,report['scope'],job=row['data'])['fields']}
        # Refresh only the observed unanswered fields. Do not reintroduce
        # independently reviewed narrative drafts or claim a new browser check.
        report={**report,'unresolved':[q for q in report.get('unresolved',[]) if q.get('id') not in resolved]}
    fields={f['id']:f for f in observed_fields(report)}
    preserved={f['id'] for f in report.get('preserved_edits',[])}
    verification_issues=[{'field':fields.get(key,{}).get('label') or key,
        'reason':'Browser edit differs from the saved answer; left unchanged' if key in preserved else 'Last browser value or selection did not pass verification'}
        for key in report.get('unverified',[])]
    verification_issues.extend({'field':'Application', 'reason':issue['message']}
                               for issue in report.get('application_blockers',[]))
    return {'id':key,'title':row['data']['title'],'status':row['status'],
        'scope':report.get('scope'),'questions':report.get('unresolved',[]),
        'method':report.get('method','browser_preparation' if report.get('scope') else None),
        'missing_files':report.get('missing_files',[]),
        'verification_issues':verification_issues,
        'reason':report.get('reason') or (row['result'] or {}).get('reason'),
        'cv':report.get('artifact',{}).get('path') or (row['result'] or {}).get('artifact',{}).get('path')}


def save_answer(store,key,directory,profile_path,question,value):
    profile=load_profile(profile_path)
    observed=questions(store,key,directory,profile)
    allowed={'needs_input','retryable','manual_review'}
    if observed['method']=='read_only_inventory':allowed|={'discovered','ranked','materials_ready','prepared'}
    if observed['status'] not in allowed:
        raise NeedsInput('Answers can only resolve an input exception before submission')
    matches=[q for q in observed['questions'] if q['field']==question]
    # An explicit correction to an already-saved scoped answer remains possible
    # after show --profile stops listing that field as unresolved.
    if not matches and any(
            a.get('question')==question and a.get('scope')==observed['scope'] for a in profile.get('answers',[])):
        filename='form-inventory.json' if observed['method']=='read_only_inventory' else 'browser.json'
        fields=observed_fields(read_json(Path(directory)/filename))
        matches=[{'field':question,'options':f.get('options'),'reason':'Existing scoped answer'}
            for f in fields if (f.get('label') or f.get('name') or '')==question]
    if not observed['scope'] or len(matches)!=1:
        raise NeedsInput(observed.get('reason') or 'Question must exactly match an observed unresolved application question')
    if CREDENTIAL.search(question) or matches[0]['reason']=='Account authentication needed':
        raise NeedsInput('Account credentials must not be stored as application answers')
    if matches[0].get('options') and value not in matches[0]['options']:
        raise NeedsInput('Answer must exactly match one of the observed choices')
    if not str(value).strip(): raise NeedsInput('Answer must not be empty')
    answers=profile.setdefault('answers',[])
    scope=observed['scope']
    answers[:]=[a for a in answers if not (a.get('scope')==scope and a.get('question')==question)]
    answers.append({'question':question,'scope':scope,'value':value,
        'source':{'method':'operator_supplied','job_id':key,'recorded_at':datetime.now(timezone.utc).isoformat()}})
    write_json(profile_path,profile)
    target='retryable' if observed['status'] in {'needs_input','retryable'} else observed['status']
    if target=='retryable':
        store.transition(key,target,{'reason':'Operator supplied a scoped answer','question':question},
            expected={'needs_input','retryable'})
    return {'id':key,'status':target,'question':question,'scope':scope,'profile':str(Path(profile_path).resolve())}
