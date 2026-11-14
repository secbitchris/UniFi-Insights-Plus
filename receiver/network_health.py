"""Single writer for bounded network-health checks and seven-day history.

Uses the existing UniFi configuration. Never changes controller settings, calls
AbuseIPDB, or runs speed tests. Independent DNS probes survive API failure.
"""
import json
import logging
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit

from unifi_api import UniFiAPI
import network_inventory
import network_radio
import network_dns
import network_reachability
import network_evidence

log = logging.getLogger(__name__)
INTERVAL = 300
MAX_AGE = 900
ROOT = Path(os.environ.get('NETWORK_HEALTH_DIR', '/app/data/network-health'))
CONTROLLER_CHECKS = (
    'Devices online', 'STP root bridge', 'STP priorities', 'AP transmit health',
    'AP load', 'Channel plan', 'DFS radar vacates', 'Client eviction margin',
    'SSID beacon cost', 'Channel utilisation', 'Switch port errors',
    'RF interference (sustained)', 'Broadcast storm (forensic)', 'Loop-risk port protection',
)


def write_json(path, data):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, separators=(',', ':')))
    os.replace(tmp, path)


def read_snapshot(root=ROOT, now=None):
    now = time.time() if now is None else now
    try:
        data = json.loads((Path(root) / 'health.json').read_text())
    except (OSError, ValueError):
        return {'status': 'unavailable', 'stale': True, 'checks': [], 'generated': None}
    age = now - data.get('generated', 0)
    data['age_seconds'] = max(0, age)
    data['stale'] = age > MAX_AGE or age < -60
    data['status'] = 'stale' if data['stale'] else 'current'
    return data


def collect(client, root=ROOT, dns_assess=network_dns.assess):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    checks = []
    dev = sta = wlan = []
    controller_error = None
    policies = network_evidence.load_json(root / "device-policy.json", {})
    now = int(time.time())
    device_rows = []
    try:
        if not client.enabled:
            raise ValueError('UniFi integration unavailable')
        values = [client._get(path).get('data') for path in
                  ('stat/device', 'stat/sta', 'rest/wlanconf')]
        if not all(isinstance(v, list) for v in values) or not values[0]:
            raise ValueError('Empty or invalid controller inventory')
        dev, sta, wlan = values
        try:
            expected = json.loads((root / 'expected.json').read_text())
        except (OSError, ValueError):
            expected = {}
        checks.extend(network_inventory.assess(dev, sta, wlan, expected, str(root), policies))
        checks.extend(network_radio.assess(dev, sta, wlan, expected, str(root)))
        port_check, port_samples = network_evidence.port_errors(dev, network_evidence.load_json(root / 'port-counters.json', {}), now)
        checks.append(port_check)
        write_json(root / 'port-counters.json', port_samples)
        device_rows = network_evidence.device_records(dev, policies, client.host, client.site, now)
        if not expected:
            for check in checks:
                if check['title'] == 'Channel plan':
                    check.update(severity='unknown', detail='No channel plan has been configured.')
        # Missing inventory is absence of coverage, not proof of health.
        for check in checks:
            needs_switch = check['title'] in ('STP root bridge', 'STP priorities', 'Switch port errors', 'Broadcast storm (forensic)', 'Loop-risk port protection')
            if (needs_switch and not any(d.get('type') == 'usw' for d in dev)) or (not needs_switch and check['title'] != 'Devices online' and not any(d.get('type') == 'uap' for d in dev)):
                check.update(severity='unknown', detail='No applicable devices returned by the controller.')
    except Exception as exc:
        controller_error = type(exc).__name__
        checks = [{'title': title, 'severity': 'unknown', 'detail': 'Controller assessment unavailable (' + controller_error + ').', 'items': []} for title in CONTROLLER_CHECKS]

    def static_records():
        if controller_error:
            raise ValueError('Controller unavailable')
        prefix = '/proxy/network' if client._controller_type == 'unifi_os' else ''
        url = client.host + prefix + '/v2/api/site/' + client.site + '/static-dns'
        response = client._get_session().get(url, timeout=10)
        response.raise_for_status()
        records = response.json()
        if not isinstance(records, list) or len(records) > 64:
            raise ValueError('Unsupported static DNS response')
        return records

    host = urlsplit(client.host).hostname if client.host else None
    if host:
        try:
            checks.extend(dns_assess(host, str(root), static_records))
        except Exception as exc:
            checks.append({'title': 'DNS probes', 'severity': 'unknown', 'detail': 'Probe failure (' + type(exc).__name__ + ').', 'items': []})
    else:
        checks.append({'title': 'DNS probes', 'severity': 'unknown', 'detail': 'No gateway configured.', 'items': []})
    now = int(time.time())
    watch = {}
    try:
        watchlist = json.loads((root / 'watchlist.json').read_text())
    except (OSError, ValueError):
        watchlist = {}
    clients = {c.get('mac'): c for c in sta}
    names = {d.get('mac'): d.get('name') for d in dev}
    for mac, label in watchlist.items():
        c = clients.get(mac)
        watch[mac] = {'label': label, 'status': 'unknown' if controller_error else ('present' if c else 'absent')}
        if c:
            watch[mac].update(ap=names.get(c.get('ap_mac')), signal=c.get('signal'), channel=c.get('channel'), uptime=c.get('uptime'))
    speedtests = [d['speedtest-status'] for d in dev if d.get('speedtest-status', {}).get('rundate')]
    states, events = network_evidence.annotate(checks, device_rows, network_evidence.load_json(root / 'check-states.json', {}), now)
    write_json(root / 'check-states.json', states)
    previous_events = network_evidence.load_json(root / 'events.json', [])
    write_json(root / 'events.json', [e for e in previous_events if now - 7*86400 <= e['at'] <= now][-1000:] + events)
    out = {'devices': device_rows, 'generated': now, 'controller_error': controller_error, 'checks': checks, 'watch': watch,
           'speedtests': [{k: s.get(k) for k in ('rundate', 'xput_download', 'xput_upload', 'latency')} for s in speedtests],
           'inventory': {'aps': sum(d.get('type') == 'uap' for d in dev), 'switches': sum(d.get('type') == 'usw' for d in dev), 'clients': len(sta)}}
    out['counts'] = {s: sum(c['severity'] == s for c in checks) for s in ('critical', 'warning', 'unknown', 'info', 'ok')}
    write_json(root / 'health.json', out)
    try:
        history = json.loads((root / 'history.json').read_text())
    except (OSError, ValueError):
        history = []
    history = [h for h in history if now - 7 * 86400 <= h.get('generated', 0) <= now][-2015:]
    # Summary history excludes raw controller responses and credentials.
    history.append({k: out[k] for k in ('generated', 'counts', 'watch', 'speedtests')})
    history[-1]['checks'] = [{'title': c['title'], 'severity': c['severity']} for c in checks]
    write_json(root / 'history.json', history)
    return out


class NetworkHealth:
    def __init__(self, db):
        self.db = db
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        def run():
            while not self.stop_event.is_set():
                try:
                    collect(UniFiAPI(self.db))
                    write_json(ROOT / "reachability.json", network_reachability.collect(ROOT))
                except Exception:
                    log.exception('Network health collection failed')
                self.stop_event.wait(INTERVAL)
        self.thread = threading.Thread(target=run, name='network-health', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=3)
