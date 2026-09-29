import copy
import json
import re
import unicodedata
import subprocess
from pathlib import Path
from .common import ROOT, NeedsInput, InvalidModelOutput, digest, write_json
from .profiles import require_profile
from .assessment_state import FULL_ASSESSMENT_VERSION,REMOTE_SCOPE_VERSION,EXPERIENCE_POLICY_VERSION,remote_scope_relevant,assessment_profile_hash

class InvalidAssessment(NeedsInput):
    """Generated assessment failed source validation, not a candidate question."""

class AssessmentFailed(InvalidAssessment):
    """The original assessment and its one bounded correction were invalid."""

def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def arr(items): return {'type':'array','items':items}
STRING = {'type':'string'}
CLAIM = obj({'text':STRING,'source_ids':arr(STRING)})
# Named dimensions adapted from Career Ops modes/_shared.md. One evaluator,
# with a holistic overall judgment; dimension ratings are not averaged.
RUBRIC_LABELS = {'cv_fit':'CV fit','career_direction':'Career direction',
    'compensation':'Compensation','culture':'Culture and working conditions','red_flags':'Red flags'}
DIMENSION = obj({'score':{'type':['number','null'],'minimum':1,'maximum':5},
    'explanation':STRING,'job_quotes':arr(STRING),'candidate_source_ids':arr(STRING)})
RANK_SCHEMA = obj({'score':{'type':'integer','minimum':0,'maximum':100},
    'dimensions':obj({key:copy.deepcopy(DIMENSION) for key in RUBRIC_LABELS}),
    'reason':STRING,'evidence':arr(obj({'quote':{'type':'string','description':'Exact excerpt from job.description ONLY, never from the candidate CV or profile.'},'explanation':STRING})),
    'candidate_source_ids':arr(STRING),'missing_facts':arr(STRING),
    'fit_category':{'type':'string','enum':['strong_match','worthwhile_stretch','poor_fit']},
    'requirements':arr(obj({'requirement':STRING,'job_quote':{'type':'string','description':'Exact excerpt from job.description or job.location. For hard_constraint location conditions only, an exact supplied title_relocation_clauses entry is also allowed. Never quote candidate facts.'},
        'kind':{'type':'string','enum':['hard_constraint','required_experience','preferred','responsibility']},
        'status':{'type':'string','enum':['met','partly_met','unverified','not_met']},
        'candidate_source_ids':arr(STRING),'explanation':STRING}))})
TAILOR_SCHEMA = obj({'summary':CLAIM,'experience':arr(obj({'index':{'type':'integer','minimum':0},'bullets':arr(CLAIM)})),
    'project_indices':arr({'type':'integer','minimum':0})})
VERIFY_SCHEMA = obj({'supported':{'type':'boolean'},'issues':arr(STRING)})

def original_quote(quote,description):
    # Models sometimes lowercase the first word or flatten a line break. Recover
    # the actual source span; never accept synonyms, omitted words or paraphrases.
    words=quote.split()
    if not words:return None
    match=re.search(r'\s+'.join(re.escape(word) for word in words),description,re.I)
    if match is None:
        # A model-added space beside an emoji/currency symbol is display
        # variation. Never remove whitespace between words or numeric tokens.
        pattern=re.escape(words[0])
        for left,right in zip(words,words[1:]):
            symbol=unicodedata.category(left[-1]) in ('Sc','So') or unicodedata.category(right[0]) in ('Sc','So')
            pattern+=(r'\s*' if symbol else r'\s+')+re.escape(right)
        match=re.search(pattern,description,re.I)
    return match.group(0) if match else None


def title_relocation_clauses(job):
    """Bounded literal title clauses, not a general location/qualification parser."""
    title=job.get('title','')
    if not isinstance(title,str):return []
    pattern=r"(?:^|[(\[|]|[–—]| - )\s*(?P<clause>relocat(?:ion|e)\s+to\s+[A-Za-z][A-Za-z .,'-]{0,79}?)\s*(?=$|[)\]])"
    return [match.group('clause').rstrip() for match in re.finditer(pattern,title,re.I)]


def posting_evidence(job):
    # Search suggestions and local provenance are not observed posting facts.
    # Also clean records saved by earlier discovery versions.
    return {key: copy.deepcopy(value) for key,value in job.items()
            if key not in {'search_hint', 'discovery_evidence'}}


