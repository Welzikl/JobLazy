"""Derive phone routing only from an explicit international contact number."""
import re
import time
from .common import ROOT

def phone_info(value):
    import phonenumbers as pn
    if not isinstance(value,str) or not re.fullmatch(r'\+[0-9()\s.\-]+',value.strip()):return None
    try:number=pn.parse(value,None)
    except pn.NumberParseException:return None
    if number.extension or not pn.is_valid_number(number):return None
    regions=[r for r in pn.region_codes_for_country_code(number.country_code) if pn.is_valid_number_for_region(number,r)]
    return {'e164':pn.format_number(number,pn.PhoneNumberFormat.E164),
        'national':pn.national_significant_number(number),'calling_code':'+'+str(number.country_code),
        'region':regions[0] if len(regions)==1 and regions[0]!='001' else None}

def normalized_label(field):
    return re.sub(r'\s+',' ',str(field.get('label') or field.get('name') or '').strip().rstrip('*:').strip()).casefold()

def phone_country_field(field):
    label=normalized_label(field);section=str(field.get('section') or '').strip().casefold()
    if re.search(r'emergency|reference|referee|supervisor|spouse|guardian|parent',label+' '+section):return False
    autocomplete=str(field.get('autocomplete') or '').casefold().split()
    return 'tel-country-code' in autocomplete or bool(re.fullmatch(r'(?:phone|telephone|mobile) country(?: code)?|country (?:phone|telephone) code|dial(?:ing|ling)? code',label)) or (
        label in ('country','country code') and section in ('phone','phone number','telephone','mobile','mobile phone','contact phone'))

def phone_mappings(fields,profile,scope=None):
    """Return overrides and fields blocked from the upstream residence mapping."""
    default=profile.get('applicant',{}).get('identity',{}).get('phone')
    countries=[f for f in fields if phone_country_field(f)]
    blocked={f['id'] for f in countries};plans={}
    # An unqualified country-code label is ambiguous unless autocomplete says residence.
    blocked.update(f['id'] for f in fields if normalized_label(f)=='country code' and str(f.get('autocomplete','')).casefold() not in ('country','country-name'))
    for country in countries:
        info=phone_info(default);source_ref='/applicant/identity/phone'
        section=country.get('section','')
        peers=[f for f in fields if f.get('section','')==section and f.get('type') in ('tel','text') and not f.get('combo') and not phone_country_field(f)
            and normalized_label(f) in ('phone','phone number','telephone','telephone number','mobile','mobile phone','mobile number')]
        siblings=[f for f in countries if f.get('section','')==section]
        if len(peers)==1 and len(siblings)==1:blocked.add(peers[0]['id'])
        if len(peers)==1:
            exact=[(i,a) for i,a in enumerate(profile.get('answers',[])) if a.get('scope')==scope and a.get('question')==peers[0].get('label')]
            if len(exact)>1:continue
            if exact:
                i,answer=exact[0];info=phone_info(answer.get('value'));source_ref=f'/answers/{i}'
        if not info:continue
        plain_code=country.get('type') in ('text','tel','number') and not country.get('combo') and (
            'tel-country-code' in str(country.get('autocomplete','')).split() or 'code' in normalized_label(country))
        choice=country.get('type') in ('select','aria_select') or (country.get('type')=='text' and country.get('combo'))
        if not plain_code and not choice:continue
        info={**info,'control':'calling_code' if plain_code else 'country_choice'}
        plans[country['id']]={'value':info['region'] or info['calling_code'],'source_ref':source_ref,
            'phone_country':info,'confidence':1.0}
        if len(peers)==1 and len(siblings)==1:
            plans[peers[0]['id']]={'value':info['national'],'source_ref':source_ref,
                'phone_number':{**info,'country_field':country['id']},'confidence':1.0}
    return plans,blocked

def install_phone_controls(page):
    if not page.evaluate("typeof window.__joblazyPhoneControl === 'function'"):
        page.evaluate((ROOT/'joblazy/phone-controls.js').read_text(encoding='utf-8'))

def fill_phone_country(page,field,timeout=3):
    install_phone_controls(page)
    query={'id':field['id'],'info':field['phone_country']}
    if page.evaluate('q=>window.__joblazyPhoneControl({...q,mode:"read"})',query)['ok']:return True
    loc=page.locator(f'[data-jpaf-id="{field["id"]}"]')
    if field['phone_country'].get('control')=='calling_code':
        loc.fill(field['phone_country']['calling_code'])
        return page.evaluate('q=>window.__joblazyPhoneControl({...q,mode:"read"})',query)['ok']
    state=page.evaluate('q=>window.__joblazyPhoneControl({...q,mode:"choices"})',query)
    native=loc.evaluate('e=>e.tagName==="SELECT"')
    if not native:
        loc.click(timeout=2000)
        if loc.evaluate('e=>e.tagName==="INPUT" && !e.readOnly'):
            loc.fill(state['search'])
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        state=page.evaluate('q=>window.__joblazyPhoneControl({...q,mode:"choices"})',query)
        if state['count']>1:return False
        if state['count']==1:
            if native:loc.select_option(index=state['index'])
            else:page.locator(f'[data-joblazy-phone-option="{field["id"]}"]').click(timeout=2000)
            return page.evaluate('q=>window.__joblazyPhoneControl({...q,mode:"read"})',query)['ok']
        if native:return False
        page.wait_for_timeout(100)
    return False

def same_phone(actual,expected):
    import phonenumbers as pn
    if not isinstance(actual,str) or not re.fullmatch(r'\+?[0-9()\s.\-]+',actual.strip()):return False
    try:
        if expected.get('region'):number=pn.parse(actual,expected['region'])
        elif actual.strip().startswith('+'):number=pn.parse(actual,None)
        else:number=pn.parse(expected['calling_code']+re.sub(r'\D','',actual),None)
    except pn.NumberParseException:return False
    return pn.is_valid_number(number) and pn.format_number(number,pn.PhoneNumberFormat.E164)==expected['e164']
