"""Reuse JobPilot's mapper, accepting only values traceable to supplied facts."""
import importlib.util
import re
import calendar
from datetime import date, datetime, timezone
from .common import ROOT

_spec = importlib.util.spec_from_file_location('upstream_mapper', ROOT/'vendor/personal-jobpilot/agents/autofill_mapper.py')
_mapper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mapper)

SENSITIVE = re.compile(r'consent|agree|acknowledg|privacy|sponsor|authori[sz]|eligib|right to work|citizen|visa|relocat|willing|salary|compensation|\bpay\b|gender|race|ethnic|disabil|veteran|sexual|lgbt|transgender|hispanic|\bage\b|\b18\b|government|conflict|(?<![a-z])referred(?![a-z])|worked (at|for|here)|previously employed|background|certify|attest|sms|whatsapp|text message|terms', re.I)
CREDENTIAL = re.compile(r'password|passcode|one.time|\botp\b|verification code|social security|\bssn\b', re.I)

def leaves(value, prefix=''):
    if isinstance(value, dict):
        for k,v in value.items(): yield from leaves(v, prefix+'/'+str(k))
    elif isinstance(value, list):
        for i,v in enumerate(value): yield from leaves(v, prefix+'/'+str(i))
    elif value is not None:
        yield prefix, value

COUNTRY_NAMES = {
    'uk':'United Kingdom', 'gb':'United Kingdom', 'gbr':'United Kingdom',
    'united kingdom':'United Kingdom', 'us':'United States', 'usa':'United States',
    'united states':'United States', 'united states of america':'United States',
    'ca':'Canada', 'can':'Canada', 'canada':'Canada',
}


def country_name(value):
    return COUNTRY_NAMES.get(str(value or '').strip().casefold())


def posting_country(job):
    """One fully represented structured country, never a candidate-derived guess."""
    if not isinstance(job,dict):return None
    evidence=job.get('location_evidence')
    if not isinstance(evidence,list) or not evidence:return None
    countries=set();location=str(job.get('location') or '').casefold();tokens=[]
    for item in evidence:
        if not isinstance(item,dict):return None
        address=item.get('postal_address')
        if not isinstance(address,dict):return None
        country=country_name(address.get('addressCountry'))
        if not country:return None
        countries.add(country)
        tokens.extend(str(v).casefold() for v in (item.get('label'),*address.values()) if isinstance(v,str) and v.strip())
    if len(countries)!=1:return None
    country=next(iter(countries))
    for name,normalized in COUNTRY_NAMES.items():
        if normalized!=country and re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',str(job.get('location') or ''),re.I):return None
    # Refuse extra locations not explained by the structured evidence.
    for token in sorted(tokens,key=len,reverse=True):
        location=re.sub(r'(?<!\w)'+re.escape(token)+r'(?!\w)',' ',location)
    if re.search(r'\w',location):return None
    return country


