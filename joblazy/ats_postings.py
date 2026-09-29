"""Read exact observed public ATS postings without a browser or candidate data.

``verify_posting(url, fetch_json=...)`` returns status, observation and, only on
success, a queue-compatible job. The injected fetch has signature
``fetch_json(api_url, timeout=seconds) -> decoded JSON`` and raises HTTPError
for non-2xx responses. Unsupported URL shapes require a different reader;
unavailable means a missing/unlisted source, never proven vacancy closure.
All request destinations are constructed from strict identifiers on fixed
official API hosts. Redirects are deliberately refused.
"""
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
import json
import math
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


UUID = r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}'
BOARD = r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}'
API_HOSTS = {'api.ashbyhq.com', 'boards-api.greenhouse.io', 'api.lever.co', 'api.eu.lever.co'}
MAX_RESPONSE_BYTES = 12 * 1024 * 1024


def parse_posting_url(url):
    """Return exact identity/request coordinates, or None; never guess slugs."""
    if not isinstance(url, str) or re.search(r'[\s\\\x00-\x1f\x7f]', url):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443):
            return None
    except ValueError:
        return None
    host = parsed.hostname
    path = parsed.path.rstrip('/')
    if host == 'jobs.ashbyhq.com':
        match = re.fullmatch(r'/(' + BOARD + r')/(' + UUID + r')(?:/application)?', path)
        if not match:
            return None
        board, posting = match.groups()
        posting = posting.lower()
        provider, region = 'ashby', 'global'
        api_url = f'https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true'
    elif host in ('boards.greenhouse.io', 'job-boards.greenhouse.io', 'job-boards.eu.greenhouse.io'):
        match = re.fullmatch(r'/(' + BOARD + r')/jobs/([0-9]{1,24})', path)
        if match:
            board, posting = match.groups()
        elif path == '/embed/job_app':
            query = parse_qs(parsed.query)
            boards, tokens = query.get('for', []), query.get('token', [])
            if len(boards) != 1 or len(tokens) != 1 or not re.fullmatch(BOARD, boards[0]) or not re.fullmatch(r'[0-9]{1,24}', tokens[0]):
                return None
            board, posting = boards[0], tokens[0]
        else:
            return None
        provider, region = 'greenhouse', 'global'
        api_url = f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{posting}'
    elif host in ('jobs.lever.co', 'jobs.eu.lever.co'):
        match = re.fullmatch(r'/(' + BOARD + r')/(' + UUID + r')(?:/apply)?', path)
        if not match:
            return None
        board, posting = match.groups()
        posting = posting.lower()
        provider, region = 'lever', 'eu' if host == 'jobs.eu.lever.co' else 'global'
        api_host = 'api.eu.lever.co' if region == 'eu' else 'api.lever.co'
        api_url = f'https://{api_host}/v0/postings/{board}/{posting}?mode=json'
    else:
        return None
    identity_provider = 'lever-eu' if provider == 'lever' and region == 'eu' else provider
    return {'provider': provider, 'region': region, 'board': board, 'posting_id': posting,
            'identity': f'{identity_provider}:{board}:{posting}', 'api_url': api_url}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_json(url, *, timeout=20):
    """Bounded stdlib GET. Never follow redirects, including to another API."""
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in API_HOSTS or parsed.username
            or parsed.password or parsed.port not in (None, 443)):
        raise ValueError('Not an allowed public ATS API destination')
    deadline = time.monotonic() + timeout
    request = Request(url, headers={'Accept': 'application/json', 'User-Agent': 'JobLazy/1.0 (public posting verification)'})
    with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
        chunks, size = [], 0
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError('Public ATS response exceeded the time limit')
            chunk = response.read(min(65536, MAX_RESPONSE_BYTES + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise ValueError('Public ATS response exceeds the size limit')
    return json.loads(b''.join(chunks).decode('utf-8-sig'))


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'section'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if tag in ('p', 'div', 'li', 'section'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _string(value):
    return value.strip() if isinstance(value, str) else ''


def _html(value):
    reader = _Text()
    reader.feed(unescape(_string(value)))
    return '\n'.join(line.strip() for line in ''.join(reader.parts).splitlines() if line.strip())


def _unique(values):
    return list(dict.fromkeys(value for value in values if value))


def _matching_url(value, source):
    parsed = parse_posting_url(value)
    return bool(parsed and parsed['identity'] == source['identity'])


def _address_location(value):
    if not isinstance(value, dict):
        return None
    address = value.get('postalAddress', value)
    if not isinstance(address, dict):
        return None
    fields = {key: address[key] for key in ('addressLocality', 'addressRegion', 'addressCountry')
              if isinstance(address.get(key), (str, dict))}
    return {'address': fields} if fields else None


def _normalize(record, source, url, checked_at):
    provider = source['provider']
    metadata = {'ats_provider': provider, 'board': source['board'], 'posting_id': source['posting_id']}
    company, locations, structured, application_url = '', [], [], None
    if provider == 'ashby':
        title = _string(record.get('title'))
        description = _string(record.get('descriptionPlain')) or _html(record.get('descriptionHtml'))
        locations.append(_string(record.get('location')))
        secondary = record.get('secondaryLocations', [])
        for place in [record, *(secondary if isinstance(secondary, list) else [])]:
            if not isinstance(place, dict):
                continue
            locations.append(_string(place.get('location')))
            address = _address_location(place.get('address'))
            if address:
                structured.append(address)
                locations.extend(_string(address['address'].get(key)) for key in ('addressLocality', 'addressRegion', 'addressCountry'))
        if record.get('isRemote') is True:
            metadata['jobLocationType'] = 'TELECOMMUTE'
        for key in ('isListed', 'publishedAt', 'workplaceType', 'employmentType', 'compensation', 'secondaryLocations', 'address'):
            if key in record:
                metadata[key] = record[key]
        application_url = record.get('applyUrl')
    elif provider == 'greenhouse':
        title, description = _string(record.get('title')), _html(record.get('content'))
        company = _string(record.get('company_name'))
        location = record.get('location')
        locations.append(_string(location.get('name')) if isinstance(location, dict) else '')
        offices = record.get('offices', [])
        for office in offices if isinstance(offices, list) else []:
            if isinstance(office, dict):
                locations.extend((_string(office.get('name')), _string(office.get('location'))))
        for key in ('location', 'offices', 'departments', 'updated_at', 'first_published', 'internal_job_id', 'requisition_id', 'absolute_url'):
            if key in record:
                metadata[key] = record[key]
        application_url = record.get('absolute_url')
    else:
        title = _string(record.get('text'))
        parts = [_string(record.get('descriptionPlain')) or _html(record.get('description'))]
        lists = record.get('lists', [])
        for item in lists if isinstance(lists, list) else []:
            if isinstance(item, dict):
                parts.extend((_string(item.get('text')), _html(item.get('content'))))
        parts.append(_string(record.get('additionalPlain')) or _html(record.get('additional')))
        description = '\n\n'.join(filter(None, parts))
        categories = record.get('categories', {})
        if isinstance(categories, dict):
            locations.append(_string(categories.get('location')))
            others = categories.get('allLocations', [])
            if isinstance(others, list):
                locations.extend(_string(value) for value in others)
        for key in ('categories', 'workplaceType', 'country', 'salaryRange', 'salaryDescription', 'createdAt'):
            if key in record:
                metadata[key] = record[key]
        if _string(record.get('workplaceType')).casefold() == 'remote':
            metadata['jobLocationType'] = 'TELECOMMUTE'
        if _string(record.get('country')):
            structured.append({'address': {'addressCountry': record['country']}})
            locations.append(record['country'])
        application_url = record.get('applyUrl')
    if company:
        metadata['hiringOrganization'] = {'name': company}
    if structured:
        metadata['jobLocation'] = structured
    metadata['location_labels'] = _unique(locations)
    job = {'url': url, 'title': title, 'company': company or 'Employer unverified',
           'location': ' | '.join(_unique(locations)) or 'Location unverified',
           'description': description, 'ats': provider, 'source_metadata': metadata,
           'description_source': source['api_url'], 'description_method': 'Official public ATS API',
           'observed_at': checked_at, 'source_provenance': {**source, 'observed_url': url, 'checked_at': checked_at}}
    if _matching_url(application_url, source):
        job['application_url'] = application_url
    return job


def verify_posting(url, *, fetch_json=None, timeout=20, now=None):
    """Verify an exact posting; returned facts never incorporate model hints.

    Failed responses can use a bounded browser fallback. Missing/unlisted
    responses retain uncertainty and must not be represented as explicitly
    closed vacancies. Caller owns persistence and any retry policy.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError('ATS timeout must be greater than zero and at most 60 seconds')
    source = parse_posting_url(url)
    checked_at = (now or datetime.now(timezone.utc)).isoformat()
    observation = {'requested_url': url, 'checked_at': checked_at, 'method': 'public_ats_api', 'http_status': None}

    def result(status, state, reason, **extra):
        return {'status': status, 'observation': {**observation, 'state': state, 'reason': reason}, **extra}

    if not source:
        return result('unsupported', 'unsupported', 'No exact supported ATS posting identity in this observed URL')
    observation.update(source)
    fetcher = fetch_json or globals()['fetch_json']
    try:
        payload = fetcher(source['api_url'], timeout=timeout)
        observation['http_status'] = 200
        if source['provider'] == 'ashby':
            if not isinstance(payload, dict) or not isinstance(payload.get('jobs'), list):
                raise ValueError('Ashby did not return a complete public jobs array')
            for item in payload['jobs']:
                item_source = parse_posting_url(item.get('jobUrl')) if isinstance(item, dict) else None
                if not item_source or item_source['provider'] != 'ashby' or item_source['board'] != source['board']:
                    raise ValueError('Ashby jobs array has malformed or unrelated board identities')
            matches = [item for item in payload['jobs'] if _matching_url(item.get('jobUrl'), source)]
            if not matches:
                return result('unavailable', 'posting_not_listed', 'Exact posting absent from public board response; closure unconfirmed')
            if len(matches) != 1:
                raise ValueError('Public board returned more than one matching posting')
            record = matches[0]
            if record.get('isListed') is False:
                return result('unavailable', 'unlisted', 'Direct-link-only posting is excluded from public search recommendations')
            if 'id' in record and str(record['id']).lower() != source['posting_id']:
                raise ValueError('Ashby posting ID disagrees with its observed URL')
        else:
            record = payload
            if not isinstance(record, dict) or str(record.get('id', '')).lower() != source['posting_id']:
                raise ValueError('ATS response does not identify the requested posting')
            if source['provider'] == 'lever' and not _matching_url(record.get('hostedUrl'), source):
                raise ValueError('Lever hosted URL does not identify the requested posting')
        job = _normalize(record, source, url, checked_at)
        if not job['title'] or not 200 <= len(job['description']) <= 80000:
            raise ValueError('Exact ATS posting lacks a complete title/description')
        return result('verified', 'public_posting_observed', 'Exact public ATS posting returned; application acceptance remains unverified', job=job)
    except HTTPError as error:
        observation['http_status'] = error.code
        if error.code in (404, 410):
            return result('unavailable', 'page_unavailable', f'Public ATS returned HTTP {error.code}; vacancy closure unconfirmed')
        state = 'temporary_failure' if error.code in (408, 429) or error.code >= 500 else 'access_unverified'
        return result('failed', state, f'Public ATS request failed (HTTP {error.code})')
    except (TimeoutError, URLError, OSError) as error:
        return result('failed', 'temporary_failure', f'Public ATS read failed ({type(error).__name__}); availability unverified')
    except (ValueError, TypeError, UnicodeError) as error:
        return result('failed', 'invalid_source', str(error))
