"""Deterministic, complementary public-discovery briefs; no inference or I/O.

Mission budgets are per model request. The coordinator owns aggregate request
reservations, run freshness, concurrency and persistence, not this planner.
"""
from copy import deepcopy
import re

SEARCH_MODEL = 'gpt-6-luna'
REVIEW_MODEL = 'gpt-6-astra'

# Only future-work preferences belong in public discovery. Never copy an entire
# profile, contact fields, candidate facts or a CV into a worker mission.
BRIEF_FIELDS = {
    'desired_work', 'role_families', 'career_change', 'company_preferences',
    'city', 'country', 'location', 'work_arrangement', 'experience_level', 'avoid',
    'primary_tracks', 'secondary_tracks', 'company_priority', 'exclusions',
    'required_experience_years', 'experience_years', 'title_or_years_filter',
    'lower_interest_roles', 'search_policy',
    'role_archetypes', 'experience_policy',
}
LANES = (
    ('Strategy and operations', r'\b(strategy|strategic operations|operations|bizops)\b'),
    ('Growth and partnerships', r'\b(growth|gtm|commercial|partnerships|sales|bdr|sdr)\b'),
    ('Product and generalist', r'\b(product|founder|generalist|consulting|consultant)\b'),
    ('Adjacent specialist roles', r'\b(finance|financial|investment|analyst)\b'),
)


def _strings(values, label):
    if not isinstance(values, (list, tuple)) or any(not isinstance(x, str) for x in values):
        raise ValueError(label + ' must be a list of strings.')
    result, seen = [], set()
    for value in values:
        value = ' '.join(value.split())
        if value and value.casefold() not in seen:
            result.append(value)
            seen.add(value.casefold())
    return result


def discovery_brief(brief):
    """Accept targeting alone or a profile envelope, excluding candidate identity."""
    if brief is None:
        return {}
    if isinstance(brief, str):
        return {'desired_work': brief}
    if not isinstance(brief, dict):
        raise ValueError('Search brief must be text or an object.')
    source = brief.get('targeting', brief)
    if isinstance(source, str):
        return {'desired_work': source}
    if not isinstance(source, dict):
        raise ValueError('Targeting must be text or an object.')
    result = {key: deepcopy(value) for key, value in source.items() if key in BRIEF_FIELDS}
    # Imported profiles put preferences beside private candidate/config data.
    # Project explicit preference fields instead of copying that envelope.
    for container_name in ('context', 'config'):
        config = source.get(container_name)
        if not isinstance(config, dict):
            continue
        for key in BRIEF_FIELDS:
            if key in config:
                result.setdefault(key, deepcopy(config[key]))
        roles = config.get('target_roles', config.get('career', {}))
        if isinstance(roles, dict):
            if isinstance(roles.get('primary'), list):
                result.setdefault('primary_tracks', deepcopy(roles['primary']))
            archetypes = roles.get('archetypes')
            if isinstance(archetypes, list):
                result.setdefault('role_archetypes', [
                    {key: item[key] for key in ('name', 'fit') if key in item}
                    for item in archetypes if isinstance(item, dict)])
            seniority = roles.get('seniority')
            if isinstance(seniority, dict):
                result.setdefault('experience_policy', {key: deepcopy(seniority[key]) for key in (
                    'mode', 'minimum_target_years', 'maximum_required_years', 'rule') if key in seniority})
        location = config.get('location')
        if isinstance(location, dict):
            for key in ('city', 'country'):
                if key in location:
                    result.setdefault(key, location[key])
            if 'working_arrangement' in location:
                result.setdefault('work_arrangement', location['working_arrangement'])
            # A generic location object could contain address and visa details.
            if isinstance(result.get('location'), dict):
                result.pop('location')
    preference_text = source.get('career_preferences')
    if isinstance(preference_text, str):
        kept, skip_level = [], None
        for line in preference_text.splitlines():
            heading = re.match(r'^(#{1,6})\s', line)
            if heading:
                level = len(heading.group(1))
                if skip_level is not None and level <= skip_level:
                    skip_level = None
                if skip_level is None and re.search(r'narrative|positioning|evidence boundary|confirmed compensation', line, re.I):
                    skip_level = level
            if skip_level is None:
                kept.append(line)
        text = '\n'.join(kept).strip()
        # Preserve preference prose but keep accidental contact details out of
        # these public-search briefs. Structured candidate fields never enter.
        text = re.sub(r'\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b', '[contact omitted]', text)
        text = re.sub(r'https?://\S+', '[link omitted]', text)
        text = re.sub(r'(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)', '[contact omitted]', text)
        if text:
            result['career_preferences'] = text
    return result


