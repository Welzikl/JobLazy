"""Select only user-confirmed alternative titles, bound to one employment record."""
from .common import NeedsInput


def allowed_titles(profile):
    options={}
    entries=profile['resume'].get('experience',[])
    for position,item in enumerate(profile.get('employment_title_options',[])):
        i=item.get('experience_index')
        if type(i) is not int or i<0 or i>=len(entries) or i in options:
            raise NeedsInput('Confirmed title options have an invalid employment identity')
        original=entries[i]
        if any(item.get(key)!=original.get(field) for key,field in
               (('company','company'),('dates','dates'),('original_role','role'))):
            raise NeedsInput('Confirmed title options no longer match the employment record')
        source=item.get('source',{})
        if source.get('method')!='operator_confirmed' or not source.get('verbatim','').strip():
            raise NeedsInput('Alternative employment titles lack user confirmation')
        alternatives=item.get('allowed_roles')
        if not isinstance(alternatives,list) or not alternatives or any(not isinstance(s,str) or not s.strip() for s in alternatives):
            raise NeedsInput('Confirmed employment title options are invalid')
        options[i]={'index':i,'company':original['company'],'dates':original['dates'],
            'allowed_roles':list(dict.fromkeys([original['role'],*alternatives])),
            'source_ref':f'/employment_title_options/{position}','confirmation':source['verbatim']}
    return options


def validate_title_selections(selections,options,included):
    selected={}
    for item in selections:
        i=item.get('index')
        if type(i) is not int or i not in options or i not in included or i in selected:
            raise NeedsInput('Tailoring selected a title for an invalid employment identity')
        if item.get('role') not in options[i]['allowed_roles']:
            raise NeedsInput('Tailoring selected an unconfirmed employment title')
        selected[i]={**item,'company':options[i]['company'],'dates':options[i]['dates'],
            'source_ref':options[i]['source_ref']}
    if set(selected)!=(set(options)&included):
        raise NeedsInput('Tailoring omitted a confirmed employment title selection')
    return selected
