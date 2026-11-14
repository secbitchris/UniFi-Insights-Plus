"""Allowlisted Ethernet observations. No raw controller payloads or credentials."""
from network_evidence import device_records

DEVICE_FIELDS = ('mac', 'name', 'model', 'version', 'state', 'uptime', 'last_seen')
PORT_FIELDS = ('port_idx', 'name', 'up', 'speed', 'full_duplex', 'autoneg',
               'rx_errors', 'tx_errors', 'rx_dropped', 'tx_dropped',
               'rx_packets', 'tx_packets', 'rx_bytes', 'tx_bytes',
               'link_down_count', 'poe_good', 'poe_mode', 'poe_power',
               'stp_state')
COUNTERS = ('rx_errors', 'tx_errors', 'rx_dropped', 'tx_dropped', 'link_down_count')


def pick(value, fields):
    return {k: value[k] for k in fields if k in value}


def fresh(seen, now):
    return isinstance(seen, (int, float)) and not isinstance(seen, bool) and -60 <= now-seen <= 180


def observations(devices, policies, now):
    devices = devices[:256]
    by_mac = {d.get('mac'): d for d in devices}
    records = device_records(devices, policies, '', 'default', now)
    out = []
    for record in records:
        d = by_mac.get(record['mac'], {})
        link = d.get('uplink') or {}
        parent = by_mac.get(link.get('uplink_mac'), {})
        port = next((p for p in parent.get('port_table', [])
                     if p.get('port_idx') == link.get('uplink_remote_port')), {})
        local = next((p for p in d.get('port_table', [])
                      if p.get('port_idx') == link.get('port_idx')), link)
        connected = (True if fresh(d.get('last_seen'), now) else None) if d.get('state') == 1 else False
        valid = connected is True and fresh(record['uplink_observed_at'], now)
        speed = record['uplink_speed_mbps'] if valid else None
        out.append({'mac': record['mac'], 'name': record['name'], 'at': now,
                    'policy': record['policy'], 'expected_mbps': record['expected_speed_mbps'],
                    'connected': connected, 'speed_mbps': speed,
                    'link_up': record['uplink_up'] if valid else None,
                    'observation_source': record['uplink_observation_source'],
                    'observed_at': record['uplink_observed_at'],
                    'path': [parent.get('mac'), port.get('port_idx')],
                    'device': pick(d, DEVICE_FIELDS), 'parent': pick(parent, DEVICE_FIELDS),
                    'reported_uplink': pick(link, PORT_FIELDS),
                    'local_port': pick(local, PORT_FIELDS), 'port': pick(port, PORT_FIELDS)})
    return out


def counter_deltas(previous, current):
    result = {}
    elapsed = current['at'] - previous.get('at', current['at'])
    for endpoint, owner in (('local_port', 'device'), ('port', 'parent')):
        old, new = previous.get(endpoint, {}), current.get(endpoint, {})
        status = 'measured'
        if previous.get('path') != current['path']:
            status = 'path changed'
        elif not 0 < elapsed <= 180:
            status = 'gap'
        elif not fresh(previous.get(owner, {}).get('last_seen'), previous.get('at', 0)) or not fresh(current[owner].get('last_seen'), current['at']):
            status = 'unavailable'
        elif current[owner].get('last_seen', 0) <= previous.get(owner, {}).get('last_seen', 0):
            status = 'no new observation'
        else:
            old_up, new_up = previous.get(owner, {}).get('uptime'), current[owner].get('uptime')
            if isinstance(old_up, (int, float)) and isinstance(new_up, (int, float)) and new_up < old_up:
                status = 'reset'
            elif any(isinstance(old.get(k), (int, float)) and isinstance(new.get(k), (int, float)) and new[k] < old[k] for k in COUNTERS):
                status = 'reset'
        values = {}
        if status == 'measured':
            values = {k: new[k]-old[k] for k in COUNTERS
                      if isinstance(old.get(k), (int, float)) and isinstance(new.get(k), (int, float))}
        result[endpoint] = {'status': status, 'seconds': elapsed, 'counters': values}
    return result