def current_authorization(field, profile, job):
    """Answer narrowly recognized current questions from positive canonical facts.

    An explicitly named country comes from the question itself. An unnamed job
    country still requires structured posting evidence. Neither route infers
    authorization from residence, telephone, preferences or sponsorship prose.
    """
    if field.get('type') not in ('select','select-one','radio','button_group'):return None
    if str(field.get('description') or '').strip():return None
    options=[v for v in (field.get('options') or []) if str(v).strip().casefold() not in ('','choose','select','please select','select an option')]
    if len(options)!=2 or {str(v).strip().casefold() for v in options}!={'yes','no'}:return None
    label=' '.join(str(field.get('label') or '').split()).rstrip(' *')
    match=re.fullmatch(
        r'(?:(?:Are you|For [\w .\'-]+ to anticipate possible immigration timelines and obligations, could you confirm you are) '
        r'(?:(?:currently|legally) ){0,2}authori[sz]ed|Do you have the legal right) to work in '
        r'(?P<country>the country (?:to|in) which you are applying|(?:the )?(?:United Kingdom|United States|Canada|UK|US))\??',
        label,re.I)
    if not match:return None
    asked=match['country'].lower()
    if asked.startswith('the country '):
        country=posting_country(job)
        evidence={'job_source_ref':'/location_evidence'}
    else:
        country=country_name(re.sub(r'^the ', '', asked))
        evidence={'question_source_ref':'label','question_country':country}
    if not country:return None
    targeting=profile.get('targeting')
    if not isinstance(targeting,dict):return None
    config=targeting.get('config',{})
    if not isinstance(config,dict) or not isinstance(config.get('location'),dict):return None
    authorized=config['location'].get('authorized_in')
    if not isinstance(authorized,list):return None
    refs=[i for i,v in enumerate(authorized) if country_name(v)==country]
    if len(refs)!=1:return None
    return {'value':next(v for v in options if str(v).strip().casefold()=='yes'),
        'source_ref':f'/targeting/config/location/authorized_in/{refs[0]}',
        **evidence,'confidence':1.0}


def exact_date(value):
    """Accept an explicit full date; never choose a day or a numeric locale."""
    if not isinstance(value,str):return None
    value=value.strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
        try:return date.fromisoformat(value).isoformat()
        except ValueError:return None
    match=re.fullmatch(r'(?:Available to start on )?(\d{1,2}) ([A-Za-z]+) (\d{4})\.?',value)
    if match:
        months={name.casefold():i for i,name in enumerate(calendar.month_name) if name}
        try:return date(int(match[3]),months[match[2].casefold()],int(match[1])).isoformat()
        except (ValueError,KeyError):return None
    return None