def build_search_missions(plan, brief=None, *, known_board_ids=(), seen_ids=(),
                          max_queries=3, max_leads=8, max_search_calls=1):
    """Return six JSON-safe missions with deterministic IDs and declared scopes.

    The first four lanes partition supplied title phrases. Domain labels are used
    only when their terms occur; no finance/product/etc preference is invented
    for unrelated professions. Sparse plans reuse titles with distinct source
    lenses. The last two lanes own new-board discovery and coverage gaps.
    """
    for name, value in (('max_queries', max_queries), ('max_leads', max_leads),
                        ('max_search_calls', max_search_calls)):
        if type(value) is not int or value < 1:
            raise ValueError(name + ' must be a positive integer.')
    if not isinstance(plan, dict):
        raise ValueError('Search plan must be an object.')
    queries = _strings(plan.get('queries'), 'Queries')
    location = plan.get('location')
    if not queries or not isinstance(location, str) or not location.strip():
        raise ValueError('Search needs at least one query and a work location.')
    safe_brief = discovery_brief(brief)
    known = _strings(known_board_ids, 'Known board IDs')
    seen = _strings(seen_ids, 'Seen posting IDs')
    buckets = [[] for _ in LANES]
    for query in queries:
        matches = [i for i, (_, pattern) in enumerate(LANES) if re.search(pattern, query, re.I)]
        available = [i for i in matches if len(buckets[i]) < max_queries]
        lane = min(available or range(4), key=lambda i: len(buckets[i]))
        buckets[lane].append(query)
    overflow = [query for bucket in buckets for query in bucket[max_queries:]]
    lenses = ('site:jobs.ashbyhq.com', 'site:job-boards.greenhouse.io',
              'site:jobs.lever.co', 'careers vacancy')
    missions = []

    def add(identity, name, owned, scope):
        missions.append({'id': identity, 'name': name, 'queries': owned[:max_queries],
            'location': location.strip(), 'brief': deepcopy(safe_brief), 'scope': scope,
            'max_search_calls': max_search_calls, 'max_queries': max_queries,
            'max_leads': max_leads, 'known_board_ids': list(known), 'seen_ids': list(seen)})

    for i, bucket in enumerate(buckets):
        domain_match = any(re.search(LANES[i][1], query, re.I) for query in bucket)
        name = LANES[i][0] if domain_match else f'Preferred roles lane {i + 1}'
        owned = bucket[:max_queries] or [queries[i % len(queries)] + ' ' + lenses[i]]
        add(f'roles-{i + 1}', name, owned,
            'Find individual current postings for the assigned phrases and requested country. '
            'Own these query phrases; preserve priority and exclusions from the brief. '
            'Do not broaden to other lanes or score candidate fit. '
            'Use only observed employer and ATS links; report availability and eligibility uncertainties.')
    add('new-boards', 'New employer and ATS discovery',
        [query + ' (site:jobs.ashbyhq.com OR site:job-boards.greenhouse.io OR site:jobs.lever.co)'
         for query in queries[:max_queries]],
        'Discover employers and public ATS boards not in known_board_ids for the supplied role phrases. '
        'Return individual posting leads and observed board identities only; never invent board slugs. '
        'Prioritize new employers, preserving the location, priority and exclusions in the brief.')
    add('coverage-gaps', 'Coverage gaps and fresh postings',
        overflow[:max_queries] or [query + ' (hiring OR vacancy OR careers)' for query in queries[-max_queries:]],
        'Cover unassigned phrases first, then supported title synonyms and fresh postings from '
        'under-covered employers. Avoid seen posting IDs and other missions\' exact queries. '
        'Explain gaps; lower-interest fallback roles remain fallback and excluded work stays excluded. '
        'Do not infer new career preferences or score candidate fit.')
    missions[-1]['deferred_queries'] = overflow[max_queries:]
    return missions
