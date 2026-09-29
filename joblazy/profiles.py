"""Validate supplied profile structure and identity consistency without inventing facts."""
import re
from jsonschema import Draft202012Validator
from .common import NeedsInput,read_json

TEXT={'type':'string'}
CONTACT={'type':'object','properties':{k:TEXT for k in ('name','full_name','first_name','last_name','email','phone')}}
SCHEMA={'type':'object','required':['targeting','applicant','resume'],'properties':{
    'example_only':{'type':'boolean'},'minimum_score':{'type':'integer','minimum':0,'maximum':100},
    'targeting':{'type':['object','string']},
    'applicant':{'type':'object','required':['identity'],'properties':{'identity':{**CONTACT,'required':['full_name']}}},
    'resume':{'type':'object','required':['candidate','experience'],'properties':{
        'candidate':{**CONTACT,'required':['name']},'summary':TEXT,
        'experience':{'type':'array','items':{'type':'object','required':['company','role','bullets'],'properties':{
            'company':TEXT,'role':TEXT,'dates':TEXT,'location':TEXT,'bullets':{'type':'array','items':TEXT}}}},
        'education':{'type':'array','items':{'type':'object'}},'projects':{'type':'array','items':{'type':'object'}}}},
    'facts':{'type':'array','items':{'type':'object','required':['text'],'properties':{'text':TEXT}}},
    'answers':{'type':'array','items':{'type':'object','required':['question','scope','value'],'properties':{
        'question':TEXT,'scope':TEXT,'value':{'type':['string','number','boolean']}}}}
}}
VALIDATOR=Draft202012Validator(SCHEMA)


class InvalidProfile(NeedsInput):pass


def check_profile(profile):
    errors=[{'path':'.'.join(str(p) for p in e.absolute_path) or '(profile)',
             'message':f'Invalid structure: {e.validator} must be {e.validator_value}'} for e in VALIDATOR.iter_errors(profile)]
    warnings=[]
    if errors:return {'valid':False,'errors':errors,'warnings':warnings}
    identity=profile['applicant']['identity'];candidate=profile['resume']['candidate']
    normalize=lambda s:' '.join(s.split()).casefold()
    for field,cv_field in (('full_name','name'),('email','email'),('phone','phone')):
        form=identity.get(field,'');cv=candidate.get(cv_field,'')
        if field=='full_name':
            for path,value in [('applicant.identity.full_name',form),('resume.candidate.name',cv)]:
                if not value.strip():errors.append({'path':path,'message':'A nonempty candidate name is required'})
        comparable=(lambda s:re.sub(r'\D','',s)) if field=='phone' else normalize
        if form.strip() and cv.strip() and comparable(form)!=comparable(cv):
            errors.append({'path':f'applicant.identity.{field}',
                'message':f'Conflicts with resume.candidate.{cv_field}; correct the source profile before continuing'})
    for field in ('first_name','last_name','email','phone'):
        if not identity.get(field,'').strip():
            warnings.append({'path':f'applicant.identity.{field}','message':'Missing; application forms may require an explicit answer'})
    if profile.get('example_only',True):warnings.append({'path':'example_only','message':'Employer preparation is disabled for an example profile'})
    return {'valid':not errors,'errors':errors,'warnings':warnings}


def require_profile(profile):
    report=check_profile(profile)
    if not report['valid']:
        raise InvalidProfile('Profile needs correction: '+'; '.join(e['path']+': '+e['message'] for e in report['errors']))
    return profile


def load_profile(path):
    try:profile=read_json(path)
    except (OSError,ValueError) as e:raise InvalidProfile('Profile could not be read as valid JSON; correct the private profile file') from e
    return require_profile(profile)
