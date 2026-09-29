"""Read-only form inventory: no candidate profile, filling, uploading or submission."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from joblazy.browser import public_url, scan
from joblazy.forms import open_application_form, application_url
from joblazy.common import write_json

parser=argparse.ArgumentParser(); parser.add_argument('url'); parser.add_argument('--output',required=True)
args=parser.parse_args()
if not public_url(args.url): raise SystemExit('Only public HTTPS application URLs are supported')
with sync_playwright() as pw:
    browser=pw.chromium.launch(channel='chrome',headless=True)
    try:
        page=browser.new_page()
        page.goto(application_url(args.url),wait_until='domcontentloaded',timeout=45000)
        form=open_application_form(page,timeout=20)
        fields=scan(form)
        write_json(args.output,{'url':page.url,'form_url':form.url,'fields':fields})
        print(f'Observed {len(fields)} form controls; no profile data sent')
    finally: browser.close()
