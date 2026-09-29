"""Explicit edits to a confirmed local profile, with private before/after evidence."""
import copy
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .common import NeedsInput, digest, read_json, write_json
from .locking import run_lock
from .onboarding import PREFERENCE_FIELDS
from .profiles import require_profile

IDENTITY_FIELDS = ('full_name', 'first_name', 'last_name', 'email', 'phone', 'city', 'country')


class ProfileEditConflict(NeedsInput):
    """The visible profile became stale before an explicitly confirmed update."""


def _strings(value, fields, label):
    if not isinstance(value, dict) or any(not isinstance(value.get(field, ''), str) for field in fields):
        raise ValueError(label + ' must contain text fields.')
    return {field: value.get(field, '').strip() for field in fields}


def _entries(value, fields, *, bullets=False):
    if not isinstance(value, list) or len(value) > 80:
        raise ValueError('Use at most 80 entries in each profile section.')
    result = []
    for entry in value:
        item = _strings(entry, fields, 'Each profile entry')
        if bullets:
            raw = entry.get('bullets', [])
            if not isinstance(raw, list) or any(not isinstance(text, str) for text in raw):
                raise ValueError('Experience bullets must be text.')
            item['bullets'] = [text.strip() for text in raw if text.strip()]
        existing_index = entry.get('existing_index')
        if existing_index is not None:
            if not isinstance(existing_index, int) or isinstance(existing_index, bool) or existing_index < 0:
                raise ValueError('Profile entry identity is invalid. Reload this page before saving.')
            item['existing_index'] = existing_index
        result.append(item)
    return result


def _merge_entries(existing, edited):
    """Keep canonical fields that this intentionally small editor does not show."""
    if not isinstance(existing, list):
        existing = []
    used = set(); merged = []
    for item in edited:
        index = item.pop('existing_index', None)
        base = {}
        if index is not None:
            if index >= len(existing) or index in used or not isinstance(existing[index], dict):
                raise ValueError('Profile entry identity changed. Reload this page before saving.')
            base = copy.deepcopy(existing[index]); used.add(index)
        base.update(item)
        merged.append(base)
    return merged


def _preserve_matching(existing, values, key, make_new):
    """Retain provenance for unchanged facts and links, including duplicates."""
    available = [copy.deepcopy(item) for item in existing if isinstance(item, dict)]
    merged = []
    for value in values:
        match = next((item for item in available if item.get(key) == value), None)
        if match is not None:
            available.remove(match); merged.append(match)
        else:
            merged.append(make_new(value))
    return merged


def _https_urls(value):
    if not isinstance(value, list) or any(not isinstance(url, str) for url in value):
        raise ValueError('Portfolio references must be links.')
    urls = []
    for url in value:
        url = url.strip()
        if not url:
            continue
        try:
            parsed = urlsplit(url)
        except ValueError:
            raise ValueError('Portfolio links must be ordinary HTTPS URLs.') from None
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Portfolio links must be ordinary HTTPS URLs.')
        if url not in urls:
            urls.append(url)
    return urls


def profile_form(profile):
    """Expose only human-editable fields; runtime state never reaches this page."""
    identity = profile['applicant']['identity']
    address = profile['applicant'].get('address', {})
    resume = profile['resume']
    skills = []
    for group in resume.get('skills', []):
        if isinstance(group, dict):
            skills.extend(item for item in group.get('items', []) if isinstance(item, str))
        elif isinstance(group, str):
            skills.append(group)
    targeting = profile.get('targeting', {})
    # Early imported profiles allowed a single free-text targeting value. Treat
    # it as the person's stated desired work so the editor can safely migrate
    # that legacy shape only after they review and confirm it.
    if isinstance(targeting, str):
        targeting = {'desired_work': targeting}
    if not isinstance(targeting, dict):
        targeting = {}
    return {
        'identity': {field: str((address if field in ('city', 'country') else identity).get(field, ''))
                     for field in IDENTITY_FIELDS},
        'summary': str(resume.get('summary', '')),
        'experience': [{field: str(entry.get(field, '')) for field in ('company', 'role', 'dates', 'location')}
                       | {'bullets': [str(text) for text in entry.get('bullets', []) if isinstance(text, str)]}
                       | {'existing_index': index}
                       for index, entry in enumerate(resume.get('experience', []))],
        'education': [{field: str(entry.get(field, '')) for field in ('org', 'title', 'year')}
                      | {'existing_index': index}
                      for index, entry in enumerate(resume.get('education', []))],
        'projects': [{field: str(entry.get(field, '')) for field in ('name', 'description')}
                     | {'existing_index': index}
                     for index, entry in enumerate(resume.get('projects', []))],
        'skills': skills,
        'facts': [str(item.get('text', '')) for item in profile.get('facts', []) if isinstance(item, dict)],
        'preferences': {field: str(targeting.get(field, '')) for field in PREFERENCE_FIELDS},
        'links': [str(item.get('url', '')) for item in profile.get('supporting_links', []) if isinstance(item, dict)],
    }


