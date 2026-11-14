"""Durable, bounded delivery of new FE incidents through an operator-set route."""
import json
from pathlib import Path
import time
from urllib.parse import urlsplit
import requests
from network_evidence import load_json

MAX_ATTEMPTS = 5


def save(path, data):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, separators=(',', ':')))
    temp.replace(path)


def message(incident, app_url):
    samples = incident.get('samples') or []
    port = samples[0].get('port', {}) if samples else {}
    parent = samples[0].get('parent', {}) if samples else {}
    return (f"{incident['name']}: Ethernet dropped to {incident['trigger_speed_mbps']} Mbps "
            f"(expected {incident['expected_mbps']} Mbps). "
            f"Uplink: {parent.get('name', 'unknown')} port {port.get('port_idx', '?')}. "
            f"Evidence saved. Inspect it before rebooting. {app_url}")


def send(config, incident):
    url = config['url']
    if urlsplit(url).scheme not in ('http', 'https'):
        raise ValueError('Unsupported notification URL')
    app_url = config.get('app_url', '')
    text = message(incident, app_url)
    headers = {}
    if config.get('token'):
        headers['Authorization'] = 'Bearer ' + config['token']
    with requests.Session() as session:
        session.trust_env = False
        if config['kind'] == 'ntfy':
            headers.update(Title='Ethernet speed drop', Priority='high', Tags='warning',
                           Click=app_url)
            response = session.post(url, data=text.encode(), headers=headers, timeout=10,
                                    allow_redirects=False)
        elif config['kind'] == 'home_assistant_webhook':
            response = session.post(url, json={'title': 'Ethernet speed drop', 'message': text,
                                    'incident_id': incident['id'], 'url': app_url},
                                    headers=headers, timeout=10, allow_redirects=False)
        else:
            raise ValueError('Unsupported notification route')
        try:
            if not 200 <= response.status_code < 300:
                raise RuntimeError('Notification endpoint rejected delivery')
        finally:
            response.close()


def deliver(root, report, now=None, sender=send):
    now = int(time.time()) if now is None else now
    root = Path(root)
    config = load_json(root / 'notification-config.json', {})
    path = root / 'notification-state.json'
    state = load_json(path, {})
    if not config.get('enabled'):
        state.update(status='disabled', armed=False)
        save(path, state)
        return state
    if not state.get('armed'):
        # Never replay incidents that predate enabling/re-enabling notifications.
        state = {'enabled_at': now, 'armed': True, 'deliveries': {}, 'status': 'enabled'}
        save(path, state)
    deliveries = state.setdefault('deliveries', {})
    incidents = {x['id']: x for x in report.get('incidents', [])
                 if x.get('detected_at', 0) > state['enabled_at']}
    deliveries = {k:v for k,v in deliveries.items() if k in incidents}
    state['deliveries'] = deliveries
    for identity, incident in incidents.items():
        if identity not in deliveries:
            deliveries[identity] = {'attempts': 0, 'next_at': now, 'status': 'pending'}
    state['status'] = 'enabled'
    # Persist discovery before external delivery; one attempt per collector tick.
    save(path, state)
    for identity, item in deliveries.items():
        if item['status'] != 'pending' or item['next_at'] > now:
            continue
        item.update(attempts=item['attempts']+1, next_at=now+min(3600,60*2**item['attempts']))
        save(path, state)
        try:
            sender(config, incidents[identity])
            item.update(status='sent', sent_at=now)
            item.pop('error', None)
        except Exception as exc:
            item['error'] = type(exc).__name__
            if item['attempts'] >= MAX_ATTEMPTS:
                item['status'] = 'failed'
        save(path, state)
        break
    return state


def public_status(root):
    state = load_json(Path(root) / 'notification-state.json', {})
    rows = list(state.get('deliveries', {}).values())
    return {'status': state.get('status', 'disabled'),
            'sent': sum(x['status']=='sent' for x in rows),
            'pending': sum(x['status']=='pending' for x in rows),
            'failed': sum(x['status']=='failed' for x in rows)}
