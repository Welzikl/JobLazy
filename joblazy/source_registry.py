"""Retain source/query observations independently of candidate-material checkpoints."""
from pathlib import Path
from .common import digest,read_json,write_json
from .store import canonical_url


def record_sources(path,runs,added_ids,observed_ids=None):
    path=Path(path)
    registry=read_json(path) if path.exists() else {'version':1,'sources':{}}
    for run in runs:
        entry=run['entry'];key=digest(entry)[:24];prior=registry['sources'].get(key,{})
        ids=sorted({(observed_ids or {}).get(canonical_url(url),digest(canonical_url(url))[:24]) for url in run.get('urls',[]) if url})
        status=run['status'];finished=run.get('finished_at')
        current={**prior,'config':entry,'last_attempt_started':run.get('started_at'),
            'evidence':run.get('evidence','instrumented_scanner'),
            'last_attempt_finished':finished,'last_status':status,'last_error':run.get('error'),
            'last_warnings':run.get('warnings',[]),'last_seen_job_ids':ids,
            'seen_job_ids':sorted(set(prior.get('seen_job_ids',[]))|set(ids)),
            'new_unique_jobs_seen':len(set(ids)&set(added_ids)),
            'last_successful_scan':prior.get('last_successful_scan'),
            'last_result_with_warnings':prior.get('last_result_with_warnings')}
        if observed_ids is not None:
            current['last_retained_job_ids']=sorted({observed_ids[canonical_url(url)] for url in run.get('urls',[]) if canonical_url(url) in observed_ids})
        if status=='completed':current['last_successful_scan']=finished
        elif status=='completed_with_warnings':current['last_result_with_warnings']=finished
        registry['sources'][key]=current
    write_json(path,registry)
    return registry
