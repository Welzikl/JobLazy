"""Run JobLazy with answers supplied by the user's current coding-agent chat.

No provider SDK, subprocess model, API key, or second AI account is used here.
The host agent answers private, hash-bound JSON requests while this process waits.
"""
import argparse
import base64
from contextlib import closing
import json
from pathlib import Path
import time

from jsonschema import validate
from .common import ROOT, NeedsInput, digest, read_json, write_json


class AgentResponseNeeded(NeedsInput):
    pass


class AgentModel:
    shared_rules_path = ROOT / 'joblazy/runtime-rules.md'
    instructions_path = ROOT / 'joblazy/worker-instructions.md'

    def __init__(self, exchange, *, wait_seconds=600, before_request=None):
        if not 0 <= wait_seconds <= 1800:
            raise ValueError('Agent response wait must be between 0 and 1800 seconds')
        self.exchange = Path(exchange)
        self.wait_seconds = wait_seconds
        self.before_request = before_request

    def generate(self, task, data, schema):
        # Read rules before considering a saved response, just like CodexModel.
        rules = [p.read_text(encoding='utf-8-sig') for p in
                 (self.shared_rules_path, self.instructions_path)]
        if any(not rule.strip() for rule in rules):
            raise NeedsInput('JobLazy agent rules are missing or empty')
        request = {'version': 1, 'transport': 'current-agent-chat', 'task': task,
                   'data': data, 'schema': schema, 'instructions': '\n\n'.join(rules)}
        key = digest(request)
        request_path = self.exchange / (key + '.request.json')
        response_path = self.exchange / (key + '.response.json')
        if not request_path.exists():
            if self.before_request:
                self.before_request()
            write_json(request_path, {'request_id': key, **request})
        pointer = {'request_id': key, 'request_path': str(request_path.resolve()),
                   'response_path': str(response_path.resolve())}
        pending = self.exchange / 'pending.json'
        write_json(pending, pointer)
        deadline = time.monotonic() + self.wait_seconds
        if not response_path.exists():
            print(json.dumps({'state': 'agent_response_needed', **pointer}), flush=True)
        while not response_path.exists():
            if time.monotonic() >= deadline:
                raise AgentResponseNeeded('Current chat must answer ' + str(request_path.resolve()))
            time.sleep(0.2)
        response = read_json(response_path)
        if response.get('request_id') != key:
            raise NeedsInput('Agent response belongs to a different request')
        validate(response.get('response'), schema)
        # No success is recorded until the response passes the exact schema.
        write_json(self.exchange / (key + '.accepted.json'), {'request_id': key})
        if pending.exists() and read_json(pending).get('request_id') == key:
            pending.unlink()
        return response['response']


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'runtime')
    parser.add_argument('--profile', type=Path, default=ROOT / 'local/profile.json')
    parser.add_argument('--wait-seconds', type=int, default=600)
    sub = parser.add_subparsers(dest='command', required=True)
    intake = sub.add_parser('intake', help='Preserve CV sources and request draft extraction from this chat')
    intake.add_argument('files', nargs='+', type=Path)
    confirm = sub.add_parser('confirm', help='Save the exact profile explicitly confirmed by the user')
    confirm.add_argument('review', type=Path)
    run = sub.add_parser('run', help='Use the existing verified job/CV pipeline for one saved role')
    run.add_argument('id')
    run.add_argument('--rank-only', action='store_true')
    run.add_argument('--browser-channel', choices=['msedge', 'chrome', 'chromium'], default='msedge')
    prepare = sub.add_parser('prepare', help='Open the existing assisted form workflow; never submit')
    prepare.add_argument('id')
    prepare.add_argument('--reviewed-cv-sha256', required=True)
    prepare.add_argument('--browser-channel', choices=['msedge', 'chrome', 'chromium'], default='msedge')
    sub.add_parser('tracker', help='Export the existing canonical opportunity tracker')
    args = parser.parse_args(argv)
    data = args.data.resolve()
    model = AgentModel(data / 'agent-exchange', wait_seconds=args.wait_seconds)
    if args.command == 'intake':
        from .onboarding import create_draft
        from .locking import run_lock
        if args.profile.exists():
            raise NeedsInput('A profile already exists. Review it instead of importing another person.')
        files = [{'name': p.name, 'content': base64.b64encode(p.read_bytes()).decode()}
                 for p in args.files]
        with run_lock(data / 'run.lock'):
            result = create_draft(data, files, model)
            output = data / 'agent-intake.json'
            write_json(output, result)
        result = {'draft_path': str(output), 'id': result['id'], 'status': 'draft'}
    elif args.command == 'confirm':
        from .onboarding import confirm_draft
        result = confirm_draft(data, args.profile, read_json(args.review))
    elif args.command == 'run':
        from datetime import datetime, timezone
        from playwright.sync_api import sync_playwright
        from .limits import DAILY_REQUESTS
        from .locking import run_lock
        from .pipeline import run_queue
        from .profiles import load_profile
        from .review import render_review
        from .store import Store
        with run_lock(data / 'run.lock'), closing(Store(data / 'jobs.sqlite')) as store:
            model.before_request = lambda: store.reserve_model_request(
                datetime.now(timezone.utc).date().isoformat(), DAILY_REQUESTS)
            profile = load_profile(args.profile)
            with sync_playwright() as pw:
                options = {'headless': True}
                if args.browser_channel != 'chromium':
                    options['channel'] = args.browser_channel
                browser = pw.chromium.launch(**options)
                try:
                    result = run_queue(store, profile, model, browser, data / 'applications', 1,
                                       only=args.id, rank_only=args.rank_only, profile_path=args.profile)
                finally:
                    browser.close()
            render_review(store, data, profile=profile)
    elif args.command == 'prepare':
        from .assist import run_assisted
        result = run_assisted(data, args.id, args.profile, browser_channel=args.browser_channel,
                              reviewed_cv_sha256=args.reviewed_cv_sha256, host_agent=True)
    else:
        from .dashboard import tracker_csv
        data.mkdir(parents=True, exist_ok=True)
        output = data / 'opportunities.csv'
        output.write_text(tracker_csv(data), encoding='utf-8-sig')
        result = {'tracker': str(output)}
    print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
    if args.command == 'run' and any(r['status'] not in ('ranked', 'not_selected', 'materials_ready') for r in result):
        return 2
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (NeedsInput, ValueError, OSError) as error:
        print(json.dumps({'state': 'needs_attention', 'message': str(error)}), flush=True)
        raise SystemExit(2)
