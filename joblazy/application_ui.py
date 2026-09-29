"""Selected-role work and explicit user decisions for the local application UI."""
from contextlib import closing
from pathlib import Path
import threading

from .answers import questions, save_answer
from .assessment_state import assessment_stale, assessment_profile_hash
from .checkpoints import load_materials
from .common import NeedsInput, digest, write_json
from .limits import account_model
from .locking import run_lock, LockBusy
from .pipeline import run_queue
from .profiles import load_profile
from .store import Store


def job_key(key):
    if not isinstance(key, str) or len(key) != 24 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('Invalid saved role identifier')
    return key


class ApplicationController:
    def __init__(self, data, profile_path, models, browser_channel='chrome', *, fixture_origin=None):
        self.data, self.profile_path = Path(data), Path(profile_path)
        self.models, self.browser_channel = models, browser_channel
        self.fixture_origin = fixture_origin
        self.mutex = threading.RLock()
        self.thread = None
        self.operation = {'state': 'idle'}
        try:
            with run_lock(self.data/'run.lock'), closing(Store(self.data/'jobs.sqlite')) as store:
                store.recover()
        except LockBusy:
            pass

    def state(self, key):
        key = job_key(key)
        profile = load_profile(self.profile_path)
        with closing(Store(self.data/'jobs.sqlite')) as store:
            row = store.get(key)
            observed = questions(store, key, self.data/'applications'/key, profile)
            choice = store.choice(key, row['data'])
            from .assist_bridge import session_state
            session = session_state(store, key)
        material = load_materials(self.data/'applications'/key, row['data'], profile)
        result = row['result'] or {}
        ranking = material['ranking'] if material else result.get('ranking', result if 'score' in result else {})
        if not material and assessment_stale(row, digest(profile), assessment_profile_hash(profile)):
            ranking = {}
        with self.mutex:
            operation = dict(self.operation) if self.operation.get('id') == key else {'state': 'idle'}
        return {'id': key, 'title': row['data']['title'], 'company': row['data'].get('company', ''),
                'status': row['status'], 'reason': result.get('reason', ''), 'ranking': ranking,
                'questions': observed, 'profile_revision': digest(profile), 'choice': choice,
                'cv': material['artifact'] if material else None, 'operation': operation,
                'models': self.models, 'session': session}

    def resume(self, key, payload):
        from .assist_bridge import request_resume
        with closing(Store(self.data/'jobs.sqlite')) as store:
            if store.get(job_key(key))['status'] != 'manual_review':
                raise NeedsInput('This role no longer has an open manual handoff.')
            return request_resume(store, key, payload.get('session_id'))

    def start(self, key, action):
        key = job_key(key)
        if action not in {'assess', 'materials'}:
            raise ValueError('Unknown application operation')
        with self.mutex:
            if self.thread and self.thread.is_alive():
                raise NeedsInput('An application operation is already running. Wait for it to finish.')
            self.operation = {'state': 'running', 'id': key, 'action': action}
            self.thread = threading.Thread(target=self._work, args=(key, action), daemon=True)
            self.thread.start()
            return dict(self.operation)

    def _work(self, key, action):
        try:
            with run_lock(self.data/'run.lock'), closing(Store(self.data/'jobs.sqlite')) as store:
                profile = load_profile(self.profile_path)
                row = store.get(key)
                if action == 'assess':
                    if row['status'] in {'manual_review', 'submitting', 'submitted', 'submission_unknown', 'processing'}:
                        raise NeedsInput('Resolve the existing handoff or active operation before assessing again.')
                    store.record_choice(key, 'pursue', 'User selected this role for full assessment in the application interface')
                    if load_materials(self.data/'applications'/key, row['data'], profile):
                        with self.mutex: self.operation.update(state='complete', message='The current assessment and verified CV are ready to review.')
                        return
                    if row['status'] in {'materials_ready', 'needs_input', 'model_failed', 'processing_failed', 'posting_unavailable'}:
                        # Explicit UI retry, never a background release of an
                        # employer handoff. Preserve the old result in history.
                        store.transition(key, 'retryable', {'reason': 'User requested a fresh assessment after resolving or reviewing saved work',
                                                         'prior_result': row['result']}, expected={row['status']})
                        row = store.get(key)
                    if row['status'] == 'ranked' and not assessment_stale(row, digest(profile), assessment_profile_hash(profile)):
                        with self.mutex: self.operation.update(state='complete', message='The current full assessment is ready to review.')
                        return
                else:
                    choice = store.choice(key, row['data'])
                    if not choice or not choice['current'] or choice['decision'] != 'pursue':
                        raise NeedsInput('Select this role for full assessment before creating its CV.')
                    if load_materials(self.data/'applications'/key, row['data'], profile):
                        with self.mutex: self.operation.update(state='complete', message='The current verified CV is ready to review.')
                        return
                    if row['status'] != 'ranked' or assessment_stale(row, digest(profile), assessment_profile_hash(profile)):
                        raise NeedsInput('Complete a current full fit assessment before creating a CV.')
                from playwright.sync_api import sync_playwright
                with sync_playwright() as pw:
                    options = {'headless': True}
                    if self.browser_channel != 'chromium': options['channel'] = self.browser_channel
                    browser = pw.chromium.launch(**options)
                    try:
                        model = account_model(self.data, store, self.models['review' if action == 'assess' else 'application'])
                        results = run_queue(store, profile, model, browser, self.data/'applications', 1, only=key,
                                            rank_only=action == 'assess', profile_path=self.profile_path,
                                            fixture_origin=self.fixture_origin)
                    finally: browser.close()
            outcome = {'state': 'complete', 'results': results}
        except (NeedsInput, LockBusy, ValueError, KeyError) as error:
            outcome = {'state': 'needs_attention', 'message': str(error)}
        except Exception as error:
            outcome = {'state': 'failed', 'message': f'Application work stopped ({type(error).__name__}). Saved progress is preserved.'}
        with self.mutex: self.operation.update(outcome)

    def answer(self, key, payload):
        key = job_key(key)
        if payload.get('confirmed') is not True:
            raise ValueError('Confirm your answer before saving it.')
        if not all(isinstance(payload.get(field), str) for field in ('question', 'value', 'profile_revision')):
            raise ValueError('An observed question, answer and current profile revision are required.')
        with run_lock(self.data/'run.lock'), closing(Store(self.data/'jobs.sqlite')) as store:
            if digest(load_profile(self.profile_path)) != payload['profile_revision']:
                raise NeedsInput('Your profile changed. Reload and review your answer before saving.')
            return save_answer(store, key, self.data/'applications'/key, self.profile_path,
                               payload['question'], payload['value'])

    def outcome(self, key, payload):
        key = job_key(key)
        if payload.get('confirmed') is not True or not isinstance(payload.get('note'), str):
            raise ValueError('Confirm the outcome you checked and add an evidence note.')
        with run_lock(self.data/'run.lock'), closing(Store(self.data/'jobs.sqlite')) as store:
            if store.get(key)['status'] not in {'manual_review', 'submission_unknown'}:
                raise NeedsInput('Only an open handoff or uncertain outcome can be reconciled here.')
            result = store.reconcile(key, payload.get('outcome'), payload['note'])
            write_json(self.data/'applications'/key/'manual-outcome.json', result)
            return result

    def verify_reviewed_cv(self, key, payload):
        key = job_key(key)
        with closing(Store(self.data/'jobs.sqlite')) as store:
            row = store.get(key)
        material = load_materials(self.data/'applications'/key, row['data'], load_profile(self.profile_path))
        if (payload.get('confirmed') is not True or not material
                or payload.get('cv_sha256') != material['artifact']['sha256']):
            raise NeedsInput('Open and confirm the current verified CV before preparing the employer form.')
        return key
