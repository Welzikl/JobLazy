"""Apply an explicit user experience ceiling to grounded job requirements."""
import re

WORDS={word:i for i,word in enumerate(('zero','one','two','three','four','five','six','seven','eight','nine','ten','eleven','twelve'))}
NUMBER=r'(?:\d+(?:\.\d+)?|'+'|'.join(WORDS)+r')'
YEARS=re.compile(r'\b('+NUMBER+r')(?:\s*(?:[-–—]|to)\s*'+NUMBER+r')?\s*\+?\s+years?\b',re.I)

def experience_ceiling(profile):
    targeting=profile.get('targeting',{})
    if not isinstance(targeting,dict):return None
    policy=targeting.get('config',{}).get('target_roles',{}).get('seniority',{})
    if policy.get('mode')!='required_experience_range':return None
    value=policy.get('maximum_required_years')
    if isinstance(value,bool) or not isinstance(value,(int,float)) or value<0:
        raise ValueError('Experience ceiling must be a nonnegative number')
    return value

def mandatory_years(requirement):
    if requirement.get('kind') not in ('required_experience','hard_constraint'):return None
    quote=requirement.get('job_quote','')
    matches=list(YEARS.finditer(quote))
    # Multiple experience durations can describe alternatives or distinct duties.
    # Leave that interpretation to assessment rather than summing or taking max.
    if len(matches)!=1:return None
    # A trailing preferred domain does not qualify the earlier duration:
    # "requires 6 years, ideally in SaaS" still requires six years.
    # Retain uncertainty for other preference wording and multiple durations.
    domain=re.search(r'\bideally\s+(?:in|within|at|with)\b',quote[matches[0].end():],re.I)
    duration_scope=quote[:matches[0].end()+domain.start()] if domain else quote
    # A subtype preference attached to an example ("such as advisory (large
    # firms preferred)") does not qualify the duration. Keep experience/tenure
    # qualifications and all preference wording outside that bounded clause.
    def example_preference(match):
        label=match.group(2)
        if not re.fullmatch(r'[a-z][a-z &/-]*',label,re.I) or re.search(
                r'\b(?:experience|years?|tenure|duration|minimum|maximum|required|mandatory|optional)\b',label,re.I):
            return match.group(0)
        return match.group(1)
    duration_scope=re.sub(r'(\bsuch as\b[^()\n.;]*?)\(\s*([^()\n.;]*?)\s+preferred\s*\)',
        example_preference,duration_scope,flags=re.I)
    if re.search(r'\bpreferred\b|\bideally\b|nice.to.have',duration_scope,re.I):return None
    if re.search(r'(?:up to|at most|maximum(?: of)?)\s*$',quote[:matches[0].start()],re.I):return None
    text=matches[0].group(1).casefold()
    return WORDS[text] if text in WORDS else float(text)

def enforce_experience_ceiling(result,profile):
    ceiling=experience_ceiling(profile)
    if ceiling is None:return []
    violations=[]
    for item in list(result['requirements']):
        if item.get('policy_rule')=='experience_ceiling':continue
        if any(r.get('policy_rule')=='experience_ceiling' and r['job_quote']==item['job_quote'] for r in result['requirements']):continue
        minimum=mandatory_years(item)
        if minimum is not None and minimum>ceiling:
            violations.append({'requirement':'Required experience exceeds the user search ceiling',
                'job_quote':item['job_quote'],'job_quote_source':item['job_quote_source'],
                'kind':'hard_constraint','status':'not_met','candidate_source_ids':['preference.experience_range'],
                'explanation':f'The role requires at least {minimum:g} years; the user targets roles requiring no more than {ceiling:g}. This is a search-policy exclusion, not a claim about candidate experience.',
                'policy_rule':'experience_ceiling'})
    if violations:
        result['requirements'].extend(violations)
        result['fit_category']='poor_fit'
        result['reason']='Excluded by the confirmed experience range. '+result['reason']
    return violations


def has_experience_policy_conflict(result):
    return any(item.get('kind')=='hard_constraint' and item.get('status')=='not_met'
        and 'preference.experience_range' in item.get('candidate_source_ids',[])
        for item in result.get('requirements',[]))


def experience_policy_errors(result,profile):
    """Reject a model's false ceiling conflict; do not invent a replacement score."""
    ceiling=experience_ceiling(profile)
    if ceiling is None:return []
    errors=[]
    for item in result.get('requirements',[]):
        if (item.get('kind')!='hard_constraint' or item.get('status')!='not_met'
                or 'preference.experience_range' not in item.get('candidate_source_ids',[])):
            continue
        minimum=mandatory_years(item)
        if minimum is not None and minimum<=ceiling:
            errors.append(f'False experience-ceiling exclusion: the quoted lower bound is {minimum:g}, '
                f'which does not exceed the user ceiling of {ceiling:g}. The upper end of a range is not its minimum. '
                'Reassess the score and fit without that search-policy conflict; assess any unconfirmed qualifying '
                'background separately as required experience. Preserve independent hard conflicts and uncertainties.')
    return errors
