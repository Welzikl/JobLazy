"""A local review document; no server, scripts, external assets or application actions."""
from datetime import datetime,timezone
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from .common import digest,read_json


def maybe_json(path):
    try:return read_json(path)
    except (OSError,ValueError):return {}


def source_link(url):
    try:
        parsed=urlsplit(url)
        return url if parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password else None
    except ValueError:return None


def render_review(store,data,output=None,limit=100,*,rows=None,pdf_links=None,profile=None):
    from .assessment_state import assessment_stale,assessment_profile_hash
    profile_hash=digest(profile) if profile is not None else None
    assessment_hash=assessment_profile_hash(profile) if profile is not None else None
    data=Path(data).resolve();output=Path(output).resolve() if output else data/'review.html'
    counts={r['status']:r['n'] for r in store.db.execute('SELECT status,count(*) AS n FROM jobs GROUP BY status')}
    if rows is None:
        rows=store.list(set(counts)-{'discovered'});included={r['id'] for r in rows}
        for inventory in (data/'applications').glob('*/form-inventory.json'):
            key=inventory.parent.name
            if key in included:continue
            try:row=store.get(key)
            except KeyError:continue
            if row['status']=='discovered':rows.append(row);included.add(key)
    items=[]
    for row in rows:
        directory=data/'applications'/row['id'];result=row['result'] or {}
        ranking=maybe_json(directory/'ranking.json') or result.get('ranking') or (result if 'score' in result else {})
        if result.get('assessment_stage')=='experience_screen':ranking=result
        if row['status']=='assessment_failed':ranking={}
        if row['status']=='processing_failed' and result.get('last_failure',{}).get('stage') not in ('tailoring','application_answers'):
            ranking={}
        if assessment_stale(row,profile_hash,assessment_hash):ranking={}
        items.append((row,directory,ranking))
    def review_order(item):
        row,_,ranking=item
        # Use the saved discovery preference for display order too. Otherwise a
        # lower-interest fallback can reappear above a target role solely from
        # its fit score, contradicting the order used to build the queue.
        from .pipeline import processing_priority
        preference=processing_priority(row['data'],profile) if profile is not None else 0
        return (row['status']=='not_selected',-preference,-(ranking.get('score') or -1),row['updated'])
    items.sort(key=review_order)
    cards=[]
    for row,directory,ranking in items[:limit]:
        from .answers import questions
        job=row['data'];result=row['result'] or {};observed=questions(store,row['id'],directory,profile)
        score='Fit score '+str(ranking['score'])+'/100' if 'score' in ranking else 'Not ranked'
        if ranking.get('assessment_stage')=='experience_screen':score='Eligibility screen · full fit not scored'
        if ranking.get('eligibility_status'):
            score+=' · '+ranking['fit_category'].replace('_',' ')+' · eligibility: '+ranking['eligibility_status'].replace('_',' ')
        reason=ranking.get('reason') or result.get('reason') or result.get('detail') or 'No assessment recorded yet.'
        if assessment_stale(row,profile_hash,assessment_hash):
            score='Stale assessment · refresh required'
            reason='The saved decision used a different candidate profile or assessment version. It is available for reassessment; its historical score is not a current recommendation.'
        links=[];url=source_link(job.get('url',''))
        if url:links.append(f'<a href="{escape(url,quote=True)}" target="_blank" rel="noopener noreferrer">Job posting</a>')
        artifact=maybe_json(directory/'artifact.json');pdf=directory/'cv.pdf';cv_note=''
        if artifact:
            try:
                valid=Path(artifact['path']).resolve()==pdf.resolve() and digest(pdf.read_bytes())==artifact['sha256']
            except (OSError,KeyError,ValueError):valid=False
            if valid:
                from .checkpoints import load_materials
                label='Tailored CV'
                if profile is None:
                    label='Saved CV (profile not checked)'
                    cv_note='<p class="warning">No candidate profile was supplied; this saved CV has not been checked against current application inputs.</p>'
                elif load_materials(directory,job,profile) is None:
                    label='Saved CV (review required)'
                    cv_note='<p class="warning">This saved CV is not verified for the current profile and posting. Its checkpoint is missing or no longer matches the inputs or saved files. The document remains available for history; review it before reuse.</p>'
                href=pdf_links[row['id']] if pdf_links is not None else pdf.as_uri()
                links.append(f'<a href="{escape(href,quote=True)}">{label}</a>')
            else:cv_note='<p class="warning">The saved CV could not be verified. Review the saved files before using it.</p>'
        gaps=list(ranking.get('missing_facts',[]))
        gaps.extend(q['field']+': '+q['reason'] for q in observed['questions'] if q.get('required'))
        gaps.extend('Required file: '+str(name) for name in observed['missing_files'])
        gaps.extend(issue['field']+': '+issue['reason'] for issue in observed.get('verification_issues',[]))
        if result.get('reason') and result['reason']!=reason:gaps.append(result['reason'])
        if observed.get('reason') and observed['reason']!=reason and observed['reason'] not in gaps:
            gaps.append(observed['reason'])
        if observed.get('reason') and observed['reason']!=reason and observed['reason'] not in gaps:gaps.append(observed['reason'])
        details=''
        if result.get('requires_user_input') is False and result.get('next_action'):
            details+='<p class="warning">'+escape(result['next_action'])+'</p>'
        choice=store.choice(row['id'],job)
        if choice and choice['decision']!='automatic':
            choice_label=('User chose to pursue' if choice['decision']=='pursue' else 'User chose to pass') if choice['current'] else 'Posting changed since user choice; choice requires review'
            details+='<p><strong>'+escape(choice_label)+'</strong>. '+escape(choice['note'])+'</p>'
        if ranking.get('dimensions'):
            from .materials import RUBRIC_LABELS
            details+='<details open><summary>Career Ops scoring dimensions</summary><p>Dimensions use 1–5, higher is more favorable. The overall fit score is a separate holistic judgment, not an average. Unknown means insufficient evidence.</p><table><colgroup><col style="width:22%"><col style="width:12%"><col style="width:66%"></colgroup><thead><tr><th>Dimension</th><th>Rating</th><th>Explanation</th></tr></thead><tbody>'
            for key,label in RUBRIC_LABELS.items():
                item=ranking['dimensions'].get(key,{})
                rating='Unknown' if item.get('score') is None else str(item['score'])+'/5'
                quotes=''.join('<li>'+escape(source['field'])+': '+escape(source['quote'])+'</li>' for source in item.get('job_quote_sources',[]))
                evidence='<details><summary>Posting evidence</summary><ul>'+quotes+'</ul></details>' if quotes else ''
                details+='<tr><td>'+escape(label)+'</td><td>'+escape(rating)+'</td><td>'+escape(item.get('explanation','Not assessed'))+evidence+'</td></tr>'
            details+='</tbody></table></details>'
        calendar=ranking.get('employment_calendar')
        if calendar:
            cells=[]
            for entry in calendar['entries']:
                extent=(str(entry['calendar_months_touched'])+' calendar months touched'
                    if entry['status']=='month_range' else 'Not quantified')
                cells.append('<tr><td>'+escape(str(entry['company']))+'</td><td>'+escape(str(entry.get('dates') or 'Dates missing'))+'</td><td>'+escape(extent)+'</td></tr>')
            details+='<details><summary>Employment calendar evidence</summary><p>'+escape(calendar['scope'])+'</p><table><thead><tr><th>Employer</th><th>Source dates</th><th>Calendar coverage</th></tr></thead><tbody>'+''.join(cells)+'</tbody></table><p>'+str(calendar['calendar_months_touched_union'])+' calendar months across the quantified entries, with shared months counted once.</p></details>'
        if ranking.get('requirements'):
            candidate_facts=ranking.get('candidate_facts',{})
            details+='<details><summary>Requirement-by-requirement assessment</summary><p>Assessments are provisional. A fit score is not a hiring probability.</p><table><thead><tr><th>Requirement</th><th>Assessment</th><th>Reason and candidate sources</th></tr></thead><tbody>'
            for item in ranking['requirements']:
                sources=', '.join(item.get('candidate_source_ids',[])) or 'No established candidate evidence'
                source_text=''.join('<p><strong>'+escape(key)+'</strong>: '+escape(candidate_facts[key])+'</p>' for key in item.get('candidate_source_ids',[]) if key in candidate_facts)
                evidence='<details><summary>Recorded candidate evidence</summary>'+source_text+'</details>' if source_text else ''
                job_source={'location':'posting location','title':'job title'}.get(item.get('job_quote_source'),'job description')
                details+='<tr><td>'+escape(item['requirement'])+'<br><small>'+escape(item['kind'].replace('_',' '))+'; source: '+job_source+'</small></td><td>'+escape(item['status'].replace('_',' '))+'</td><td>'+escape(item['explanation'])+'<br><small>'+escape(sources)+'</small>'+evidence+'</td></tr>'
            details+='</tbody></table></details>'
        if observed['method']=='read_only_inventory':
            details+='<p class="warning">Read-only form check: no candidate data was entered or uploaded. Later form steps may add questions.</p>'
        gap_note=f'<p class="warning">{len(gaps)} gaps to review before applying.</p>' if gaps else ''
        if gaps:details+='<details><summary>Questions and gaps</summary><ul>'+''.join('<li>'+escape(str(g))+'</li>' for g in gaps)+'</ul></details>'
        evidence=ranking.get('evidence',[])[:2]
        if evidence:
            excerpts=[];remaining=25
            for entry in evidence:
                if remaining<=0:break
                words=entry['quote'].split();excerpt=' '.join(words[:remaining]);remaining-=min(remaining,len(words))
                if len(words)>len(excerpt.split()):excerpt+='…'
                source='posting location' if entry.get('quote_source')=='location' else 'job description'
                excerpts.append('<small>Source: '+source+'</small><blockquote>'+escape(excerpt)+'</blockquote><p>'+escape(entry['explanation'])+'</p>')
            details+='<details><summary>Posting evidence excerpts</summary>'+''.join(excerpts)+'</details>'
        drafts=maybe_json(directory/'answer-drafts.json').get('drafts',{})
        if drafts:
            details+='<details><summary>Application answer drafts</summary>'+''.join('<h3>'+escape(d['question']['label'])+'</h3><p>'+escape(d.get('text') or d.get('reason','Unresolved'))+'</p>' for d in drafts.values())+'</details>'
        status=row['status'].replace('_',' ')
        if row['status']=='manual_review':
            details+='<p class="warning">Awaiting your recorded application outcome. Automatic retries are paused.</p>'
        if result.get('method')=='operator_report':
            status+=' · operator reported'
            details+='<details><summary>Recorded outcome</summary><p>'+escape(result['note'])+'</p></details>'
        if result.get('method')=='imported_history':
            status+=' · imported history'
            gap_note='<p class="warning">Historical application: review its outcome before any repeat application.</p>'
            details+='<details><summary>Imported outcome</summary><p>'+escape(str(result.get('historical_outcome','Unknown')))+'; '+escape(str(result.get('evidence_class','legacy record')).replace('_',' '))+'. This is not a new JobLazy submission.</p></details>'
        cards.append(f'''<article><div class="meta">{escape(score)} · {escape(status)}</div>
<h2>{escape(job.get('title','Untitled role'))}</h2><p class="company">{escape(job.get('company',''))} · {escape(job.get('location',''))}</p>
<p>{escape(reason)}</p>{gap_note}<nav>{' · '.join(links)}</nav>{cv_note}{details}
<p class="id">Job ID: <code>{escape(row['id'])}</code></p></article>''')
    stats=' · '.join(f'{value} {key.replace("_"," ")}' for key,value in sorted(counts.items())) or 'No jobs yet'
    html=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>JobLazy — your shortlist</title><style>
