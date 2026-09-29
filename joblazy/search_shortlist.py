"""Small preliminary shortlist review for freshly verified search roles.

This is a recommendation aid, not an eligibility assessment or application
clearance. Full factual citations are retained and checked against canonical
profile facts and each supplied posting.
"""
import copy
from pathlib import Path

import jsonschema

from .common import InvalidModelOutput, ModelUnavailable, NeedsInput, digest, write_json
from .materials import original_quote, ranking_request
from .assessment_state import assessment_profile_hash


def _object(properties):
    return {'type': 'object', 'properties': properties,
            'required': list(properties), 'additionalProperties': False}


def _array(item):
    return {'type': 'array', 'items': item}


def _schema(ids, fact_ids):
    decision = _object({
        'id': {'type': 'string', 'enum': ids},
        'recommend': {'type': 'boolean'},
        'reason': {'type': 'string'},
        'job_quotes': _array({'type': 'string'}),
        'candidate_source_ids': _array({'type': 'string', 'enum': fact_ids}),
        'caveats': _array({'type': 'string'}),
    })
    return _object({'results': _array(decision)})


def _task():
    return (
        'Create a preliminary shortlist decision for each supplied job, independently. '
        'Recommend roles that plausibly fit the candidate’s saved future-work direction and '
        'documented evidence. First screen explicit location, sector, function, and required-'
        'experience exclusions in the supplied targeting. Do not treat a title or keyword '
        'overlap as proof of qualifications. Compare important duties with actual candidate '
        'facts; missing evidence is unknown, not a failure or a claim. Cite saved preferences '
        'for policy judgments and cite at least one non-preference candidate fact for any '
        'positive recommendation. Use concise reasons and the shortest exact supporting '
        'quotes from that job’s title, location, or description. Never invent facts, quotes, '
        'company information, or hiring odds. A recommendation only prioritizes further '
        'review; it does not establish eligibility, a complete fit assessment, or clearance '
        'to apply. Resolve candidate_fact_ref objects using candidate_facts. For an explicit '
        'required-experience ceiling, compare the lower bound of mandatory ranges; preferred '
        'experience is not mandatory and titles do not establish years. Never convert '
        'overlapping calendar coverage into full-time or specialist tenure. '
        'Return exactly one decision per supplied id, preserving each id exactly.'
    )


def _validate_decision(decision, job, facts):
    if type(decision.get('recommend')) is not bool:
        raise ValueError('Recommendation must be a boolean')
    if not decision.get('reason','').strip():
        raise ValueError('Decision reason is empty')
    for name in ('job_quotes', 'candidate_source_ids', 'caveats'):
        values=decision.get(name)
        if not isinstance(values,list) or any(not isinstance(value,str) for value in values):
            raise ValueError(f'{name} must be an array of strings')
    quotes=[]
    sources=decision['candidate_source_ids']
    if len(set(sources))!=len(sources) or any(source not in facts for source in sources):
        raise ValueError('Decision cites an unknown or duplicate candidate source')
    searchable=[job.get(key,'') for key in ('title','location','description')]
    for quote in decision['job_quotes']:
        exact=next((span for source in searchable if isinstance(source,str)
                    for span in [original_quote(quote,source)] if span is not None),None)
        if exact is None:
            raise ValueError('Decision includes a quote absent from its job title, location, or description')
        quotes.append(exact)
    decision['job_quotes']=quotes
    if decision['recommend']:
        if not quotes:
            raise ValueError('Positive recommendation lacks a posting quote')
        if not any(not source.startswith('preference.') for source in sources):
            raise ValueError('Positive recommendation lacks non-preference candidate evidence')
    return decision


