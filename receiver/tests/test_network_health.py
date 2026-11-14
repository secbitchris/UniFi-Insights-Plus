"""Coverage contracts for the migrated monitor; no live network or database."""
import json
import socket
from unittest.mock import Mock

import pytest

from network_health import collect, read_snapshot
from network_dns import assess
import network_inventory


class Client:
    enabled = True
    host = 'https://192.168.1.1'
    _controller_type = 'unifi_os'
    site = 'default'

    def _get(self, path):
        raise RuntimeError('authentication failed')


def test_controller_failure_does_not_hide_dns_and_watch_unknown(tmp_path):
    (tmp_path / 'watchlist.json').write_text(json.dumps({'aa': 'Camera'}))
    dns = Mock(return_value=[{'title': 'DNS resolver', 'severity': 'critical'}])
    result = collect(Client(), tmp_path, dns_assess=dns)
    dns.assert_called_once()
    assert result['counts']['critical'] == 1
    assert result['counts']['unknown'] == 14
    assert result['watch']['aa']['status'] == 'unknown'
    with pytest.raises(ValueError):
        dns.call_args.args[2]()


def test_empty_controller_inventory_is_not_a_green_result(tmp_path):
    client = Client()
    client._get = lambda path: {'data': []}
    result = collect(client, tmp_path, dns_assess=lambda *args: [])
    assert result['counts']['ok'] == 0
    assert result['counts']['unknown'] == 14


def test_snapshot_freshness_and_missing_file(tmp_path):
    assert read_snapshot(tmp_path, 1000)['status'] == 'unavailable'
    (tmp_path / 'health.json').write_text(json.dumps({'generated': 1000, 'checks': []}))
    assert read_snapshot(tmp_path, 1100)['status'] == 'current'
    assert read_snapshot(tmp_path, 2000)['status'] == 'stale'
    assert read_snapshot(tmp_path, 900)['status'] == 'stale'


def test_dns_failure_with_reachable_internet_is_attributed_to_dns(tmp_path, monkeypatch):
    import network_dns
    def dns(*args, **kwargs):
        raise socket.timeout()
    monkeypatch.setattr(network_dns, 'dns_query', dns)
    monkeypatch.setattr(network_dns, 'tcp_open', lambda host, port, **kw: port == 443)
    checks = {x['title']: x for x in assess('192.168.1.1', str(tmp_path), lambda: [])}
    assert checks['DNS resolver']['severity'] == 'critical'
    assert 'DNS FAULT' in checks['DNS or WAN (attribution)']['detail']
    assert checks['DNS egress policy']['severity'] != 'ok'


def test_positive_dns_leak_wins_over_failed_control(tmp_path, monkeypatch):
    import network_dns
    def dns(host, *args, **kwargs):
        if host == '192.168.1.1':
            raise socket.timeout()
        return 0, ['1.2.3.4'], 1
    monkeypatch.setattr(network_dns, 'dns_query', dns)
    monkeypatch.setattr(network_dns, 'tcp_open', lambda *a, **kw: False)
    result = assess('192.168.1.1', str(tmp_path), lambda: [])
    assert next(x for x in result if x['title'] == 'DNS egress policy')['severity'] == 'critical'


def test_per_model_load_and_unknown_radio_baseline(tmp_path):
    devices = [{'type': 'usw', 'name': 'Switch', 'mac': 'aa', 'stp_priority': 4096, 'stp_version': 'rstp'},
                {'type': 'uap', 'name': 'Studio', 'model': 'UAP6MP', 'sys_stats': {'loadavg_1': 3.06}},
                {'type': 'uap', 'name': 'Attic', 'model': 'U7PG2', 'sys_stats': {'loadavg_1': 1.6}}]
    checks = {x['title']: x for x in network_inventory.assess(devices, [], [], {}, str(tmp_path))}
    assert checks['AP load']['severity'] == 'warning'
    assert 'Attic' in str(checks['AP load']['items'])
    assert 'Studio' not in str(checks['AP load']['items'])
    assert checks['AP transmit health']['severity'] == 'unknown'


@pytest.mark.parametrize('priority, expected', [('4096', 'ok'), ('32768', 'warning'), (None, 'unknown'), ('invalid', 'unknown')])
def test_controller_priority_types(tmp_path, priority, expected):
    result = network_inventory.assess([{'type': 'usw', 'name': 'Switch', 'mac': 'aa', 'state': 1, 'stp_priority': priority}], [], [], {}, str(tmp_path))
    assert next(c for c in result if c['title'] == 'STP priorities')['severity'] == expected


def test_live_sized_dns_override_inventory_is_not_discarded(tmp_path, monkeypatch):
    import network_health
    monkeypatch.setattr(network_health.network_inventory, 'assess', lambda *args: [])
    monkeypatch.setattr(network_health.network_radio, 'assess', lambda *args: [])
    client = Client()
    client._get = lambda path: {'data': [{'type': 'usw'}]} if path == 'stat/device' else {'data': []}
    response = Mock()
    response.json.return_value = [{'enabled': True, 'record_type': 'A', 'key': f'host{i}.example', 'value': '192.0.2.1'} for i in range(46)]
    client._get_session = lambda: Mock(get=lambda *a, **kw: response)
    def dns(host, root, get_static):
        assert len(get_static()) == 46
        return [{'title': 'DNS override integrity', 'severity': 'ok'}]
    out = collect(client, tmp_path, dns_assess=dns)
    assert out['controller_error'] is None
    assert out['counts']['ok'] == 1
