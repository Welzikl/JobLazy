"""Exercise real Chromium and PDF rendering against a local fictional employer."""
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from joblazy.common import ROOT, write_json
from joblazy.store import Store
from joblazy.pipeline import run_queue
from tests.support import fixture_server, example_profile, FixtureModel, job

output=ROOT/'runtime/demo'
output.mkdir(parents=True,exist_ok=True)
with fixture_server() as (origin,received), sync_playwright() as pw:
    browser_name=os.environ.get('JOBLAZY_TEST_BROWSER_CHANNEL','chrome')
    launch={'headless':True}
    if browser_name!='chromium':launch['channel']=browser_name
    browser=pw.chromium.launch(**launch)
    store=Store(output/'jobs.sqlite')
    try:
        for mode in ('success','unknown','redirect','disappear','embedded','autofill','multistep','multistep_unknown','ambiguous'): store.ingest(job(origin+'/'+mode))
        results=run_queue(store,example_profile(),FixtureModel(),browser,output,10,
            prepare=True,submit=True,fixture_origin=origin,verify_seconds=1)
        report={'model':'FixtureModel — canned test outputs, NOT live Codex inference',
            'browser':'Installed Chrome driven by Playwright','external_applications':0,
            'results':results,'local_server_requests':[{'path':r['path'],'bytes':len(r['body']),
            'contains_pdf':b'%PDF-' in r['body']} for r in received]}
        write_json(output/'report.json',report)
        print(json.dumps(report,indent=2))
    finally: store.close(); browser.close()