def ranking_posting(job):
    """Posting evidence used for assessment, without volatile fetch bookkeeping."""
    observed={'observed_at','description_source','description_method','discovery_source_urls',
        'description_retained_from','description_refresh_required','_application_route_observation'}
    result={key:value for key,value in posting_evidence(job).items() if key not in observed}
    if isinstance(result.get('source_provenance'),dict):
        for key in ('checked_at','api_url','board_api_url'):
            result['source_provenance'].pop(key,None)
    return result


def ranking_input(job,profile,facts):
    """Keep every profile value; refer to long facts instead of repeating them."""
    references={};ambiguous=set()
    for key,value in facts.items():
        if isinstance(value,str) and len(value)>=64:
            if value in references:ambiguous.add(value)
            else:references[value]=key
    # Identical wording may belong to different employers. Do not replace a
    # contextual occurrence with an arbitrary employer's source ID.
    for value in ambiguous:references.pop(value)
    def compact(value):
        if isinstance(value,str) and value in references:return {'candidate_fact_ref':references[value]}
        if isinstance(value,list):return [compact(item) for item in value]
        if isinstance(value,dict):return {key:compact(item) for key,item in value.items()}
        return value
    # Fetch timestamps and source bookkeeping cannot change substantive fit.
    # Preserve unknown posting fields, including additional practical conditions.
    return {'job':ranking_posting(job),
        'targeting':compact(profile['targeting']),'resume':compact(profile['resume']),
        'candidate_facts':copy.deepcopy(facts)}

