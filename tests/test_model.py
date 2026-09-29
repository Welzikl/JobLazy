import json
import copy
import os
import jsonschema
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from joblazy.common import ROOT, NeedsInput, ModelUnavailable, InvalidModelOutput, write_json, read_json, digest
from joblazy.model import CodexModel, CodexWebSearch, find_codex_executable, shared_enum_schema
from joblazy.materials import obj, rank
from joblazy.pipeline import run_queue
from joblazy.store import Store
from .support import example_profile, job, FixtureModel

class ModelTests(unittest.TestCase):
    def test_reasoning_effort_is_explicit_and_separates_cached_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = []
            def cli(args, **kwargs):
                if args[1] == 'login': return subprocess.CompletedProcess(args, 0, 'Logged in', '')
                calls.append(args)
                write_json(args[args.index('--output-last-message') + 1], {'value': 'ok'})
                return subprocess.CompletedProcess(args, 0, '', '')
            schema = obj({'value': {'type': 'string'}})
            with patch('joblazy.model.subprocess.run', side_effect=cli):
                for effort in ('low', 'medium', 'low'):
                    CodexModel(temp, executable='fixture', reasoning_effort=effort).generate('fixture', {}, schema)
            self.assertEqual(len(calls), 2)
            self.assertIn('model_reasoning_effort="low"', calls[0])
            self.assertIn('model_reasoning_effort="medium"', calls[1])
            with self.assertRaises(ValueError): CodexModel(temp, reasoning_effort='invalid')

    def test_search_routing_is_luna_with_explicit_overrides_and_no_ordinary_model_change(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertEqual(CodexModel(temp).model, 'gpt-5.6-terra')
            self.assertEqual(CodexWebSearch(temp).model, 'gpt-6-luna')
            self.assertEqual(CodexWebSearch(temp, model='chosen-model').model, 'chosen-model')
            self.assertEqual(CodexWebSearch(temp, 'positional-model').model, 'positional-model')

    def test_search_event_validation_counts_all_queries_and_rejects_unproved_actions(self):
        def event(action): return {'type': 'web_search', 'action': action}
        with tempfile.TemporaryDirectory() as temp:
            model = CodexWebSearch(temp, max_search_calls=2, max_queries=4)
            valid = [event({'type': 'search', 'queries': ['a', 'b', 'c']}),
                     event({'type': 'search', 'query': 'd'})]
            self.assertEqual(model.validate_search_events(valid), {'search_calls': 2, 'queries': 4})
            for events in ([], valid + valid, [event({'type': 'search', 'queries': ['a'] * 5})],
                           [event({'type': 'open_page', 'url': 'https://example.test'})],
                           [event(None)], [event({'type': 'search'})],
                           [event({'type': 'search', 'queries': 'abc'})],
                           [event({'type': 'search', 'queries': ['']})],
                           [event({'type': 'search', 'queries': [None]})]):
                with self.subTest(events=events), self.assertRaises(ModelUnavailable):
                    model.validate_search_events(events)
            with self.assertRaises(ModelUnavailable): CodexWebSearch(temp).validate_search_events(valid)

    def test_search_budget_is_in_prompt_cache_identity_and_retained_observation(self):
        schema = obj({'value': {'type': 'string'}})
        events = [{'type': 'item.completed', 'item': {'type': 'web_search',
                   'action': {'type': 'search', 'queries': ['a', 'b']}}}] * 2
        with tempfile.TemporaryDirectory() as temp:
            reservations = []
            model = CodexWebSearch(temp, executable='fixture', max_search_calls=2, max_queries=4,
                                   before_request=lambda: reservations.append(1))
            def cli(args, **kwargs):
                if args[1] == 'login': return subprocess.CompletedProcess(args, 0, 'Logged in', '')
                self.assertEqual(args[args.index('--model') + 1], 'gpt-6-luna')
                self.assertIn('SEARCH BUDGET:', kwargs['input'])
                write_json(args[args.index('--output-last-message') + 1], {'value': 'ok'})
                return subprocess.CompletedProcess(args, 0, '\n'.join(map(json.dumps, events)), '')
            with patch('joblazy.model.subprocess.run', side_effect=cli):
                self.assertEqual(model.generate('fixture', {}, schema), {'value': 'ok'})
                model.generate('fixture', {}, schema)
                strict = CodexWebSearch(temp, executable='fixture', before_request=lambda: reservations.append(1))
                with self.assertRaises(ModelUnavailable): strict.generate('fixture', {}, schema)
            self.assertEqual(len(reservations), 2)
            requests = [read_json(p) for p in (Path(temp) / 'requests').glob('*.json')]
            self.assertEqual(len(requests), 2)
            self.assertEqual({r['search_budget']['max_queries'] for r in requests}, {3, 4})
            evidence = [read_json(p) for p in (Path(temp) / 'search-evidence').glob('*.json')]
            self.assertEqual(len(evidence), 2)
            self.assertTrue(all(e['enforcement'] == 'post_execution_validation' for e in evidence))
            self.assertTrue(all(len(e['events']) == 2 for e in evidence))

    def test_invalid_search_budget_is_rejected_without_inference(self):
        for field in ('max_search_calls', 'max_queries'):
            for value in (0, -1, True, 1.5, '3'):
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    CodexWebSearch('unused', **{field: value})

    def test_finds_desktop_codex_when_path_has_no_command(self):
        with tempfile.TemporaryDirectory() as temp:
            executable = Path(temp) / 'OpenAI' / 'Codex' / 'bin' / 'build-a' / 'codex.exe'
            executable.parent.mkdir(parents=True); executable.write_text('fixture')
            with patch.dict(os.environ, {'LOCALAPPDATA': temp}, clear=False), patch('joblazy.model.shutil.which', return_value=None):
                self.assertEqual(find_codex_executable(), str(executable))

    def test_exact_request_survives_success_cache_replay_and_timeout(self):
        for timeout in (False,True):
            with self.subTest(timeout=timeout),tempfile.TemporaryDirectory() as temp:
                model=CodexModel(temp,executable='fixture-codex')
                task='Rank a fictional posting';data={'text':'Fictional evidence','application_url':'https://example.test/observed/apply'}
                schema=obj({'value':{'type':'string'}})
                def cli(args,**kwargs):
                    if args[1]=='login':return subprocess.CompletedProcess(args,0,'Logged in','')
                    paths=list((Path(temp)/'requests').glob('*.json'))
                    self.assertEqual(len(paths),1)
                    request=read_json(paths[0])
                    self.assertEqual(paths[0].stem,digest(request))
                    self.assertEqual(request['task'],task);self.assertEqual(request['data'],data)
                    self.assertEqual(request['schema'],schema);self.assertEqual(request['model'],model.model)
                    self.assertEqual(json.loads(kwargs['input'].split('\nINPUT JSON:',1)[1]),request['data'])
                    self.assertIn('\nTASK: '+request['task']+'\n',kwargs['input'])
                    if timeout:raise subprocess.TimeoutExpired(args,1)
                    write_json(args[args.index('--output-last-message')+1],{'value':'ok'})
                    return subprocess.CompletedProcess(args,0,'','')
                with patch('joblazy.model.subprocess.run',side_effect=cli):
                    if timeout:
                        with self.assertRaises(ModelUnavailable):model.generate(task,data,schema)
                    else:
                        self.assertEqual(model.generate(task,data,schema),{'value':'ok'})
                paths=list((Path(temp)/'requests').glob('*.json'));self.assertEqual(len(paths),1)
                original=paths[0].read_bytes()
                if not timeout:
                    with patch('joblazy.model.subprocess.run') as run:
                        self.assertEqual(model.generate(task,data,schema),{'value':'ok'})
                        run.assert_not_called()
                    self.assertEqual(paths[0].read_bytes(),original)
                calls=[read_json(p) for p in (Path(temp)/'calls').rglob('*.json')]
                self.assertTrue(all(c['input_key']==paths[0].stem for c in calls))

    def test_missing_and_schema_invalid_answers_are_technical_with_private_evidence(self):
        for missing in (True,False):
            with self.subTest(missing=missing),tempfile.TemporaryDirectory() as temp:
                def cli(args,**kwargs):
                    if args[1]=='login':return subprocess.CompletedProcess(args,0,'Logged in','')
                    if not missing:write_json(args[args.index('--output-last-message')+1],{'value':123})
                    return subprocess.CompletedProcess(args,0,'[]\n'+json.dumps({'type':'turn.completed','usage':{'output_tokens':5}}),'')
                model=CodexModel(temp,executable='fixture-codex')
                with patch('joblazy.model.subprocess.run',side_effect=cli),self.assertRaises(InvalidModelOutput) as raised:
                    model.generate('fixture',{},obj({'value':{'type':'string'}}))
                self.assertNotIsInstance(raised.exception,NeedsInput)
                evidence=read_json(raised.exception.evidence_path)
                self.assertEqual(evidence['usage']['output_tokens'],5)
                self.assertEqual(evidence['response_text'] is None,missing)
                self.assertEqual(len([p for p in Path(temp).glob('*.json') if not p.name.endswith('.invalid.json')]),0)

    def test_corrupt_cache_is_retained_and_never_passed_as_valid_output(self):
        with tempfile.TemporaryDirectory() as temp:
            model=CodexModel(temp,executable='fixture-codex');schema=obj({'value':{'type':'string'}})
            def cli(args,**kwargs):
                if args[1]=='login':return subprocess.CompletedProcess(args,0,'Logged in','')
                write_json(args[args.index('--output-last-message')+1],{'value':'ok'})
                return subprocess.CompletedProcess(args,0,'','')
            with patch('joblazy.model.subprocess.run',side_effect=cli):model.generate('fixture',{},schema)
            cached=next(p for p in Path(temp).glob('*.json') if not p.name.endswith('.meta.json'))
            cached.write_text('corrupt fictional cache',encoding='utf-8')
            with patch('joblazy.model.subprocess.run') as run,self.assertRaises(InvalidModelOutput) as raised:
                model.generate('fixture',{},schema)
            run.assert_not_called();self.assertEqual(cached.read_text(),'corrupt fictional cache')
            evidence=read_json(raised.exception.evidence_path)
            self.assertEqual(evidence['stage'],'cached response');self.assertIsNone(evidence['usage'])

    def test_shared_ranking_enums_preserve_every_source_constraint(self):
        class Capture(FixtureModel):
            def generate(self,task,data,schema):
                self.schema=schema;self.response=super().generate(task,data,schema)
                return self.response
        profile=example_profile();profile['facts']=[{'text':f'Fictional sourced fact {i}.'} for i in range(50)]
        capture=Capture();rank(job('https://example.test/schema'),profile,capture)
        original=copy.deepcopy(capture.schema);shared=shared_enum_schema(original)
        self.assertEqual(original,capture.schema)
        self.assertLess(len(json.dumps(shared)),len(json.dumps(original))*0.7)
        jsonschema.Draft202012Validator.check_schema(shared)
        variants=[capture.response]
        for name in original['properties']['dimensions']['properties']:
            bad=copy.deepcopy(capture.response);bad['dimensions'][name]['candidate_source_ids']=['invented.source'];variants.append(bad)
        for target in ('candidate_source_ids','requirements'):
            bad=copy.deepcopy(capture.response)
            if target=='requirements':bad[target][0]['candidate_source_ids']=['invented.source']
            else:bad[target]=['invented.source']
            variants.append(bad)
        for value in variants:
            self.assertEqual(jsonschema.Draft202012Validator(original).is_valid(value),jsonschema.Draft202012Validator(shared).is_valid(value))
        self.assertTrue(jsonschema.Draft202012Validator(shared).is_valid(variants[0]))
        self.assertTrue(all(not jsonschema.Draft202012Validator(shared).is_valid(v) for v in variants[1:]))

    def test_shared_enums_preserve_existing_definitions_and_other_constraints(self):
        values=[f'fictional.source.{i}' for i in range(30)];enum={'type':'string','enum':values}
        schema=obj({'a':enum,'b':copy.deepcopy(enum),'c':{'$ref':'#/$defs/joblazy_enum_1'},
            'd':{**copy.deepcopy(enum),'pattern':'0$'}})
        schema['$defs']={'joblazy_enum_1':{'type':'integer'}}
        before=copy.deepcopy(schema);shared=shared_enum_schema(schema)
        self.assertEqual(schema,before);self.assertEqual(shared['$defs']['joblazy_enum_1'],{'type':'integer'})
        for data in ({'a':values[0],'b':values[1],'c':3,'d':values[0]},
                     {'a':values[0],'b':values[1],'c':'3','d':values[0]},
                     {'a':values[0],'b':values[1],'c':3,'d':values[1]}):
            self.assertEqual(jsonschema.Draft202012Validator(schema).is_valid(data),jsonschema.Draft202012Validator(shared).is_valid(data))

    def test_transport_uses_shared_schema_and_keeps_existing_cache_identity(self):
        enum={'type':'string','enum':[f'fictional.source.{i}' for i in range(50)]}
        schema=obj({'a':enum,'b':copy.deepcopy(enum)});value={'a':enum['enum'][0],'b':enum['enum'][1]}
        def transport(args,**kwargs):
            if args[1]=='login':return subprocess.CompletedProcess(args,0,'Logged in','')
            sent=read_json(args[args.index('--output-schema')+1]);self.assertIn('$defs',sent)
            jsonschema.validate(value,sent)
            write_json(args[args.index('--output-last-message')+1],value)
            return subprocess.CompletedProcess(args,0,'','')
        with tempfile.TemporaryDirectory() as temp:
            model=CodexModel(temp,executable='codex-test');data={'text':'fictional'}
            legacy_key=digest({'task':'test','data':data,'schema':schema,'model':model.model,'version':2,
                'compact':True,'instructions':digest((ROOT/'joblazy/worker-instructions.md').read_bytes())})
            write_json(Path(temp)/(legacy_key+'.json'),value)
            with patch('joblazy.model.subprocess.run') as run:
                self.assertEqual(model.generate('test',data,schema),value);run.assert_not_called()
            with patch('joblazy.model.subprocess.run',side_effect=transport):
                self.assertEqual(model.generate('new task',data,schema),value)
            meta=next(Path(temp).glob('*.meta.json'))
            self.assertLess(read_json(meta)['transport_schema_chars'],read_json(meta)['validation_schema_chars'])

    def test_missing_login_never_invokes_inference(self):
        with tempfile.TemporaryDirectory() as temp:
            model=CodexModel(temp,executable='codex-test')
            with patch('joblazy.model.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','Not logged in')) as run:
                with self.assertRaises(ModelUnavailable): model.generate('test',{},obj({'value':{'type':'string'}}))
                self.assertEqual(run.call_count,1)
                self.assertEqual(run.call_args.args[0][1:],['login','status'])
    def test_schema_cache_and_stdin_contract(self):
        with tempfile.TemporaryDirectory() as temp:
            model=CodexModel(temp,executable='codex-test')
            def fake(args,**kwargs):
                if args[1]=='login': return subprocess.CompletedProcess(args,0,'Logged in','')
                self.assertIn('--sandbox',args); self.assertIn('read-only',args)
                self.assertEqual(args[-1],'-'); self.assertIn('private test input',kwargs['input'])
                self.assertNotIn('private test input',' '.join(args))
                write_json(Path(args[args.index('--output-last-message')+1]),{'value':'ok'})
                return subprocess.CompletedProcess(args,0,'','')
            schema=obj({'value':{'type':'string'}})
            reservations=[];model.before_request=lambda:reservations.append('reserved')
            with patch('joblazy.model.subprocess.run',side_effect=fake) as run:
                self.assertEqual(model.generate('test',{'text':'private test input'},schema),{'value':'ok'})
                self.assertEqual(model.generate('test',{'text':'private test input'},schema),{'value':'ok'})
                self.assertEqual(run.call_count,2)
                self.assertEqual(reservations,['reserved'])
    def test_global_model_pause_preserves_queue(self):
        class Unavailable:
            def generate(self,*args): raise ModelUnavailable('Login needed')
        with tempfile.TemporaryDirectory() as temp:
            store=Store(Path(temp)/'queue.sqlite')
            try:
                for n in range(3): store.ingest(job(f'https://example.test/{n}'))
                with patch('joblazy.discovery.enrich',side_effect=lambda job,*args,**kwargs:job):
                    result=run_queue(store,example_profile(),Unavailable(),None,temp,10)
                self.assertEqual(len(result),1)
                self.assertEqual(sorted(r['status'] for r in store.list()),['discovered','discovered','retryable'])
            finally: store.close()
