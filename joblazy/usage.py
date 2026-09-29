"""Private invocation accounting, separate from request-limit reservations."""
from contextvars import ContextVar
from datetime import datetime, timezone, date
from pathlib import Path
from uuid import uuid4
import time
import math
from .common import read_json, write_json


model_context=ContextVar('joblazy_model_context',default=None)
TOKEN_FIELDS=('input_tokens','cached_input_tokens','cache_write_input_tokens','output_tokens','reasoning_output_tokens')


class ModelCall:
    def __init__(self,cache,model):
        now=datetime.now(timezone.utc)
        self.path=Path(cache)/'calls'/now.date().isoformat()/(uuid4().hex+'.json')
        self.started=time.monotonic()
        context=model_context.get() or {}
        self.record={'version':1,'started_at':now.isoformat(),'model':model,
            'job_id':context.get('job_id'),'stage':context.get('stage'),'state':'incomplete',
            'cache':'unchecked','inference_attempted':False,'usage':None,'elapsed_seconds':None}
        self.update()

    def update(self,**values):
        self.record.update(values)
        write_json(self.path,self.record)

    def finish(self,state,error=None):
        self.update(state=state,error_type=type(error).__name__ if error else None,
            elapsed_seconds=round(time.monotonic()-self.started,4))


def _aggregate(records):
    attempts=[r for r in records if r['inference_attempted']]
    tokens={}
    for field in TOKEN_FIELDS:
        values=[(r.get('usage') or {}).get(field) for r in attempts]
        valid=[v for v in values if type(v) is int and v>=0]
        tokens[field]={'reported':sum(valid),'unknown_attempts':len(values)-len(valid)}
    return {'calls':len(records),'inference_attempts':len(attempts),
        'cache_hits':sum(r['cache']=='hit' for r in records),
        'cached_failures':sum(r['cache'] in ('invalid_hit','corrupt_hit') for r in records),
        'failed_calls':sum(r['state']=='failed' for r in records),
        'incomplete_calls':sum(r['state']=='incomplete' for r in records),
        'completed_call_seconds':round(sum(r['elapsed_seconds'] or 0 for r in records),4),
        'tokens':tokens}


def summarize(cache,day=None,job_id=None):
    day=day or datetime.now(timezone.utc).date().isoformat()
    if date.fromisoformat(day).isoformat()!=day:raise ValueError('Use YYYY-MM-DD for the UTC day')
    records=[];unreadable=0
    for path in sorted((Path(cache)/'calls'/day).glob('*.json')):
        try:
            record=read_json(path)
            if (record.get('version')!=1 or not {'job_id','stage','elapsed_seconds'}.issubset(record)
                or type(record.get('inference_attempted')) is not bool
                or record.get('state') not in ('incomplete','complete','failed')
                or record.get('cache') not in ('unchecked','miss','hit','invalid_hit','corrupt_hit')
                or not isinstance(record.get('usage'),(dict,type(None)))
                or not isinstance(record.get('job_id'),(str,type(None)))
                or not isinstance(record.get('stage'),(str,type(None)))
                or (record.get('elapsed_seconds') is not None and (type(record['elapsed_seconds']) not in (int,float)
                    or not math.isfinite(record['elapsed_seconds']) or record['elapsed_seconds']<0))):
                raise ValueError('Invalid invocation record')
        except (OSError,ValueError,AttributeError):unreadable+=1;continue
        if job_id is None or record.get('job_id')==job_id:records.append(record)
    groups={}
    for record in records:groups.setdefault((record['job_id'],record['stage']),[]).append(record)
    from .workflow_usage import summarize_workflow
    return {'day_utc':day,'job_filter':job_id,'totals':_aggregate(records),'unreadable_records':unreadable,
        'workflow':summarize_workflow(Path(cache).parent,day,job_id),
        'by_job_stage':[{'job_id':key[0],'stage':key[1],**_aggregate(value)} for key,value in groups.items()],
        'scope':'Recorded CodexModel calls only; older caches and uninstrumented models have no invocation history. '
            'Cache hits add no inference tokens. Unknown usage is not zero. Attempts are not confirmed billing. '
            'Time covers model calls, not the whole application. Token fields are reported separately, not summed.'}
