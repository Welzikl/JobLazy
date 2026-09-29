"""Session-bound commands between the local UI and its visible browser process."""
import time
import uuid
from .common import NeedsInput


def session_state(store, key):
    row = store.db.execute('SELECT * FROM assist_sessions WHERE job_id=?', (key,)).fetchone()
    if not row:
        return {'active': False, 'message': 'No connected preparation session.'}
    fresh = 0 <= time.time() - row['heartbeat'] < 10
    active = fresh and row['status'] == 'waiting' and row['command'] is None
    return {'id': row['session_id'], 'active': active, 'status': row['status'],
            'message': row['message'] if fresh or row['status'] == 'closed' else
            'The preparation connection is unavailable. Check the browser and record its outcome before retrying.'}


def request_resume(store, key, session_id):
    with store.db:
        store.db.execute('BEGIN IMMEDIATE')
        state = session_state(store, key)
        if not state['active'] or state.get('id') != session_id:
            raise NeedsInput('This preparation session is unavailable or changed. Reload before continuing.')
        store.db.execute("UPDATE assist_sessions SET command='resume' WHERE job_id=? AND session_id=?",
                         (key, session_id))
    return {'message': 'Continue requested for this open form.'}


class BrowserBridge:
    def __init__(self, store, key):
        self.store, self.key, self.id = store, key, uuid.uuid4().hex
        with store.db:
            store.db.execute('INSERT OR REPLACE INTO assist_sessions VALUES(?,?,?,?,?,NULL)',
                             (key, self.id, 'working', time.time(), 'Opening the reviewed application.'))

    def wait(self, page, message, *, stop_when=None, **kwargs):
        while not page.is_closed():
            if self.store.get(self.key)['status'] != 'manual_review': return 'done'
            if stop_when and stop_when(): return 'done'
            with self.store.db:
                self.store.db.execute('BEGIN IMMEDIATE')
                row = self.store.db.execute('SELECT * FROM assist_sessions WHERE job_id=?', (self.key,)).fetchone()
                if not row or row['session_id'] != self.id: return 'done'
                command = row['command']
                self.store.db.execute('UPDATE assist_sessions SET status=?,heartbeat=?,message=?,command=NULL WHERE job_id=? AND session_id=?',
                                      ('working' if command else 'waiting', time.time(),
                                       'Continuing in the open form.' if command else
                                       'Review the employer browser. Save any answers here, then choose Continue in the open form.',
                                       self.key, self.id))
            if command == 'resume': return 'resume'
            page.wait_for_timeout(250)
        return 'done'

    def close(self, message='Browser session closed. Record the outcome you checked.'):
        with self.store.db:
            self.store.db.execute("UPDATE assist_sessions SET status='closed',heartbeat=?,message=?,command=NULL WHERE job_id=? AND session_id=?",
                                  (time.time(), message, self.key, self.id))
