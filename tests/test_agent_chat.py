"""The same intake/CV pipeline works with host-chat answers and no provider CLI."""
import copy
import importlib.util
from contextlib import closing
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from jsonschema import ValidationError
from joblazy.agent import AgentModel, AgentResponseNeeded
from joblazy.common import ROOT, NeedsInput, read_json, write_json
from joblazy.materials import obj
from .support import FixtureModel, example_profile, fixture_server, job
from .test_onboarding import IntakeModel, upload, confirmation


class HostResponder:
    def __init__(self, exchange, model):
        self.exchange = Path(exchange)
        self.model = model
        self.stop = threading.Event()
        self.errors = []
        self.tasks = []

    def __enter__(self):
        def answer():
            while not self.stop.wait(.02):
                for path in self.exchange.glob('*.request.json'):
                    request = read_json(path)
                    target = self.exchange / (request['request_id'] + '.response.json')
                    if target.exists():
                        continue
                    try:
                        self.tasks.append(request['task'])
                        value = self.model.generate(request['task'], request['data'], request['schema'])
                        write_json(target, {'request_id': request['request_id'], 'response': value})
                    except Exception as error:
                        self.errors.append(error)
                        return
        self.thread = threading.Thread(target=answer, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(2)
        if self.errors:
            raise self.errors[0]


class AgentChatTests(unittest.TestCase):
    def test_response_is_bound_to_inputs_schema_and_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            model = AgentModel(temp, wait_seconds=0)
            schema = obj({'value': {'type': 'string'}})
            with self.assertRaises(AgentResponseNeeded):
                model.generate('task', {'candidate': 'fictional'}, schema)
            pending = read_json(Path(temp) / 'pending.json')
            response = Path(pending['response_path'])
            write_json(response, {'request_id': 'wrong', 'response': {'value': 'ok'}})
            with self.assertRaisesRegex(NeedsInput, 'different request'):
                model.generate('task', {'candidate': 'fictional'}, schema)
            write_json(response, {'request_id': pending['request_id'], 'response': {'value': 7}})
            with self.assertRaises(ValidationError):
                model.generate('task', {'candidate': 'fictional'}, schema)
            write_json(response, {'request_id': pending['request_id'], 'response': {'value': 'ok'}})
            self.assertEqual(model.generate('task', {'candidate': 'fictional'}, schema), {'value': 'ok'})
            self.assertFalse((Path(temp) / 'pending.json').exists())
            with self.assertRaises(AgentResponseNeeded):
                model.generate('task', {'candidate': 'someone else'}, schema)
            rules = Path(temp) / 'rules.md'
            rules.write_text('Changed portable rules', encoding='utf-8')
            model.shared_rules_path = rules
            with self.assertRaises(AgentResponseNeeded):
                model.generate('task', {'candidate': 'fictional'}, schema)
            rules.unlink()
            with self.assertRaises(FileNotFoundError):
                model.generate('task', {'candidate': 'fictional'}, schema)

    def test_intake_waits_for_host_and_preserves_confirmation_boundary(self):
        from joblazy.onboarding import create_draft, confirm_draft
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = AgentModel(root / 'exchange', wait_seconds=5)
            with patch('joblazy.model.subprocess.run', side_effect=AssertionError('No provider process')):
                with HostResponder(model.exchange, IntakeModel()):
                    draft = create_draft(root / 'runtime', upload(), model)
                profile = root / 'local/profile.json'
                self.assertFalse(profile.exists())
                payload = confirmation(draft)
                payload['confirmed'] = False
                with self.assertRaises(ValueError):
                    confirm_draft(root / 'runtime', profile, payload)
                payload['confirmed'] = True
                confirm_draft(root / 'runtime', profile, payload)
                self.assertEqual(read_json(profile)['resume']['candidate']['name'], 'Morgan Example')
                with self.assertRaises(ValueError):
                    confirm_draft(root / 'runtime', profile, payload)

    def test_existing_pipeline_renders_and_checkpoints_host_chat_cv(self):
        from playwright.sync_api import sync_playwright
        from joblazy.pipeline import run_queue
        from joblazy.store import Store
        from joblazy.checkpoints import load_materials
        with tempfile.TemporaryDirectory() as temp, fixture_server() as (origin, received):
            data = Path(temp)
            with closing(Store(data / 'jobs.sqlite')) as store, sync_playwright() as pw:
                profile = example_profile()
                key = store.ingest(job(origin + '/success'))
                model = AgentModel(data / 'exchange', wait_seconds=10)
                channel = os.environ.get('JOBLAZY_TEST_BROWSER_CHANNEL', 'msedge')
                options = {'headless': True}
                if channel != 'chromium':
                    options['channel'] = channel
                browser = pw.chromium.launch(**options)
                try:
                    # Node is needed by the real renderer. Only model construction is forbidden.
                    with patch('joblazy.model.CodexModel', side_effect=AssertionError('No second AI login')):
                        with HostResponder(model.exchange, FixtureModel()) as responder:
                            result = run_queue(store, profile, model, browser, data / 'applications',
                                               1, only=key, fixture_origin=origin)
                    self.assertEqual(result[0]['status'], 'materials_ready', result)
                    self.assertTrue(any('Independently check' in task for task in responder.tasks))
                    checkpoint = load_materials(data / 'applications' / key, store.get(key)['data'], profile)
                    self.assertEqual(checkpoint['artifact']['pages'], 1)
                    from joblazy.assist import prepare_assisted
                    with self.assertRaisesRegex(NeedsInput, 'reviewed CV changed'):
                        prepare_assisted(store, key, profile, model, browser, data,
                                         fixture_origin=origin, reviewed_cv_sha256='wrong')
                    page, status = prepare_assisted(store, key, profile, model, browser, data,
                        fixture_origin=origin, reviewed_cv_sha256=checkpoint['artifact']['sha256'])
                    self.assertEqual(page.locator('[name=resume]').evaluate('e=>e.files.length'), 1)
                    self.assertEqual(store.get(key)['status'], 'manual_review')
                    page.close()
                    store.reconcile(key, 'not-submitted', 'Closed fictional form without submitting')
                    from joblazy.dashboard import tracker_csv
                    self.assertIn('Fictional Software Ltd', tracker_csv(data))
                    self.assertEqual(received, [])
                finally:
                    browser.close()

    def test_host_answer_cannot_invent_cv_metric(self):
        from joblazy.materials import tailor, TailoringFailed
        class BadModel(FixtureModel):
            def generate(self, task, data, schema):
                value = super().generate(task, data, schema)
                if 'Tailor the CV' in task:
                    value['experience'][0]['bullets'][0]['text'] = 'Coordinated onboarding for 999 partners.'
                return value
        with tempfile.TemporaryDirectory() as temp:
            model = AgentModel(temp, wait_seconds=5)
            with HostResponder(temp, BadModel()), self.assertRaises(TailoringFailed):
                tailor(job('https://example.test/fictional'), example_profile(), model)

    def test_agent_preflight_does_not_construct_codex_model(self):
        spec = importlib.util.spec_from_file_location('preflight_agent_test', ROOT / 'scripts/preflight.py')
        preflight = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(preflight)
        with patch('joblazy.model.CodexModel', side_effect=AssertionError('No Codex required')):
            result = preflight.check(agent=True)
        self.assertEqual(result['model'], 'current-agent-chat')
        self.assertIsNone(result['signed_in'])


if __name__ == '__main__':
    unittest.main()