def application_default(field, profile, job):
    """Reuse confirmed defaults only for known, unambiguous question forms."""
    defaults=profile.get('application_defaults')
    if not isinstance(defaults,dict):return None
    source=defaults.get('source')
    if not isinstance(source,dict) or source.get('method')!='operator_supplied':return None
    if field.get('combo') or str(field.get('description') or '').strip():return None
    label=' '.join(str(field.get('label') or '').split()).rstrip(' *').casefold()
    kind=field.get('type');options=field.get('options')
    if kind in ('select','select-one','radio','button_group') and label in {
            'notice period/availiablity','notice period/availability'}:
        availability=defaults.get('availability',{})
        if not isinstance(availability,dict):return None
        day=exact_date(availability.get('exact_day'))
        today=datetime.now(timezone.utc).date()
        if not day or day<today.isoformat():return None
        if availability.get('month') and day[:7]!=availability['month']:return None
        # This observed menu asks availability as well as notice. Compute from
        # the confirmed date on each run, never persist a stale notice duration.
        choices={str(v).strip().casefold().replace('\u2013','-'):v for v in (options or [])}
        if len(choices)!=len(options or []) or set(choices)!={'immediate','2-4 weeks','1-2 months','2+ months'}:return None
        def months_after(count):
            index=today.year*12+today.month-1+count
            year,month=divmod(index,12);month+=1
            return date(year,month,min(today.day,calendar.monthrange(year,month)[1]))
        start=date.fromisoformat(day);days=(start-today).days
        matches=[]
        if days==0:matches.append('immediate')
        if 14<=days<=28:matches.append('2-4 weeks')
        if months_after(1)<=start<=months_after(2):matches.append('1-2 months')
        if start>=months_after(2):matches.append('2+ months')
        # Shared endpoints and gaps need a more precise choice; do not guess.
        if len(matches)!=1:return None
        return {'value':choices[matches[0]],'source_ref':'/application_defaults/availability/exact_day',
                'calculated_on':today.isoformat(),'confidence':1.0}
    if kind in ('text','textarea','date') and not options and label in {
            'next available starting date','what is the earliest you would want to start?',
            'please outline your start date availability or notice period','notice period/availiablity'}:
        availability=defaults.get('availability',{})
        if not isinstance(availability,dict):return None
        supplied=availability.get('exact_day')
        if supplied is not None:
            day=exact_date(supplied)
            if not day or day<datetime.now(timezone.utc).date().isoformat():return None
            if availability.get('month') and day[:7]!=availability['month']:return None
            value=day if kind=='date' else f'Available to start on {int(day[8:])} {calendar.month_name[int(day[5:7])]} {day[:4]}.'
            return {'value':value,'source_ref':'/application_defaults/availability/exact_day','confidence':1.0}
    if kind in ('text','textarea','number') and not options:
        salary_questions={"what's your annual total comp expectation?",
            'what is your desired gross annual salary (local currency)?',
            'expected salary: what are your yearly base salary expectations? please include currency',
            'please outline your compensation expectations?', 'please outline your compensation expectations'}
        if label in salary_questions:
            salary=defaults.get('salary',{})
            if not isinstance(salary,dict):return None
            amount=salary.get('annual_amount')
            # These observed forms do not explicitly name a currency; a UK
            # posting supplies it. Never infer the job country from residence.
            if salary.get('currency')!='GBP' or type(amount) is not int or amount<=0:return None
            if posting_country(job)!='United Kingdom':return None
            return {'value':str(amount) if kind=='number' else f'GBP {amount:,} per year',
                'source_ref':'/application_defaults/salary','job_source_ref':'/location_evidence','confidence':1.0}
        if kind in ('text','textarea') and label in {
                'next available starting date','what is the earliest you would want to start?',
                'please outline your start date availability or notice period','notice period/availiablity'}:
            availability=defaults.get('availability',{})
            if not isinstance(availability,dict):return None
            month=availability.get('month')
            if not isinstance(month,str) or not re.fullmatch(r'\d{4}-(?:0[1-9]|1[0-2])',month):return None
            if month<datetime.now(timezone.utc).strftime('%Y-%m'):return None
            return {'value':f'Available to start in {calendar.month_name[int(month[5:])]} {month[:4]}.',
                'source_ref':'/application_defaults/availability/month','confidence':1.0}
    if kind not in ('select','select-one','radio','button_group') or not options:return None
    sponsorship=defaults.get('sponsorship',{})
    if not isinstance(sponsorship,dict) or type(sponsorship.get('required')) is not bool:return None
    countries=sponsorship.get('countries')
    if not isinstance(countries,list):return None
    if label in {'do you require visa sponsorship to work within the uk?',
            'will you now or in the future require sponsorship for employment authorization in the uk?'}:
        country='United Kingdom';evidence={'question_source_ref':'label','question_country':country}
    elif label in {'will you now or in the future require visa sponsorship to work in the country where this role is based?',
            'will you now or in the future require sponsorship for employment visa status?'}:
        country=posting_country(job);evidence={'job_source_ref':'/location_evidence'}
    else:return None
    if not country or sum(country_name(c)==country for c in countries)!=1:return None
    # Keep compound options (such as no sponsorship AND current work rights)
    # scoped to explicit answers, rather than inferring their extra assertions.
    choices=[v for v in options if str(v).strip().casefold() not in ('','choose','select','please select','select an option')]
    if len(choices)!=2 or {str(v).strip().casefold() for v in choices}!={'yes','no'}:return None
    wanted='yes' if sponsorship['required'] else 'no'
    return {'value':next(v for v in choices if str(v).strip().casefold()==wanted),
        'source_ref':'/application_defaults/sponsorship',**evidence,'confidence':1.0}


