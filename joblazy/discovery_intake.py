"""Retain location candidates and join only exact, observed application routes."""
import re
from collections import Counter,defaultdict
from urllib.parse import urlsplit,parse_qsl
from .coverage import location_class
from .store import canonical_url

LOCATION_CLASSES={'location_missing','other_london','london_uk_explicit','london_country_unverified',
    'uk_remote_candidate','remote_eligibility_unverified','uk_city_unspecified_or_elsewhere','other_or_unverified_location'}


def validate_locations(classes):
    if classes is not None and (not isinstance(classes,list) or not classes or any(not isinstance(c,str) or c not in LOCATION_CLASSES for c in classes)):
        raise ValueError('location_classes must be a nonempty list of supported coverage classifications')


def posting_identity(url):
    from .ats_postings import parse_posting_url
    ats = parse_posting_url(url)
    if ats:
        return ats['identity']
    parsed=urlsplit(url);path=parsed.path.strip('/').split('/')
    if parsed.scheme=='https' and parsed.hostname=='jobs.ashbyhq.com' and len(path) in (2,3):
        if re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',path[1]) and (len(path)==2 or path[2]=='application'):
            return 'ashby:'+path[0]+':'+path[1].lower()
    if parsed.scheme=='https' and parsed.hostname in ('boards.greenhouse.io','job-boards.greenhouse.io'):
        if len(path)==3 and path[1]=='jobs' and path[2].isdigit():return 'greenhouse:'+path[0]+':'+path[2]
    if parsed.scheme=='https' and parsed.hostname in ('amazon.jobs','www.amazon.jobs'):
        if len(path) in (3,4) and re.fullmatch(r'[a-z]{2}(?:-[a-z]{2})?',path[0]) and path[1]=='jobs' and path[2].isdigit():
            return 'amazon:'+path[2]
    if parsed.scheme=='https' and parsed.hostname=='account.amazon.jobs':
        if len(path)==3 and path[0]=='jobs' and path[1].isdigit() and path[2]=='apply':return 'amazon:'+path[1]
    if parsed.scheme=='https' and parsed.hostname=='lifeattiktok.com':
        if len(path)==2 and path[0]=='search' and path[1].isdigit():return 'tiktok:'+path[1]
    return None


def identity(url):
    return posting_identity(url) or canonical_url(url)


def application_identity(url):
    """A shared portal is a navigation destination, not evidence of one job.

    This is a bounded generic-route filter; unknown specific URL shapes retain
    exact URL matching, without inferring equivalence across hosts or slugs.
    """
    known=posting_identity(url)
    if known:return known
    parsed=urlsplit(url);parts=parsed.path.strip('/').casefold().split('/')
    job_parameters={'gh_jid','jobid','job_id','requisitionid','requisition_id'}
    if any(k.casefold() in job_parameters and v.strip() for k,v in parse_qsl(parsed.query)):
        return canonical_url(url)
    if parsed.hostname in ('jobs.ashbyhq.com','boards.greenhouse.io','job-boards.greenhouse.io') and len(parts)==1:
        return None
    generic={'','login','signin','sign-in','sign_in','account','register','signup','sign-up',
        'careers','career','jobs','search','apply','application','opportunities'}
    # Preserve job-specific paths whose final step is an application page.
    specific_apply=(len(parts)>=3 and parts[-1] in ('apply','application')
        and parts[-3] in ('job','jobs','position','positions','requisition','requisitions')
        and parts[-2] not in generic)
    if parts[-1] in generic and not specific_apply:return None
    return canonical_url(url)


def routes(job):
    urls=[job.get('url'),*job.get('discovery_source_urls',[])]
    result={identity(url) for url in urls if isinstance(url,str) and url}
    application=job.get('application_url')
    if isinstance(application,str) and application:
        route=application_identity(application)
        if route:result.add(route)
    return result


def ingest_jobs(store,jobs,classes=None):
    validate_locations(classes)
    index=defaultdict(set);existing={row['id']:row for row in store.list()}
    aliases=store.observed_routes(list(existing.values()))
    for key,row in existing.items():
        for route in routes(row['data'])|aliases.get(key,set()):index[route].add(key)
    ids=[];observed_ids={};excluded=Counter();ambiguous=[];joined=[]
    for observed in jobs:
        if not observed.get('url'):continue
        kind=location_class(observed.get('location'))
        if classes is not None and kind not in classes:excluded[kind]+=1;continue
        matches=set().union(*(index.get(route,set()) for route in routes(observed)))
        if len(matches)>1:
            ambiguous.append({'url':observed['url'],'existing_ids':sorted(matches)})
            continue
        posting=dict(observed)
        posting['discovery_source_urls']=sorted(set(observed.get('discovery_source_urls',[]))|{observed['url']})
        if matches:
            key=next(iter(matches));old=existing[key]['data']
            # A public API can omit the employer display name. Preserve a
            # previously sourced name with its provenance, never a search hint.
            old_org = old.get('source_metadata', {}).get('hiringOrganization', {})
            old_name = old_org.get('name') if isinstance(old_org, dict) else old_org
            if (posting.get('company') == 'Employer unverified' and old_name
                    and old_name == old.get('company') and old.get('description_source')):
                posting['company'] = old_name
                retained = dict(old.get('retained_source_fields', {}))
                if retained.get('company', {}).get('value') != old_name:
                    retained['company'] = {'value': old_name, 'source': old['description_source'],
                                           'observed_at': old.get('observed_at')}
                posting['retained_source_fields'] = retained
                posting['source_metadata'] = {**posting.get('source_metadata', {}),
                                              'hiringOrganization': old_org}
            posting['discovery_source_urls']=sorted(set(old.get('discovery_source_urls',[]))|
                set(observed.get('discovery_source_urls',[]))|{old['url'],observed['url']})
            # Stable canonical URL/ID preserves existing handoffs and checkpoints.
            # The observed URL remains explicit provenance, never a fuzzy title match.
            posting['url']=old['url']
            if old.get('application_url') and not posting.get('application_url'):posting['application_url']=old['application_url']
            if old['url']!=observed['url']:joined.append({'id':key,'observed_url':observed['url'],'canonical_url':old['url']})
        key=store.ingest(posting);ids.append(key);observed_ids[canonical_url(observed['url'])]=key
        existing[key]=store.get(key)
        # Content changes invalidate earlier observed-route bindings immediately,
        # including during a single multi-source intake batch.
        for route in aliases.get(key,set()):index[route].discard(key)
        aliases[key]=store.observed_routes([existing[key]]).get(key,set())
        for route in routes(posting)|aliases[key]:index[route].add(key)
    return {'ids':ids,'observed_ids':observed_ids,'excluded_by_location':dict(excluded),
        'exact_route_joins':joined,'ambiguous_route_matches':ambiguous}
