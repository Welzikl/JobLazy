import json
import subprocess
import tempfile
import unittest
from contextlib import closing,nullcontext
from pathlib import Path
from unittest.mock import patch
from joblazy.common import ROOT,read_json,write_json
from joblazy.pipeline import discover
from joblazy.store import Store
from joblazy.worker import Worker
from .support import job,example_profile,FixtureModel


class ScanRecoveryTests(unittest.TestCase):
    def test_short_search_deadline_retains_completed_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp) / 'jobs.sqlite')) as store:
            root = Path(temp); boards = root / 'boards.json'; checkpoint = root / 'checkpoint.json'
            write_json(boards, {'boards': []})
            def timeout(args, **kwargs):
                self.assertEqual(kwargs['timeout'], 45)
                write_json(checkpoint, {'jobs': [job('https://example.test/partial')], 'errors': [], 'source_runs': []})
                raise subprocess.TimeoutExpired(args, 45)
            with patch('joblazy.pipeline.subprocess.run', side_effect=timeout):
                result = discover(boards, store, checkpoint, timeout=45)
            self.assertEqual(result['new_unique_jobs'], 1)
            self.assertIn('time budget exceeded', result['errors'][-1]['error'])

    def test_actual_node_exit_retains_completed_work_and_worker_restart_does_not_rescan(self):
        with tempfile.TemporaryDirectory() as temp:
            data=Path(temp);profile=data/'profile.json';boards=data/'boards.json'
            write_json(profile,example_profile())
            write_json(boards,{'boards':[{'name':'Completed','provider':'ashby'},
                {'name':'Interrupted','provider':'ashby'}]})
            script=r'''
                import ashby from './scripts/ashby.mjs';
                const [boards,checkpoint,posting]=process.argv.slice(1);
                ashby.fetch=async(entry)=>{
                    if(entry.name==='Interrupted')process.exit(23);
                    return [JSON.parse(posting)];
                };
                process.argv=['node','scan.mjs',boards,checkpoint];
                await import('./scripts/scan.mjs');
            '''
            real_run=subprocess.run
            def scanner_process(args,**kwargs):
                return real_run(['node','--input-type=module','-e',script,args[2],args[3],
                    json.dumps(job('https://example.test/completed'))],cwd=ROOT,**kwargs)
            def worker():return Worker(data,profile,boards,rank_only=True,clock=lambda:1720000000,
                browser_factory=lambda:nullcontext(None),model_factory=lambda _:FixtureModel())
            with (patch('joblazy.pipeline.subprocess.run',side_effect=scanner_process) as scans,
                  patch('joblazy.discovery.enrich',side_effect=lambda p,*a,**k:p)):
                first=worker().tick();second=worker().tick()
            self.assertEqual(scans.call_count,1)
            self.assertEqual(first['scan']['new_unique_jobs'],1)
            self.assertEqual(first['results'][0]['status'],'ranked')
            self.assertIn('23',first['scan']['errors'][-1]['error'])
            self.assertIsNone(second['scan']);self.assertEqual(second['results'],[])
            self.assertEqual(second['state'],'idle')
            registry=read_json(data/'source-registry.json')
            self.assertEqual({r['config']['name']:r['last_status'] for r in registry['sources'].values()},
                {'Completed':'completed','Interrupted':'interrupted'})

    def test_timeout_uses_checkpoint_but_corrupt_checkpoint_is_not_silently_empty(self):
        for corrupt in (False,True):
            with self.subTest(corrupt=corrupt),tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
                data=Path(temp);boards=data/'boards.json';checkpoint=data/'scan.json';write_json(boards,{'boards':[]})
                def timeout(args,**kwargs):
                    if corrupt:checkpoint.write_text('{broken',encoding='utf-8')
                    else:write_json(checkpoint,{'jobs':[job('https://example.test/retained')],'errors':[],'source_runs':[]})
                    raise subprocess.TimeoutExpired(args,600)
                with patch('joblazy.pipeline.subprocess.run',side_effect=timeout):
                    if corrupt:
                        with self.assertRaisesRegex(RuntimeError,'checkpoint is unreadable'):discover(boards,store,checkpoint)
                        self.assertEqual(store.list(),[])
                    else:
                        result=discover(boards,store,checkpoint)
                        self.assertEqual(result['new_unique_jobs'],1)
                        self.assertIn('time budget exceeded',result['errors'][-1]['error'])

    def test_no_checkpoint_does_not_claim_recovered_results(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            boards=Path(temp)/'boards.json';write_json(boards,{'boards':[]})
            with patch('joblazy.pipeline.subprocess.run',return_value=subprocess.CompletedProcess([],23,'','Fictional failure')):
                with self.assertRaises(RuntimeError) as caught:discover(boards,store)
            self.assertIn('23',str(caught.exception));self.assertNotIn('retained',str(caught.exception))

    def test_process_exit_during_write_preserves_previous_complete_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            checkpoint=Path(temp)/'scan.json';old={'jobs':[job('https://example.test/first')],'errors':[],'source_runs':[]}
            write_json(checkpoint,old)
            script=r'''
                import fs from 'node:fs/promises';
                import {saveCheckpoint} from './scripts/scan-checkpoint.mjs';
                const original=fs.writeFile;
                fs.writeFile=async(path,value)=>{
                    await original(path,value.slice(0,12));
                    process.exit(23);
                };
                await saveCheckpoint(process.argv[1],{jobs:[{url:'https://example.test/second'}],errors:[]});
            '''
            result=subprocess.run(['node','--input-type=module','-e',script,str(checkpoint)],cwd=ROOT,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode,23,result.stderr)
            self.assertEqual(read_json(checkpoint),old)

    def test_nonzero_scanner_exit_retains_completed_source_and_marks_active_source_interrupted(self):
        with tempfile.TemporaryDirectory() as temp,closing(Store(Path(temp)/'jobs.sqlite')) as store:
            boards=Path(temp)/'boards.json';checkpoint=Path(temp)/'last-scan.json'
            write_json(boards,{'boards':[]})
            posting=job('https://example.test/completed')
            first={'name':'Completed fictional source','provider':'fixture'}
            second={'name':'Interrupted fictional source','provider':'fixture'}
            def crash(args,**kwargs):
                write_json(checkpoint,{'jobs':[posting],'errors':[],
                    'source_runs':[{'entry':first,'status':'completed','urls':[posting['url']],
                        'finished_at':'2026-09-14T12:00:00Z'},
                        {'entry':second,'status':'in_progress','urls':[]}]})
                return subprocess.CompletedProcess(args,23,'','Fictional scanner crash')
            with patch('joblazy.pipeline.subprocess.run',side_effect=crash):result=discover(boards,store,checkpoint)
            self.assertEqual(result['new_unique_jobs'],1)
            self.assertIn('23',result['errors'][-1]['error'])
            sources=list(read_json(Path(temp)/'source-registry.json')['sources'].values())
            complete=next(r for r in sources if r['config']==first)
            interrupted=next(r for r in sources if r['config']==second)
            self.assertEqual(complete['last_successful_scan'],'2026-09-14T12:00:00Z')
            self.assertEqual(interrupted['last_status'],'interrupted')
            self.assertIsNone(interrupted['last_successful_scan'])
