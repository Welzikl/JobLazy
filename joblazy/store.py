"""SQLite is the durable queue. Submission intent is committed BEFORE a click."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from .common import digest

def canonical_url(url):
    p = urlsplit(url)
    query = [(k,v) for k,v in parse_qsl(p.query) if not k.startswith('utm_') and k not in ('source','ref')]
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), urlencode(sorted(query)), ''))

def choice_job_hash(job):
    # Bind interest to the actual role, ignoring source bookkeeping and whitespace.
    return digest({k:' '.join(str(job.get(k) or '').split()) for k in ('company','title','location','description')})

class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          PRAGMA journal_mode=WAL;
          CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, url TEXT UNIQUE, data TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'discovered', result TEXT,
            updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
          CREATE TABLE IF NOT EXISTS events (
            seq INTEGER PRIMARY KEY, job_id TEXT, status TEXT, detail TEXT,
            created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
          CREATE TABLE IF NOT EXISTS model_requests (
            id INTEGER PRIMARY KEY, day TEXT NOT NULL,
            created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
          CREATE TABLE IF NOT EXISTS job_choices (
            job_id TEXT PRIMARY KEY, decision TEXT NOT NULL, job_hash TEXT NOT NULL,
            note TEXT NOT NULL, recorded_at TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS assist_sessions (
            job_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, status TEXT NOT NULL,
            heartbeat REAL NOT NULL, message TEXT NOT NULL, command TEXT);
        ''')
    def close(self):
        self.db.close()
    def record_choice(self,key,decision,note):
        if decision not in ('pursue','pass','automatic') or not isinstance(note,str) or not note.strip():
            raise ValueError('A job choice requires pursue, pass or automatic and an explicit user note')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.get(key)
            record={'job_id':key,'decision':decision,'job_hash':choice_job_hash(row['data']),
                'note':note.strip(),'recorded_at':datetime.now(timezone.utc).isoformat()}
            self.db.execute('INSERT OR REPLACE INTO job_choices VALUES(?,?,?,?,?)',tuple(record.values()))
            self.db.execute('INSERT INTO events(job_id,status,detail) VALUES(?,?,?)',
                (key,'user_choice',json.dumps(record)))
        return record
    def choice(self,key,job=None):
        row=self.db.execute('SELECT * FROM job_choices WHERE job_id=?',(key,)).fetchone()
        if row is None:return None
        record=dict(row);record['current']=record['job_hash']==choice_job_hash(job if job is not None else self.get(key)['data'])
        return record
    def pursued_ids(self,rows):
        """Current explicit interest for scheduling; never grant queue readiness."""
        jobs={row['id']:row['data'] for row in rows}
        return {choice['job_id'] for choice in self.db.execute(
            "SELECT job_id,job_hash FROM job_choices WHERE decision='pursue'")
            if choice['job_id'] in jobs and choice['job_hash']==choice_job_hash(jobs[choice['job_id']])}
    def ingest(self, job):
        url = canonical_url(job['url'])
        key = digest(url)[:24]
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO jobs(id,url,data) VALUES(?,?,?)', (key,url,json.dumps(job)))
            row=self.get(key)
            # Preserve the exact posting used for prepared/submitted artifacts. Refresh
            # unprocessed observations; re-evaluate rejected postings only if content changed.
            stopped=row['status'] in ('posting_unavailable','posting_expired','posting_closed','processing_failed')
            protected_history=stopped and self.db.execute(
                "SELECT 1 FROM events WHERE job_id=? AND status IN "
                "('materials_ready','prepared','manual_review','submitting','submitted','submission_unknown') LIMIT 1",
                (key,)).fetchone() is not None
            # Changed source content warrants another public check, not an assertion
            # that the vacancy reopened. Historical application bindings stay frozen.
            if (stopped and not protected_history) or row['status'] in ('discovered','retryable','not_selected','ranked','assessment_failed','model_failed'):
                normalize=lambda value:' '.join(str(value or '').split())
                old=row['data']
                if not str(job.get('description') or '').strip() and str(old.get('description') or '').strip():
                    # A summary-only feed omitted the JD; it did not delete it.
                    job={**job,'description':old['description'],
                        'description_retained_from':old.get('description_retained_from',{'observed_at':old.get('observed_at')})}
                    for field in ('description_source','description_method'):
                        if field in old:job[field]=old[field]
                    if old.get('description_refresh_required') or any(normalize(old.get(k))!=normalize(job.get(k)) for k in ('title','company','location')):
                        job['description_refresh_required']=True
                content=lambda j: {k:normalize(j.get(k)) for k in ('title','company','location','description')}
                changed=content(row['data']) != content(job)
                state='discovered' if changed else row['status']
                self.db.execute('UPDATE jobs SET data=?,status=? WHERE id=?',(json.dumps(job),state,key))
                if changed:
                    self.db.execute('INSERT INTO events(job_id,status,detail) VALUES(?,?,?)',
                        (key,state,json.dumps({'reason':'Posting content changed'})))
        return key
    def get(self, key):
        row = self.db.execute('SELECT * FROM jobs WHERE id=?', (key,)).fetchone()
        if row is None: raise KeyError(key)
        d = dict(row); d['data'] = json.loads(d['data']); d['result'] = json.loads(d['result']) if d['result'] else None
        return d
    def record_description(self,key,source_job,observed):
        """Persist public extraction before inference without rebinding past artifacts."""
        if not all(observed.get(field) for field in ('description','description_source','description_method')):
            return source_job
        if any(observed.get(field)!=source_job.get(field) for field in ('url','title','company','location')):
            raise ValueError('Description observation changed the source posting identity')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.get(key)
            if digest(row['data'])!=digest(source_job):
                raise ValueError('Source posting changed during description retrieval')
            protected=self.db.execute(
                "SELECT 1 FROM events WHERE job_id=? AND status IN "
                "('materials_ready','prepared','manual_review','submitting','submitted','submission_unknown') LIMIT 1",
                (key,)).fetchone()
            if protected or row['status'] not in ('discovered','processing','retryable'):
                return source_job
            saved={**source_job,**{field:observed[field] for field in
                ('description','description_source','description_method')}}
            for field in ('description_refresh_required','description_retained_from'):
                if field not in observed:saved.pop(field,None)
            if saved!=source_job:
                self.db.execute('UPDATE jobs SET data=? WHERE id=?',(json.dumps(saved),key))
                self.db.execute('INSERT INTO events(job_id,status,detail) VALUES(?,?,?)',
                    (key,'description_observed',json.dumps({
                        'source_url':observed['description_source'],'method':observed['description_method'],
                        'previous_job_hash':digest(source_job),'job_hash':digest(saved)})))
            return saved
    def list(self, statuses=None):
        sql='SELECT * FROM jobs'; args=()
        if statuses is not None:
            args=tuple(statuses)
            if not args: return []
            sql+=' WHERE status IN ('+','.join('?' for _ in args)+')'
        rows=self.db.execute(sql+' ORDER BY updated,id',args)
        result=[]
        for row in rows:
            d=dict(row);d['data']=json.loads(d['data']);d['result']=json.loads(d['result']) if d['result'] else None
            result.append(d)
        return result
    def daily_usage(self,day):
        return {'job_attempts':self.db.execute("SELECT count(*) FROM events WHERE status='processing' AND date(created)=?",(day,)).fetchone()[0],
            'model_requests':self.db.execute('SELECT count(*) FROM model_requests WHERE day=?',(day,)).fetchone()[0]}
    def prior_application(self,job,exclude_id=None):
        """Match exact observed routes, including previously imported outcomes."""
        from .discovery_intake import routes
        rows=self.list({'submitted','submission_unknown','submitting','manual_review'})
        scope=rows+([self.get(exclude_id)] if exclude_id else [])
        aliases=self.observed_routes(scope)
        target=routes(job)|aliases.get(exclude_id,set())
        return next((row for row in rows
            if row['id']!=exclude_id and target.intersection(routes(row['data'])|aliases.get(row['id'],set()))),None)

    def record_application_route(self,key,observation):
        """Save a posting-specific public link without changing source/CV bindings."""
        from .discovery_intake import posting_identity
        route=posting_identity(observation.get('url',''))
        if not route:return False  # Generic account/careers links cannot identify a job.
        if not all(isinstance(observation.get(k),str) and observation[k].strip()
                   for k in ('source_url','checked_at','method')):
            raise ValueError('An observed route needs source, method and observation time')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.get(key)
            if row['status'] in ('submitted','submitting','submission_unknown','manual_review'):
                raise ValueError('Cannot change route evidence after an application handoff')
            record={**observation,'route':route,'job_hash':choice_job_hash(row['data'])}
            self.db.execute('INSERT INTO events(job_id,status,detail) VALUES(?,?,?)',
                (key,'application_route_observed',json.dumps(record)))
        return True

    def observed_routes(self,rows):
        """Only retain aliases still bound to the saved posting's substantive data."""
        jobs={r['id']:r['data'] for r in rows};hashes={};result={}
        if not jobs:return result
        for event in self.db.execute("SELECT job_id,detail FROM events WHERE status='application_route_observed' ORDER BY seq"):
            key=event['job_id']
            if key not in jobs:continue
            # Most saved jobs have no observed alias. Hash only those with an
            # event, once per call; current data still invalidates stale links.
            if key not in hashes:hashes[key]=choice_job_hash(jobs[key])
            detail=json.loads(event['detail'])
            result.pop(key,None)
            if detail['job_hash']==hashes[key]:result[key]={detail['route']}
        return result
    def reserve_model_request(self,day,limit):
        from .common import DailyModelLimit
        from .limits import DAILY_REQUESTS
        if type(limit) is not int or limit < 1:
            raise ValueError('Model request limit must be a positive integer')
        limit = min(limit, DAILY_REQUESTS)
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            if self.daily_usage(day)['model_requests']>=limit:
                raise DailyModelLimit('Daily model-request budget reached; waiting until the next UTC day')
            self.db.execute('INSERT INTO model_requests(day) VALUES(?)',(day,))
    def transition(self, key, status, detail=None, expected=None):
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            old = self.get(key)['status']
            if expected is not None and old not in expected:
                raise ValueError(f'cannot transition {old} to {status}')
            if old in ('submitting','submitted','submission_unknown') and status not in ('submitted','submission_unknown'):
                raise ValueError('Submission already attempted; reconcile outcome before another attempt')
            if old=='manual_review' and status not in ('manual_review','submitted','submission_unknown'):
                raise ValueError('Application handed to operator; reconcile outcome before another attempt')
            if status == 'processing':
                from .common import DailyJobLimit
                from .limits import DAILY_JOBS
                day = datetime.now(timezone.utc).date().isoformat()
                if self.daily_usage(day)['job_attempts'] >= DAILY_JOBS:
                    raise DailyJobLimit('Daily processing allowance reached (25 attempts); saved work remains available until the next UTC day')
            self.db.execute('UPDATE jobs SET status=?,result=?,updated=? WHERE id=?',
                (status,json.dumps(detail),datetime.now(timezone.utc).isoformat(),key))
            self.db.execute('INSERT INTO events(job_id,status,detail) VALUES(?,?,?)', (key,status,json.dumps(detail)))
    def recover(self):
        # A process may have died after the server accepted a click. Never retry it.
        for row in self.list({'submitting','processing'}):
            if row['status'] == 'submitting':
                self.transition(row['id'], 'submission_unknown', {'reason':'Interrupted after durable submit intent'})
            elif row['status'] == 'processing':
                detail = row.get('result') or {}
                if (isinstance(detail, dict) and detail.get('stage') == 'search_shortlist'
                        and detail.get('prior_status') in {'discovered', 'retryable', 'ranked', 'not_selected'}
                        and 'prior_result' in detail):
                    self.transition(row['id'], detail['prior_status'], detail['prior_result'])
                else:
                    self.transition(row['id'], 'retryable', {'reason':'Interrupted before submission'})
    def reconcile(self,key,outcome,note):
        if outcome not in ('submitted','not-submitted','uncertain') or not note.strip():
            raise ValueError('A supported outcome and an explicit operator note are required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row=self.get(key)
            if row['status'] in ('processing','submitting'):
                raise ValueError('Recover the interrupted run before reconciling its outcome')
            if row['status']=='submitted':
                raise ValueError('A recorded submission cannot be undone by outcome reconciliation')
            if outcome in ('not-submitted','uncertain') and row['status'] not in ('submission_unknown','manual_review'):
                raise ValueError('Only an uncertain submission or manual handoff can be reconciled as not submitted')
            target={'submitted':'submitted','not-submitted':'needs_input','uncertain':'submission_unknown'}[outcome]
            detail={'method':'operator_report','outcome':outcome,'note':note.strip(),
                'previous_status':row['status'],'reason':'Operator reconciled the application outcome'}
            self.db.execute('UPDATE jobs SET status=?,result=?,updated=? WHERE id=?',
                (target,json.dumps(detail),datetime.now(timezone.utc).isoformat(),key))
            self.db.execute('INSERT INTO events(job_id,status,detail) VALUES(?,?,?)',(key,target,json.dumps(detail)))
            return {'id':key,'status':target,**detail}