def ranking_request(job, profile):
    """Build the canonical full-evidence assessment contract for any transport."""
    require_profile(profile)
    if job.get('description_refresh_required'):raise NeedsInput('Posting context changed; retrieve a fresh description before ranking')
    if not job.get('description','').strip(): raise NeedsInput('Full job description missing')
    facts=source_facts(profile)
    # Ranking needs citable chronology and work-pattern context, not just duties.
    # Keep this separate from CV claim sources and their existing checkpoints.
    for i,entry in enumerate(profile['resume'].get('experience',[])):
        context={key:value for key,value in entry.items() if key!='bullets'}
        if context:facts[f'employment.{i}']=json.dumps(context,ensure_ascii=False)
    # Ranking must cite user policy when a preference, rather than a missing
    # qualification, excludes a role. Keep these out of CV claim sources;
    # narrative drafting adds career preferences separately for role-fit prose.
    targeting=profile.get('targeting',{})
    if isinstance(targeting,dict):
        # First-run profiles record the desired next move in these fields,
        # rather than the legacy career_preferences/config structure. Make all
        # saved targeting citable without treating preferences as CV history.
        if targeting:facts['preference.targeting']=json.dumps(targeting,ensure_ascii=False)
        if targeting.get('career_preferences'):facts['preference.career_rules']=targeting['career_preferences']
        location=targeting.get('config',{}).get('location',{})
        if location:facts['preference.location']=str(location)
    from .experience_policy import experience_ceiling
    from .chronology import employment_calendar
    ceiling=experience_ceiling(profile)
    if ceiling is not None:
        facts['preference.experience_range']=f'User targets roles requiring no more than {ceiling:g} years of experience; exclude a higher mandatory minimum.'
    schema=copy.deepcopy(RANK_SCHEMA)
    reference={'type':'string','enum':list(facts)}
    schema['properties']['candidate_source_ids']['items']=reference
    schema['properties']['requirements']['items']['properties']['candidate_source_ids']['items']=reference
    for dimension in schema['properties']['dimensions']['properties'].values():
        dimension['properties']['candidate_source_ids']['items']=reference
    task = ('Rank this full job description against the saved targeting rules and canonical candidate facts. '
        'Assess role substance, not ATS convenience. Do not invent salary, title, or years filters beyond the explicit saved user criteria. '
        'evidence[].quote must be an exact substring of job.description. requirements[].job_quote must be an exact substring of job.description or job.location, NEVER candidate CV excerpts. '
        'The sole title exception is an exact supplied title_relocation_clauses entry, quoted only for a hard_constraint work-location condition. Code records the source field. '
        'Assess explicit relocation clauses as material placement conditions against saved location policy. A location list may name recruiting origins rather than alternative final placements. '
        'For a strict London-based-only policy, required relocation to another city is not_met unless the posting explicitly offers London placement as an alternative. '
        'Do not treat a multi-location label alone as that offer; explain contradictory explicit placement statements as uncertainty. Optional relocation or relocation to an allowed work location is not itself a policy failure. '
        'Keep location-policy conflict separate from work authorization; do not infer an immigration status or unwillingness to relocate from residence alone. '
        'A candidate_fact_ref object in resume or targeting points to the complete original text in candidate_facts; resolve it before assessing. '
        'Explain the connection to candidate evidence in explanations and cite candidate source IDs for fit claims. '
        'preference.targeting records the saved desired next move and constraints; cite it for career-direction alignment. It is not evidence of past skills or experience. '
        'employment.i records the exact non-bullet context of resume.experience[i]; experience.i.j records that same role\'s duties. '
        'Use and cite supplied employment dates when assessing relevant years; do not report dates missing when they are supplied. '
        'Explain which roles and duties count toward a duration requirement and which remain uncertain. '
        'Use the code-calculated employment_calendar for date arithmetic. month_distance compares calendar endpoints; '
        'calendar_months_touched includes both endpoint months, and the union counts overlapping months once. '
        'These are calendar coverage, not confirmed worked tenure, continuous full-time employment or time on a particular skill. '
        'Prefer exact source date ranges when describing tenure; do not invent computed lengths or quantify unparsed year-only or open-ended ranges. '
        'Do not double-count overlapping calendar periods or assume that a role\'s entire tenure was spent on a particular skill. '
        'Year-only ranges do not establish exact months; freelance, project, internship or part-time periods do not automatically establish continuous full-time equivalent experience. '
        'Preserve supplied work patterns and missing dates, hours or continuity; never infer completed future tenure or invent a total. '
        'Employment context supports chronology, employer and stated capacity; cite duty evidence separately for relevance. '
        'Apply explicit saved location, sector and function exclusions before positive career-track or company preferences; '
        'an excluded primary function or sector must be poor_fit even when the title overlaps a target. '
        'Read allowed tracks and exclusions together. A secondary or opportunistic allowed track is lower priority, not forbidden merely because it is outside the primary tracks. '
        'When saved preferences allow commercial/strategic finance but exclude accounting-led work, classify the actual duties and their purpose, not the finance department or FP&A label alone. '
        'Budgeting, forecasting, financial modelling, cost analysis and ROI-based investment decisions can support commercial strategy; these activities alone do not establish an accounting-led exclusion. '
        'For an accounting-led exclusion, cite posting duties such as ownership of financial books, journal entries, reconciliations, close, statutory reporting, tax or audit, and explain why they dominate the role. '
        'For mixed or unclear scope, describe that uncertainty instead of assuming a categorical exclusion. '
        'These examples do not override a user policy that explicitly excludes all finance work or another applicable sector/function. '
        'Being in an allowed track does not establish candidate qualifications: independently assess missing hands-on experience and substantive fit, without guaranteeing a positive category or score. '
        'Separate practical eligibility from attractiveness. Code derives overall eligibility from your hard-constraint assessments. '
        'Identify every material requirement with its exact job quote, importance, status, candidate evidence and explanation. '
        'Confirmed evidence is required for met, partly_met and not_met. Missing evidence is unverified rather than proof of not_met. '
        'Respect the logic and scope of each quoted requirement: for A OR B, confirmed evidence of either alternative satisfies it. '
        'Evaluate the alternatives BEFORE assigning a status, and name the satisfied alternative in the explanation. '
        'For example, documented SQL dashboard development meets "Python or SQL" and "querying a database, auditing outputs, or automating in Python" through the SQL/database alternative. '
        'Do not mark those requirements partly_met merely because Python or output auditing is unverified. '
        'By contrast, "SQL and annotation QA" remains partly_met with SQL evidence alone: AND still requires both. '
        'An unchosen alternative is not a missing qualification unless a separate requirement actually needs it. '
        'Do not turn alternatives into cumulative demands or add unstated depth, duration, tools or specialisation to a broad requirement. '
        'Assess separately stated specialised responsibilities and experience gaps separately; meeting a broad requirement does not establish that deeper expertise. '
        'Use preference.* source IDs to cite saved career or location rules for policy judgments; these are preferences, not evidence of skills or experience. '
        'A different documented degree or career history does not prove the absence of an alternative qualification or equivalent experience. '
        'Classify practical conditions and explicitly non-negotiable gates as hard_constraint; assess other experience requirements as required_experience. '
        'Assess explicit job experience requirements and obey any saved required-experience range. A mandatory minimum above the user ceiling is a search-policy exclusion, even if other evidence transfers well. '
        'Split mixed requirements into their separately qualified parts. In "You have shipped B2B products, ideally in finance", shipping B2B products is required experience while finance is preferred; ideally does not make the entire sentence optional. Likewise, "3-5 years in consulting is a plus" is preferred in full. '
        'Distinguish required from preferred experience. Use the lower bound of a required range (6-11 means at least 6); do not invent years from titles or infer them when unstated. '
        'Consider transferable experience and worthwhile stretches without inventing seniority, technical depth, language proficiency or qualifications. '
        'Education dates alone do not establish current enrolment or award status. '
        'Use strong_match, worthwhile_stretch or poor_fit based on substantive requirements and career preferences. '
        'A desirable employer or overlapping keywords cannot compensate for a core skill gap. Scores measure attractiveness, not hiring odds. '
        'Use the original Career Ops named rubric within this same assessment: CV fit, career direction (North Star alignment), compensation, culture/working conditions, and red flags. '
        'Each dimension has a 1-5 rating (higher is more favorable), an explanation, exact job description/location/title quotes and candidate source IDs where relevant. Rubric quotes may cite the supplied job.title; code records its field. A title alone cannot establish years, technical depth or a mandatory qualification. Requirement title quotes are limited to the supplied relocation clauses as described above. '
        'Use null, with an explicit explanation, when evidence is insufficient; do not give unknown pay or unknown culture a neutral numeric rating. '
        'For compensation compare the advertised terms with saved expectations only; do not invent market salary benchmarks or treat expected salary as advertised pay. '
        'Culture ratings describe posting signals, not verified company culture. Apply any saved culture_screen requirements and surface contradictions or missing evidence explicitly. '
        'For red flags, higher means fewer observed concerns; absence of posting evidence cannot prove legitimacy, and browser access failures are not poor fit. '
        'The overall 0-100 score is a holistic judgment informed by these dimensions, never their arithmetic average or a converted legacy score. '
        'Existing hard constraints and fit-category exclusions take precedence over favorable dimension ratings.')
    if remote_scope_relevant(job):
        task+=(' For remote-location postings, assess where the candidate can actually perform the work. '
            'An advertised UK-remote location (for example United Kingdom (Remote)) includes working remotely from London '
            'unless a more specific posting condition excludes that location. When saved policy accepts remote work while based in London, '
            'do not mark location unverified merely because this UK-remote label omits the literal city name. '
            'Read the full description and title for narrower regional residency, a required office work base, or relocation; '
            'those explicit conditions take precedence over a broad remote label. Distinguish occasional business travel from a required work base '
            'and assess any separate travel commitment without inventing willingness. '
            'Remote without an advertised eligible country remains uncertain; a foreign-only remote hiring scope does not become UK-eligible '
            'because the applicant lives in London. Keep geographical work scope, work authorization and qualification evidence separate. '
            'Quote the exact location label or relevant description condition and cite the saved location policy for this comparison.')
    payload=ranking_input(job,profile,facts)
    payload['employment_calendar']=employment_calendar(profile)
    relocation=title_relocation_clauses(job)
    if relocation:payload['title_relocation_clauses']=relocation
    return task,payload,schema,facts


