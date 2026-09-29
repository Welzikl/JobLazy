import tempfile
import unittest
import io
from pathlib import Path
from unittest.mock import patch
import json

from joblazy.common import read_json, write_json
from joblazy.store import choice_job_hash


def case(key, split='development'):
    return {'id':key,'split':split,'category':'adjacent','job':{
        'url':f'https://example.test/{key}','company':'Example','title':key,
        'location':'London, United Kingdom','description':'A complete role description.'}}


class CalibrationJudgmentTests(unittest.TestCase):
    def test_records_a_user_judgment_in_a_new_hash_bound_dataset(self):
        from joblazy.calibration import record_judgment
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'cases.json';output=Path(temp)/'labeled.json'
            write_json(source,{'version':1,'cases':[case('development'),case('holdout','holdout')]})
            result=record_judgment(source,output,'development',True,'I would pursue this role.','full description review',
                                   recorded_at='2026-09-14T12:00:00+00:00')
            saved=read_json(output);judgment=saved['cases'][0]['judgment']
            self.assertEqual(result['id'],'development')
            self.assertEqual(judgment['worthwhile'],True)
            self.assertEqual(judgment['job_hash'],choice_job_hash(saved['cases'][0]['job']))
            self.assertEqual(judgment['source'],{'kind':'user','quote':'I would pursue this role.',
                'basis':'full description review','recorded_at':'2026-09-14T12:00:00+00:00'})
            self.assertNotIn('judgment',saved['cases'][1])
            self.assertEqual(read_json(source)['cases'][0].get('judgment'),None)

    def test_rejects_holdout_overwrite_and_empty_user_evidence(self):
        from joblazy.calibration import record_judgment
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'cases.json';output=Path(temp)/'labeled.json'
            write_json(source,{'version':1,'cases':[case('development'),case('holdout','holdout')]})
            with self.assertRaisesRegex(ValueError,'development'):
                record_judgment(source,output,'holdout',False,'No.','full description review')
            with self.assertRaisesRegex(ValueError,'quote'):
                record_judgment(source,output,'development',False,' ','full description review')
            record_judgment(source,output,'development',False,'No.','full description review')
            with self.assertRaisesRegex(ValueError,'already'):
                record_judgment(output,Path(temp)/'second.json','development',True,'Actually yes.','full description review')
            with self.assertRaisesRegex(ValueError,'different'):
                record_judgment(source,source,'development',True,'Yes.','full description review')

    def test_explicit_supersede_preserves_an_older_judgment_in_new_version(self):
        from joblazy.calibration import record_judgment
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'cases.json';first=Path(temp)/'first.json';second=Path(temp)/'second.json'
            write_json(source,{'version':1,'cases':[case('development')]})
            record_judgment(source,first,'development',True,'Short role summary: yes.','short summary')
            result=record_judgment(first,second,'development',False,'Full description: no.','full description review',supersede=True)
            saved=read_json(second)['cases'][0]
            self.assertTrue(result['superseded'])
            self.assertEqual(saved['judgment']['source']['basis'],'full description review')
            self.assertEqual(saved['judgment_history'][0]['source']['basis'],'short summary')

    def test_cli_writes_a_development_label_without_opening_queue_state(self):
        from joblazy.__main__ import main
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'cases.json';output=Path(temp)/'labeled.json';stdout=io.StringIO()
            write_json(source,{'version':1,'cases':[case('development')]})
            argv=['joblazy','record-judgment',str(source),'development','--output',str(output),
                  '--decision','worthwhile','--quote','Worth pursuing.','--basis','full description card']
            with patch('sys.argv',argv),patch('sys.stdout',stdout):main()
            self.assertTrue(output.exists())
            self.assertEqual(json.loads(stdout.getvalue())['worthwhile'],True)
            self.assertFalse((Path(temp)/'jobs.sqlite').exists())
