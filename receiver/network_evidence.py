"""Evidence and lifecycle metadata for network health, without controller writes."""
import json
from pathlib import Path
from urllib.parse import quote


GUIDANCE = {
    'Devices online': ('Expected devices should report to the controller. Intentionally offline and retired inventory stay visible separately.', 'Check power, uplink and last-seen time. Use intentionally offline for planned shutdowns; retired only for removed devices.'),
    'STP root bridge': ('An unexpected spanning-tree root can change switching paths.', 'Inspect the root device and switch priorities in UniFi.'),
    'STP priorities': ('Switch priorities determine which device becomes the spanning-tree root.', 'Compare intended root and backup priorities before making changes.'),
    'AP transmit health': ('This compares each AP with its own recent baseline, not other AP models.', 'Wait for baseline coverage; investigate a sustained drop before power cycling.'),
    'AP load': ('Load limits vary by hardware model.', 'Compare with this AP’s history and connected clients.'),
    'Channel plan': ('Only enabled radios with a reported channel can be checked for drift.', 'Inspect the affected radio and intended plan. Disabled radios are not drift.'),
    'DFS radar vacates': ('Configured and reported channel differences may follow radar avoidance.', 'Inspect radio events and channel history; this check alone does not prove radar.'),
    'Client eviction margin': ('Clients close to minimum RSSI may disconnect or roam.', 'Inspect that client’s signal and AP placement before adjusting RSSI.'),
    'SSID beacon cost': ('Low minimum rates use more airtime but can support older IoT devices.', 'Review client compatibility before raising minimum rates.'),
    'Channel utilisation': ('High airtime use can reflect your own traffic; it does not prove interference.', 'Compare the trend and active clients before changing channels.'),
    'Switch port errors': ('New errors are measured between samples. Lifetime totals remain context only.', 'Investigate rising counters on the named port; inspect cable, endpoint and link negotiation.'),
    'RF interference (sustained)': ('Sustained external airtime requires enough samples and reliable radio counters.', 'Wait for coverage or inspect spectrum evidence; missing attribution is unknown.'),
    'Broadcast storm (forensic)': ('Counter deltas can reveal a prior storm after connectivity returns.', 'Compare affected ports and time windows. This is not a prevention control.'),
    'Loop-risk port protection': ('A downstream switch without STP relies on upstream protection.', 'Inspect the named uplink and its existing storm-control configuration.'),
    'DNS resolver': ('Resolver reachability is tested independently of the UniFi API.', 'Check the gateway resolver and compare the external TCP probe.'),
    'DNS or WAN (attribution)': ('Comparing name resolution with direct TCP reachability helps narrow the fault.', 'Compare both probes and other locations; a single failed target is not proof of a WAN outage.'),
    'DNS override integrity': ('Configured A overrides are compared with actual gateway DNS answers.', 'Inspect mismatched names and resolver records in UniFi.'),
    'DNS egress policy': ('Known DNS egress restrictions are tested against a working resolver control.', 'Inspect existing policy if a probe succeeds unexpectedly; DoH is outside this check.'),
}


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def device_records(devices, policies, host, site, now):
    url = host.rstrip('/') + '/network/' + quote(site, safe='') + '/devices' if host else None
    result = []
    for device in devices:
        if device.get('type') not in ('uap', 'usw'):
            continue
        mac = (device.get('mac') or '').lower()
        policy = policies.get(mac, {})
        state = policy.get('status', 'expected')
        if state not in ('expected', 'intentionally_offline', 'retired'):
            state = 'expected'
        uplink = device.get('uplink') or {}
        parent = next((d for d in devices if d.get('mac') == uplink.get('uplink_mac')), None)
        port = next((p for p in (parent or {}).get('port_table', []) if p.get('port_idx') == uplink.get('uplink_remote_port')), {})
        own_seen = device.get('last_seen') or 0
        parent_seen = (parent or {}).get('last_seen') or 0
        use_own = isinstance(uplink.get('up'), bool) and own_seen >= parent_seen
        link = uplink if use_own else port
        seen = device.get('last_seen')
        result.append({'mac': mac, 'name': device.get('name') or mac, 'ip': device.get('ip'),
                       'model': device.get('model'), 'policy': state,
                       'policy_reason': policy.get('reason', ''),
                       'expected_speed_mbps': policy.get('expected_speed_mbps'),
                       'uplink_up': link.get('up'),
                       'uplink_speed_mbps': link.get('speed') if link.get('up') else None,
                       'uplink_observation_source': 'device' if use_own else 'parent',
                       'uplink_observed_at': own_seen if use_own else parent_seen,
                       'connected': device.get('state') == 1,
                       'last_seen': seen, 'last_seen_age_seconds': max(0, now-seen) if isinstance(seen, (float, int)) else None,
                       'unifi_url': url})
    return result


