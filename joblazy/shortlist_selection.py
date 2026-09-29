"""Broaden a small preliminary review batch without discarding candidates."""
from collections import Counter
import re

from .coverage import normalized
from .pipeline import employer_rotation_aliases, processing_priority
from .ats_postings import parse_posting_url


def diversify_candidates(rows, profile, *, pursued_ids=(), per_employer=2):
    """Soft cap within location/fallback tiers; explicit pursuits remain first."""
    if type(per_employer) is not int or per_employer < 1:
        raise ValueError('Per-employer review batch size must be a positive integer')
    pursued_ids=set(pursued_ids)
    aliases=employer_rotation_aliases(profile)
    fallback=profile.get('discovery_preferences',{}).get('title_filter',{}).get('deprioritized',[])
    def lower_interest(job):
        title=job.get('title','').casefold()
        return any(all(token.strip() and re.search(r'(?<!\w)'+re.escape(token.strip().casefold())+r'(?!\w)',title)
                       for token in phrase.split('+')) for phrase in fallback)
    def employer(row):
        label=normalized(row['data'].get('company'))
        if label in aliases:return ('group',aliases[label])
        if label and label!='employer unverified':return ('employer',label)
        posting=parse_posting_url(row['data'].get('url'))
        if posting:return ('board',posting['provider'],posting['region'],posting['board'])
        return ('unknown',row['id'])
    groups={};pursued=[]
    for row in rows:
        if row['id'] in pursued_ids:
            pursued.append(row)
            continue
        # Empty title isolates the existing location score. Within that tier,
        # explicit lower-interest work still follows all ordinary candidates.
        key=(processing_priority({**row['data'],'title':''},profile),not lower_interest(row['data']))
        groups.setdefault(key,[]).append(row)
    ordered=list(pursued)
    for tier in sorted(groups,reverse=True):
        remaining=groups[tier]
        while remaining:
            counts=Counter();deferred=[]
            for row in remaining:
                company=employer(row)
                if counts[company]<per_employer:
                    ordered.append(row);counts[company]+=1
                else:deferred.append(row)
            remaining=deferred
    return ordered
