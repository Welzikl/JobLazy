import io
import json
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from joblazy.store import Store
from joblazy.common import write_json
from .support import example_profile,job


class RunLimitTests(unittest.TestCase):
    def test_rank_only_run_clamps_the_batch_to_remaining_daily_job_attempts(self):
        import joblazy.__main__ as cli
        with tempfile.TemporaryDirectory() as directory:
            data=Path(directory);profile=data/'profile.json'
            write_json(profile,example_profile())
            store=Store(data/'jobs.sqlite')
            try:
                for index in range(8):
                    key=store.ingest(job(f'https://example.test/attempt-{index}'))
                    store.transition(key,'processing')
            finally:store.close()
            class Playwright:
                chromium=None
                def __init__(self):self.chromium=self
                def __enter__(self):return self
                def __exit__(self,*args):return False
                def launch(self,**kwargs):return types.SimpleNamespace(close=lambda:None)
            class Model:
                def __init__(self,*args,**kwargs):self.before_request=kwargs.get('before_request')
            playwright=types.ModuleType('playwright');sync_api=types.ModuleType('playwright.sync_api')
            sync_api.sync_playwright=lambda:Playwright()
            limits=[]
            def process(store,profile,model,browser,applications,limit,**kwargs):
                limits.append(limit);return []
            with patch.dict(sys.modules,{'playwright':playwright,'playwright.sync_api':sync_api}), \
                 patch.object(sys,'argv',['joblazy','--data',str(data),'run','--profile',str(profile),'--rank-only','--limit','5','--daily-jobs','10']), \
                 patch.object(cli,'CodexModel',Model),patch.object(cli,'run_queue',side_effect=process):
                cli.main()
            self.assertEqual(limits,[2])

    def test_rank_only_run_reserves_an_uncached_model_request_before_queue_processing(self):
        import joblazy.__main__ as cli
        with tempfile.TemporaryDirectory() as directory:
            data=Path(directory);profile=data/'profile.json'
            write_json(profile,example_profile())
            store=Store(data/'jobs.sqlite');store.ingest(job('https://example.test/one-off-limit'));store.close()
            class Playwright:
                chromium=None
                def __init__(self):self.chromium=self
                def __enter__(self):return self
                def __exit__(self,*args):return False
                def launch(self,**kwargs):return types.SimpleNamespace(close=lambda:None)
            class Model:
                def __init__(self,*args,**kwargs):self.before_request=kwargs.get('before_request')
            playwright=types.ModuleType('playwright');sync_api=types.ModuleType('playwright.sync_api')
            sync_api.sync_playwright=lambda:Playwright()
            def process(store,profile,model,*args,**kwargs):
                self.assertIsNotNone(model.before_request)
                model.before_request()
                return []
            with patch.dict(sys.modules,{'playwright':playwright,'playwright.sync_api':sync_api}), \
                 patch.object(sys,'argv',['joblazy','--data',str(data),'run','--profile',str(profile),'--rank-only','--limit','1']), \
                 patch.object(cli,'CodexModel',Model),patch.object(cli,'run_queue',side_effect=process):
                cli.main()
            store=Store(data/'jobs.sqlite')
            try:self.assertEqual(store.daily_usage(__import__('datetime').datetime.now(__import__('datetime').timezone.utc).date().isoformat())['model_requests'],1)
            finally:store.close()

    def test_rank_only_run_stops_before_browser_when_daily_request_budget_is_exhausted(self):
        import joblazy.__main__ as cli
        with tempfile.TemporaryDirectory() as directory:
            data=Path(directory);profile=data/'profile.json'
            write_json(profile,example_profile())
            store=Store(data/'jobs.sqlite')
            try:
                for _ in range(50):store.reserve_model_request(__import__('datetime').datetime.now(__import__('datetime').timezone.utc).date().isoformat(),50)
            finally:store.close()
            launched=[]
            class Playwright:
                chromium=None
                def __init__(self):self.chromium=self
                def __enter__(self):return self
                def __exit__(self,*args):return False
                def launch(self,**kwargs):
                    launched.append(kwargs)
                    return types.SimpleNamespace(close=lambda:None)
            playwright=types.ModuleType('playwright');sync_api=types.ModuleType('playwright.sync_api')
            sync_api.sync_playwright=lambda:Playwright()
            output=io.StringIO()
            with patch.dict(sys.modules,{'playwright':playwright,'playwright.sync_api':sync_api}), \
                 patch.object(sys,'argv',['joblazy','--data',str(data),'run','--profile',str(profile),'--rank-only','--limit','1']), \
                 patch.object(cli,'run_queue',return_value=[]) as run_queue, redirect_stdout(output):
                cli.main()
            result=json.loads(output.getvalue())
            self.assertEqual(result['state'],'daily_limit')
            self.assertEqual(result['results'],[])
            self.assertEqual(launched,[])
            run_queue.assert_not_called()


if __name__=='__main__':unittest.main()
