import asyncio,tempfile,json,time,unittest
from pathlib import Path
from playwright.sync_api import sync_playwright
from joblazy.route_cleanup import release_routes


class RouteCleanupTests(unittest.TestCase):
    def test_stalled_acknowledgement_is_bounded_and_keeps_existing_page(self):
        with tempfile.TemporaryDirectory() as temp,sync_playwright() as pw:
            browser=pw.chromium.launch(channel='chrome',headless=True)
            try:
                page=browser.new_page();page.set_content('<input value="operator edit">')
                original=page._impl_obj.unroute_all
                async def stalled(**kwargs):await asyncio.Event().wait()
                page._impl_obj.unroute_all=stalled
                started=time.monotonic()
                self.assertFalse(release_routes(page,temp,timeout=.1))
                self.assertLess(time.monotonic()-started,2)
                self.assertFalse(page.is_closed())
                self.assertEqual(page.locator('input').input_value(),'operator edit')
                result=json.loads((Path(temp)/'route-cleanup.json').read_text())
                self.assertEqual(result['state'],'pending')
                page._impl_obj.unroute_all=original
                self.assertTrue(release_routes(page,temp))
                self.assertEqual(json.loads((Path(temp)/'route-cleanup.json').read_text())['state'],'complete')
            finally:browser.close()
