"""Audit saved discovery observations without treating them as verified vacancies."""
import re
from collections import Counter,defaultdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
from .common import read_json,write_json
from .store import canonical_url


def normalized(value):
    return ' '.join(str(value or '').casefold().split())


def location_class(value):
    text=normalized(str(value or '').replace('\n','|'))
    if not text:return 'location_missing'
    uk=r'\b(?:united kingdom|uk|gb|gbr|england|great britain)\b|\bu\.k\.(?=\W|$)'
    london=[]
    # Older providers flattened cities and countries into middle-dot lists.
    # Those tokens cannot establish a city/country association: retain bare
    # London as unverified instead of borrowing a different city's country.
    for part in re.split(r'[|;\n\u00b7]',text):
        if not re.search(r'\blondon\b',part):continue
        # East London can describe part of London, England or the South African
        # city. Resolve the country within this same location group first.
        if re.search(r'\bnew london\b',part) or re.search(r'\b(?:canada|can|ca|ontario|south africa|za|zaf|connecticut|united states|us|usa)\b',part):
            london.append('other_london')
        elif re.search(uk,part):london.append('london_uk_explicit')
        else:london.append('london_country_unverified')
    if 'london_uk_explicit' in london:return 'london_uk_explicit'
    if 'london_country_unverified' in london:return 'london_country_unverified'
    if london:return 'other_london'
    if re.search(r'\bremote\b|anywhere|worldwide',text):
        return 'uk_remote_candidate' if re.search(uk,text) else 'remote_eligibility_unverified'
    if re.search(uk,text):return 'uk_city_unspecified_or_elsewhere'
    return 'other_or_unverified_location'


def timestamp(value):
    try:
        if isinstance(value,bool) or value is None or value=='':return None
        if isinstance(value,(int,float)) or re.fullmatch(r'\d+(?:\.\d+)?',str(value)):
            value=float(value)
            if value<=0:return None
            return datetime.fromtimestamp(value/1000 if value>=100_000_000_000 else value,timezone.utc)
        parsed=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError,TypeError,OverflowError,OSError):return None


