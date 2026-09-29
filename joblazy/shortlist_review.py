"""Batch transport for the same full-evidence assessment used by materials.rank."""
import copy
import os
from pathlib import Path

import jsonschema

from .common import InvalidModelOutput, ModelUnavailable, NeedsInput, digest, write_json
from .materials import InvalidAssessment, arr, obj, ranking_request, validate_assessment


def rank_batch(jobs, profile, model, *, directory=None):
    """Assess [{id, data}] with shared profile context and at most two requests.

    Returns results/errors maps keyed by the caller's immutable IDs, plus model_calls.
    Invalid input IDs raise ValueError before inference. Missing posting context is a
    per-job error. A malformed ID envelope rejects the whole pending response;
    otherwise only invalid assessments enter the single correction request.
    ModelUnavailable (including DailyModelLimit) propagates with batch_results and
    batch_errors attributes so callers can persist valid siblings before resuming.
    This function never reads sites or changes queue/application state.
    """
    rows=list(jobs)
    ids=[row.get('id') for row in rows]
    if any(not isinstance(key,str) or not key.strip() for key in ids) or len(set(ids))!=len(ids):
        raise ValueError('Batch assessment requires unique nonempty string job IDs')
    results={};errors={};requests={};postings={};attempts=[];calls=0
    for row in rows:
        key=row['id'];posting=copy.deepcopy(row['data'])
        try:requests[key]=ranking_request(posting,profile)
        except NeedsInput as error:errors[key]=str(error)
        else:postings[key]=posting
    pending=list(requests)
    original_hash=digest({'jobs':rows,'profile':profile})

    def audit(status):
        if directory is not None:
            write_json(Path(directory)/'batch-ranking-validation.json',{
                'status':status,'input_hash':original_hash,'model_calls':calls,
                'results':list(results),'errors':errors,'attempts':attempts})

    def contract(keys):
        tasks=[requests[key][0] for key in keys]
        # Share the exact common instructions. Any job-specific suffix remains
        # attached to its own posting (currently remote-scope instructions).
        common=os.path.commonprefix(tasks)
        first=requests[keys[0]][1]
        shared={key:copy.deepcopy(value) for key,value in first.items()
                if key not in ('job','title_relocation_clauses')}
        entries=[]
        for key in keys:
            task,payload,_,_=requests[key]
            entry={'id':key,'job':copy.deepcopy(payload['job']),
                   'assessment_instructions':task[len(common):]}
            if 'title_relocation_clauses' in payload:
                entry['title_relocation_clauses']=copy.deepcopy(payload['title_relocation_clauses'])
            entries.append(entry)
        shared['jobs']=entries
        task=(common+' Assess each jobs entry independently using the shared targeting, resume, '
              'candidate_facts and employment_calendar. Apply each entry\'s assessment_instructions '
              'and title_relocation_clauses to that entry only. Never transfer posting quotes or '
              'requirements between jobs. Return exactly one complete assessment per supplied id. '
              'Copy each id exactly; do not omit, duplicate, create or reorder the identity mapping. '
              'All original evidence rules apply separately to every assessment. '
              'Keep explanations concise, usually one sentence each. Use the shortest exact quote '
              'that preserves the condition and its qualifications. Cover every material requirement '
              'without repeating the same evidence or rationale in multiple prose paragraphs.')
        schema=obj({'results':arr(obj({'id':{'type':'string','enum':keys},
                                      'assessment':copy.deepcopy(requests[keys[0]][2])}))})
        return task,shared,schema

    rejected={}
    for attempt in range(2):
        if not pending:break
        task,payload,schema=contract(pending)
        if attempt:
            task+=(' Correct the rejected assessments using only original source fields. '
                   'Rejected assessments are not evidence. Fix all unsupported quotes, references '
                   'and resulting judgments without lowering validation standards.')
            payload={'original_input':payload,'rejected_assessments':rejected}
        response=None;record={'ids':list(pending),'valid':[],'rejected':{}}
        try:
            calls+=1
            response=model.generate(task,payload,schema)
            if not isinstance(response,dict) or set(response)!= {'results'} or not isinstance(response['results'],list):
                raise InvalidAssessment('Batch response must contain only a results array')
            returned=[entry.get('id') if isinstance(entry,dict) else None for entry in response['results']]
            if (any(not isinstance(key,str) for key in returned) or len(returned)!=len(pending)
                    or len(set(returned))!=len(returned) or set(returned)!=set(pending)):
                raise InvalidAssessment('Batch response has omitted, duplicate or unexpected job IDs')
        except ModelUnavailable as error:
            error.batch_results=copy.deepcopy(results)
            error.batch_errors=copy.deepcopy(errors)
            error.batch_pending=list(pending)
            record['interrupted']=str(error);attempts.append(record);audit('interrupted')
            raise
        except (InvalidAssessment,InvalidModelOutput) as error:
            failure={'error':str(error),'response':copy.deepcopy(response)}
            if isinstance(error,InvalidModelOutput):
                failure.update(failure_kind='model_output',evidence_path=error.evidence_path)
            record['envelope_failure']=failure
            rejected={key:copy.deepcopy(failure) for key in pending}
        else:
            rejected={}
            by_id={entry['id']:entry for entry in response['results']}
            for key in pending:
                entry=by_id[key]
                try:
                    jsonschema.validate(entry,schema['properties']['results']['items'])
                    assessment=validate_assessment(copy.deepcopy(entry['assessment']),postings[key],profile,requests[key][3])
                except (InvalidAssessment,jsonschema.ValidationError) as error:
                    rejected[key]={'error':str(error),'response':copy.deepcopy(entry)}
                else:
                    assessment['validation']={'correction_attempts':attempt,'status':'corrected' if attempt else 'valid'}
                    results[key]=assessment;record['valid'].append(key)
        record['rejected']=copy.deepcopy(rejected);attempts.append(record)
        pending=list(rejected)
        if attempt:
            errors.update({key:'Assessment validation failed after one correction: '+value['error']
                           for key,value in rejected.items()})
        audit('correction_pending' if pending and not attempt else 'complete')
    audit('complete')
    return {'results':results,'errors':errors,'model_calls':calls}
