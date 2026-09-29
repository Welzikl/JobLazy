"""An OS lock, not a stale lock-file heuristic. Released even if the process dies."""
import os
from pathlib import Path
from contextlib import contextmanager


class LockBusy(RuntimeError):
    """Another process owns the lock; this is normal coordination, not failure."""

@contextmanager
def run_lock(path):
    path = Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as file:
        file.seek(0,2)
        if file.tell() == 0: file.write(b'0'); file.flush()
        file.seek(0)
        if os.name == 'nt':
            import msvcrt
            lock = lambda: msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
            unlock = lambda: msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            lock = lambda: fcntl.flock(file,fcntl.LOCK_EX|fcntl.LOCK_NB)
            unlock = lambda: fcntl.flock(file,fcntl.LOCK_UN)
        try: lock()
        except OSError as e: raise LockBusy('Another JobLazy run is active') from e
        try: yield
        finally: file.seek(0); unlock()
