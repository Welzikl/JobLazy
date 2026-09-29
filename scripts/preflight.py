"""Check local prerequisites without inference or exposing sign-in details."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def installed_browser():
    roots = [Path(value) for key in ('PROGRAMFILES(X86)', 'PROGRAMFILES', 'LOCALAPPDATA')
             if (value := os.environ.get(key))]
    for channel, relative in [('msedge', 'Microsoft/Edge/Application/msedge.exe'),
                              ('chrome', 'Google/Chrome/Application/chrome.exe')]:
        if any((root/relative).is_file() for root in roots): return channel
    return None


def check():
    errors, warnings = [], []
    if sys.version_info < (3, 12): errors.append('Install Python 3.12 or later, then rerun Setup.cmd.')
    for package in ('playwright', 'jsonschema', 'pypdf', 'PyYAML', 'phonenumberslite'):
        try: importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError: errors.append(f'Missing dependency {package}; run Setup.cmd.')
    node_version = None
    node = shutil.which('node')
    try:
        if node:
            result = subprocess.run([node, '--version'], capture_output=True, text=True, timeout=10)
            node_version = result.stdout.strip()
            if result.returncode or int(node_version.lstrip('v').split('.')[0]) < 22:
                errors.append('Install Node.js 22 or later from nodejs.org.')
        else: errors.append('Install Node.js 22 or later from nodejs.org.')
    except (OSError, ValueError, subprocess.TimeoutExpired): errors.append('Node.js could not be checked; install version 22 or later.')
    browser = installed_browser()
    if not browser: errors.append('Install Microsoft Edge or Google Chrome, then retry.')
    signed_in = False
    if not any('Missing dependency' in error for error in errors):
        from joblazy.model import CodexModel
        model = CodexModel(ROOT/'runtime/model-cache', model='gpt-6-luna')
        if not model.executable:
            errors.append('Install Codex desktop/CLI using https://learn.chatgpt.com/docs/quickstart, then retry.')
        else:
            signed_in = bool(model.status()['available'])
            if not signed_in: warnings.append('Codex needs sign-in. Use Connect Codex in JobLazy; no API key is required.')
    warnings.append('Sign-in does not prove Luna access or remaining allowance. The first bounded operation checks actual inference.')
    return {'ok': not errors, 'python': '.'.join(map(str,sys.version_info[:3])), 'node': node_version,
            'browser': browser, 'preset': 'friend', 'model': 'gpt-6-luna', 'signed_in': signed_in,
            'errors': errors, 'warnings': warnings}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--json', action='store_true')
    args = parser.parse_args(); report = check()
    if args.json: print(json.dumps(report))
    else:
        print('JobLazy prerequisite check: '+('ready' if report['ok'] else 'needs attention'))
        for message in report['errors'] + report['warnings']: print('- '+message)
    raise SystemExit(0 if report['ok'] else 1)
