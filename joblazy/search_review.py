"""Batch fit review for freshly verified search snapshots, never applications."""
from datetime import datetime, timezone
from pathlib import Path

from .common import ModelUnavailable, DailyModelLimit, write_json
from .discovery_intake import routes
from .pipeline import queue_candidates, schedule_candidates
from .profiles import require_profile
from .usage import model_context
from .workflow_usage import ProcessingAttempt


def snapshot_matches(observed, saved, *, now=None, freshness_seconds=900):
    """Only reuse recent source checks for the same substantive posting."""
    try:
        checked = datetime.fromisoformat(observed['observed_at'])
        age = ((now or datetime.now(timezone.utc)) - checked).total_seconds()
    except (KeyError, TypeError, ValueError):
        return False
    if not 0 <= age <= freshness_seconds or not (routes(observed) & routes(saved)):
        return False
    normal = lambda value: ' '.join(str(value or '').split())
    if any(normal(observed.get(key)) != normal(saved.get(key)) for key in ('title', 'location', 'description')):
        return False
    if normal(observed.get('company')) == normal(saved.get('company')):
        return True
    retained = saved.get('retained_source_fields', {}).get('company', {})
    return (observed.get('company') == 'Employer unverified' and retained.get('source')
            and retained.get('value') == saved.get('company'))


class SnapshotIndex:
    """Find exact-route candidates before checking freshness and source content."""
    def __init__(self, observed_jobs):
        self.by_route = {}
        for observed in observed_jobs:
            for route in routes(observed):
                self.by_route.setdefault(route, []).append(observed)

    def matches(self, saved, *, now=None):
        return any(snapshot_matches(observed, saved, now=now)
                   for route in routes(saved) for observed in self.by_route.get(route, ()))


def review_verified(store, profile, model, observed_jobs, output, *, limit=5, directory=None, batch_size=2):
    """Return None if no fresh candidates exist, so caller can use normal reads.

    Caller owns the process lock and global daily limits. Each processed role
    receives the ordinary durable processing event, so shared attempt accounting
    and interruption recovery remain intact. Shared request reservations still
    occur in the supplied model's before_request callback.
    """
    from .shortlist_review import rank_batch
    if type(batch_size) is not int or not 1 <= batch_size <= 5:
        raise ValueError('Review batch size must be between one and five.')
    require_profile(profile)
    store.recover()
    candidates = queue_candidates(store, rank_only=True, profile=profile)
    candidates = [row for row in candidates if any(snapshot_matches(observed, row['data']) for observed in observed_jobs)]
    candidates = schedule_candidates(candidates, profile, prioritized_ids=store.pursued_ids(candidates))[:limit]
    if not candidates:
        return None
    results = []
    # Full evidence assessments produce much more output than discovery leads.
    # A live five-role Astra batch exceeded the transport deadline; keep the
    # default small so early validated results persist before the next request.
    for offset in range(0, len(candidates), batch_size):
        batch, timings = [], {}
        for row in candidates[offset:offset + batch_size]:
            key, job = row['id'], row['data']
            choice = store.choice(key, job)
            if choice and choice['current'] and choice['decision'] == 'pass':
                store.transition(key, 'not_selected', {'reason': 'User chose to pass on this role', 'user_choice': choice}, expected={row['status']})
                results.append({'id': key, 'status': 'not_selected'})
                continue
            prior = store.prior_application(job, exclude_id=key)
            if prior:
                store.transition(key, 'needs_input', {'reason': 'Exact posting has a prior application or unresolved handoff',
                                 'prior_job_id': prior['id'], 'prior_status': prior['status']}, expected={row['status']})
                results.append({'id': key, 'status': 'needs_input'})
                continue
            store.transition(key, 'processing', expected={row['status']})
            timings[key] = ProcessingAttempt(Path(output) / key, key, 'rank_only', False)
            batch.append(row)
        if not batch: continue
        context = model_context.set({'job_id': None, 'stage': 'shortlist_review'})
        interruption = None
        try:
            review = rank_batch(batch, profile, model,
                                directory=Path(directory) / str(offset) if directory else None)
        except ModelUnavailable as error:
            interruption = error
            review = {'results': getattr(error, 'batch_results', {}), 'errors': getattr(error, 'batch_errors', {})}
        finally:
            model_context.reset(context)
        for row in batch:
            key, job = row['id'], row['data']
            if interruption is not None and key not in review['results']:
                detail = {'reason': str(interruption), 'failure_kind': 'daily_model_limit' if isinstance(interruption, DailyModelLimit) else 'model_unavailable',
                          'requires_user_input': False}
                store.transition(key, 'retryable', detail, expected={'processing'})
                results.append({'id': key, 'status': 'retryable', **detail})
            elif key in review['errors']:
                detail = {'reason': review['errors'][key], 'failure_kind': 'assessment_validation', 'requires_user_input': False}
                store.transition(key, 'assessment_failed', detail, expected={'processing'})
                results.append({'id': key, 'status': 'assessment_failed', **detail})
            else:
                ranking = review['results'][key]
                choice = store.choice(key, job)
                pursue = bool(choice and choice['current'] and choice['decision'] == 'pursue')
                selected = (ranking['eligible'] and ranking.get('fit_category') != 'poor_fit'
                            and (ranking['score'] >= profile.get('minimum_score', 70) or pursue))
                status = 'ranked' if selected else 'not_selected'
                write_json(Path(output) / key / 'ranking.json', ranking)
                write_json(Path(output) / key / 'selection.json', {'user_choice': choice,
                           'below_cutoff_override': bool(selected and ranking['score'] < profile.get('minimum_score', 70))})
                store.transition(key, status, {'ranking': ranking} if selected else ranking, expected={'processing'})
                results.append({'id': key, 'status': status})
            timings[key].finish(results[-1]['status'])
        if interruption is not None: break
    return results