def audit_rows(rows,*,boards=None,last_scan=None,source_registry=None,now=None,max_age_days=45):
    if max_age_days<1:raise ValueError('Posting age threshold must be positive')
    now=now or datetime.now(timezone.utc)
    jobs=[r['data'] for r in rows];locations=Counter();ages=Counter();descriptions=Counter()
    observed=Counter();availability_states=Counter();employers=set();by_provider=defaultdict(list);duplicates=defaultdict(list)
    current_london=[];london_employers=set();missing_employer=0;closed=0
    canonical=set();missing_url=0
    for row in rows:
        job=row['data'];location=location_class(job.get('location'));locations[location]+=1
        employer=normalized(job.get('company'))
        if employer:employers.add(employer)
        else:missing_employer+=1
        url=job.get('url')
        if url:canonical.add(canonical_url(url))
        else:missing_url+=1
        date=timestamp(job.get('postedAt'))
        age='posting_date_unknown' if date is None else 'posting_date_in_future' if date>now+timedelta(days=1) else 'within_age_threshold' if date>=now-timedelta(days=max_age_days) else 'older_than_threshold'
        ages[age]+=1
        seen=timestamp(job.get('observed_at'))
        observed['observation_unknown' if seen is None else 'observation_in_future' if seen>now+timedelta(days=1) else 'observed_within_48h' if seen>=now-timedelta(days=2) else 'observation_older_than_48h']+=1
        length=len(str(job.get('description') or '').strip())
        descriptions['missing' if length==0 else 'shorter_than_200_characters' if length<200 else 'at_least_200_characters']+=1
        availability_states[row.get('status','discovered') if row.get('status') in ('posting_closed','posting_expired','posting_unavailable') else 'no_saved_stop']+=1
        is_closed=job.get('closed') is True or job.get('isClosed') is True or job.get('isActive') is False or row.get('status')=='posting_closed'
        closed+=bool(is_closed)
        by_provider[job.get('ats') or 'unknown'].append((job,location,age))
        if location=='london_uk_explicit':
            if employer:london_employers.add(employer)
            if age=='within_age_threshold' and not is_closed and row.get('status') not in ('posting_expired','posting_unavailable'):current_london.append(row['id'])
        if employer and job.get('title') and url:
            key=(employer,normalized(job['title']),normalized(job.get('location')))
            duplicates[key].append({'id':row['id'],'url':canonical_url(url),'provider':job.get('ats')})
    candidates=[{'company':k[0],'title':k[1],'location':k[2],'records':v}
        for k,v in duplicates.items() if len({r['url'] for r in v})>1]
    provider_rows=[]
    for provider,items in sorted(by_provider.items()):
        dates=[timestamp(j.get('observed_at')) for j,_,_ in items];dates=[d for d in dates if d]
        provider_rows.append({'provider':provider,'saved_jobs':len(items),
            'distinct_employer_labels':len({normalized(j.get('company')) for j,_,_ in items if j.get('company')}),
            'locations':dict(Counter(l for _,l,_ in items)),
            'posting_age':dict(Counter(a for _,_,a in items)),
            'latest_saved_observation':max(dates).isoformat() if dates else None})
    failures=(last_scan or {}).get('errors',[])
    registry=[]
    for entry in (boards or {}).get('boards',[]):
        tracked=next((v for v in (source_registry or {}).get('sources',{}).values() if v.get('config')==entry),None)
        registry.append({'name':entry.get('name'),'provider':entry.get('provider'),'enabled':entry.get('enabled',True),
            'last_successful_scan':None,'new_unique_jobs':None,
            'reported_failures':[e for e in failures if e.get('board')==entry.get('name')],
            'evidence':'Historical query attribution unavailable; provider totals cannot identify a particular query.'})
        if tracked:registry[-1].update({'last_successful_scan':tracked.get('last_successful_scan'),
            'new_unique_jobs':tracked.get('new_unique_jobs_seen'),'last_status':tracked.get('last_status'),
            'last_warnings':tracked.get('last_warnings',[]),'last_error':tracked.get('last_error'),
            'distinct_seen_jobs':len(tracked.get('seen_job_ids',[])),
            'evidence':'Recorded source/query run. A successful fetch does not establish exhaustive coverage or current employer availability.'})
    return {'generated_at':now.isoformat(),'max_posting_age_days':max_age_days,
        'summary':{'saved_queue_records':len(jobs),'distinct_canonical_urls':len(canonical),'missing_urls':missing_url,
            'history_only_records':sum(j.get('historical_application') is True for j in jobs),
            'imported_application_outcomes':sum(isinstance(r.get('result'),dict) and r['result'].get('method')=='imported_history' for r in rows),
            'distinct_employer_labels':len(employers),'missing_employer_labels':missing_employer,
            'explicit_london_uk_records':locations['london_uk_explicit'],
            'explicit_london_uk_employer_labels':len(london_employers),
            'explicit_london_within_posting_age_threshold':len(current_london),
            'possible_duplicate_groups':len(candidates),'explicit_closed_flags':closed,
            'current_employer_availability_unverified':len(jobs)-closed},
        'locations':dict(locations),'posting_age':dict(ages),'description_length':dict(descriptions),
        'availability_stops':dict(availability_states),
        'observation_age':dict(observed),'providers':provider_rows,'source_registry':registry,
        'latest_saved_scan_errors':failures,'potential_cross_url_duplicates':candidates,
        'recent_explicit_london_ids':current_london,
        'limitations':[
            'London classification uses saved location labels, not verified employer eligibility. Bare London and UK-wide remote jobs remain separate candidates.',
            'Posting age and last observation are different. Neither confirms that an employer still accepts applications; old postings are not automatically closed.',
            'Description length is a coverage proxy, not proof that the full description is present.',
            'Employer counts normalize case and whitespace only. Duplicate groups are review candidates, not automatic merges or confirmed reposts.',
            'This report makes no model calls, network requests, queue transitions or recommendation-quality claims.']}


def write_coverage(store,data,boards_path=None,max_age_days=45):
    data=Path(data)
    scan=data/'last-scan.json'
    registry=data/'source-registry.json'
    report=audit_rows(store.list(),boards=read_json(boards_path) if boards_path else None,
        last_scan=read_json(scan) if scan.exists() else None,
        source_registry=read_json(registry) if registry.exists() else None,max_age_days=max_age_days)
    output=data/'coverage.json';write_json(output,report)
    return {'path':str(output.resolve()),**report['summary'],'limitations':report['limitations']}