def rank(job, profile, model, *, directory=None):
    task,payload,schema,facts=ranking_request(job,profile)
    request_task=task;request_payload=payload
    attempts=[]
    def audit(status):
        if directory is not None:
            write_json(Path(directory)/'ranking-validation.json',{'status':status,
                'input_hash':digest(payload),'correction_attempts':max(0,len(attempts)-1),'attempts':attempts})
    for attempt in range(2):
        response=None
        try:
            response=model.generate(request_task,request_payload,schema)
            result=validate_assessment(copy.deepcopy(response),job,profile,facts)
        except (InvalidAssessment,InvalidModelOutput) as error:
            rejected={'valid':False,'error':str(error)}
            if isinstance(error,InvalidModelOutput):rejected.update(failure_kind='model_output',evidence_path=error.evidence_path)
            else:rejected['response']=copy.deepcopy(response)
            attempts.append(rejected)
            audit('failed' if attempt else 'correction_pending')
            if attempt:raise AssessmentFailed('Assessment validation failed after one correction: '+str(error)) from error
            request_task=(task+' Correct the rejected assessment using the original source fields. '
                'The rejected assessment is not evidence. Fix all unsupported quotes, references and resulting judgments; '
                'do not invent replacement evidence or lower validation standards. Return the complete corrected assessment.')
            request_payload={'original_input':payload,'rejected_assessment':response,'validation_error':str(error)}
        else:
            attempts.append({'valid':True})
            result['validation']={'correction_attempts':attempt,'status':'corrected' if attempt else 'valid'}
            audit(result['validation']['status'])
            return result


