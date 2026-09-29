"""Deterministic, conservative selection of public-board search candidates."""
import re


# Ignore only level words and grammatical filler. Business and strategy are
# meaningful terms: a request for "business strategy" requires both.
_TITLE_IGNORED = {
    'senior', 'junior', 'mid', 'midlevel', 'entry', 'principal', 'staff',
    'lead', 'head', 'director', 'intern',
    'a', 'an', 'and', 'as', 'at', 'by', 'for', 'from', 'in', 'of', 'on',
    'or', 'the', 'to', 'with',
}
_REMOTE_WORDS = {'remote', 'anywhere', 'distributed', 'telecommute'}
_COUNTRY_ALIASES = {
    'uk': {'uk', 'gb', 'united kingdom', 'great britain', 'england', 'scotland', 'wales'},
    'us': {'us', 'usa', 'united states', 'united states of america'},
    # "CA" is ambiguous between Canada and California; spell out Canada.
    'ca': {'canada'},
    'ie': {'ie', 'ireland'},
    'de': {'germany'}, 'in': {'india'}, 'au': {'australia', 'au'},
    'sg': {'singapore'}, 'fr': {'france'}, 'nl': {'netherlands'},
    'es': {'spain'}, 'it': {'italy'}, 'ch': {'switzerland'},
    'se': {'sweden'}, 'dk': {'denmark'}, 'no': {'norway'},
    'pl': {'poland'}, 'jp': {'japan'}, 'cn': {'china'},
}
_CANADIAN_PROVINCES = {
    'ontario', 'on', 'quebec', 'qc', 'british columbia', 'bc', 'alberta', 'ab',
    'manitoba', 'mb', 'saskatchewan', 'sk', 'nova scotia', 'ns', 'new brunswick',
    'nb', 'newfoundland and labrador', 'nl', 'prince edward island', 'pei',
}


def _words(value):
    return re.findall(r'[a-z0-9]+', str(value or '').casefold())


def _discriminators(query):
    aliases = {'consultant': 'consulting', 'consultants': 'consulting',
               'strategic': 'strategy', 'operation': 'operations', 'partnership': 'partnerships'}
    abbreviations = {'bdr': ('business', 'development', 'representative'),
                     'sdr': ('sales', 'development', 'representative'),
                     'bizops': ('business', 'operations'), 'gtm': ('go', 'to', 'market')}
    expanded = [part for word in _words(query) for part in abbreviations.get(word, (word,))]
    return {aliases.get(word, word) for word in expanded if word not in _TITLE_IGNORED}


def title_matches(title, queries):
    """Require every non-level, non-stopword term from a requested phrase."""
    title_words = _discriminators(title)
    return any((terms := _discriminators(query)) and terms <= title_words for query in queries)


def _location_parts(value):
    text = str(value or '').strip()
    if not text:
        return []
    # Preserve city/country commas; split only common multi-location separators.
    parts = re.split(r'\s*(?:\||;|/|\n|\bor\b|\band\b)\s*', text, flags=re.I)
    return [part.strip(' ,') for part in parts if part.strip(' ,')]


def _country_key(value):
    original = str(value or '')
    words = ' '.join(_words(original))
    for key, aliases in _COUNTRY_ALIASES.items():
        if words in aliases or any(alias in words.split() for alias in aliases if len(alias) <= 3) or \
                any(alias in words for alias in aliases if len(alias) > 3):
            return key
    word_set = set(words.split())
    # Full province names can occur anywhere in a location. Two-letter
    # province codes count only as complete comma-delimited fields, so "on-site"
    # and "London (On site)" do not become Ontario.
    fields = {field.strip(' .()[]').casefold() for field in original.split(',')}
    if any((province in fields if len(province) <= 3 else province in words)
           for province in _CANADIAN_PROVINCES):
        return 'ca'
    # These explicit city labels occur without a country on observed boards.
    # Internal team codes such as DTNL are deliberately not country evidence:
    # that same code also appeared on a London/Manchester posting.
    if words in {'amsterdam', 'rotterdam'}:
        return 'nl'
    return None


def _target(location):
    fields = [field.strip() for field in str(location or '').split(',') if field.strip()]
    if not fields:
        return '', None
    return fields[0].casefold(), _country_key(' '.join(fields[1:]))


def _classify_location(location, target_city, target_country):
    """Return match, mismatch, or unknown for one asserted location."""
    original = str(location or '').strip()
    # Reuse the repository's audited London label classifier for its specific
    # aliases and namesakes, while still resolving explicit country text below.
    if target_city == 'london':
        from .coverage import location_class
        classification = location_class(original)
        if classification == 'london_uk_explicit' and target_country in (None, 'uk'):
            return 'match'
        if classification == 'other_london':
            found = _country_key(original)
            if target_country and found and found == target_country:
                return 'match'
            if found:
                return 'mismatch'
            return 'unknown'
        if classification == 'london_country_unverified':
            found = _country_key(original)
            if target_country and found:
                return 'match' if target_country == found else 'mismatch'
            return 'candidate'
    location = re.sub(r'^(?:hybrid|on[- ]site|onsite|in[- ]office)(?:\s*[:\-–]\s*|\s+)', '',
                      str(location or '').strip(), flags=re.I)
    normalized = ' '.join(_words(location))
    if not normalized:
        return 'unknown'
    words = normalized.split()
    if any(word in _REMOTE_WORDS for word in words):
        found_country = _country_key(location)
        if target_country and found_country and target_country != found_country:
            return 'mismatch'
        return 'unknown'
    city = ' '.join(_words(location.split(',')[0]))
    if not city:
        return 'unknown'
    broad_or_noncity = {
        'europe', 'emea', 'americas', 'worldwide', 'global', 'hybrid',
        'north america', 'south america', 'apac', 'latam',
        'location unspecified', 'location flexible', 'location unverified',
        'multiple locations', 'united kingdom', 'great britain', 'england',
        'united states', 'united states of america', 'canada', 'germany',
        'india', 'australia', 'singapore', 'france', 'netherlands', 'spain',
        'italy', 'switzerland', 'sweden', 'denmark', 'norway', 'poland',
        'japan', 'china',
    }
    found_country = _country_key(location)
    if city != target_city:
        # A different city is a conflict only when the label also identifies a
        # country. Bare regions, country-only labels and unfamiliar labels stay
        # available for review.
        if city in broad_or_noncity or not found_country:
            if target_country and found_country and target_country != found_country:
                return 'mismatch'
            return 'unknown'
        return 'mismatch'
    if target_country and found_country and target_country != found_country:
        return 'mismatch'
    return 'match' if found_country or not target_country else 'candidate'


def location_matches(location, target_location):
    """Reject only clearly different locations; retain remote/unknown claims."""
    target_city, target_country = _target(target_location)
    if not target_city:
        return True
    parts = _location_parts(location)
    if not parts:
        return True
    states = [_classify_location(part, target_city, target_country) for part in parts]
    # An unrecognised internal region code must not cancel an explicit foreign
    # location. A named target city, including an unresolved country, can.
    return 'match' in states or 'candidate' in states or 'mismatch' not in states


def select_board_candidates(jobs, queries, location, profile, limit=20):
    """Filter explicit location conflicts, then rank candidates for verification."""
    from .pipeline import processing_priority

    candidates = [job for job in jobs
                  if location_matches(job.get('location'), location)
                  and title_matches(job.get('title'), queries)]
    return sorted(candidates, key=lambda job: -processing_priority(job, profile))[:limit]
