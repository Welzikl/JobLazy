"""Bound handoff cleanup so a stalled browser acknowledgement cannot own the batch."""
import asyncio
from pathlib import Path
from playwright.sync_api import Error as BrowserError
from .common import write_json


def release_routes(page,directory,timeout=5):
    if page.is_closed():return True
    try:
        # The pinned Playwright sync API exposes no timeout for unroute_all.
        # Use its existing sync bridge; never start a second event loop/thread.
        page._sync(asyncio.wait_for(page._impl_obj.unroute_all(behavior='ignoreErrors'),timeout))
        result={'state':'complete'}
    except (TimeoutError,BrowserError) as error:
        result={'state':'pending','reason':'Browser route cleanup did not complete',
                'error_type':type(error).__name__,'browser_must_remain_serviced':True}
    write_json(Path(directory)/'route-cleanup.json',result)
    return result['state']=='complete'
