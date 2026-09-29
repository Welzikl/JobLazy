"""Read explicit public application destinations without clicking or sending answers."""
import re
from urllib.parse import urlsplit, urldefrag, parse_qs
from .common import ROOT, NeedsInput, write_json
from .browser import public_url

APPLY_LABEL=re.compile(r'^(?:apply|apply now|apply (?:for|to) (?:this |the )?(?:job|position|role)|apply at .{1,100})$',re.I)
AGGREGATORS={'thehub.io','speedrun-talent-network.com','www.themuse.com','themuse.com'}


def smartrecruiters_destination(anchor,source):
    """An observed posting's marked application link, not a generic interest CTA."""
    if anchor.get('sr_track')!='apply' or anchor.get('label','').strip().casefold() not in {"i'm interested","i’m interested"}:
        return False
    try:
        origin=urlsplit(source);target=urlsplit(anchor.get('url',''))
        if origin.scheme!='https' or origin.netloc!='jobs.smartrecruiters.com':return False
        if target.scheme!='https' or target.netloc!=origin.netloc or target.fragment:return False
        posting=re.fullmatch(r'/([^/]+)/\d+(?:-[^/]+)?/?',origin.path)
        application=re.fullmatch(r'/oneclick-ui/company/([^/]+)/publication/[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}/?',target.path)
        if not posting or not application or posting[1]!=application[1]:return False
        company=parse_qs(target.query,keep_blank_values=True).get('dcr_ci')
        return company is None or company==[posting[1]]
    except (TypeError,ValueError):return False


def destination(raw, source):
    """A unique explicit link, or the exact The Hub posting's public link field."""
    candidates=[]
    for anchor in raw.get('anchors',[]):
        label=' '.join(anchor.get('label','').split())
        target=anchor.get('url','')
        if APPLY_LABEL.fullmatch(label) and urldefrag(target)[0]!=urldefrag(source)[0]:
            candidates.append({'url':target,'method':'visible apply link','label':label})
        elif smartrecruiters_destination({**anchor,'label':label},source):
            candidates.append({'url':target,'method':'visible SmartRecruiters application link','label':label})
    # Some employer sites expose a generic account-level Apply link alongside
    # the posting's explicit "Apply to this job" link. Prefer the latter wording.
    specific=[item for item in candidates if item['label'].casefold() not in ('apply','apply now')]
    if specific: candidates=specific
    parsed=urlsplit(source)
    hub=raw.get('hub_job') or {}
    if parsed.hostname=='thehub.io' and parsed.path.rstrip('/')==f"/jobs/{hub.get('id','')}":
        if hub.get('link'):
            candidates.append({'url':hub['link'],'method':'public The Hub job.link','posting_id':hub['id']})
    if parsed.hostname in ('www.themuse.com','themuse.com'):
        for item in raw.get('muse_jobs',[]):
            if not isinstance(item,dict):continue
            company=item.get('company_slug');slug=item.get('job_slug')
            if (isinstance(company,str) and isinstance(slug,str) and company and slug
                    and item.get('company_short_name')==company and item.get('short_title')==slug
                    and parsed.path.rstrip('/')==f'/jobs/{company}/{slug}'
                    and isinstance(item.get('link'),str) and item['link']):
                candidates.append({'url':item['link'],'method':'public Muse job.applyLink','posting_id':item.get('id')})
    unique={item['url']:item for item in candidates}
    if len(unique)>1: raise NeedsInput('Multiple application destinations; choose the intended employer route')
    if not unique: return None
    result=next(iter(unique.values()))
    try: valid=public_url(result['url'])
    except (TypeError,ValueError): valid=False
    if not valid: raise NeedsInput('Application destination is not a public HTTPS address')
    return result


def resolve_application(job,browser,directory,*,page=None):
    """Recheck routing when preparing, independently of cached ranking/CV content."""
    source=job.get('application_url') or job['url']
    if not public_url(source): raise NeedsInput('Cannot resolve a non-public application URL')
    owned_page=page is None
    page=page or browser.new_page()
    observations=[]
    try:
        checked={}
        def guard(route):
            parsed=urlsplit(route.request.url); origin=f'{parsed.scheme}://{parsed.netloc}'
            if origin not in checked: checked[origin]=public_url(route.request.url)
            route.fallback() if checked[origin] else route.abort()
        page.route('**/*',guard)
        visited=set()
        for _ in range(4):
            if source in visited: raise NeedsInput('Application links form a routing loop')
            visited.add(source)
            response=page.goto(source,wait_until='domcontentloaded',timeout=45000)
            observation={'requested_url':source,'page_url':page.url,'http_status':response.status if response else None}
            observations.append(observation)
            if not response or not response.ok:
                observation['boundary']='http_error'
                raise NeedsInput(f"Application destination is unavailable (HTTP {observation['http_status'] or 'no response'})")
            page.wait_for_timeout(1000)
            raw=page.evaluate((ROOT/'joblazy/read-jd.js').read_text(encoding='utf-8'))
            observation.update({'page_url':page.url,'title':raw['title']})
            # Amazon's email-first account gate has no password input and lives
            # at the host root. Stop before its Continue control resembles a form step.
            if (urlsplit(page.url).hostname == 'passport.amazon.jobs'
                    or urlsplit(page.url).path.rstrip('/').casefold() in ('/login','/signin','/sign-in')
                    or page.locator('input[type=password]:visible').count()):
                observation['boundary']='employer_sign_in'
                raise NeedsInput(f'Employer sign-in is required to open this application: {source}')
            try: route=destination(raw,page.url)
            except NeedsInput as e:
                observation['error']=str(e)
                observation['anchors']=raw.get('anchors',[])
                raise
            observation['destination']=route
            if route:
                source=route['url']
                continue
            if urlsplit(page.url).hostname in AGGREGATORS:
                raise NeedsInput('No explicit employer application destination found on the aggregator')
            return {**job,'application_url':page.url}
        raise NeedsInput('Application route exceeded four public pages')
    finally:
        write_json(directory/'application-route.json',{'observations':observations})
        if owned_page:page.close()
        elif not page.is_closed():page.unroute('**/*',guard)