def validate_assessment(result,job,profile,facts):
    from .chronology import chronology_errors,employment_calendar
    from .experience_policy import enforce_experience_ceiling,experience_policy_errors
    if not result['evidence']: raise InvalidAssessment('Ranking lacks job-description evidence')
    description_evidence=False
    for item in result['evidence']:
        quoted=original_quote(item['quote'],job['description'])
        if quoted is not None:description_evidence=True
        elif isinstance(job.get('location'),str):
            # Recover an exact location quote in the summary-evidence slot;
            # preserve its real source rather than relabeling it as JD text.
            quoted=original_quote(item['quote'],job['location'])
            if quoted is not None:item['quote_source']='location'
        if quoted is None:
            raise InvalidAssessment('Ranking evidence is not present in the job description')
        item['quote']=quoted
    if not description_evidence:raise InvalidAssessment('Ranking lacks job-description evidence')
    if any(s not in facts for s in result['candidate_source_ids']):
        raise InvalidAssessment('Ranking cites unknown candidate evidence')
    dimensions=result.get('dimensions')
    if not isinstance(dimensions,dict) or set(dimensions)!=set(RUBRIC_LABELS):
        raise InvalidAssessment('Ranking lacks the complete Career Ops rubric')
    for name,item in dimensions.items():
        rating=item.get('score')
        if rating is not None and (type(rating) not in (int,float) or not 1<=rating<=5):
            raise InvalidAssessment('Invalid rubric dimension rating')
        if not str(item.get('explanation','')).strip():raise InvalidAssessment('Rubric dimension lacks an explanation')
        if any(s not in facts for s in item.get('candidate_source_ids',[])):
            raise InvalidAssessment('Rubric dimension cites unknown candidate evidence')
        if rating is not None and not item.get('job_quotes'):
            raise InvalidAssessment('Scored rubric dimension lacks posting evidence')
        if rating is not None and name in ('cv_fit','career_direction') and not item.get('candidate_source_ids'):
            raise InvalidAssessment('Scored candidate-fit dimension lacks candidate evidence')
        quotes=[];quote_sources=[]
        for quote in item.get('job_quotes',[]):
            source=next(((field,matched) for field in ('description','location','title')
                if isinstance(job.get(field),str) and (matched:=original_quote(quote,job[field]))),None)
            if source is None:raise InvalidAssessment(f'Rubric {name} quote is not present in description, location or title: {quote!r}')
            field,recovered=source
            quotes.append(recovered);quote_sources.append({'quote':recovered,'field':field})
        item['job_quotes']=quotes
        item['job_quote_sources']=quote_sources
    if not result['requirements']:raise InvalidAssessment('Ranking lacks a requirements assessment')
    for item in result['requirements']:
        quote=original_quote(item['job_quote'],job['description']);field='description'
        if quote is None and isinstance(job.get('location'),str):
            quote=original_quote(item['job_quote'],job['location']);field='location'
        if quote is None and item['kind']=='hard_constraint':
            normalized=' '.join(item['job_quote'].casefold().split())
            quote=next((clause for clause in title_relocation_clauses(job)
                if ' '.join(clause.casefold().split())==normalized),None)
            if quote is not None:field='title'
        if quote is None:raise InvalidAssessment('Requirement evidence is not in description/location or an allowed hard-constraint title relocation clause')
        item['job_quote']=quote
        item['job_quote_source']=field
        if any(s not in facts for s in item['candidate_source_ids']):raise InvalidAssessment('Requirement cites unknown candidate evidence')
        if item['status'] in ('met','partly_met','not_met') and not item['candidate_source_ids']:
            raise InvalidAssessment('Requirement judgment lacks candidate evidence')
    errors=chronology_errors(result,profile)+experience_policy_errors(result,profile)
    if errors:raise InvalidAssessment('; '.join(errors))
    result['employment_calendar']=employment_calendar(profile)
    enforce_experience_ceiling(result,profile)
    hard=[r for r in result['requirements'] if r['kind']=='hard_constraint']
    blocked=any(r['status']=='not_met' for r in hard)
    uncertain=any(r['status'] in ('unverified','partly_met') for r in hard)
    result['eligibility_status']='blocked' if blocked else 'uncertain' if uncertain else 'no_known_conflict'
    result['eligible']=not blocked
    if result['eligible'] and result['fit_category']!='poor_fit' and not result['candidate_source_ids']:
        raise InvalidAssessment('Positive ranking lacks candidate evidence')
    result['assessment_version']=FULL_ASSESSMENT_VERSION
    result['experience_policy_version']=EXPERIENCE_POLICY_VERSION
    if remote_scope_relevant(job):result['remote_scope_version']=REMOTE_SCOPE_VERSION
    result['rubric']='career_ops_named_dimensions_v1'
    result['ranking_context_version']=3
    cited=set(result['candidate_source_ids'])
    cited.update(s for item in dimensions.values() for s in item.get('candidate_source_ids',[]))
    cited.update(s for item in result['requirements'] for s in item['candidate_source_ids'])
    result['candidate_facts']={key:facts[key] for key in sorted(cited)}
    result['candidate_profile_hash']=digest(profile)
    result['assessment_profile_hash']=assessment_profile_hash(profile)
    return result

