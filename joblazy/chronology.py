"""Deterministic calendar evidence; never infer employment capacity or continuity."""
import calendar
import re
from .experience_policy import NUMBER,WORDS

MONTHS={name.casefold():i for names in (calendar.month_name,calendar.month_abbr)
        for i,name in enumerate(names) if i}
ENDPOINT=r'(?:[A-Za-z]+\.?\s+\d{4}|\d{4}-\d{2})'
RANGE=re.compile(r'('+ENDPOINT+r')\s*(?:[-–—]|to)\s*('+ENDPOINT+r')',re.I)
DURATION=re.compile(r'\b(?:(?P<years>'+NUMBER+r')\s+years?(?:\s+(?:and\s+)?(?P<months>'+NUMBER+r')\s+months?)?|(?P<only_months>'+NUMBER+r')\s+months?)\b',re.I)
UNCERTAIN=re.compile(r"\b(?:not|cannot|unverified|unconfirmed|uncertain|unknown|whether|requires?|required|requirement|would|if)\b|can't|doesn't",re.I)


def month_index(value):
    iso=re.fullmatch(r'(\d{4})-(\d{2})',value)
    if iso:year,month=map(int,iso.groups())
    else:
        named=re.fullmatch(r'([A-Za-z]+)\.?\s+(\d{4})',value)
        if not named:return None
        month=MONTHS.get(named[1].casefold());year=int(named[2])
    return year*12+month-1 if month and 1<=month<=12 and 1<=year<=9999 else None


def employment_calendar(profile):
    entries=[];periods={};covered=set()
    for i,source in enumerate(profile['resume'].get('experience',[])):
        item={'source_id':f'employment.{i}','company':source.get('company',''),
            'dates':source.get('dates'),'status':'unquantified'}
        match=RANGE.fullmatch(str(source.get('dates') or '').strip())
        start=month_index(match[1]) if match else None;end=month_index(match[2]) if match else None
        if start is not None and end is not None and start<=end:
            months=set(range(start,end+1));covered.update(months);periods[item['source_id']]=months
            item.update(status='month_range',start_month=f'{start//12:04d}-{start%12+1:02d}',
                end_month=f'{end//12:04d}-{end%12+1:02d}',month_distance=end-start,
                calendar_months_touched=end-start+1)
        else:item['reason']='Date range not quantified by the supported month-range parser; retain the original dates.'
        entries.append(item)
    for item in entries:
        if item['source_id'] in periods:
            item['overlapping_source_ids']=[key for key,months in periods.items()
                if key!=item['source_id'] and months&periods[item['source_id']]]
    return {'version':1,'entries':entries,'calendar_months_touched_union':len(covered),
        'scope':'Calendar coverage of fully parsed month ranges, counting shared months once. '
                'Month distance compares named endpoints; months touched includes both endpoint months. '
                'Exact days, continuous work, hours, full-time equivalence and skill-specific experience are not established. '
                'Unquantified entries are excluded from the union, not assumed to have zero experience.'}


def chronology_errors(result,profile):
    """Catch plainly attributed positive tenure beyond a unique employer's range.

    This is a bounded contradiction check, not comprehensive prose verification.
    Ambiguous employers, unparsed dates and explicitly uncertain claims defer.
    """
    timeline=employment_calendar(profile);aliases={}
    for entry in timeline['entries']:
        name=str(entry['company']).strip()
        if not name:continue
        names={name.casefold()};first=name.split()[0]
        if re.fullmatch(r'[A-Za-z]{4,}',first):names.add(first.casefold())
        for alias in names:aliases.setdefault(alias,[]).append(entry)
    unique={key:value[0] for key,value in aliases.items()
            if len(value)==1 and value[0]['status']=='month_range'}
    if not unique:return []
    employer=re.compile(r'\s+(?:at|with)\s+('+ '|'.join(re.escape(s) for s in sorted(unique,key=len,reverse=True))+r')\b',re.I)
    global_refs=result.get('candidate_source_ids',[])
    texts=[('reason',result.get('reason',''),global_refs)]
    texts.extend((f'dimensions.{key}.explanation',item.get('explanation',''),item.get('candidate_source_ids',[]))
                 for key,item in result.get('dimensions',{}).items())
    texts.extend((f'requirements.{i}.explanation',item.get('explanation',''),item.get('candidate_source_ids',[]))
                 for i,item in enumerate(result.get('requirements',[])))
    texts.extend((f'evidence.{i}.explanation',item.get('explanation',''),global_refs)
                 for i,item in enumerate(result.get('evidence',[])))
    def number(text):return WORDS[text.casefold()] if text.casefold() in WORDS else float(text)
    errors=[]
    for path,text,refs in texts:
        for duration in DURATION.finditer(text):
            name=employer.match(text,duration.end())
            if not name:continue
            entry=unique[name[1].casefold()];index=entry['source_id'].split('.')[-1]
            if not any(ref==entry['source_id'] or ref.startswith(f'experience.{index}.') for ref in refs):continue
            prefix=re.split(r'[;.!?\n]',text[:duration.start()])[-1]
            suffix=re.split(r'[;.!?\n]',text[name.end():])[0]
            if UNCERTAIN.search(prefix[-120:]+' '+suffix):continue
            years=duration['years'];months=duration['months'] or duration['only_months']
            claimed=(number(years)*12 if years else 0)+(number(months) if months else 0)
            # Whole years may be rounded in prose. Month-precision claims get
            # only one month of tolerance when explicitly approximate.
            tolerance=11 if years and not months and '.' not in years else (
                1 if re.search(r'\b(?:about|roughly|approximately|nearly)\s*$',prefix,re.I) else 0)
            if claimed>entry['calendar_months_touched']+tolerance:
                errors.append(f'{path}: {duration.group()} at {entry["company"]} exceeds the '
                    f'{entry["calendar_months_touched"]} calendar months touched by {entry["source_id"]} '
                    f'({entry["dates"]}). Use the supplied calendar evidence; it does not establish worked or full-time tenure.')
    return errors
