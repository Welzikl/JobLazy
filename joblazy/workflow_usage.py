"""Durable processing-attempt timing and read-only counts of recorded operator actions."""
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from uuid import uuid4
from contextlib import closing
import json
import math
import sqlite3
import time
from .common import read_json,write_json


class ProcessingAttempt:
    def __init__(self,directory,job_id,mode,fixture_mode):
        now=datetime.now(timezone.utc)
        self.path=Path(directory)/'processing-attempts'/now.date().isoformat()/(uuid4().hex+'.json')
        self.started=time.monotonic()
        self.record={'version':1,'job_id':job_id,'mode':mode,'fixture_mode':fixture_mode,
            'started_at':now.isoformat(),'finished_at':None,'state':'incomplete',
            'outcome_status':None,'elapsed_seconds':None}
        write_json(self.path,self.record)

    def finish(self,status):
        if status in ('processing','submitting'):return
        self.record.update(state='complete',outcome_status=status,
            finished_at=datetime.now(timezone.utc).isoformat(),
            elapsed_seconds=round(time.monotonic()-self.started,4))
        write_json(self.path,self.record)


def operator_actions(database,day,job_id):
    counts=Counter();by_job={}
    available=False;unreadable=0
    if Path(database).exists():
        try:
            with closing(sqlite3.connect('file:'+Path(database).resolve().as_posix()+'?mode=ro',uri=True)) as db:
                query='SELECT job_id,status,detail FROM events WHERE date(created)=?'
                args=[day]
                if job_id is not None:query+=' AND job_id=?';args.append(job_id)
                for key,status,raw in db.execute(query,args):
                    try:detail=json.loads(raw) if raw else {}
                    except (ValueError,TypeError):unreadable+=1;continue
                    if not isinstance(detail,dict):detail={}
                    kind=('job_choice' if status=='user_choice' else
                        'scoped_answer' if detail.get('reason')=='Operator supplied a scoped answer' else
                        'outcome_report' if detail.get('method')=='operator_report' else None)
                    if kind:
                        counts[kind]+=1;by_job.setdefault(key,Counter())[kind]+=1
                available=True
        except sqlite3.Error:pass
    return {'history_available':available,'by_kind':dict(counts) if available else None,
        'by_job':[{'job_id':key,'by_kind':dict(value)} for key,value in sorted(by_job.items())],
        'unreadable_events':unreadable,'all_interventions_measured':False,
        'scope':'Recorded job choices, scoped-answer transitions and operator outcome reports only. '
            'Manual browser edits, chat clarifications and unjournaled actions are not counted; these counts are not total human interventions.'}


def summarize_workflow(data,day,job_id=None):
    records=[];unreadable=0
    for path in sorted((Path(data)/'applications').glob('*/processing-attempts/'+day+'/*.json')):
        try:
            record=read_json(path);elapsed=record.get('elapsed_seconds')
            if (record.get('version')!=1 or not isinstance(record.get('job_id'),str)
                    or record['job_id']!=path.parents[2].name
                    or record.get('mode') not in ('rank_only','cv_only','prepare','submit')
                    or type(record.get('fixture_mode')) is not bool
                    or record.get('state') not in ('incomplete','complete')
                    or (record['state']=='complete' and (type(elapsed) not in (int,float)
                        or not math.isfinite(elapsed) or elapsed<0 or not isinstance(record.get('outcome_status'),str)))
                    or (record['state']=='incomplete' and elapsed is not None)):
                raise ValueError('Invalid processing attempt')
        except (OSError,ValueError,AttributeError):unreadable+=1;continue
        if job_id is None or record['job_id']==job_id:records.append(record)
    def aggregate(items):
        completed=[r for r in items if r['state']=='complete']
        return {'attempts':len(items),'completed_attempts':len(completed),
            'incomplete_attempts':len(items)-len(completed),
            'completed_attempt_seconds':round(sum(r['elapsed_seconds'] for r in completed),4) if completed else None,
            'outcomes':dict(Counter(r['outcome_status'] for r in completed))}
    groups={}
    for record in records:groups.setdefault((record['job_id'],record['mode'],record['fixture_mode']),[]).append(record)
    return {**aggregate(records),'unreadable_records':unreadable,
        'by_job_mode':[{'job_id':key[0],'mode':key[1],'fixture_mode':key[2],**aggregate(items)} for key,items in sorted(groups.items())],
        'recorded_operator_actions':operator_actions(Path(data)/'jobs.sqlite',day,job_id),
        'scope':'New pipeline attempts only, grouped by start UTC day, job and requested mode. '
            'Elapsed time includes posting reads, model work and local preparation inside each processing attempt, not queue waiting or human review time. '
            'Older or incomplete attempts have unknown total time; incomplete does not mean still running. '
            'Fixture mode records whether a fixture origin was supplied, not independent proof of a real employer run. '
            'Outcome statuses are not a preparation success rate or verified submission receipts.'}