def source_facts(profile):
    facts = {}
    base = profile['resume']
    if base.get('summary'): facts['summary'] = base['summary']
    for i,entry in enumerate(base.get('experience', [])):
        for j,b in enumerate(entry.get('bullets', [])):
            text = b if isinstance(b,str) else b.get('text','')
            facts[f'experience.{i}.{j}'] = text
    for i,f in enumerate(profile.get('facts', [])):
        facts[f'fact.{i}'] = f['text']
    for i,entry in enumerate(base.get('education',[])):
        facts[f'education.{i}']='; '.join(str(entry[k]) for k in ('org','title','year','description') if entry.get(k))
    for i,entry in enumerate(base.get('projects',[])):
        if entry.get('description'):facts[f'project.{i}.description']=entry['description']
        for j,text in enumerate(entry.get('bullets',[])):
            if isinstance(text,str):facts[f'project.{i}.{j}']=text
    for kind in ('skills','competencies','certifications'):
        for i,text in enumerate(base.get(kind,[])):
            if isinstance(text,str):facts[f'{kind}.{i}']=text
            elif kind=='skills' and isinstance(text,dict):
                for j,item in enumerate(text.get('items',[])):
                    if isinstance(item,str) and item.strip():facts[f'skills.{i}.{j}']=item
    address=profile.get('applicant',{}).get('address',{})
    if address.get('city') and address.get('country'):
        facts['applicant.residence']='Recorded residence: '+', '.join(str(address[k]) for k in ('city','state_full','country') if address.get(k))
    targeting=profile.get('targeting')
    location=targeting.get('config',{}).get('location',{}) if isinstance(targeting,dict) else {}
    if isinstance(location,dict) and isinstance(location.get('visa_status'),str):
        facts['work_authorization.statement']=location['visa_status']
    return facts

def validate_claims(claims,facts):
    for claim in claims:
        if not claim['text'].strip() or not claim['source_ids'] or any(s not in facts for s in claim['source_ids']):
            raise NeedsInput('Generated text contains an ungrounded claim')
        source=' '.join(facts[s] for s in claim['source_ids'])
        numbers=lambda text:set(re.findall(r'\d+(?:[.,]\d+)*(?:%|[kKmMbB])?',text))
        if not numbers(claim['text']).issubset(numbers(source)):
            raise NeedsInput('Generated text introduced or changed a metric')
        # Using an existing artifact does not establish authorship. This
        # conservative lexical check complements the semantic review, which
        # missed a live "through a checklist" -> "creating a checklist" change.
        authorship = r'\b(?:creat(?:e|es|ed|ing|ion)|author(?:ed|ing)?)\b'
        creation_evidence = r'\b(?:creat(?:e|es|ed|ing|ion)|author(?:ed|ing)?|built|build(?:s|ing)?|design(?:ed|ing)?|develop(?:ed|ing)?|invent(?:ed|ing)?)\b'
        if re.search(authorship, claim['text'], re.I) and not re.search(creation_evidence, source, re.I):
            raise NeedsInput('Generated text introduced authorship not present in its cited sources')

