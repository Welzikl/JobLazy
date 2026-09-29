import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from joblazy.answers import questions,save_answer
from joblazy.common import NeedsInput,write_json
from joblazy.store import Store
from .support import example_profile,job


class AnswerRefreshTests(unittest.TestCase):
    def test_preparation_refresh_preserves_other_questions_scope_and_drafts(self):
        with tempfile.TemporaryDirectory() as temp, closing(Store(Path(temp)/'jobs.sqlite')) as store:
            directory=Path(temp)
            scope='https://example.test/one';key=store.ingest(job(scope))
            store.transition(key,'needs_input')
            profile=example_profile()
            fields=[{'id':str(i),'label':label,'type':'select','options':['Yes','No'],'required':True}
                for i,label in enumerate(['Work authorization','Relocation','Consent'])]
            fields.append({'id':'draft','label':'Describe your experience','type':'textarea','required':True})
            unresolved=[{'id':f['id'],'field':f['label'],'options':f['options'],'required':True,'reason':'No unambiguous saved answer'} for f in fields[:3]]
            profile['answers']=[
                {'scope':scope,'question':'Work authorization','value':'Yes'},
                {'scope':'https://example.test/other','question':'Relocation','value':'Yes'},
                {'scope':scope,'question':'Consent','value':'Maybe'}]
            for metadata in ({'fields':fields},{'rounds':[{'plan':{'_scanMeta':fields}}]}):
                write_json(directory/'browser.json',{'scope':scope,'unresolved':unresolved,**metadata})
                before=store.list();profile_path=directory/'profile.json';write_json(profile_path,profile)
                original=profile_path.read_bytes()
                shown=questions(store,key,directory,profile)
                self.assertEqual([q['field'] for q in shown['questions']],['Relocation','Consent'])
                self.assertEqual(shown['method'],'browser_preparation')
                self.assertEqual(store.list(),before);self.assertEqual(profile_path.read_bytes(),original)
                with self.assertRaises(NeedsInput):save_answer(store,key,directory,profile_path,'Work authorization','Maybe')
                self.assertEqual(profile_path.read_bytes(),original)
            # Without scan metadata, retain the old report rather than guessing.
            write_json(directory/'browser.json',{'scope':scope,'unresolved':unresolved})
            self.assertEqual(questions(store,key,directory,profile)['questions'],unresolved)


if __name__=='__main__':unittest.main()
