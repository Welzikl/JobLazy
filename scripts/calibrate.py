"""Small real-model calibration batch. Does not open employer application forms."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from joblazy.common import ROOT,read_json,write_json
from joblazy.model import CodexModel
from joblazy.store import Store
from joblazy.pipeline import run_queue,plain_text
from joblazy.locking import run_lock

parser=argparse.ArgumentParser();parser.add_argument('jobs');parser.add_argument('--profile',default='local/profile.json')
parser.add_argument('--output',default='runtime/calibration');args=parser.parse_args()
output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=True)
with run_lock(output/'run.lock'),sync_playwright() as pw:
    store=Store(output/'queue.sqlite');browser=pw.chromium.launch(channel='chrome',headless=True)
    try:
        for job in read_json(args.jobs):
            job['description']=plain_text(job['description']);store.ingest(job)
        result=run_queue(store,read_json(args.profile),CodexModel(output/'model-cache'),browser,output,limit=3)
        report={'model':'gpt-5.6-terra','live_model':True,'employer_forms_opened':False,'results':result}
        write_json(output/'report.json',report);print(json.dumps(report,indent=2))
    finally:store.close();browser.close()