def review_shortlist(rows, profile, model, *, directory=None):
    """Return validated preliminary recommendations keyed by immutable job ID.

    The caller supplies already-verified posting rows. This function reads no
    store, performs no network access, and changes no queue or application state.
    It makes at most two model calls (one correction), preserving valid siblings
    if the provider interrupts a correction request.
    """
    rows=list(rows)
    ids=[row.get('id') if isinstance(row,dict) else None for row in rows]
    if any(not isinstance(key,str) or not key.strip() for key in ids) or len(set(ids))!=len(ids):
        raise ValueError('Shortlist review requires unique nonempty string job IDs')
    results={};errors={};requests={};postings={};payloads={};attempts=[];calls=0
    for row in rows:
        key=row['id']
        try:
            _,payload,_,facts=ranking_request(copy.deepcopy(row.get('data',{})),profile)
        except NeedsInput as error:
            errors[key]=str(error)
            continue
        requests[key]=facts
        postings[key]=payload['job']
        payloads[key]=payload
    pending=list(requests)
    if not pending:
        return {'results':results,'errors':errors,'model_calls':calls}
    candidate_profile_hash=digest(profile)
    profile_hash=assessment_profile_hash(profile)
    job_hashes={row['id']:digest(row['data']) for row in rows if row['id'] in requests}
    input_hash=digest({'jobs':[(row['id'],row['data']) for row in rows],
                       'profile_hash':profile_hash})
    first=next(key for key in pending)
    shared_context={key:copy.deepcopy(value) for key,value in payloads[first].items()
                    if key not in ('job','title_relocation_clauses')}
    all_fact_ids=sorted({fact for key in pending for fact in requests[key]})
    schema=_schema(pending,all_fact_ids)

    def audit(status):
        if directory is not None:
            write_json(Path(directory)/'shortlist-validation.json',{
                'status':status,'input_hash':input_hash,'profile_hash':profile_hash,
                'job_hashes':job_hashes,'model_calls':calls,'results':list(results),
                'errors':errors,'attempts':attempts})

    rejected={}
    for attempt in range(2):
        if not pending:break
        current_schema=_schema(pending,sorted({fact for key in pending for fact in requests[key]}))
        current_task=_task()
        if attempt:
            current_task+=(' Correct rejected decisions using only the supplied original job and candidate evidence. '
                           'Keep all validation standards unchanged; rejected decisions are not evidence.')
            correction_input=copy.deepcopy(shared_context)
            correction_input['jobs']=[{'id':key,'job':copy.deepcopy(postings[key]),
                **({'title_relocation_clauses':copy.deepcopy(payloads[key]['title_relocation_clauses'])}
                   if 'title_relocation_clauses' in payloads[key] else {})} for key in pending]
            current_payload={'original_input':correction_input,'rejected_decisions':rejected}
        else:
            current_payload=copy.deepcopy(shared_context)
            current_payload['jobs']=[{'id':key,'job':copy.deepcopy(postings[key]),
                **({'title_relocation_clauses':copy.deepcopy(payloads[key]['title_relocation_clauses'])}
                   if 'title_relocation_clauses' in payloads[key] else {})} for key in pending]
        response=None;record={'ids':list(pending),'valid':[],'rejected':{}}
        try:
            calls+=1
            response=model.generate(current_task,current_payload,current_schema)
            if not isinstance(response,dict) or set(response)!={'results'} or not isinstance(response['results'],list):
                raise InvalidModelOutput('Shortlist response must contain only a results array')
            returned=[entry.get('id') if isinstance(entry,dict) else None for entry in response['results']]
            if (any(not isinstance(key,str) for key in returned) or len(returned)!=len(pending)
                    or len(set(returned))!=len(returned) or set(returned)!=set(pending)):
                raise InvalidModelOutput('Shortlist response omitted, duplicated, or invented job IDs')
        except ModelUnavailable as error:
            error.batch_results=copy.deepcopy(results)
            error.batch_errors=copy.deepcopy(errors)
            error.batch_pending=list(pending)
            record['interrupted']=str(error);attempts.append(record);audit('interrupted')
            raise
        except (InvalidModelOutput,ValueError) as error:
            rejected={key:{'error':str(error),'response':copy.deepcopy(response)} for key in pending}
        else:
            rejected={}
            for entry in response['results']:
                key=entry['id']
                try:
                    jsonschema.validate(entry,current_schema['properties']['results']['items'])
                    decision=_validate_decision(copy.deepcopy(entry),postings[key],requests[key])
                except (ValueError,jsonschema.ValidationError) as error:
                    rejected[key]={'error':str(error),'response':copy.deepcopy(entry)}
                else:
                    decision.update({'candidate_profile_hash':candidate_profile_hash,
                                     'assessment_profile_hash':profile_hash,
                                     'job_hash':job_hashes[key],
                                     'input_hash':input_hash,
                                     'assessment_stage':'search_shortlist'})
                    results[key]=decision;record['valid'].append(key)
        record['rejected']=copy.deepcopy(rejected);attempts.append(record)
        pending=list(rejected)
        if attempt:
            errors.update({key:'Shortlist validation failed after one correction: '+value['error']
                           for key,value in rejected.items()})
        audit('correction_pending' if pending and not attempt else 'complete')
    audit('complete')
    return {'results':results,'errors':errors,'model_calls':calls}
