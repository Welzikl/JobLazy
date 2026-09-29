"""Bounded discovery workers; only the calling thread owns queue mutations."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timezone
from pathlib import Path
from threading import BoundedSemaphore
import time
from urllib.parse import urlsplit
from uuid import uuid4

from .common import NeedsInput, PostingUnavailable, digest, read_json, write_json
from .discovery_intake import identity
from .pipeline import ingest_discovery_result
from .targeted_search import find_postings


def discover_missions(entry, store, directory, *, missions, model_factory, verifier,
                      max_workers=3, progress=None, run_id=None, registry_path=None,
                      board_reader=None, select_board_jobs=None, max_boards=12, max_board_jobs=120):
    """Search and verify concurrently, checkpointing each completed observation.

    A supplied run_id resumes completed immutable worker/verification artifacts.
    An ordinary new search uses a new run ID, so cached model responses cannot
    masquerade as freshly dispatched searches. Store never enters an executor.
    """
    if type(max_workers) is not int or not 1 <= max_workers <= 6:
        raise ValueError('Search concurrency must be between one and six')
    run_id = run_id or uuid4().hex
    if not run_id.isalnum() or len(run_id) > 64:
        raise ValueError('Invalid search run identifier')
    directory = Path(directory)
    run_dir = directory / 'runs' / run_id
    binding = digest({'entry': entry, 'missions': missions})
    manifest = run_dir / 'manifest.json'
    if manifest.exists() and read_json(manifest).get('binding') != binding:
        raise ValueError('Search resume inputs changed')
    started = time.monotonic()
    write_json(manifest, {'run_id': run_id, 'binding': binding, 'entry': entry, 'missions': missions, 'state': 'running',
                         'started_at': datetime.now(timezone.utc).isoformat()})
    known = {r[0] for r in store.db.execute('SELECT id FROM jobs')}
    accepted, rejected, errors, warnings, seen = [], [], [], [], set()
    accepted_keys = set()
    source = {'entry': entry, 'status': 'in_progress', 'urls': [], 'warnings': warnings}
    data = {'jobs': accepted, 'errors': errors, 'source_runs': [source]}
    metrics = {'run_id': run_id, 'missions': len(missions), 'missions_completed': 0,
               'missions_failed': 0, 'raw_leads': 0, 'duplicate_leads': 0,
               'verified': 0, 'rejected': 0, 'first_verified_seconds': None,
               'boards_scanned': 0, 'board_jobs_added': 0, 'cached_board_jobs': 0,
               'search_concurrency': max_workers, 'state': 'running'}
    host_limits = {}
    registry = read_json(registry_path) if registry_path and Path(registry_path).exists() else {}
    registry_dirty = False
    scheduled_boards = set()
    intaked = 0
    report = {'discovered': 0, 'new_unique_jobs': 0, 'errors': errors, 'fetched_records': 0,
              'excluded_by_location': {}, 'exact_route_joins': [], 'ambiguous_route_matches': []}

    def checkpoint():
        nonlocal intaked, registry_dirty
        if len(accepted) > intaked:
            batch = ingest_discovery_result({'jobs': accepted[intaked:], 'errors': [], 'source_runs': [source]},
                                            store, run_dir / 'intake.json')
            report['discovered'] += batch['discovered']
            report['new_unique_jobs'] += batch['new_unique_jobs']
            for key in ('exact_route_joins', 'ambiguous_route_matches'):
                report[key].extend(batch[key])
            intaked = len(accepted)
        report['fetched_records'] = len(accepted)
        write_json(directory / 'checkpoint.json', {**data, 'intake': report})
        metrics.update(verified=len(accepted) - metrics['cached_board_jobs'], rejected=len(rejected),
                       elapsed_seconds=round(time.monotonic() - started, 3))
        write_json(run_dir / 'progress.json', metrics)
        write_json(run_dir / 'verification.json', {'accepted': accepted, 'rejected': rejected})
        if registry_path and registry_dirty:
            write_json(registry_path, registry)
            registry_dirty = False
        if progress: progress(dict(metrics))
        return report

    def search(index, mission):
        path = run_dir / 'missions' / f'{index}.json'
        if path.exists():
            result = read_json(path)
            from jsonschema import validate
            from .targeted_search import SCHEMA
            validate(result, SCHEMA)
            return result
        request = {**mission, 'search_run': run_id}
        result = find_postings(request, request.get('brief', entry['brief']), model_factory(mission))
        write_json(path, result)
        return result

    def verify(candidate, limiter):
        path = run_dir / 'postings' / digest(identity(candidate['url']))[:24] / 'verified.json'
        if path.exists() and time.time() - path.stat().st_mtime <= 900:
            return read_json(path)
        with limiter:
            result = verifier(candidate, path.parent)
        if not isinstance(result, dict) or not result.get('description') or not result.get('url'):
            raise NeedsInput('Posting verification returned no source description')
        write_json(path, result)
        return result

    checkpoint()
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='job-search') as searches, \
         ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='posting-read') as readers:
        pending = {searches.submit(search, i, mission): ('search', mission)
                   for i, mission in enumerate(missions)}

        def schedule_boards():
            if not registry_path or not board_reader: return
            from .ats_registry import due_boards, board_key
            for board in due_boards(registry):
                key = board_key(board)
                if key in scheduled_boards: continue
                if len(scheduled_boards) >= max_boards:
                    if 'Board scan limit reached; remaining sources await a later search.' not in warnings:
                        warnings.append('Board scan limit reached; remaining sources await a later search.')
                    break
                scheduled_boards.add(key)
                pending[readers.submit(board_reader, board)] = ('board', board)

        if registry_path and board_reader:
            from .ats_registry import board_key
            for artifact in (run_dir / 'boards').glob('*.json'):
                previous = read_json(artifact)
                observation = previous.get('observation', {})
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(observation['checked_at'])).total_seconds()
                except (KeyError, ValueError, TypeError): continue
                key = observation.get('board_key')
                if key not in registry or not 0 <= age <= 900: continue
                scheduled_boards.add(key)
                pending[readers.submit(lambda result=previous: result)] = ('board', registry[key])
        schedule_boards()
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                kind, item = pending.pop(future)
                try:
                    result = future.result()
                    if kind == 'search':
                        metrics['missions_completed'] += 1
                        warnings.extend(result['gaps'])
                        for candidate in result['jobs']:
                            metrics['raw_leads'] += 1
                            try:
                                parsed = urlsplit(candidate['url'])
                                if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
                                    raise ValueError('Not a public HTTPS posting URL')
                                key = identity(candidate['url'])
                            except ValueError:
                                rejected.append({'url': candidate['url'], 'reason': 'Malformed or unsupported posting URL'})
                                continue
                            if key in seen or key in accepted_keys:
                                metrics['duplicate_leads'] += 1
                                continue
                            seen.add(key)
                            limiter = host_limits.setdefault(parsed.hostname, BoundedSemaphore(2))
                            pending[readers.submit(verify, candidate, limiter)] = ('verify', candidate)
                    elif kind == 'board':
                        from .ats_registry import record_scan
                        record_scan(registry, result)
                        registry_dirty = True
                        metrics['boards_scanned'] += 1
                        write_json(run_dir / 'boards' / (digest(result['observation']['board_key'])[:24] + '.json'), result)
                        if not result['complete']:
                            errors.append({'board': result['observation']['board_key'],
                                           'error': '; '.join(result['observation']['errors'])})
                        selected = select_board_jobs(result['jobs']) if select_board_jobs else result['jobs']
                        for job in selected:
                            key = identity(job['url'])
                            if key in accepted_keys: continue
                            if metrics['board_jobs_added'] >= max_board_jobs:
                                if 'Board candidate limit reached; full source evidence is retained.' not in warnings:
                                    warnings.append('Board candidate limit reached; full source evidence is retained.')
                                break
                            seen.add(key)
                            accepted_keys.add(key)
                            accepted.append(job)
                            source['urls'].append(job['url'])
                            metrics['board_jobs_added'] += 1
                            if metrics['first_verified_seconds'] is None:
                                metrics['first_verified_seconds'] = round(time.monotonic() - started, 3)
                    else:
                        key = identity(result['url'])
                        if key not in accepted_keys:
                            accepted_keys.add(key)
                            accepted.append(result)
                            source['urls'].append(result['url'])
                        if metrics['first_verified_seconds'] is None:
                            metrics['first_verified_seconds'] = round(time.monotonic() - started, 3)
                        if registry_path:
                            from .ats_registry import learn_board
                            proof_path = run_dir / 'postings' / digest(identity(item['url']))[:24] / 'ats.json'
                            if proof_path.exists():
                                registry_dirty = learn_board(registry, read_json(proof_path)) or registry_dirty
                                schedule_boards()
                except Exception as error:
                    if kind == 'search':
                        metrics['missions_failed'] += 1
                        errors.append({'board': entry['name'], 'mission': item.get('id', ''),
                                       'error': f'Search mission failed ({type(error).__name__})'})
                    elif kind == 'board':
                        from .ats_registry import board_key
                        errors.append({'board': board_key(item), 'error': f'Board read failed ({type(error).__name__})'})
                    else:
                        state = error.status if isinstance(error, PostingUnavailable) else 'unverified'
                        rejected.append({'url': item['url'], 'reason': str(error) if isinstance(error, (NeedsInput, PostingUnavailable))
                                         else f'Posting read failed ({type(error).__name__})', 'state': state})
                        if state in ('retryable', 'unverified'):
                            errors.append({'board': entry['name'], 'url': item['url'],
                                           'error': rejected[-1]['reason']})
                checkpoint()
    if registry_path:
        from .ats_registry import cached_jobs
        for board in registry.values():
            cached = cached_jobs(board)
            for job in select_board_jobs(cached) if select_board_jobs else cached:
                key = identity(job['url'])
                if key in accepted_keys or metrics['board_jobs_added'] >= max_board_jobs: continue
                seen.add(key)
                accepted_keys.add(key)
                accepted.append(job)
                source['urls'].append(job['url'])
                metrics['cached_board_jobs'] += 1
                metrics['board_jobs_added'] += 1
        source['cached_board_jobs'] = metrics['cached_board_jobs']
        source['oldest_observed_at'] = min((job.get('observed_at') for job in accepted if job.get('observed_at')), default=None)
    def rescued(item):
        try: return identity(item.get('url', '')) in accepted_keys
        except ValueError: return False
    rejected[:] = [item for item in rejected if not rescued(item)]
    errors[:] = [item for item in errors if not rescued(item)]
    if rejected: warnings.append(f'{len(rejected)} candidate links could not be verified.')
    source['status'] = 'completed_with_warnings' if errors or warnings else 'completed'
    source['finished_at'] = datetime.now(timezone.utc).isoformat()
    metrics['state'] = 'complete_with_gaps' if errors or warnings else 'complete'
    report = checkpoint()
    report['new_unique_jobs'] = len({r[0] for r in store.db.execute('SELECT id FROM jobs')} - known)
    report['metrics'] = metrics
    write_json(manifest, {'run_id': run_id, 'binding': binding, 'entry': entry, 'missions': missions, 'state': metrics['state'],
                         'finished_at': source['finished_at']})
    return report
