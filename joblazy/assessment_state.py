"""Current assessment contracts and refresh eligibility for unprepared decisions."""
FULL_ASSESSMENT_VERSION=9
SCREEN_ASSESSMENT_VERSION='experience_screen_v1'
REMOTE_SCOPE_VERSION=1
EXPERIENCE_POLICY_VERSION=1


def remote_scope_relevant(job):
    from .coverage import location_class
    return location_class(job.get('location')) in ('uk_remote_candidate','remote_eligibility_unverified')


def assessment_profile_hash(profile):
    # Discovery settings affect intake/scheduling, never ranking evidence or policy.
    # Keep every other field so new candidate facts conservatively refresh decisions.
    from .common import digest
    return digest({key:value for key,value in profile.items() if key!='discovery_preferences'})


def assessment_stale(row,profile_hash,assessment_hash=None):
    from .experience_policy import has_experience_policy_conflict
    if profile_hash is None or row['status'] not in ('ranked','not_selected'):return False
    result=row['result'] or {};assessment=result.get('ranking') or result
    screened=assessment.get('assessment_stage')=='experience_screen'
    # An operator pass or other non-assessment result must not become a loop.
    if not screened and 'score' not in assessment:return False
    expected=SCREEN_ASSESSMENT_VERSION if screened else FULL_ASSESSMENT_VERSION
    saved_hash=assessment.get('assessment_profile_hash')
    profile_changed=(saved_hash!=assessment_hash if saved_hash and assessment_hash
                     else assessment.get('candidate_profile_hash')!=profile_hash)
    return (profile_changed
            or assessment.get('assessment_version')!=expected
            or (not screened and has_experience_policy_conflict(assessment)
                and assessment.get('experience_policy_version')!=EXPERIENCE_POLICY_VERSION)
            or (not screened and remote_scope_relevant(row['data'])
                and assessment.get('remote_scope_version')!=REMOTE_SCOPE_VERSION))
