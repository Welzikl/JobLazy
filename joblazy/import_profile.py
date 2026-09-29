"""Deterministic private migration; reads only the explicitly named source files."""
import re
from pathlib import Path
import yaml
from .common import digest, write_json

def parse_cv(text):
    sections = {'Experience':[],'Education':[],'Projects':[]}
    current = None; entry = None
    for line in text.splitlines():
        if line.startswith('## '): current=line[3:].strip(); entry=None
        elif line.startswith('### ') and current in sections:
            title=line[4:].strip()
            left,sep,right=title.partition(' — ')
            entry={'heading':title,'left':left,'right':right,'details':'','bullets':[]}
            sections[current].append(entry)
        elif entry is not None and line.startswith('**') and line.endswith('**'):
            if not line.startswith('**Tailoring-approved'): entry['details']=line.strip('*')
        elif entry is not None and line.startswith('- '): entry['bullets'].append(line[2:])
    result={'experience':[],'education':[],'projects':[]}
    for entry in sections['Experience']:
        details=entry['details'].split(' | ')
        # Preserve all non-location date context verbatim (including client names).
        result['experience'].append({'company':entry['left'],'role':entry['right'],
            'dates':' | '.join(details[:-1]) if len(details)>1 else details[0],
            'location':details[-1] if len(details)>1 else '', 'bullets':entry['bullets']})
    for entry in sections['Education']:
        result['education'].append({'org':entry['left'],'title':entry['right'],
            'year':entry['details'],'description':' '.join(entry['bullets'])})
    for entry in sections['Projects']:
        result['projects'].append({'name':entry['heading'],'description':' '.join(entry['bullets']),'bullets':entry['bullets']})
    if not result['experience'] or any(not e['role'] for e in result['experience']):
        raise ValueError('Unrecognized canonical CV structure; migration stopped')
    return result

def import_profile(source, destination):
    source=Path(source).resolve(); destination=Path(destination).resolve()
    names=['cv.md','config/profile.yml','modes/_profile.md','modes/_custom.md']
    docs={n:(source/n).read_text(encoding='utf-8-sig') for n in names}
    config=yaml.safe_load(docs['config/profile.yml']); candidate=config['candidate']
    resume=parse_cv(docs['cv.md'])
    resume.update({'candidate':{'name':candidate['full_name'],'email':candidate.get('email',''),
        'phone':candidate.get('phone',''),'location':candidate.get('location',''),'linkedin':candidate.get('linkedin','')},
        'summary':config.get('narrative',{}).get('strategy_operations',''),'page_format':'a4','skills':[],
        'competencies':[],'certifications':[],'awards':[]})
    profile={'example_only':False,'minimum_score':70,'targeting':{'config':config,
        'career_preferences':docs['modes/_profile.md']},'writing_preferences':docs['modes/_custom.md'],
        'applicant':{'identity':{'full_name':candidate['full_name'],'email':candidate.get('email',''),
            'phone':candidate.get('phone','')},'address':{'city':config.get('location',{}).get('city',''),
            'country':config.get('location',{}).get('country','')},'links':{'linkedin':candidate.get('linkedin','')}},
        'answers':[],'facts':[], 'resume':resume,
        'provenance':{'root':str(source),'files':[{ 'path':n,'sha256':digest(docs[n].encode())} for n in names]}}
    profile['search_location']={k:config.get('location',{}).get(k,'') for k in ('city','country')}
    # No inference of missing phone, salary, availability, consents, or name decomposition.
    write_json(destination,profile)
    portals = yaml.safe_load((source/'portals.yml').read_text(encoding='utf-8-sig'))
    boards = portals.get('tracked_companies',[])+portals.get('job_boards',[])
    profile['discovery_preferences'] = {k:portals[k] for k in ('title_filter','location_filter','max_posting_age_days') if k in portals}
    write_json(destination,profile)
    write_json(destination.with_name('boards.json'),{'boards':boards})
    return {'path':str(destination),'employment_entries':len(resume['experience']),
        'education_entries':len(resume['education']),'project_entries':len(resume['projects']),
        'tracked_boards':len(boards)}
