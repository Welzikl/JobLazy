from urllib.parse import urlsplit,urlunsplit,parse_qs
import re
import unicodedata
from datetime import datetime,timezone,timedelta
from playwright.sync_api import Error as BrowserError
from .common import ROOT,NeedsInput,PostingUnavailable,PostingDescriptionError,write_json
from .browser import public_url,disconnected

def availability(raw, status, *, now=None):
    """Conservative observations, never infer closure from posting age or HTTP 404."""
    now=now or datetime.now(timezone.utc)
    if status in (404,410):
        return {'state':'page_unavailable','queue_status':'posting_unavailable','reason':f'Posting page returned HTTP {status}; vacancy closure is unconfirmed'}
    if status is None or status==408 or status==429 or status>=500:
        return {'state':'temporary_failure','queue_status':'retryable','reason':f'Posting check temporarily failed (HTTP {status or "no response"})'}
    if status<200 or status>=300:
        return {'state':'access_unverified','queue_status':'needs_input','reason':f'Posting access could not be verified (HTTP {status})'}
    for heading in raw.get('headings',[]):
        text=' '.join(heading.casefold().split()).rstrip('.!')
        if re.fullmatch(r'(?:this |the )?(?:job|position|role|vacancy)(?: posting)? (?:is |has been )?(?:closed|filled|no longer (?:available|open)|no longer accepting applications)',text) or text in ('applications are closed','applications for this role are closed'):
            return {'state':'explicit_closure','queue_status':'posting_closed','reason':'Posting displays an explicit closure notice','evidence':heading}
        if text in ('job not found','position not found','this job could not be found'):
            return {'state':'page_unavailable','queue_status':'posting_unavailable','reason':'Posting displays a missing-job notice; closure is unconfirmed','evidence':heading}
    postings=raw.get('postings',[])
    if len(postings)==1:
        value=postings[0].get('validThrough')
        # A date-only deadline includes that whole day. A timezone-less time
        # cannot establish an exact deadline; leave it unverified.
        if isinstance(value,str):
            try:
                if re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
                    deadline=datetime.fromisoformat(value).replace(tzinfo=timezone.utc)+timedelta(days=1)
                    # Allow all civil timezones to finish a date-only deadline.
                    deadline+=timedelta(hours=12)
                else:
                    deadline=datetime.fromisoformat(value.replace('Z','+00:00'))
                    if deadline.tzinfo is None:deadline=None
                if deadline is not None and deadline<=now:
                    return {'state':'deadline_expired','queue_status':'posting_expired','reason':'The posting advertises an elapsed application deadline; actual closure is unconfirmed','evidence':{'validThrough':value}}
            except (ValueError,OverflowError):pass
    return {'state':'no_closure_observed','reason':'Public page responded; this does not prove that applications are accepted'}


def greenhouse_job_frame(page,source):
    """Find the visible employer-embedded job matching the outer gh_jid exactly."""
    ids=parse_qs(urlsplit(source).query).get('gh_jid',[])
    if len(ids)!=1 or not ids[0].isdigit():return None
    candidates=[]
    for frame in page.frames:
        parsed=urlsplit(frame.url)
        if parsed.scheme!='https' or parsed.hostname not in ('boards.greenhouse.io','job-boards.greenhouse.io'):continue
        if parsed.path.rstrip('/')!='/embed/job_app' or parse_qs(parsed.query).get('token')!=ids:continue
        if frame==page.main_frame or frame.is_detached():continue
        if frame.frame_element().is_visible():candidates.append(frame)
    if len(candidates)>1:raise NeedsInput('Multiple embedded descriptions match this job; inspect the posting')
    return candidates[0] if candidates else None


def posting_read_url(url):
    """Read known ATS description routes without changing stored job identity."""
    parsed=urlsplit(url)
    suffix={'jobs.ashbyhq.com':'application','jobs.lever.co':'apply'}.get(parsed.hostname)
    if suffix and re.fullmatch(
            r'/[^/]+/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}/'+suffix+r'/?',parsed.path):
        path=parsed.path.rstrip('/').removesuffix('/'+suffix)
        return urlunsplit((parsed.scheme,parsed.netloc,path,parsed.query,parsed.fragment))
    return url


def description_identity(job,raw,directory):
    """Bind extracted content to one role before using it or its deadline.

    A related-role link or HTTP 200 is not posting evidence. Title differences
    beyond formatting remain a source-resolution task, not a fit rejection.
    """
    def normalized(value):
        if not isinstance(value,str):return ''
        value=unicodedata.normalize('NFKC',value).casefold().replace('&',' and ')
        return ' '.join(re.sub(r'[^\w]+',' ',value).split())
    expected=normalized(job.get('title'))
    postings=raw.get('postings',[])
    schema_title=postings[0].get('title') if len(postings)==1 else None
    observed=schema_title if schema_title else raw.get('title')
    matches=normalized(observed)==expected
    # Some ATS templates use document.title instead of a role h1. Strip only
    # an exact saved employer label separated from the otherwise exact title.
    if not schema_title and isinstance(observed,str):
        parts=re.split(r'\s+(?:[-–—|·•:]|at)\s+',observed)
        company=normalized(job.get('company'))
        if len(parts)==2 and company:
            matches=matches or [normalized(p) for p in parts] in ([company,expected],[expected,company])
    matched=bool(expected and len(postings)<=1 and matches)
    evidence={'expected_title':job.get('title'),'page_title':raw.get('title'),
        'structured_titles':[p.get('title') for p in postings],
        'matched':matched,'method':'structured posting title' if schema_title else 'primary page title',
        'reason':None if matched else 'Public page does not identify one matching role; resolve the specific posting before ranking.'}
    path=directory/'description-check.json';write_json(path,evidence)
    if not matched:raise PostingDescriptionError(evidence['reason'],path)
    return evidence