def profile_state(profile_path):
    profile = require_profile(read_json(profile_path))
    return {'profile': profile_form(profile), 'revision': digest(profile)}


def edit_profile(data, profile_path, payload):
    if not isinstance(payload, dict) or payload.get('confirmed') is not True:
        raise ValueError('Review the edited facts and tick the confirmation before saving.')
    revision = payload.get('revision')
    if not isinstance(revision, str):
        raise ValueError('Profile revision is missing. Reload this page before saving.')
    form = payload.get('profile')
    if not isinstance(form, dict):
        raise ValueError('Expected an edited profile form.')
    identity = _strings(form.get('identity'), IDENTITY_FIELDS, 'Identity')
    summary = form.get('summary', '')
    if not isinstance(summary, str):
        raise ValueError('Professional summary must be text.')
    experience = _entries(form.get('experience'), ('company', 'role', 'dates', 'location'), bullets=True)
    education = _entries(form.get('education'), ('org', 'title', 'year'))
    projects = _entries(form.get('projects'), ('name', 'description'))
    skills = form.get('skills', [])
    facts = form.get('facts', [])
    if (not isinstance(skills, list) or not isinstance(facts, list)
            or any(not isinstance(value, str) for value in skills + facts)):
        raise ValueError('Skills and additional facts must be text.')
    preferences = _strings(form.get('preferences'), PREFERENCE_FIELDS, 'Search preferences')
    if not all(preferences[field] for field in ('desired_work', 'city', 'country')):
        raise ValueError('Tell us the work you want and your preferred city and country.')
    links = _https_urls(form.get('links', []))
    profile_path = Path(profile_path)
    edit_id = uuid.uuid4().hex
    # The command-line answer writer uses this same lock. A revision check only
    # detects a stale page when all canonical-profile writers serialize first.
    with run_lock(Path(data) / 'run.lock'):
        before = require_profile(read_json(profile_path))
        if digest(before) != revision:
            raise ProfileEditConflict('This profile changed in another page. Reload and review the latest saved profile before replacing it.')
        after = copy.deepcopy(before)
        after['applicant']['identity'].update({field: identity[field] for field in IDENTITY_FIELDS if field not in ('city', 'country')})
        after['applicant'].setdefault('address', {}).update(city=identity['city'], country=identity['country'])
        candidate = after['resume'].setdefault('candidate', {})
        candidate.update(name=identity['full_name'], email=identity['email'], phone=identity['phone'], location=identity['city'])
        after['resume'].update(summary=summary.strip(),
                               experience=_merge_entries(after['resume'].get('experience'), experience),
                               education=_merge_entries(after['resume'].get('education'), education),
                               projects=_merge_entries(after['resume'].get('projects'), projects))
        clean_skills = [value.strip() for value in skills if value.strip()]
        old_skills = profile_form(before)['skills']
        after['resume']['skills'] = copy.deepcopy(after['resume'].get('skills', [])) if clean_skills == old_skills else (
            [{'category': 'Skills', 'items': clean_skills}] if clean_skills else [])
        original_targeting = after.get('targeting')
        after['targeting'] = copy.deepcopy(original_targeting) if isinstance(original_targeting, dict) else {}
        after['targeting'].update(preferences)
        after['search_location'] = copy.deepcopy(after.get('search_location', {})) if isinstance(after.get('search_location'), dict) else {}
        after['search_location'].update({field: preferences[field] for field in ('city', 'country')})
        stamp = datetime.now(timezone.utc).isoformat()
        after['facts'] = _preserve_matching(after.get('facts', []), [value.strip() for value in facts if value.strip()], 'text',
            lambda value: {'text': value, 'source': {'method': 'operator_profile_edit', 'edit_id': edit_id, 'confirmed_at': stamp}})
        after['supporting_links'] = _preserve_matching(after.get('supporting_links', []), links, 'url',
            lambda url: {'url': url, 'status': 'not_read'})
        require_profile(after)
        audit = Path(data) / 'profile-edits' / edit_id
        write_json(audit / 'before.json', before)
        write_json(audit / 'after.json', after)
        write_json(audit / 'receipt.json', {'id': edit_id, 'confirmed_at': stamp, 'before_revision': revision,
                                             'after_revision': digest(after), 'status': 'confirmed'})
        write_json(profile_path, after)
    return {'status': 'confirmed', 'revision': digest(after), 'edit_id': edit_id,
            'message': 'Your profile changes are saved. Existing fit scores and CVs are checked against the new profile before reuse.'}
