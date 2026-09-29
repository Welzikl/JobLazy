import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from joblazy.common import ROOT


def script(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


public=script('check-public');vendor=script('verify-vendor')


class ReleaseTests(unittest.TestCase):
    def test_nested_source_export_cannot_pass_a_zero_file_git_audit(self):
        runtime=ROOT/'runtime';runtime.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=runtime) as temp:
            root=Path(temp);(root/'app.py').write_text('print("fictional")',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'source-tree'):public.audit(root)
            result=public.audit(root,source_tree=True)
            self.assertEqual(result['checked_files'],1);self.assertEqual(result['failures'],[])

    def test_empty_tree_and_private_directories_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with self.assertRaisesRegex(ValueError,'No source files'):public.audit(root,source_tree=True)
            (root/'app.py').write_text('# source',encoding='utf-8')
            (root/'local').mkdir();(root/'local'/'token.txt').write_text('private',encoding='utf-8')
            (root/'.hermes').mkdir();(root/'.hermes'/'session.json').write_text('private',encoding='utf-8')
            result=public.audit(root,source_tree=True)
            self.assertTrue(any(f[0]=='local' for f in result['failures']))
            self.assertTrue(any(f[0]=='.hermes' for f in result['failures']))

    def test_export_can_check_private_values_without_containing_the_profile(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'source';root.mkdir()
            (root/'app.py').write_text('# example sensitive person',encoding='utf-8')
            profile=Path(temp)/'private.json'
            profile.write_text(json.dumps({'resume':{'candidate':{'name':'Example Sensitive Person'}}}),encoding='utf-8')
            result=public.audit(root,source_tree=True,private_profile=profile)
            self.assertTrue(result['private_profile_checked']);self.assertEqual(len(result['failures']),1)

    def test_vendor_verifier_detects_changed_and_extra_files_without_rewriting_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for name,kind in [('personal-jobpilot','gitBlob'),('career-ops','sha256')]:
                directory=root/'vendor'/name;directory.mkdir(parents=True)
                raw=b'Fixture license';(directory/'LICENSE').write_bytes(raw)
                value=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() if kind=='gitBlob' else hashlib.sha256(raw).hexdigest()
                (root/'vendor'/f'{name}-source.json').write_text(json.dumps({'files':[{'path':'LICENSE',kind:value}]}),encoding='utf-8')
            self.assertTrue(all(r['license_retained'] and not r['hash_mismatches'] for r in vendor.verify(root)))
            manifest=root/'vendor/career-ops-source.json';before=manifest.read_bytes()
            (root/'vendor/career-ops/LICENSE').write_text('Changed',encoding='utf-8')
            (root/'vendor/career-ops/extra.py').write_text('# Extra',encoding='utf-8')
            result=vendor.verify(root)[1]
            self.assertEqual(result['hash_mismatches'],['LICENSE']);self.assertEqual(result['extra'],['extra.py'])
            self.assertEqual(manifest.read_bytes(),before)
