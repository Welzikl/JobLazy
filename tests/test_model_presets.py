import sys
import unittest
from unittest.mock import patch

from joblazy.model_presets import model_preset


class ModelPresetTests(unittest.TestCase):
    def test_unknown_preset_fails_without_fallback(self):
        with self.assertRaises(ValueError):
            model_preset('unknown')

    def test_cli_forwards_friend_preset_to_dashboard(self):
        from joblazy.__main__ import main
        with patch.object(sys, 'argv', ['joblazy', 'dashboard', '--preset', 'friend', '--no-open']), \
             patch('joblazy.dashboard.serve') as serve:
            main()
        self.assertEqual(serve.call_args.kwargs['model_preset_name'], 'friend')
