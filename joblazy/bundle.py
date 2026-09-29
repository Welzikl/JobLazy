"""Portable private review ZIP. Reads saved work; no model, browser or queue actions."""
import io
import json
import tempfile
import zipfile
from datetime import datetime,timezone
from pathlib import Path
from pypdf import PdfReader
from .checkpoints import load_materials
from .common import NeedsInput,digest
from .profiles import require_profile
from .review import render_review,source_link
from .answers import questions
from .uploads import cv_filename


def bundle_review(store,data,profile,limit=20):
    require_profile(profile)
    if limit<1:raise ValueError('Bundle limit must be positive')
    data=Path(data).resolve()
    candidates=[];excluded=[]
    # Preserve manual-review ownership and never turn a bundle into a retry.
    for row in store.list({'materials_ready','prepared','needs_input','manual_review'}):
        directory=data/'applications'/row['id']
        checkpoint=load_materials(directory,row['data'],profile)
        if not checkpoint:
            excluded.append({'id':row['id'],'reason':'No current verified material checkpoint'})
            continue
        ranking=checkpoint['ranking']
        if not ranking['eligible'] or ranking.get('fit_category')=='poor_fit' or ranking['score']<profile.get('minimum_score',70):
            excluded.append({'id':row['id'],'reason':'Saved assessment does not meet the selection threshold'})
            continue
        candidates.append((row,checkpoint))
    candidates.sort(key=lambda item:(-item[1]['ranking']['score'],item[0]['id']))
    if not candidates:raise NeedsInput('No current verified CVs are available to bundle; existing exports were preserved')
    selected=candidates[:limit];entries=[];pdfs={};links={}
    for row,checkpoint in selected:
        artifact=checkpoint['artifact'];raw=Path(artifact['path']).read_bytes()
        if digest(raw)!=artifact['sha256']:raise NeedsInput('A selected CV changed during export; existing exports were preserved')
        try:pages=len(PdfReader(io.BytesIO(raw)).pages)
        except Exception as e:raise NeedsInput('A selected CV is not a readable PDF; existing exports were preserved') from e
        if pages!=1:raise NeedsInput('A selected CV is not one page; existing exports were preserved')
        name='cvs/'+row['id']+'/'+cv_filename(profile,checkpoint['job']);pdfs[name]=raw;links[row['id']]=name
        ranking=checkpoint['ranking'];job=checkpoint['job']
        observed=questions(store,row['id'],data/'applications'/row['id'],profile)
        entries.append({'id':row['id'],'title':job.get('title',''),'company':job.get('company',''),
            'location':job.get('location',''),'status':row['status'],'score':ranking['score'],
            'reason':ranking['reason'],'gaps':ranking.get('missing_facts',[]),
            'eligibility_status':ranking.get('eligibility_status','legacy_unclassified'),
            'fit_category':ranking.get('fit_category','legacy_unclassified'),'requirements':ranking.get('requirements',[]),
            'posting_url':source_link(job.get('url','')),
            'application_url':source_link(observed.get('scope') or job.get('application_url') or job.get('url','')),
            'application_questions':observed['questions'],'form_observation_method':observed['method'],
            'form_observation_reason':observed.get('reason'),
            'cv':name,'sha256':artifact['sha256'],'pages':pages})
    manifest={'created_at':datetime.now(timezone.utc).isoformat(),'requested':limit,'included':len(entries),
        'available':len(candidates),'excluded':excluded,'options':entries,
        'notice':'Verified CVs for review. This export does not fill, upload, submit or retry applications. Saved questions and draft answers require review against the current employer form.'}
    output=data/'review-bundle.zip'
    # Stage the complete archive, including PDF bytes already verified above,
    # before atomically replacing an earlier successful export.
    with tempfile.TemporaryDirectory(prefix='bundle-',dir=data) as temp:
        temp=Path(temp)
        result=render_review(store,data,temp/'index.html',limit,rows=[r for r,_ in selected],pdf_links=links,profile=profile)
        html=Path(result['path']).read_text(encoding='utf-8')
        if html.count('>Tailored CV</a>')!=len(entries):
            raise NeedsInput('CV verification changed while rendering the review; existing exports were preserved')
        archive=temp/'bundle.zip'
        with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as target:
            target.writestr('index.html',html)
            target.writestr('manifest.json',json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
            target.writestr('README.txt','Private JobLazy review pack\n\nExtract the whole ZIP, then open index.html. CV links are relative and work after moving the folder.\n\n'+manifest['notice']+'\n\nKeep this pack private; it contains your CVs.\n')
            for name,raw in pdfs.items():target.writestr(name,raw)
        with zipfile.ZipFile(archive) as target:
            if target.testzip() is not None:raise NeedsInput('Archive integrity verification failed')
        archive.replace(output)
    return {'path':str(output),'sha256':digest(output.read_bytes()),'requested':limit,
        'included':len(entries),'available':len(candidates),'excluded':excluded}
