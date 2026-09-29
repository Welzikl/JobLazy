import json
import subprocess
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from joblazy.common import read_json,write_json
from joblazy.common import ROOT
from joblazy.coverage import audit_rows
from joblazy.pipeline import discover
from joblazy.source_registry import record_sources
from joblazy.store import Store
from .support import job


class SourceRegistryTests(unittest.TestCase):
    def test_actual_scanner_records_unsupported_source_without_network_or_false_success(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp);boards=data/'boards.json';checkpoint=data/'scan.json'
            write_json(boards,{'boards':[{'name':'Unsupported','provider':'fictional_missing_provider'},
                {'name':'Disabled','provider':'ashby','enabled':False}]})
            result=subprocess.run(['node',str(ROOT/'scripts/scan.mjs'),str(boards),str(checkpoint)],
                cwd=ROOT,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
            saved=read_json(checkpoint);self.assertEqual(saved,json.loads(result.stdout))
            self.assertEqual(len(saved['source_runs']),1);self.assertEqual(saved['source_runs'][0]['status'],'failed')
            self.assertEqual(saved['jobs'],[]);self.assertIn('Unsupported',saved['errors'][0]['board'])

    def test_discovery_records_new_ids_partial_warnings_and_failure_history(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            data=Path(temp);entry={'name':'London query','provider':'fixture','q':'London'}
            checkpoint=data/'last-scan.json';boards=data/'boards.json';write_json(boards,{'boards':[entry]})
            posting=job('https://example.test/one')
            def response(status,rows,stderr=''):
                source={'entry':entry,'started_at':'2026-09-12T00:00:00Z','finished_at':'2026-09-12T00:01:00Z',
                    'status':status,'urls':[j['url'] for j in rows],'warnings':[stderr] if stderr else []}
                if status=='failed':source['error']='429'
                return SimpleNamespace(returncode=0,stderr=stderr,stdout=json.dumps({'jobs':rows,'errors':[],'source_runs':[source]}))
            with patch('joblazy.pipeline.subprocess.run',return_value=response('completed',[posting,posting])):
                result=discover(boards,store,checkpoint)
            self.assertEqual(result['new_unique_jobs'],1);self.assertEqual(result['discovered'],2)
            key=store.list()[0]['id'];store.transition(key,'manual_review');before=store.get(key)
            with patch('joblazy.pipeline.subprocess.run',return_value=response('completed_with_warnings',[{**posting,'description':'Changed'}],'Truncated at page cap')):
                result=discover(boards,store,checkpoint)
            self.assertEqual(result['new_unique_jobs'],0);self.assertEqual(store.get(key),before)
            self.assertIn('Truncated',result['warnings'][0]);self.assertIn('warnings',read_json(checkpoint))
            with patch('joblazy.pipeline.subprocess.run',return_value=response('failed',[])):
                discover(boards,store,checkpoint)
            registry=read_json(data/'source-registry.json');saved=next(iter(registry['sources'].values()))
            self.assertEqual(saved['last_successful_scan'],'2026-09-12T00:01:00Z')
            self.assertEqual(saved['seen_job_ids'],[key]);self.assertEqual(saved['last_status'],'failed')
            self.assertEqual(saved['last_error'],'429')
            audit=audit_rows(store.list(),boards={'boards':[entry]},source_registry=registry)
            self.assertEqual(audit['source_registry'][0]['last_status'],'failed')

    def test_interrupted_query_does_not_replace_last_success_or_other_source_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'sources.json'
            entries=[{'name':'One','q':'operations'},{'name':'Two','q':'London'}]
            runs=[{'entry':e,'status':'completed','finished_at':'2026-09-12','urls':['https://example.test/job']} for e in entries]
            first=record_sources(path,runs,set())
            result=record_sources(path,[{'entry':entries[0],'status':'in_progress','urls':[]}],set())
            self.assertEqual(len(result['sources']),2)
            for saved in result['sources'].values():
                self.assertEqual(saved['last_successful_scan'],'2026-09-12');self.assertEqual(len(saved['seen_job_ids']),1)


if __name__=='__main__':unittest.main()