def enrich(job,browser,directory,*,check_only=False):
    """Read a public posting. Never click an Apply control or send candidate data."""
    from .pipeline import plain_text
    url=posting_read_url(job['url'])
    if not public_url(url): raise NeedsInput('Cannot read a non-public job URL')
    page=browser.new_page()
    try:
        checked={}
        def guard(route):
            p=urlsplit(route.request.url);host=f'{p.scheme}://{p.netloc}'
            if host not in checked: checked[host]=public_url(route.request.url)
            if checked[host]:route.continue_()
            else:route.abort()
        page.route('**/*',guard)
        response=page.goto(url,wait_until='domcontentloaded',timeout=45000)
        status=response.status if response else None
        raw={}
        description_url=page.url
        if response and response.ok:
            page.wait_for_timeout(1000)
            raw=page.evaluate((ROOT/'joblazy/read-jd.js').read_text(encoding='utf-8'))
            # Branded careers pages can put the real description in a Greenhouse
            # frame. Never substitute their navigation/intro for the requested JD.
            if parse_qs(urlsplit(page.url).query).get('gh_jid') and not raw.get('postings'):
                frame=greenhouse_job_frame(page,page.url)
                for _ in range(8):
                    if frame:break
                    page.wait_for_timeout(500);frame=greenhouse_job_frame(page,page.url)
                if frame:
                    frame.wait_for_selector('h1',state='visible',timeout=10000)
                    raw=frame.evaluate((ROOT/'joblazy/read-jd.js').read_text(encoding='utf-8'))
                    description_url=frame.url
                elif not raw.get('title') or not re.sub(r'\W+','',job.get('title','')).casefold() in re.sub(r'\W+','',raw['title']).casefold():
                    raise NeedsInput('The careers page did not expose a matching job description; ranking was not attempted')
        observation={**availability(raw,status),'requested_url':url,'observed_url':page.url,
            'http_status':status,'checked_at':datetime.now(timezone.utc).isoformat(),
            'page_title':raw.get('title'),'visible_headings':raw.get('headings',[]),
            'description_url':description_url,
            'structured_posting_count':len(raw.get('postings',[]))}
        # Explicit closure/access failures keep their existing handling. A deadline
        # from structured data is usable only after identifying the matching role.
        if not observation.get('queue_status') or observation.get('state')=='deadline_expired':
            try:description_identity(job,raw,directory)
            except PostingDescriptionError as error:
                observation.update(state='description_unresolved',queue_status='processing_failed',reason=str(error))
                write_json(directory/'availability.json',observation)
                raise
        write_json(directory/'availability.json',observation)
        if observation.get('queue_status'):raise PostingUnavailable(observation)
        # Keep an explicit public link even when the feed already supplied the JD.
        # Pass observation metadata separately so the queue can journal it without
        # changing ranking inputs or material-checkpoint source bindings.
        from .routes import destination
        route_observation=None
        try:
            route=destination(raw,description_url)
            if route:
                job={**job,'application_url':route['url']}
                route_observation={**route,'source_url':description_url,'checked_at':observation['checked_at']}
        except NeedsInput:pass
        if check_only:return {**job,'_application_route_observation':route_observation}
        postings=raw['postings']
        if len(postings)==1: text=plain_text(postings[0]['description']); method='JobPosting structured data'
        elif not postings: text=raw['text'].strip();method='Visible posting text'
        else: raise NeedsInput('Page contains multiple job postings; select an exact posting')
        if len(text)<200 or len(text)>80000:
            raise NeedsInput('Could not isolate a complete job description')
        observed={**job,'description':text,'description_source':description_url,'description_method':method}
        observed.pop('description_refresh_required',None)
        observed.pop('description_retained_from',None)
        # Preserve discovery URL as identity. The actual form URL can be separate.
        metadata = {key: postings[0].get(key) for key in (
            'hiringOrganization', 'jobLocation', 'jobLocationType', 'applicantLocationRequirements', 'datePosted')} if postings else {}
        write_json(directory/'posting.json',{'job':observed,'extraction':method,'source_metadata':metadata})
        return {**observed,'_application_route_observation':route_observation}
    except BrowserError as error:
        observation={'state':'temporary_failure','queue_status':'retryable',
            'reason':'Public posting read failed; availability remains unverified',
            'requested_url':url,'observed_url':page.url,'checked_at':datetime.now(timezone.utc).isoformat(),
            'error':type(error).__name__,'detail':str(error)}
        write_json(directory/'availability.json',observation)
        raise PostingUnavailable(observation) from error
    finally:
        if not disconnected(browser):page.close()