def port_errors(devices, previous, now):
    samples, evidence = {}, []
    for device in devices:
        if device.get('type') != 'usw' or device.get('state') != 1:
            continue
        for port in device.get('port_table', []):
            if not port.get('up') or 'SFP' in str(port.get('name', '')).upper():
                continue
            key = str(device.get('mac')) + ':' + str(port.get('port_idx'))
            rx, tx = port.get('rx_errors'), port.get('tx_errors')
            if not all(isinstance(v, (int, float)) and v >= 0 for v in (rx, tx)):
                continue
            total = rx + tx
            sample = {'at': now, 'errors': total, 'uptime': device.get('uptime')}
            samples[key] = sample
            old = previous.get(key, {})
            elapsed = now - old.get('at', now)
            reset = total < old.get('errors', total) or (isinstance(sample['uptime'], (int,float)) and isinstance(old.get('uptime'), (int,float)) and sample['uptime'] < old['uptime'])
            delta = total - old.get('errors', total) if 0 < elapsed <= 900 and not reset else None
            # Keep clean ports out of the table once they have a valid baseline.
            if total or delta is None:
                evidence.append({'device': device.get('name'), 'mac': device.get('mac'), 'port': port.get('port_idx'),
                                 'lifetime_errors': total, 'new_errors': delta,
                                 'interval_seconds': elapsed if delta is not None else None,
                                 'errors_per_minute': round(delta*60/elapsed, 3) if delta is not None else None,
                                 'status': 'reset' if reset else ('baseline' if delta is None else ('rising' if delta else 'stable'))})
    rising = [p for p in evidence if p['new_errors'] is not None and p['new_errors'] > 0]
    uncertain = [p for p in evidence if p['new_errors'] is None]
    positive = [p for p in evidence if p['lifetime_errors'] > 0]
    severity = 'warning' if rising else ('unknown' if uncertain or not samples else ('info' if positive else 'ok'))
    detail = (f'{len(rising)} port(s) accumulated new errors.' if rising else
              'Waiting for comparable samples; resets and gaps cannot establish an error rate.' if uncertain or not samples else
              'No new errors in the sampled interval. Lifetime totals are historical context.')
    return {'title': 'Switch port errors', 'severity': severity, 'detail': detail,
            'items': [f"{p['device']} port {p['port']}: {p['new_errors']} new / {p['lifetime_errors']} lifetime" for p in positive if p['new_errors'] is not None],
            'ports': evidence}, samples


def annotate(checks, devices, previous, now):
    states, events = {}, []
    for check in checks:
        title, severity = check['title'], check['severity']
        old = previous.get(title, {})
        changed = old.get('severity') != severity
        since = now if changed else old.get('since', now)
        last_clear = now if old.get('severity') in ('warning', 'critical') and severity == 'ok' else old.get('last_clear')
        states[title] = {'severity': severity, 'since': since, 'last_clear': last_clear}
        check.update(status_since=since, last_observed=now, last_clear=last_clear)
        why, next_step = GUIDANCE.get(title, ('Coverage is based on the latest available evidence.', 'Inspect the evidence and its timestamp.'))
        check.update(why=why, next_step=next_step)
        text = ' '.join([check.get('detail','')] + [str(x) for x in check.get('items',[])])
        check['devices'] = [d for d in devices if d['name'] in text or any(p.get('mac') == d['mac'] for p in check.get('ports', []))]
        if old and changed:
            events.append({'at': now, 'title': title, 'from': old['severity'], 'to': severity})
    return states, events
