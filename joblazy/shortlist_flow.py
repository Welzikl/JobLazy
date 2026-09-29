"""Preliminary search recommendations without full application assessment."""
from pathlib import Path

from .common import ModelUnavailable, digest, read_json, write_json
from .pipeline import queue_candidates, schedule_candidates
from .search_review import SnapshotIndex
from .shortlist_selection import diversify_candidates
from .materials import ranking_posting
from .usage import model_context
from .workflow_usage import ProcessingAttempt


def shortlist_verified(store, profile, model, observed_jobs, directory, *, limit=5):
    from .search_shortlist import review_shortlist
    if type(limit) is not int or limit < 0:
        raise ValueError('Shortlist attempt limit must be a nonnegative integer')
    directory = Path(directory)
    store.recover()
    snapshots = SnapshotIndex(observed_jobs)
    rows = []
    for row in queue_candidates(store, rank_only=True, profile=profile):
        if not snapshots.matches(row['data']): continue
        if row['data'].get('description_refresh_required'): continue
        choice = store.choice(row['id'], row['data'])
        if choice and choice['current'] and choice['decision'] == 'pass': continue
        if store.prior_application(row['data'], exclude_id=row['id']): continue
        rows.append(row)
    pursued_ids=store.pursued_ids(rows)
    rows = schedule_candidates(rows, profile, prioritized_ids=pursued_ids)
    def binding(row, *, legacy=False):
        return digest({'profile': profile, 'job': row['data'] if legacy else ranking_posting(row['data']),
                       'review_contract': 1 if legacy else 2,
                       'model': getattr(model, 'model', type(model).__name__),
                       'reasoning_effort': getattr(model, 'reasoning_effort', None)})
    pending, decisions, records, unrevised = [], {}, [], []
    for row in rows:
        path = directory / 'decisions' / (row['id'] + '.json')
        try: saved = read_json(path) if path.exists() else None
        except (OSError, ValueError): saved = None
        current_binding=binding(row)
        if (isinstance(saved, dict) and isinstance(saved.get('decision'), dict)
                and saved.get('binding') in {current_binding,binding(row,legacy=True)}):
            decisions[row['id']] = saved['decision']
            if saved['binding']!=current_binding:
                write_json(path,{'binding':current_binding,'decision':saved['decision']})
        else:
            unrevised.append(row)
    pending=diversify_candidates(unrevised,profile,pursued_ids=pursued_ids)[:limit]
    attempts, processing_rows = {}, []
    if pending:
        context = model_context.set({'job_id': None, 'stage': 'search_shortlist'})
        try:
            for row in pending:
                store.transition(row['id'], 'processing', {'stage': 'search_shortlist',
                    'prior_status': row['status'], 'prior_result': row['result']}, expected={row['status']})
                processing_rows.append(row)
                attempts[row['id']] = ProcessingAttempt(directory / 'attempts' / row['id'], row['id'], 'search_shortlist', False)
            try:
                review = review_shortlist(pending, profile, model, directory=directory / 'audits' / digest(pending))
            except ModelUnavailable as error:
                review = {'results': getattr(error, 'batch_results', {}),
                          'errors': {row['id']: str(error) for row in pending if row['id'] not in getattr(error, 'batch_results', {})}}
            for row in pending:
                key = row['id']
                if key in review['results']:
                    decision = review['results'][key]
                    decisions[key] = decision
                    write_json(directory / 'decisions' / (key + '.json'), {
                        'binding': binding(row), 'decision': decision})
                    records.append({'id': key, 'status': 'shortlisted' if decision['recommend'] else 'not_shortlisted'})
                else:
                    records.append({'id': key, 'status': 'review_failed', 'reason': review['errors'].get(key, 'No validated decision')})
        finally:
            model_context.reset(context)
            # Preliminary opinions never promote a role to ranked, clear a
            # prior assessment failure, or overwrite its preparation state.
            for row in processing_rows:
                store.transition(row['id'], row['status'], row['result'], expected={'processing'})
                outcome = next((r['status'] for r in records if r['id'] == row['id']), 'review_failed')
                if row['id'] in attempts: attempts[row['id']].finish(outcome)
    shortlist = []
    for row in rows:
        decision = decisions.get(row['id'])
        if not decision or not decision['recommend']: continue
        job = row['data']
        shortlist.append({'id': row['id'], 'title': job['title'], 'company': job.get('company', ''),
            'url': job['url'], 'location': job.get('location', ''), 'score': None,
            'preliminary': True, 'reason': decision['reason'], 'missing_facts': decision['caveats'],
            'observed_at': job.get('observed_at'), 'evidence': decision['job_quotes']})
    unresolved = sum(r['status'] == 'review_failed' for r in records)
    return {'results': records, 'shortlist': shortlist, 'preliminary': True,
            'reused_decisions': len(decisions)-sum(r['status'] in {'shortlisted','not_shortlisted'} for r in records),
            'message': ('Shortlist review finished' + (f' with {unresolved} unresolved roles' if unresolved else '') +
                        '. Recommendations are preliminary; run the full fit assessment before preparation. No applications were prepared.')}
