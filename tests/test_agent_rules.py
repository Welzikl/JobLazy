import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from joblazy.common import ModelUnavailable, digest, read_json, write_json
from joblazy.materials import obj
from joblazy.model import CodexModel, CodexWebSearch


class AgentRuleTests(unittest.TestCase):
    def test_effective_rules_reach_every_mode_and_match_saved_request(self):
        for kind, compact in ((CodexModel, True), (CodexModel, False), (CodexWebSearch, True)):
            with self.subTest(kind=kind.__name__, compact=compact), tempfile.TemporaryDirectory() as temp:
                model = kind(temp, executable='fixture', compact=compact)
                def cli(args, **kwargs):
                    if args[1] == 'login':
                        return subprocess.CompletedProcess(args, 0, 'Logged in', '')
                    setting = next(a for a in args if a.startswith('model_instructions_file='))
                    raw = Path(json.loads(setting.split('=', 1)[1])).read_bytes()
                    text = raw.decode('utf-8')
                    self.assertIn(model.shared_rules_path.read_text(encoding='utf-8-sig').strip(), text)
                    self.assertIn(model.instructions_path.read_text(encoding='utf-8-sig').strip(), text)
                    request = read_json(next((Path(temp) / 'requests').glob('*.json')))
                    self.assertEqual(request['instructions'], digest(raw))
                    self.assertIn('features.shell_tool=false', args)
                    self.assertIn('apps._default.enabled=false', args)
                    self.assertIn('web_search=' + json.dumps(model.web_search_mode), args)
                    write_json(args[args.index('--output-last-message') + 1], {'value': 'ok'})
                    event = {'type': 'item.completed', 'item': {'type': 'web_search',
                             'action': {'type': 'search', 'query': 'fictional role'}}}
                    return subprocess.CompletedProcess(args, 0, json.dumps(event), '')
                with patch('joblazy.model.subprocess.run', side_effect=cli):
                    self.assertEqual(model.generate('fixture', {}, obj({'value': {'type': 'string'}})), {'value': 'ok'})

    def test_changing_either_policy_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = CodexModel(root / 'cache', executable='fixture')
            model.shared_rules_path = root / 'shared.md'
            model.instructions_path = root / 'worker.md'
            model.shared_rules_path.write_text('Shared first', encoding='utf-8')
            model.instructions_path.write_text('Worker first', encoding='utf-8')
            reservations = []
            model.before_request = lambda: reservations.append(1)
            def cli(args, **kwargs):
                if args[1] == 'login':
                    return subprocess.CompletedProcess(args, 0, 'Logged in', '')
                write_json(args[args.index('--output-last-message') + 1], {'value': str(len(reservations))})
                return subprocess.CompletedProcess(args, 0, '', '')
            schema = obj({'value': {'type': 'string'}})
            with patch('joblazy.model.subprocess.run', side_effect=cli):
                self.assertEqual(model.generate('fixture', {}, schema), {'value': '1'})
                self.assertEqual(model.generate('fixture', {}, schema), {'value': '1'})
                model.shared_rules_path.write_text('Shared revised', encoding='utf-8')
                self.assertEqual(model.generate('fixture', {}, schema), {'value': '2'})
                model.instructions_path.write_text('Worker revised', encoding='utf-8')
                self.assertEqual(model.generate('fixture', {}, schema), {'value': '3'})
            self.assertEqual(len(reservations), 3)
            # Even a cached answer is unavailable without intact policy files.
            for path in (model.shared_rules_path, model.instructions_path):
                original = path.read_bytes()
                for content in (None, b'  \n', b'\xff'):
                    if content is None:
                        path.unlink()
                    else:
                        path.write_bytes(content)
                    with patch('joblazy.model.subprocess.run') as run:
                        with self.assertRaisesRegex(ModelUnavailable, 'agent rules'):
                            model.generate('fixture', {}, schema)
                        run.assert_not_called()
                    self.assertEqual(len(reservations), 3)
                path.write_bytes(original)
