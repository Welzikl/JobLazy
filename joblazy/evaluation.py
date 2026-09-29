"""Evaluate frozen rankings against separately sourced human judgments. No inference."""
from collections import Counter
from .common import read_json,write_json
from .store import choice_job_hash
from .discovery_intake import routes

CATEGORIES={'obvious_match','misleading_keywords','adjacent','seniority_stretch','internship','hard_constraint','other'}

def validate_cases(dataset):
    if dataset.get('version')!=1 or not isinstance(dataset.get('cases'),list):
        raise ValueError('Evaluation dataset must contain version 1 and a cases list')
    ids=set();seen_routes=set();hashes=set()
    for case in dataset['cases']:
        key=case['id'];posting=case['job'];content_hash=choice_job_hash(posting)
        if not isinstance(key,str) or not key or key in ids:raise ValueError('Duplicate or empty evaluation case ID')
        if case.get('split') not in ('development','holdout'):raise ValueError('Case split must be development or holdout')
        if case.get('category') not in CATEGORIES:raise ValueError('Unknown evaluation category')
        if any(not isinstance(posting.get(k),str) or not posting[k].strip() for k in ('url','company','title','description')):
            raise ValueError('Each case needs a posting URL, employer, title and description')
        aliases=routes(posting)
        if aliases & seen_routes or content_hash in hashes:raise ValueError('Duplicate posting across evaluation cases or splits')
        ids.add(key);seen_routes.update(aliases);hashes.add(content_hash)
        judgment=case.get('judgment')
        if judgment is not None:
            source=judgment.get('source',{})
            if type(judgment.get('worthwhile')) is not bool or source.get('kind')!='user' or not all(isinstance(source.get(k),str) and source[k].strip() for k in ('quote','recorded_at','basis')):
                raise ValueError('Worthwhile judgments require an explicit user source, date and basis; model scores are not labels')
            if not isinstance(judgment.get('job_hash'),str):raise ValueError('Judgment must be bound to a posting hash')
        constraint=case.get('known_block')
        if constraint is not None:
            source=constraint.get('source',{})
            quote=source.get('quote','')
            if source.get('kind')!='reviewed_posting' or not isinstance(quote,str) or not quote or not any(isinstance(posting.get(field),str) and quote in posting[field] for field in ('description','location')) or not constraint.get('policy_reason'):
                raise ValueError('Known blocks require exact posting evidence and the independent policy reason')
    return dataset['cases']

