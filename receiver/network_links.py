"""Minute polling and atomic local evidence persistence; never modifies UniFi."""
import json
import logging
from pathlib import Path
import threading
import time

from network_evidence import load_json
from network_link_samples import observations
from network_link_state import transition
from network_native_events import capture
from network_notifications import deliver, public_status
from unifi_api import UniFiAPI

log = logging.getLogger(__name__)
INTERVAL = 60


def save(root, state):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    target = root / 'link-evidence.json'
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, separators=(',', ':')))
    temporary.replace(target)


def poll(client, root, now=None):
    now = int(time.time()) if now is None else now
    state = load_json(Path(root) / 'link-evidence.json', {})
    try:
        if not client.enabled:
            raise ValueError('UniFi integration unavailable')
        devices = client._get('stat/device').get('data')
        if not isinstance(devices, list) or not devices:
            raise ValueError('Empty controller inventory')
        rows = observations(devices, load_json(Path(root) / 'device-policy.json', {}), now)
        if not rows:
            raise ValueError('No Ethernet device observations')
        state = transition(state, rows, now)
    except Exception as exc:
        # Retain the last successful observation and all incidents on API failure.
        state.update(error=type(exc).__name__, attempted_at=now)
    if client.enabled:
        capture(client, state, now)
    save(root, state)
    try:
        deliver(root, state, now)
    except Exception:
        log.exception("FE notification persistence failed; link evidence retained")
    return state


def read_report(root, now=None):
    now = time.time() if now is None else now
    state = load_json(Path(root) / 'link-evidence.json', {})
    generated = state.get('generated')
    stale = not isinstance(generated, (int, float)) or not -60 <= now-generated <= 180
    return {'generated': generated, 'stale': stale or bool(state.get('error')),
            'error': state.get('error'), 'poll_interval_seconds': INTERVAL,
            'incidents': state.get('incidents', []), 'events': state.get('events', []),
            'observations': state.get('observations', []),
            'native': state.get('native', {}),
            'notifications': public_status(root),
            'native_event_history': 'Native controller system logs and sampled transitions are labeled separately.'}


class LinkMonitor:
    def __init__(self, db, root):
        self.db, self.root = db, root
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        def run():
            while not self.stop_event.is_set():
                try:
                    poll(UniFiAPI(self.db), self.root)
                except Exception:
                    log.exception('Ethernet evidence persistence failed')
                self.stop_event.wait(INTERVAL)
        self.thread = threading.Thread(target=run, name='ethernet-evidence', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
