"""Observed ATS boards and bounded public retrieval; caller owns persistence.

Only ``learn_board`` accepts verified reader results. It never accepts a model
board suggestion. Registry dictionaries are JSON serializable and contain no
candidate data. Scans return queue-compatible jobs but do not write the queue.
An empty/partial/failed board read never asserts that any vacancy has closed.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
import time
from urllib.error import HTTPError, URLError

from .ats_postings import _normalize, fetch_json as public_fetch_json, parse_posting_url

SUCCESS_TTL = timedelta(hours=6)
FAILURE_TTL = timedelta(minutes=5)


def _now(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        raise ValueError('Registry timestamps must include a timezone')
    return value.astimezone(timezone.utc)


def _date(value):
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, TypeError):
        return None


def board_key(source):
    return ':'.join(source[key] for key in ('provider', 'region', 'board'))


def _entry_source(entry):
    proof = entry.get('proof', {}) if isinstance(entry, dict) else {}
    if not isinstance(proof, dict):
        return None
    source = parse_posting_url(proof.get('observed_url'))
    if not source or any(entry.get(key) != source[key] for key in ('provider', 'region', 'board')):
        return None
    if proof.get('identity') != source['identity'] or not _date(proof.get('checked_at')):
        return None
    return source


def learn_board(registry, verification):
    """Learn an exact board from a successful independent ATS read, not a hint.

    Pass the entire ``verify_posting`` result. Browser/model results without
    matching official API observation coordinates cannot seed a board.
    """
    if not isinstance(verification, dict) or verification.get('status') != 'verified':
        return False
    job, observation = verification.get('job', {}), verification.get('observation', {})
    if not isinstance(job, dict) or not isinstance(observation, dict):
        return False
    proof = job.get('source_provenance', {})
    if not isinstance(proof, dict):
        return False
    source = parse_posting_url(proof.get('observed_url'))
    if not source or parse_posting_url(job.get('url')) != source:
        return False
    if (observation.get('method') != 'public_ats_api' or observation.get('http_status') != 200
            or observation.get('state') != 'public_posting_observed'
            or not _date(proof.get('checked_at'))
            or observation.get('checked_at') != proof.get('checked_at')
            or any(proof.get(key) != value or observation.get(key) != value for key, value in source.items())):
        return False
    key = board_key(source)
    previous = registry.get(key, {})
    entry = previous if _entry_source(previous) else {}
    entry.update({key: source[key] for key in ('provider', 'region', 'board')})
    entry.setdefault('first_observed_at', proof['checked_at'])
    entry.update({'last_observed_at': proof['checked_at'], 'proof': deepcopy(proof)})
    registry[key] = entry
    return True


def due_boards(registry, *, now=None):
    """Return proven boards eligible for refresh, oldest observation first."""
    current = _now(now)
    entries = [deepcopy(entry) for entry in registry.values()
               if _entry_source(entry) and (not _date(entry.get('next_scan_at'))
                                           or _date(entry['next_scan_at']) <= current)]
    return sorted(entries, key=lambda entry: (entry.get('last_scan_at', ''), board_key(entry)))


def cached_jobs(entry, *, now=None):
    """Return a dated complete-success cache only while its six-hour TTL holds."""
    checked = _date(entry.get('last_success_at'))
    if not _entry_source(entry) or not checked or not checked <= _now(now) < checked + SUCCESS_TTL:
        return []
    return deepcopy(entry.get('cached_jobs', []))


def _record_source(record, source):
    provider, board = source['provider'], source['board']
    if not isinstance(record, dict):
        raise ValueError('Board record is not an object')
    if provider == 'ashby':
        url = record.get('jobUrl')
    elif provider == 'lever':
        url = record.get('hostedUrl')
    else:
        # Greenhouse permits custom employer absolute_url values. Board and
        # posting identity are established by its official board API response.
        url = f"https://job-boards.greenhouse.io/{board}/jobs/{record.get('id', '')}"
    parsed = parse_posting_url(url)
    if not parsed or board_key(parsed) != board_key(source):
        raise ValueError('Board record does not identify a posting on this board')
    if 'id' in record and str(record['id']).lower() != parsed['posting_id']:
        raise ValueError('Board posting ID disagrees with its URL')
    return parsed, url


def scan_board(entry, *, fetch_json=None, timeout=20, max_pages=4,
               max_records=1000, page_size=100, now=None):
    """Read a discovered board within one total time/page/record budget.

    Ashby and Greenhouse return a single public array; Lever uses bounded
    ``skip``/``limit`` pagination. ``complete`` means the fetched public array
    ended and every listed record could be normalized, not market coverage or
    application acceptance. Partial results preserve good records and errors.
    The injected fetch must honor its supplied timeout, as the default does.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError('Board timeout must be greater than zero and at most 60 seconds')
    for name, value, cap in [('max_pages', max_pages, 20), ('max_records', max_records, 5000), ('page_size', page_size, 1000)]:
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= cap:
            raise ValueError(f'{name} must be an integer between 1 and {cap}')
    source = _entry_source(entry)
    if not source:
        raise ValueError('Board has no independently verified posting proof')
    checked_at = _now(now).isoformat()
    provider, board = source['provider'], source['board']
    if provider == 'ashby':
        base = f'https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true'
    elif provider == 'greenhouse':
        base = f'https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true'
    else:
        host = 'api.eu.lever.co' if source['region'] == 'eu' else 'api.lever.co'
        base = f'https://{host}/v0/postings/{board}?mode=json'
    observation = {'board_key': board_key(source), 'checked_at': checked_at,
                   'method': 'public_ats_board_api', 'api_url': base, 'pages': 0,
                   'records_seen': 0, 'unlisted': 0, 'errors': [], 'closure_inferred': False}
    jobs, seen, ended = [], set(), False
    fetcher = fetch_json or public_fetch_json
    deadline = time.monotonic() + timeout
    for page in range(max_pages):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            observation['errors'].append('Board total time limit reached')
            break
        count = min(page_size, max_records - observation['records_seen'])
        url = f'{base}&skip={observation["records_seen"]}&limit={count}' if provider == 'lever' else base
        try:
            payload = fetcher(url, timeout=remaining)
            observation['pages'] += 1
            if time.monotonic() > deadline:
                raise TimeoutError('Board total time limit reached')
            records = payload if provider == 'lever' else payload.get('jobs') if isinstance(payload, dict) else None
            if not isinstance(records, list):
                raise ValueError('Public board response lacks its jobs array')
            if provider == 'greenhouse' and isinstance(payload.get('meta'), dict):
                total = payload['meta'].get('total')
                if isinstance(total, int) and not isinstance(total, bool) and total > len(records):
                    observation['errors'].append('Greenhouse reports more postings than its returned jobs array')
            available = max_records - observation['records_seen']
            limit = min(available, count) if provider == 'lever' else available
            bounded = records[:limit]
            if len(records) > limit:
                observation['errors'].append('Board record limit reached or provider exceeded requested page size')
            for record in bounded:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Board total time limit reached')
                observation['records_seen'] += 1
                try:
                    item_source, posting_url = _record_source(record, source)
                    if item_source['identity'] in seen:
                        raise ValueError('Duplicate posting identity in board response')
                    seen.add(item_source['identity'])
                    if provider == 'ashby' and record.get('isListed') is False:
                        observation['unlisted'] += 1
                        continue
                    job = _normalize(record, item_source, posting_url, checked_at)
                    if not job['title'] or not 200 <= len(job['description']) <= 80000:
                        raise ValueError('Board posting lacks a complete title/description')
                    # Preserve the actual collection API, not an unperformed
                    # individual detail read, as description evidence.
                    job['description_source'] = url
                    job['source_provenance']['board_api_url'] = url
                    jobs.append(job)
                except (ValueError, TypeError) as error:
                    observation['errors'].append(str(error))
            ended = len(records) <= limit and (provider != 'lever' or len(records) < count)
            if ended or observation['records_seen'] >= max_records:
                break
        except (HTTPError, URLError, OSError, ValueError, TypeError, UnicodeError) as error:
            observation['errors'].append(f'{type(error).__name__}: {error}')
            if isinstance(error, HTTPError):
                observation['http_status'] = error.code
            break
    if not ended and not observation['errors']:
        observation['errors'].append('Board page or record limit reached before end of results')
    complete = ended and not observation['errors']
    return {'status': 'complete' if complete else 'partial' if jobs else 'failed',
            'complete': complete, 'jobs': jobs, 'observation': observation}


def record_scan(registry, result):
    """Persist scan metadata/cache in caller-owned registry; never infer closure."""
    observation = result['observation']
    entry = registry.get(observation['board_key'])
    if not _entry_source(entry):
        raise ValueError('Scan does not belong to a proven registry board')
    checked = _date(observation.get('checked_at'))
    if not checked:
        raise ValueError('Scan has no valid timestamp')
    if _date(entry.get('last_scan_at')) and checked < _date(entry['last_scan_at']):
        return False
    successful = result.get('status') == 'complete' and result.get('complete') is True
    entry.update({'last_scan_at': checked.isoformat(), 'last_scan_status': result['status'],
                  'last_scan': deepcopy(observation),
                  'next_scan_at': (checked + (SUCCESS_TTL if successful else FAILURE_TTL)).isoformat()})
    if successful:
        entry.update({'last_success_at': checked.isoformat(), 'cached_jobs': deepcopy(result['jobs'])})
    return True