def evaluate(dataset,run,*,top_k=10,minimum_score=70):
    if type(top_k) is not int or top_k<1 or type(minimum_score) is not int or not 0<=minimum_score<=100:
        raise ValueError('top_k must be positive and minimum_score must be between 0 and 100')
    cases=validate_cases(dataset)
    if run.get('version')!=1 or not isinstance(run.get('predictions'),list):raise ValueError('Predictions must contain version 1 and a predictions list')
    predictions={};errors=[];case_ids={c['id'] for c in cases}
    for prediction in run['predictions']:
        key=prediction['id']
        if key in predictions:raise ValueError('Duplicate prediction ID')
        if key not in case_ids:raise ValueError('Prediction has no corresponding evaluation case')
        predictions[key]=prediction
    reports={}
    for split in ('development','holdout'):
        subset=[c for c in cases if c['split']==split];assessed=[];missing=[];stale_labels=[];contexts=set();versions=Counter()
        for case in subset:
            key=case['id'];posting_hash=choice_job_hash(case['job']);prediction=predictions.get(key)
            judgment=case.get('judgment')
            if judgment and judgment['job_hash']!=posting_hash:stale_labels.append(key);judgment=None
            if not prediction:missing.append(key);continue
            ranking=prediction.get('assessment')
            if prediction.get('job_hash')!=posting_hash:
                errors.append({'id':key,'reason':'Prediction posting changed'});missing.append(key);continue
            from .experience_screen import is_screen_exclusion
            screened=is_screen_exclusion(ranking,case['job'])
            if not screened and (not isinstance(ranking,dict) or ranking.get('assessment_stage')=='experience_screen' or type(ranking.get('score')) is not int or not 0<=ranking['score']<=100 or type(ranking.get('eligible')) is not bool or ranking.get('fit_category') not in ('strong_match','worthwhile_stretch','poor_fit')):
                errors.append({'id':key,'reason':'Missing or invalid assessment'});missing.append(key);continue
            if not isinstance(prediction.get('profile_hash'),str) or not prediction['profile_hash']:
                errors.append({'id':key,'reason':'Missing candidate-profile binding'});missing.append(key);continue
            contexts.add(prediction['profile_hash']);versions[str(ranking.get('assessment_version','unknown'))]+=1
            selected=ranking['eligible'] and ranking['fit_category']!='poor_fit' and ranking['score']>=minimum_score
            # Expected blocks are annotated independently of the model under test.
            # Do not silently fix a bad prediction here: report it as a violation.
            blocked=case.get('known_block') is not None or ranking.get('eligibility_status')=='blocked' or any(r.get('kind')=='hard_constraint' and r.get('status')=='not_met' for r in ranking.get('requirements',[]))
            assessed.append({'id':key,'score':ranking.get('score'),'selected':selected,'known_block':blocked,'judgment':judgment,'screened':screened})
        recommendations=sorted([r for r in assessed if r['selected']],key=lambda r:(-r['score'],r['id']))
        top=recommendations[:top_k];judged=[r for r in top if r['judgment'] is not None]
        worthwhile=sum(r['judgment']['worthwhile'] for r in judged);total=len(top);unknown=total-len(judged)
        precision=worthwhile/total if total and not unknown else None
        reports[split]={'cases':len(subset),'categories':dict(Counter(c['category'] for c in subset)),
            'assessed':len(assessed),'eligibility_screened':sum(r['screened'] for r in assessed),
            'missing_assessment_ids':missing,'profile_contexts':len(contexts),'assessment_versions':dict(versions),
            'stale_judgment_ids':stale_labels,'recommended_count':len(recommendations),'top_ids':[r['id'] for r in top],
            'top_count':total,'top_judged':len(judged),'top_worthwhile':worthwhile,'top_label_coverage':len(judged)/total if total else None,
            'precision_at_available_top_k':precision,
            'precision_bounds_from_missing_labels':[worthwhile/total,(worthwhile+unknown)/total] if total else None,
            'observed_80_percent':precision>=0.8 if precision is not None else None,
            'known_block_violation_ids':[r['id'] for r in recommendations if r['known_block']],
            'worthwhile_not_recommended_ids':[r['id'] for r in assessed if not r['selected'] and r['judgment'] and r['judgment']['worthwhile']],
            'judgment_bases':dict(Counter(r['judgment']['source']['basis'] for r in assessed if r['judgment'])),
            'quality_status':'fictional_example' if dataset.get('example_only') is True else 'provisional_observation' if precision is not None else 'insufficient_judgments'}
    return {'version':1,'example_only':dataset.get('example_only') is True,'run_name':run.get('name'),'top_k_requested':top_k,'minimum_score':minimum_score,'splits':reports,'prediction_errors':errors,
        'limitations':['Development and holdout observations are never pooled. Reserved cases without predictions or judgments are not a completed holdout evaluation.',
            'Precision is null when any selected top role is unlabeled. Bounds describe possible label outcomes, not statistical confidence intervals.',
            'Small, selected or summary-only judgment samples do not establish general recommendation quality. Inspect label coverage, profile/version differences and missed worthwhile roles.',
            'Known-block checks cover saved model constraints and independently reviewed annotations only; zero violations does not prove all posting requirements were extracted.',
            'User choices do not override the automatic cutoff in this evaluation. No queue changes, inference or employer actions occur.']}

def evaluate_files(dataset_path,predictions_path,output,*,top_k=10,minimum_score=70):
    from pathlib import Path
    if Path(output).resolve() in {Path(dataset_path).resolve(),Path(predictions_path).resolve()}:
        raise ValueError('Evaluation output must not overwrite its dataset or predictions')
    report=evaluate(read_json(dataset_path),read_json(predictions_path),top_k=top_k,minimum_score=minimum_score)
    write_json(output,report)
    return {'path':str(Path(output).resolve()),**report}
