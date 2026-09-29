"""Public web discovery with independent posting reads before queue intake."""
from datetime import datetime, timezone
from pathlib import Path
import time
from urllib.parse import urlsplit

from jsonschema import validate

from .common import NeedsInput, PostingUnavailable, digest, read_json, write_json
from .discovery import enrich
from .materials import obj, arr
from .pipeline import ingest_discovery_result

TEXT = {'type': 'string'}
SCHEMA = obj({
    'jobs': {**arr(obj({'url': TEXT, 'title': TEXT, 'company': TEXT, 'location': TEXT, 'reason': TEXT})), 'maxItems': 8},
    'gaps': arr(TEXT),
})


def find_postings(plan, brief, model):
    result = model.generate(
        'Find individual current job postings for this personal search brief. Actually search the web. '
        'Prioritize the desired work, location and seniority; use title synonyms and related roles where justified. '
        'Prefer employer career sites and direct ATS postings. Search across employers, never a fixed company list. '
        'Distinguish cities with the same name in different countries; require the requested country. '
        'Remote must plausibly support that country. '
        'Apply an experience ceiling to the stated mandatory minimum, inclusively, never the upper end of a range. '
        'For a five-year ceiling retain 5, 5+, 3-6 and 5-8 years; exclude a confirmed mandatory 6+ minimum. '
        'Do not exclude on senior titles alone under a years-based preference; explicit title exclusions still apply. '
        'Preferred or unclear experience must not become a mandatory exclusion. You have no candidate CV or tenure. '
        'Avoid explicitly closed or expired listings. Do not return careers homepages, '
        'search result pages, articles or speculative jobs. Use exact observed vacancy URLs and titles. '
        'Make exactly one web-search tool call with up to three focused queries and return up to eight distinct posting leads. '
        'Do not open result pages or make follow-up searches; the caller performs actual page verification. '
        'Fewer or zero is fine; explain gaps. '
        'Do not score applicant fit. The caller will independently open and verify every candidate.',
        {'queries': plan['queries'], 'location': plan['location'], 'brief': brief,
         'mission': plan.get('scope', ''), 'search_run': plan.get('search_run'),
         'known_board_ids': plan.get('known_board_ids', []), 'seen_ids': plan.get('seen_ids', []),
         'as_of': datetime.now(timezone.utc).date().isoformat(), 'refresh_window': int(time.time() // 21600)}, SCHEMA)
    validate(result, SCHEMA)
    return result


def source_labels(metadata):
    """Only metadata extracted from the independently read JobPosting is authoritative."""
    def name(value):
        if isinstance(value, str): return value.strip()
        if isinstance(value, dict) and isinstance(value.get('name'), str): return value['name'].strip()
        return ''
    company = name(metadata.get('hiringOrganization'))
    locations = metadata.get('jobLocation') or []
    if isinstance(locations, dict): locations = [locations]
    labels = []
    for item in locations if isinstance(locations, list) else []:
        address = item.get('address') if isinstance(item, dict) else None
        if isinstance(address, dict):
            label = ', '.join(filter(None, (name(address.get(key)) for key in ('addressLocality', 'addressRegion', 'addressCountry'))))
            if label: labels.append(label)
    if metadata.get('jobLocationType') == 'TELECOMMUTE':
        regions = metadata.get('applicantLocationRequirements') or []
        if not isinstance(regions, list): regions = [regions]
        labels.append('Remote' + (': ' + ', '.join(filter(None, map(name, regions))) if any(map(name, regions)) else ' (country unverified)'))
    return company, ' | '.join(dict.fromkeys(labels))


def verify_postings(candidates, browser, directory, *, reader=enrich):
    directory = Path(directory)
    accepted, rejected, seen = [], [], set()
    for candidate in candidates:
        url = candidate['url']
        try: parsed = urlsplit(url)
        except ValueError:
            rejected.append({'url': url, 'reason': 'Malformed posting URL.'}); continue
        if url in seen: continue
        seen.add(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            rejected.append({'url': url, 'reason': 'Not an ordinary public HTTPS posting URL.'}); continue
        evidence = directory / digest(url)[:24]
        # Do not seed authoritative fields with model-written descriptions,
        # employer labels or location claims. Only the title is an identity target.
        seed = {'url': url, 'title': candidate['title'], 'company': '', 'location': '', 'description': '', 'ats': 'web_search'}
        try:
            observed = reader(seed, browser, evidence)
            metadata = read_json(evidence / 'posting.json').get('source_metadata', {})
            company, location = source_labels(metadata)
            observed.pop('_application_route_observation', None)
            observed.update(company=company or 'Employer unverified', location=location or 'Location unverified',
                            observed_at=datetime.now(timezone.utc).isoformat(),
                            source_metadata=metadata)
            accepted.append(observed)
        except PostingUnavailable as error:
            rejected.append({'url': url, 'reason': error.observation['reason'], 'state': error.status})
        except NeedsInput as error:
            rejected.append({'url': url, 'reason': str(error), 'state': 'unverified'})
    return accepted, rejected


def discover_targeted(entry, model, browser, store, directory):
    directory = Path(directory)
    started_at = datetime.now(timezone.utc).isoformat()
    result = find_postings(entry, entry['brief'], model)
    write_json(directory / 'search-results.json', result)
    accepted, rejected = verify_postings(result['jobs'], browser, directory / 'postings')
    warnings = list(result['gaps'])
    if rejected:
        warnings.append(f"{len(rejected)} candidate links could not be verified.")
        warnings.extend(f"Not saved: {item['url']} — {item['reason']}" for item in rejected)
    source_run = {'entry': entry, 'started_at': started_at,
                  'finished_at': datetime.now(timezone.utc).isoformat(),
                  'status': 'completed_with_warnings' if warnings else 'completed',
                  'urls': [job['url'] for job in accepted], 'warnings': warnings}
    # Failed page reads are incomplete discovery, not a six-hour empty success.
    errors = [{'board': entry['name'], 'url': item['url'], 'error': item['reason']}
              for item in rejected if item.get('state') == 'retryable']
    data = {'jobs': accepted, 'errors': errors, 'source_runs': [source_run]}
    report = ingest_discovery_result(data, store, directory / 'checkpoint.json')
    write_json(directory / 'verification.json', {'accepted': len(accepted), 'rejected': rejected,
                                               'gaps': result['gaps']})
    return report
