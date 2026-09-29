"""Bounded, read-only queue status for everyday operation."""
import json
from datetime import datetime,timezone


def summary(store,limit=20,*,profile=None):
    from .common import digest
    from .assessment_state import assessment_stale,assessment_profile_hash
    profile_hash=digest(profile) if profile is not None else None
    assessment_hash=assessment_profile_hash(profile) if profile is not None else None
    if limit<1:raise ValueError('Status limit must be positive')
    counts={row[0]:row[1] for row in store.db.execute('SELECT status,count(*) FROM jobs GROUP BY status ORDER BY status')}
    rows=store.db.execute("""SELECT id,data,status,result FROM jobs
        LEFT JOIN (SELECT job_id,MAX(seq) AS last_event FROM events GROUP BY job_id) recent ON recent.job_id=jobs.id
        WHERE status!='discovered' ORDER BY updated DESC,last_event DESC,id LIMIT ?""",(limit,))
    jobs=[]
    for row in rows:
        data=json.loads(row['data']);result=(json.loads(row['result']) if row['result'] else None) or {}
        ranking=result.get('ranking') or result
        stale=assessment_stale({'status':row['status'],'result':result,'data':data},profile_hash,assessment_hash)
        jobs.append({'id':row['id'],'title':data['title'],'company':data.get('company',''),
            'status':row['status'],'score':None if stale else ranking.get('score'),
            'assessment_stale':stale if profile is not None else None,
            'reason':'Saved decision uses a different profile or assessment version; refresh required.' if stale else result.get('reason') or ranking.get('reason')})
    day=datetime.now(timezone.utc).date().isoformat()
    processed=sum(n for state,n in counts.items() if state!='discovered')
    return {'total':sum(counts.values()),'counts':counts,'usage_day_utc':day,'usage':store.daily_usage(day),
        'assessment_profile_checked':profile is not None,
        'recent_results':jobs,'more_results':max(0,processed-len(jobs))}
