"""Bounded, persistent incident lifecycle for reported Fast Ethernet drops."""
from copy import deepcopy
from network_link_samples import counter_deltas

RETENTION = 30 * 86400
PRE_SAMPLES = 10
MAX_SAMPLES = 60
MAX_INCIDENTS = 100
MAX_EVENTS = 1000


def transition(state, rows, now):
    state = deepcopy(state)
    devices = state.setdefault('devices', {})
    incidents = [x for x in state.get('incidents', []) if now-x['detected_at'] <= RETENTION]
    events = [x for x in state.get('events', []) if now-x['at'] <= RETENTION]
    seen = set()
    current_rows = []
    for row in rows:
        mac = row['mac']
        seen.add(mac)
        saved = devices.get(mac, {})
        history = saved.get('recent', [])
        previous = history[-1] if history else {}
        row = deepcopy(row)
        row['deltas'] = counter_deltas(previous, row)
        active = next((x for x in reversed(incidents) if x['mac'] == mac and x['status'] == 'active'), None)
        path_known = all(value is not None for value in row['path'])
        same_path = saved.get('path') == row['path']
        baseline = saved.get('baseline_mbps', 0) if same_path or not path_known or row['connected'] is not True else 0
        if isinstance(row['speed_mbps'], (int, float)):
            baseline = max(baseline, row['speed_mbps'])
        expected = row.get('expected_mbps')
        expected = expected if isinstance(expected, (int, float)) else max(baseline, active['expected_mbps'] if active else 0)
        row['effective_expected_mbps'] = expected
        current_rows.append(row)
        observed = []
        if previous:
            for key, label in (('path', 'reported uplink changed'), ('connected', 'connection changed'),
                               ('speed_mbps', 'speed changed')):
                if row[key] != previous.get(key):
                    observed.append({'kind': label, 'from': previous.get(key), 'to': row[key]})
            for endpoint, delta in row['deltas'].items():
                if delta['status'] == 'reset':
                    observed.append({'kind': 'counter or uptime reset', 'endpoint': endpoint})
                elif any(v > 0 for v in delta['counters'].values()):
                    observed.append({'kind': 'port counters increased', 'endpoint': endpoint,
                                     'counters': delta['counters']})
        for event in observed:
            event.update(at=now, previous_at=previous['at'], mac=mac, name=row['name'],
                         source='sampled controller state')
            events.append(event)
        excluded = row['policy'] != 'expected'
        low = (not excluded and row['connected'] is True and row['link_up'] is True
               and isinstance(row['speed_mbps'], (int, float))
               and 0 < row['speed_mbps'] <= 100 and expected >= 1000)
        if low and active is None:
            active = {'id': mac + '-' + str(now), 'mac': mac, 'name': row['name'],
                      'detected_at': now, 'previous_observed_at': previous.get('at'),
                      'status': 'active', 'expected_mbps': expected,
                      'trigger_speed_mbps': row['speed_mbps'],
                      'capture_reason': 'reported drop' if baseline >= 1000 else 'below explicit expectation',
                      'source': 'sampled controller state',
                      'native_event_history': 'Not collected; this monitor records sampled transitions.',
                      'before': deepcopy(history), 'samples': [],
                      'events': [e for e in events if e['mac'] == mac and 0 < now-e['at'] <= 600]}
            incidents.append(active)
        if active:
            active['samples'].append(row)
            if len(active['samples']) > MAX_SAMPLES:
                active['samples'] = [active['samples'][0]] + active['samples'][-(MAX_SAMPLES-1):]
            active['events'] = (active['events'] + observed)[-100:]
            recovered = (row['connected'] is True and isinstance(row['speed_mbps'], (int, float))
                         and row['speed_mbps'] >= expected)
            if excluded or expected < 1000 or recovered:
                active.update(status='closed', closed_at=now,
                              resolution='expectation changed' if excluded or expected < 1000 else 'speed recovered')
        devices[mac] = {'path': row['path'] if path_known else saved.get('path', row['path']), 'baseline_mbps': baseline,
                        'recent': (history + [row])[-PRE_SAMPLES:]}
    # Missing inventory does not mean recovery. Keep active evidence unchanged.
    devices = {k: v for k, v in devices.items()
               if k in seen or now-v['recent'][-1]['at'] <= RETENTION}
    state.update(generated=now, devices=dict(list(devices.items())[-256:]),
                 observations=current_rows, incidents=incidents[-MAX_INCIDENTS:], events=events[-MAX_EVENTS:],
                 error=None)
    return state
