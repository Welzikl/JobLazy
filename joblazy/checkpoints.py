"""Reuse reviewed materials only while their inputs and saved files still match."""
from pathlib import Path
import copy
from .common import NeedsInput, digest, read_json, write_json


def material_profile_hash(profile):
    # Full profile binding for observed forms and legacy document checkpoints.
    return digest({k:v for k,v in profile.items() if k != 'answers'})


def document_profile_hash(profile,*,legacy=False):
    """Ignore form/discovery-only inputs; preserve the historical v2 binding."""
    from .materials import source_facts
    excluded={'answers'} if legacy else {'answers','discovery_preferences'}
    inputs=copy.deepcopy({k:v for k,v in profile.items() if k not in excluded})
    applicant=inputs.get('applicant',{})
    for group,keys in (
        ('identity',('full_name','first_name','last_name','email','phone')),
        ('links',('github','portfolio','website'))):
        if isinstance(applicant.get(group),dict):
            for key in keys:applicant[group].pop(key,None)
            if not applicant[group]:applicant.pop(group)
    # Printed identity remains bound through resume.candidate; callers also
    # validate consistency with applicant.identity. Residence stays bound.
    # A future evidence extractor change must invalidate existing documents.
    inputs['candidate_facts']=source_facts(profile)
    return digest(inputs)


def resume_material_hash(profile):
    # Only a live session retains the original profile needed to prove this
    # narrower comparison. Do not rebind legacy persisted checkpoints to it.
    # Follow the same evidence extractor used by ranking/tailoring, so future
    # applicant-derived evidence cannot silently escape material validation.
    # Identity consistency is checked by require_profile.
    from .materials import source_facts
    inputs={k:v for k,v in profile.items() if k not in ('answers','applicant','discovery_preferences')}
    inputs['candidate_facts']=source_facts(profile)
    return digest(inputs)


def save_materials(directory, source_job, job, profile, ranking, artifact):
    directory=Path(directory)
    record={'version':3,'source_job_hash':digest(source_job),'job':job,
        'profile_material_hash':material_profile_hash(profile),'ranking':ranking,'artifact':artifact,
        'profile_document_hash':document_profile_hash(profile),
        'files':{name:digest((directory/name).read_bytes()) for name in ('material.json','ranking.json','cv.json','cv.html','cv.pdf')}}
    write_json(directory/'materials-checkpoint.json',record)
    return record


def load_materials(directory, source_job, profile):
    directory=Path(directory)
    try:
        record=read_json(directory/'materials-checkpoint.json')
        from .profiles import check_profile
        if not check_profile(profile)['valid']:return None
        if record['version'] not in (1,2,3) or record['source_job_hash']!=digest(source_job): return None
        if record['version']==1:
            if record['profile_material_hash']!=material_profile_hash(profile): return None
        elif record['profile_document_hash']!=document_profile_hash(profile,legacy=record['version']==2):return None
        if set(record['files'])!={'material.json','ranking.json','cv.json','cv.html','cv.pdf'}: return None
        for name,expected in record['files'].items():
            if digest((directory/name).read_bytes())!=expected: return None
        artifact=record['artifact']
        if Path(artifact['path']).resolve()!=(directory/'cv.pdf').resolve(): return None
        if artifact['sha256']!=record['files']['cv.pdf'] or artifact['pages']!=1: return None
        material=read_json(directory/'material.json')
        if material['job_hash']!=digest(record['job']): return None
        if not material['review']['supported'] or material['review']['issues']: return None
        from .materials import source_facts, validate_claims
        if not isinstance(material.get('claims'), list) or not material['claims']: return None
        validate_claims(material['claims'], source_facts(profile))
        if record['ranking']!=read_json(directory/'ranking.json'): return None
        return record
    except (OSError,ValueError,KeyError,TypeError,NeedsInput):
        return None