def plan_fields(fields, profile, scope, *, job=None):
    plan, unresolved = [], []
    # Ordinary fields use applicant facts. Work rights and preferred work
    # locations use their explicit targeting fields, never general prose.
    applicant = profile.get('applicant', {})
    facts = list(leaves(applicant, '/applicant'))
    answers = profile.get('answers', [])
    from .phones import phone_mappings
    phone_plans,phone_blocked=phone_mappings(fields,profile,scope)
    for f in fields:
        label = f.get('label') or f.get('name') or ''
        context = ' '.join(str(f.get(k,'')) for k in ('label','name','section','autocomplete'))
        result = None
        if CREDENTIAL.search(context):
            unresolved.append({'id':f['id'],'field':label,'required':f.get('required',False),'reason':'Account authentication needed'})
            continue
        exact = [(i,a) for i,a in enumerate(answers) if a.get('question') == label and a.get('scope') == scope]
        if len(exact) == 1:
            i, a = exact[0]
            value = a.get('value')
            if value is not None and (not f.get('options') or value in f['options']):
                result = {'value':value,'source_ref':f'/answers/{i}','confidence':1.0}
        elif not exact:
            result=current_authorization(f,profile,job) or application_default(f,profile,job)
        if not SENSITIVE.search(context) and f['id'] in phone_plans:
            phone=phone_plans[f['id']]
            if not exact or (result and phone.get('phone_number') and result.get('source_ref')==phone['source_ref']):result=phone
        if not exact and not result and f['id'] not in phone_blocked and not SENSITIVE.search(context) and f.get('type') not in ('file','checkbox','radio','password','button_group','unsupported'):
            preferred_location=re.fullmatch(r'preferred(?: work)? location\??',label.strip(),re.I)
            if preferred_location and f.get('type') in ('text','textarea') and not f.get('combo') and not f.get('options') and not str(f.get('description') or '').strip():
                targeting=profile.get('targeting',{})
                config=targeting.get('config',{}) if isinstance(targeting,dict) else {}
                preference=config.get('location',{}) if isinstance(config,dict) else {}
                if isinstance(preference,dict) and all(isinstance(preference.get(k),str) and preference[k].strip() for k in ('city','country')):
                    result={'value':', '.join(preference[k].strip() for k in ('city','country')),
                            'source_ref':'/targeting/config/location','confidence':1.0}
            # The upstream mapper matches "current" before this longer country
            # question. Residence country is explicit and independent of phone.
            residence_country=re.fullmatch(r'(?:please let us know your )?(?:current )?country of residence\??',label.strip(),re.I)
            country=applicant.get('address',{}).get('country')
            if residence_country and country and (not f.get('options') or country in f['options']):
                result={'value':country,'source_ref':'/applicant/address/country','confidence':1.0}
                if f.get('combo'):result['exact_location']=True
            mapped = None if residence_country or preferred_location else _mapper.map_standard_field(f,applicant)
            if mapped and not mapped.get('needs_review'):
                value = mapped.get('value')
                refs = [p for p,v in facts if value is not None and str(v) == str(value)]
                if refs and (not f.get('options') or value in f['options']):
                    result = {'value':value,'source_ref':refs[0],'confidence':mapped['confidence']}
        address=applicant.get('address',{})
        if f.get('type')=='date':
            day=exact_date(result.get('value')) if result else None
            result={**result,'value':day,'exact_date':True} if day else None
        if result and f.get('combo') and result['source_ref'] in ('/applicant/address/city','/applicant/address/location_line'):
            # A city-only autocomplete can select a namesake in another country.
            # Compose only supplied address facts and require a full exact choice.
            if not address.get('city') or not address.get('country'):
                result=None
            else:
                result={**result,'value':', '.join(
                    str(address[k]) for k in ('city','state_full','country') if address.get(k)),
                    'source_ref':'/applicant/address','exact_location':True}
        if result:
            plan.append({'id':f['id'],'source':'deterministic','needs_review':False,**result})
        elif f.get('type') != 'file':
            unresolved.append({'id':f['id'],'field':label,'required':f.get('required',False),'options':f.get('options'),
                'reason':'An exact date (year, month and day) is required' if f.get('type')=='date' else 'No unambiguous saved answer'})
    return {'fields':plan,'unresolved':unresolved,'_scanMeta':fields}
