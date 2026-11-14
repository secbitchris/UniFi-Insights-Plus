"""Persistent blacklist freshness and backoff, serialized across app processes."""
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
import fcntl
import json
import os
from pathlib import Path
import time

FRESH_SECONDS = 86400
RETRY_SECONDS = 3600


def persist(path, state):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state))
    temp.replace(path)


@contextmanager
def attempt():
    root = Path(os.environ.get('NETWORK_HEALTH_DIR', '/app/data/network-health'))
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'blacklist-download.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = root / 'blacklist-download.json'
        try:
            state = json.loads(path.read_text())
        except FileNotFoundError:
            state = {}
        # Corrupt state fails closed through caller's exception handling.
        now = time.time()
        if now < state.get('next_attempt', 0) or now < state.get('last_success', 0) + FRESH_SECONDS:
            yield None
            return
        state.update(last_attempt=now, next_attempt=now + RETRY_SECONDS, status='attempting')
        persist(path, state)
        yield path, state


def completed(ticket, count):
    path, state = ticket
    now = time.time()
    state.update(last_success=now, next_attempt=now+FRESH_SECONDS,
                 status='ok', count=count)
    persist(path, state)


def rate_limited(ticket, headers):
    path, state = ticket
    now = time.time()
    # With no usable provider header, wait for the next UTC reset.
    until = (int(now)//86400+1)*86400
    retry = headers.get('Retry-After')
    try:
        if retry is not None:
            until = max(until, now+float(retry))
    except (TypeError, ValueError):
        try:
            until = max(until, parsedate_to_datetime(retry).timestamp())
        except (TypeError, ValueError, OverflowError):
            pass
    try:
        until = max(until, float(headers.get('X-RateLimit-Reset', 0)))
    except (TypeError, ValueError):
        pass
    state.update(next_attempt=until, status='rate_limited')
    persist(path, state)