body{{margin:0;background:#f4f3ef;color:#232921;font:16px/1.6 system-ui,sans-serif}}main{{max-width:900px;margin:auto;padding:48px 24px}}
h1{{font-size:38px;letter-spacing:-1px;margin:0}}h2{{font-size:23px;line-height:1.3;margin:8px 0}}h3{{font-size:17px}}.intro,.company,.id{{color:#596253}}
article{{background:white;padding:28px;margin:22px 0;border:1px solid #dce0d6;border-radius:12px}}.meta{{color:#315936;font-weight:650}}
nav{{margin:18px 0}}a{{color:#225a36;text-underline-offset:3px}}details{{border-top:1px solid #e4e8df;padding:12px 0}}summary{{cursor:pointer;font-weight:600}}
table{{width:100%;border-collapse:collapse;font-size:14px}}th,td{{text-align:left;vertical-align:top;padding:8px;border-bottom:1px solid #e4e8df;overflow-wrap:anywhere}}
blockquote{{border-left:3px solid #a5b59c;margin:14px 0;padding-left:16px}}.id{{font-size:12px;overflow-wrap:anywhere}}.warning{{color:#8b471e}}
@media print{{body{{background:white}}article{{break-inside:avoid}}main{{padding:0}}}}
</style></head><body><main><h1>Your JobLazy shortlist</h1>
<p class="intro">Reviewed roles, tailored CVs and questions that still need your input.</p><p>{escape(stats)}</p>
<p class="intro">Showing {min(len(items),limit)} of {len(items)} assessed, inspected or interrupted roles. Updated {datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M UTC')}.</p>
{''.join(cards) or '<article>No assessed roles yet. Run discovery and ranking to build your shortlist.</article>'}
<footer class="intro">This local document does not submit applications. Use the job ID with JobLazy to inspect or continue a role. It contains private career material; keep it private.</footer>
</main></body></html>'''
    output.parent.mkdir(parents=True,exist_ok=True)
    temp=output.with_suffix(output.suffix+'.tmp');temp.write_text(html,encoding='utf-8');temp.replace(output)
    return {'path':str(output),'shown':min(len(items),limit),'assessed':len(items),'counts':counts}
