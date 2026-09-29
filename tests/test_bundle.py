import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from pypdf import PdfWriter
from joblazy.bundle import bundle_review
from joblazy.uploads import cv_filename
from joblazy.checkpoints import save_materials
from joblazy.common import NeedsInput,digest,write_json
from joblazy.store import Store
from .support import example_profile,job


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name);self.profile=example_profile()
        self.store=Store(self.data/'jobs.sqlite');self.addCleanup(self.store.close)

    def material(self,label,score,status='materials_ready',pdf_bytes=None):
        posting=job('https://example.test/'+label,title=label)
        key=self.store.ingest(posting);directory=self.data/'applications'/key
        directory.mkdir(parents=True)
        writer=PdfWriter();writer.add_blank_page(width=595,height=842)
        stream=io.BytesIO();writer.write(stream)
        pdf_bytes=stream.getvalue() if pdf_bytes is None else pdf_bytes
        (directory/'cv.pdf').write_bytes(pdf_bytes)
        (directory/'cv.html').write_text('<p>Fictional CV</p>',encoding='utf-8')
        write_json(directory/'cv.json',{'fictional':True})
        write_json(directory/'material.json',{'job_hash':digest(posting),'review':{'supported':True,'issues':[]},
            'claims':[{'text':self.profile['resume']['summary'],'source_ids':['summary']}]})
        ranking={'score':score,'eligible':True,'reason':'Fictional supported assessment','missing_facts':[]}
        write_json(directory/'ranking.json',ranking)
        artifact={'path':str(directory/'cv.pdf'),'sha256':digest(pdf_bytes),'pages':1}
        write_json(directory/'artifact.json',artifact)
        save_materials(directory,posting,posting,self.profile,ranking,artifact)
        self.store.transition(key,status,{'ranking':ranking,'artifact':artifact})
        return key,directory

    def test_portable_selection_verifies_bytes_and_never_changes_manual_ownership(self):
        lower,_=self.material('lower',75)
        high,directory=self.material('high',95,'manual_review')
        unsafe,_=self.material('unsafe',99)
        self.store.transition(unsafe,'submitting');self.store.transition(unsafe,'submission_unknown')
        before=self.store.list()
        report=bundle_review(self.store,self.data,self.profile,1)
        self.assertEqual(report['included'],1);self.assertEqual(report['available'],2)
        with zipfile.ZipFile(report['path']) as archive:
            manifest=json.loads(archive.read('manifest.json'))
            self.assertEqual([o['id'] for o in manifest['options']],[high])
            self.assertEqual(manifest['options'][0]['status'],'manual_review')
            self.assertEqual(archive.read('cvs/'+high+'/'+cv_filename(self.profile,self.store.get(high)['data'])),(directory/'cv.pdf').read_bytes())
            html=archive.read('index.html').decode('utf-8')
            self.assertIn('href="cvs/'+high+'/'+cv_filename(self.profile,self.store.get(high)['data'])+'"',html)
            self.assertNotIn('file://',html)
            self.assertIn('Automatic retries are paused',html)
            self.assertNotIn(lower,html);self.assertNotIn(unsafe,html)
            self.assertEqual(archive.testzip(),None)
        self.assertEqual(self.store.list(),before)

    def test_stale_profile_and_changed_files_cannot_replace_good_export(self):
        key,directory=self.material('one',90)
        output=Path(bundle_review(self.store,self.data,self.profile)['path']);saved=output.read_bytes()
        changed=copy.deepcopy(self.profile);changed['minimum_score']=71
        with self.assertRaisesRegex(NeedsInput,'No current verified'):bundle_review(self.store,self.data,changed)
        self.assertEqual(output.read_bytes(),saved)
        (directory/'cv.html').write_text('modified',encoding='utf-8')
        with self.assertRaisesRegex(NeedsInput,'No current verified'):bundle_review(self.store,self.data,self.profile)
        self.assertEqual(output.read_bytes(),saved)

    def test_partial_bundle_reports_missing_materials_and_does_not_copy_private_extras(self):
        good,directory=self.material('good',90)
        bad,changed=self.material('changed',99)
        (changed/'cv.pdf').write_bytes(b'modified')
        (directory/'secret.txt').write_text('NEVER EXPORT ME',encoding='utf-8')
        report=bundle_review(self.store,self.data,self.profile,20)
        self.assertEqual((report['requested'],report['included'],report['available']),(20,1,1))
        self.assertEqual([x['id'] for x in report['excluded']],[bad])
        with zipfile.ZipFile(report['path']) as archive:
            self.assertEqual(set(archive.namelist()),{'index.html','manifest.json','README.txt','cvs/'+good+'/'+cv_filename(self.profile,self.store.get(good)['data'])})

    def test_pdf_page_count_and_atomic_failure_preserve_prior_export(self):
        key,directory=self.material('good',90)
        output=Path(bundle_review(self.store,self.data,self.profile)['path']);before=output.read_bytes()
        with patch('joblazy.bundle.render_review',side_effect=OSError('Injected render failure')):
            with self.assertRaises(OSError):bundle_review(self.store,self.data,self.profile)
        self.assertEqual(output.read_bytes(),before)
        writer=PdfWriter();writer.add_blank_page(width=595,height=842);writer.add_blank_page(width=595,height=842)
        stream=io.BytesIO();writer.write(stream)
        self.material('two-pages-with-false-metadata',99,pdf_bytes=stream.getvalue())
        with self.assertRaisesRegex(NeedsInput,'not one page'):bundle_review(self.store,self.data,self.profile)
        self.assertEqual(output.read_bytes(),before)

    def test_cli_requires_profile_and_exports_without_model_or_browser_setup(self):
        self.material('cli',90);profile=self.data/'profile.json';write_json(profile,self.profile)
        def run(*args):
            return subprocess.run([sys.executable,'-m','joblazy','--data',str(self.data),'review','--bundle',*args],
                capture_output=True,text=True,timeout=15)
        missing=run();self.assertNotEqual(missing.returncode,0);self.assertIn('requires --profile',missing.stderr)
        result=run('--profile',str(profile),'--limit','20');self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['included'],1)

if __name__=='__main__':unittest.main()