class TailoringFailed(NeedsInput):
    """Exhausted generated-claim repair, not a missing candidate answer."""
    def __init__(self,message,evidence):
        super().__init__(message)
        self.evidence=evidence


def tailor(job, profile, model, fit_feedback=None, repair_feedback=None, _repair_attempt=0):
    require_profile(profile)
    facts = source_facts(profile)
    if not any(str(value).strip() for key,value in facts.items()
               if not key.startswith(('applicant.', 'work_authorization.'))):
        raise NeedsInput('Add confirmed education, projects, skills or experience before creating a CV.')
    from .employment_titles import allowed_titles,validate_title_selections
    title_options=allowed_titles(profile)
    # Constrain references at generation time, as the application-answer worker
    # already does. Free-form IDs allowed invented prefixes such as facts.summary.
    schema = copy.deepcopy(TAILOR_SCHEMA)
    reference = {'type':'string','enum':list(facts)}
    schema['properties']['summary']['properties']['source_ids']['items'] = reference
    schema['properties']['experience']['items']['properties']['bullets']['items']['properties']['source_ids']['items'] = reference
    title_instruction=''
    inputs={'job':posting_evidence(job),'facts':facts,'resume':profile['resume'],'writing_preferences':profile.get('writing_preferences',''),
        'layout_feedback':fit_feedback,'factual_correction':repair_feedback}
    if title_options:
        schema['properties']['title_selections']=arr(obj({'index':{'type':'integer','enum':list(title_options)},
            'role':{'type':'string','enum':sorted({role for option in title_options.values() for role in option['allowed_roles']})},'reason':STRING}))
        schema['required'].append('title_selections')
        inputs['confirmed_employment_title_options']=list(title_options.values())
        title_instruction=(' For every included employer with confirmed title options, select exactly one of that employer\'s allowed_roles and give a short relevance reason in title_selections. '
            'These are user-confirmed title alternatives, not permission to expand duties or imply new people-management experience. '
            'Choose the title most relevant to this posting. Employers without options retain their original title.')
    generated = model.generate('Tailor the CV summary and experience bullets for this full job description. '
        'Select and rewrite relevant evidence, preserving scope, agency, metrics and truth. '
        'Using an artifact does not establish that the candidate created it: for example, "through a shared checklist" must not become "by creating a shared checklist". '
        'Use the supplied source IDs exactly, without adding a facts. prefix. Each experience entry must reference its own source bullets; '
        'keep the original job identities and chronology. Give relevant experience sufficient space; no fixed three-bullet limit. '
        'If no employment is recorded, return an empty experience array and use the confirmed education, projects and skills. Never invent an employer or convert a project into employment. '
        'Do not invent skills, achievements, seniority or authorship. Select relevant projects by original index; '
        'return an empty project_indices list when irrelevant. Target one page in the existing template. '
        'Respect the supplied writing and content-allocation preferences. Return a substantive tailored CV.'+title_instruction,
        inputs, schema)
    claims = [generated['summary']]
    seen = set()
    for entry in generated['experience']:
        i = entry['index']
        if i in seen or i < 0 or i >= len(profile['resume'].get('experience', [])):
            raise NeedsInput('Tailoring returned an invalid or duplicated employment identity')
        seen.add(i)
        for claim in entry['bullets']:
            if any(not s.startswith(f'experience.{i}.') for s in claim['source_ids']):
                raise NeedsInput('Tailoring moved evidence between employers')
            claims.append(claim)
    if (profile['resume'].get('experience') and not generated['experience']) or not generated['summary']['text'].strip():
        raise NeedsInput('Tailoring produced an incomplete CV')
    titles=validate_title_selections(generated.get('title_selections',[]),title_options,seen)
    def repair(issues):
        evidence={'issues':issues,'rejected_draft':generated,'factual_repair_attempts':_repair_attempt}
        if _repair_attempt < 2:
            return tailor(job,profile,model,fit_feedback=fit_feedback,
                repair_feedback={'issues':issues,'rejected_draft':generated,
                    'instruction':'Remove or faithfully narrow unsupported wording. Do not add facts. Every revised claim will be checked again.'},
                _repair_attempt=_repair_attempt+1)
        raise TailoringFailed('CV factual review failed: '+'; '.join(issues),evidence)
    try:validate_claims(claims,facts)
    except NeedsInput as error:return repair([str(error)])
    review = model.generate('Independently check EVERY generated claim against its cited source facts. '
        'Reject invented responsibility, expanded scope, changed metrics, implied authorship, or unsupported expertise. '
        'Faithful paraphrasing is allowed. supported is true only when every claim is entailed.',
        {'facts':facts,'claims':claims}, VERIFY_SCHEMA)
    if not review['supported'] or review['issues']:
        return repair(review['issues'] or ['The factual reviewer did not support every generated claim.'])
    payload = copy.deepcopy(profile['resume'])
    payload['summary'] = generated['summary']['text']
    payload['experience'] = [{**payload['experience'][e['index']],
        'role':titles[e['index']]['role'] if e['index'] in titles else payload['experience'][e['index']]['role'],
        'bullets':[b['text'] for b in e['bullets']]}
        for e in sorted(generated['experience'],key=lambda e:e['index'])]
    projects = generated['project_indices']
    if len(set(projects)) != len(projects) or any(i >= len(payload.get('projects',[])) for i in projects):
        raise NeedsInput('Tailoring returned invalid project selection')
    payload['projects'] = [payload['projects'][i] for i in projects]
    return {'payload':payload,'claims':claims,'review':review,'factual_repair_attempts':_repair_attempt,
        'title_selections':list(titles.values()),
        'profile_hash':digest(profile),'job_hash':digest(job)}

