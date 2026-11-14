import json
from unittest.mock import Mock
import pytest
from network_link_samples import observations, counter_deltas
from network_link_state import transition
from network_links import poll, read_report

AP = '00:11:22:33:44:55'
SW = '00:11:22:33:44:66'


def devices(now, speed=1000, errors=0, uptime=1000):
    port = {'port_idx': 2, 'up': True, 'speed': speed, 'autoneg': True,
            'rx_errors': errors, 'tx_errors': 0, 'rx_dropped': 0, 'tx_dropped': 0,
            'link_down_count': 1, 'poe_good': True}
    return [
        {'type': 'uap', 'mac': AP, 'name': 'Test AP', 'state': 1, 'last_seen': now,
         'uptime': uptime, 'version': 'test', 'password': 'must-not-be-saved',
         'uplink': {'uplink_mac': SW, 'uplink_remote_port': 2, 'port_idx': 1,
                    'up': True, 'speed': speed},
         'port_table': [{**port, 'port_idx': 1}]},
        {'type': 'usw', 'mac': SW, 'name': 'Test switch', 'state': 1,
         'last_seen': now, 'uptime': now + 5000, 'port_table': [port]}]


def rows(now, speed=1000, errors=0, uptime=1000, policy=None):
    return observations(devices(now, speed, errors, uptime), {AP: policy} if policy else {}, now)


def step(state, now, **kw):
    return transition(state, rows(now, **kw), now)


def test_drop_freezes_preceding_samples_and_both_port_counters():
    state = step({}, 1000)
    before = json.dumps(state)
    result = step(state, 1060, speed=100, errors=7)
    incident = result['incidents'][0]
    assert json.dumps(state) == before
    assert incident['before'][0]['speed_mbps'] == 1000
    assert incident['samples'][0]['speed_mbps'] == 100
    assert incident['samples'][0]['deltas']['port']['counters']['rx_errors'] == 7
    assert incident['samples'][0]['deltas']['local_port']['counters']['rx_errors'] == 7
    assert any(e['kind'] == 'speed changed' for e in incident['events'])
    assert 'must-not-be-saved' not in json.dumps(result)
    assert len(step(result, 1120, speed=100)['incidents']) == 1


def test_evidence_survives_serialization_reboot_and_recovery():
    state = step(step({}, 1000), 1060, speed=100, errors=10, uptime=1060)
    restored = json.loads(json.dumps(state))
    offline = rows(1120, speed=100)
    offline[0].update(connected=False, speed_mbps=None, link_up=None)
    state = transition(restored, offline, 1120)
    assert state['incidents'][0]['status'] == 'active'
    state = step(state, 1180, speed=1000, errors=0, uptime=15)
    incident = state['incidents'][0]
    assert incident['status'] == 'closed'
    assert incident['resolution'] == 'speed recovered'
    assert incident['samples'][-1]['deltas']['local_port']['status'] == 'reset'
    assert incident['samples'][-1]['deltas']['local_port']['counters'] == {}
    assert incident['before'][0]['speed_mbps'] == 1000


@pytest.mark.parametrize('policy', [
    {'status': 'expected', 'expected_speed_mbps': 100},
    {'status': 'intentionally_offline'}, {'status': 'retired'}])
def test_explicit_low_speed_and_offline_policies_do_not_alert(policy):
    state = step({}, 1000)
    assert step(state, 1060, speed=100, policy=policy)['incidents'] == []


def test_already_low_without_baseline_requires_explicit_expectation():
    assert step({}, 1000, speed=100)['incidents'] == []
    state = step({}, 1000, speed=100, policy={'status': 'expected', 'expected_speed_mbps': 1000})
    assert state['incidents'][0]['capture_reason'] == 'below explicit expectation'


def test_stale_device_data_does_not_create_false_drop():
    state = step({}, 1000)
    stale = devices(1000, speed=100)
    result = transition(state, observations(stale, {}, 1300), 1300)
    assert result['incidents'] == []
    assert result['observations'][0]['connected'] is None


def test_duplicate_source_and_long_gap_do_not_claim_measured_deltas():
    first = rows(1000)[0]
    same = observations(devices(1000), {}, 1060)[0]
    assert counter_deltas(first, same)['port']['status'] == 'no new observation'
    assert counter_deltas(first, rows(1400)[0])['port']['status'] == 'gap'


def test_history_and_incident_sample_bounds_keep_trigger():
    state = {}
    for now in range(1000, 1900, 60):
        state = step(state, now)
    state = step(state, 1900, speed=100)
    assert len(state['incidents'][0]['before']) == 10
    for now in range(1960, 7000, 60):
        state = step(state, now, speed=100)
    assert len(state['incidents'][0]['samples']) == 60
    assert state['incidents'][0]['samples'][0]['at'] == 1900
    assert len(state['devices'][AP]['recent']) == 10


def test_controller_failure_preserves_incident_and_marks_report_stale(tmp_path, monkeypatch):
    monkeypatch.setattr("network_links.capture", lambda *args: None)
    client = Mock(enabled=True)
    client._get.return_value = {'data': devices(1000)}
    poll(client, tmp_path, 1000)
    client._get.return_value = {'data': devices(1060, speed=100)}
    poll(client, tmp_path, 1060)
    client._get.side_effect = ConnectionError('unavailable')
    poll(client, tmp_path, 1120)
    result = read_report(tmp_path, 1120)
    assert result['stale']
    assert result['error'] == 'ConnectionError'
    assert result['incidents'][0]['status'] == 'active'
    assert result['generated'] == 1060


def test_missing_device_does_not_close_active_incident():
    state = step(step({}, 1000), 1060, speed=100)
    result = transition(state, [], 1120)
    assert result['incidents'][0]['status'] == 'active'


def test_parent_port_change_does_not_transfer_learned_baseline():
    state = step({}, 1000)
    changed = rows(1060, speed=100)
    changed[0]['path'] = [SW, 3]
    result = transition(state, changed, 1060)
    assert result['incidents'] == []


def test_policy_change_closes_without_deleting_evidence():
    state = step(step({}, 1000), 1060, speed=100)
    result = step(state, 1120, speed=100, policy={'status': 'intentionally_offline'})
    assert result['incidents'][0]['status'] == 'closed'
    assert result['incidents'][0]['resolution'] == 'expectation changed'
    assert result['incidents'][0]['before']

def test_reboot_with_missing_uplink_keeps_incident_open():
    state = step(step({}, 1000), 1060, speed=100)
    data = devices(1120)
    data[0].update(state=0, uplink={}, port_table=[], last_seen=1060, uptime=None)
    state = transition(state, observations(data, {}, 1120), 1120)
    assert state['incidents'][0]['status'] == 'active'
    assert state['devices'][AP]['baseline_mbps'] == 1000
    state = step(state, 1180, speed=1000, uptime=10)
    assert state['incidents'][0]['resolution'] == 'speed recovered'
