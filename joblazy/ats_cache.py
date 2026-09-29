"""Share identical public ATS reads during one search, including in-flight work."""
from concurrent.futures import Future
from copy import deepcopy
from threading import Lock
from .ats_postings import fetch_json


class SearchATSCache:
    def __init__(self, fetcher=None):
        self.fetcher = fetcher or fetch_json
        self.lock = Lock()
        self.requests = {}
        self.network_reads = 0
        self.cache_hits = 0

    def __call__(self, url, *, timeout=20):
        with self.lock:
            future = self.requests.get(url)
            owner = future is None
            if owner:
                future = Future()
                self.requests[url] = future
                self.network_reads += 1
            else:
                self.cache_hits += 1
        if owner:
            try: future.set_result(self.fetcher(url, timeout=timeout))
            except Exception as error:
                future.set_exception(error)
                # Failed reads are not a success cache. Waiting callers see the
                # same failure; a later explicit fallback may try the source.
                with self.lock:
                    if self.requests.get(url) is future: del self.requests[url]
        return deepcopy(future.result(timeout=timeout))