class PageOverflow(NeedsInput):
    pass

def render(material, directory, browser):
    from pypdf import PdfReader
    material=copy.deepcopy(material)
    candidate=material['payload']['candidate']
    if isinstance(candidate.get('linkedin'),str) and candidate['linkedin']:
        url=candidate['linkedin']
        candidate['linkedin']={'url':url,'display':re.sub(r'^https?://(?:www\.)?','',url).rstrip('/')}
    directory = Path(directory); directory.mkdir(parents=True,exist_ok=True)
    write_json(directory/'material.json',material)
    write_json(directory/'cv.json',material['payload'])
    r = subprocess.run(['node',str(ROOT/'vendor/career-ops/build-cv-html.mjs'),str(directory/'cv.json'),str(directory/'cv.html')],
        capture_output=True,text=True,encoding='utf-8',timeout=30)
    if r.returncode: raise NeedsInput('CV HTML rendering failed: '+r.stderr)
    page = browser.new_page()
    try:
        page.route('**/*',lambda route: route.continue_() if route.request.url.startswith('file:') else route.abort())
        page.goto((directory/'cv.html').resolve().as_uri())
        page.pdf(path=str(directory/'cv.pdf'),format='A4',print_background=True,prefer_css_page_size=True,tagged=True)
    finally: page.close()
    pdf = PdfReader(directory/'cv.pdf')
    if len(pdf.pages) != 1: raise PageOverflow(f'CV is {len(pdf.pages)} pages; shorten low-relevance content before upload')
    text = pdf.pages[0].extract_text()
    normalize = lambda s: re.sub(r'\s+',' ',s).strip().casefold()
    if normalize(material['payload']['candidate']['name']) not in normalize(text):
        raise NeedsInput('Rendered PDF is missing candidate identity')
    if candidate.get('linkedin') and normalize(candidate['linkedin']['display']) not in normalize(text):
        raise NeedsInput('Rendered PDF is missing the LinkedIn contact')
    for entry in material['payload'].get('education',[]):
        if not entry.get('title') or normalize(entry['title']) not in normalize(text):
            raise NeedsInput('Rendered PDF is missing an education title')
    result = {'path':str((directory/'cv.pdf').resolve()),'sha256':digest((directory/'cv.pdf').read_bytes()),'pages':1}
    write_json(directory/'artifact.json',result)
    return result
