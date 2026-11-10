"""Offline tests for the persisted background quota and selective policy."""
from unittest.mock import MagicMock, patch

import pytest

from threat_refresh import daily_limit, refresh_one, reserve_slot, reserve_state
from enrichment import AbuseIPDBEnricher


@pytest.mark.parametrize('value,expected', [('200', 200), ('5000', 200), ('-1', 0), ('typo', 0), ('0', 0)])
def test_limit_is_bounded_and_invalid_fails_closed(monkeypatch, value, expected):
    monkeypatch.setenv('ABUSEIPDB_BACKGROUND_DAILY_LIMIT', value)
    assert daily_limit() == expected


def test_background_disabled_by_default(monkeypatch):
    monkeypatch.delenv('ABUSEIPDB_BACKGROUND_DAILY_LIMIT', raising=False)
    db, abuse = MagicMock(), MagicMock()
    refresh_one(db, abuse)
    db.get_conn.assert_not_called()
    abuse.lookup.assert_not_called()


def test_spacing_day_reset_cap_and_no_catchup():
    state = reserve_state(None, 1000, 200)
    assert state == {'day': 0, 'used': 1, 'next_at': 1432}
    assert reserve_state(state, 1431, 200) is None
    assert reserve_state(state, 1432, 200)['used'] == 2
    late = reserve_state(state, 5000, 200)
    assert late['used'] == 2 and late['next_at'] == 5432
    assert reserve_state({'day': 0, 'used': 200, 'next_at': 0}, 86399, 200) is None
    assert reserve_state({'day': 0, 'used': 200, 'next_at': 0}, 86400, 200)['used'] == 1


def test_reservation_persisted_under_lock_before_return():
    db = MagicMock()
    cur = db.get_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [(1000,), ({'day': 0, 'used': 3, 'next_at': 1000},)]
    assert reserve_slot(db, 200)
    statements = [call.args[0] for call in cur.execute.call_args_list]
    assert 'pg_advisory_xact_lock' in statements[1]
    assert 'INSERT INTO system_config' in statements[-1]
    assert '"used": 4' in cur.execute.call_args.args[1][1]
    db.get_conn.return_value.__exit__.assert_called_once()


def test_persistence_failure_never_calls_api(monkeypatch):
    monkeypatch.setenv('ABUSEIPDB_BACKGROUND_DAILY_LIMIT', '200')
    db, abuse = MagicMock(), MagicMock()
    cur = db.get_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = ('8.8.8.8',)
    with patch('threat_refresh.reserve_slot', side_effect=RuntimeError('db unavailable')):
        refresh_one(db, abuse)
    abuse.lookup.assert_not_called()


def test_selective_refresh_forces_http_without_backdating(monkeypatch):
    monkeypatch.setenv('ABUSEIPDB_BACKGROUND_DAILY_LIMIT', '200')
    db, abuse = MagicMock(), MagicMock()
    cur = db.get_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = ('8.8.8.8',)
    abuse.lookup.return_value = {}  # Failure must retain prior score unchanged.
    with patch('threat_refresh.reserve_slot', return_value=True):
        refresh_one(db, abuse)
    sql = cur.execute.call_args.args[0]
    assert 'threat_score >= 25' in sql and "INTERVAL '24 hours'" in sql
    assert 'UPDATE' not in sql
    abuse.lookup.assert_called_once_with('8.8.8.8', force_refresh=True)
    db.patch_from_cache_for_ips.assert_not_called()


def test_cached_only_miss_never_calls_http():
    with patch.object(AbuseIPDBEnricher, '_write_stats'), patch('enrichment.requests.get') as http:
        db = MagicMock()
        db.get_config.return_value = None
        db.get_threat_cache.return_value = None
        abuse = AbuseIPDBEnricher(api_key='test-only', db=db)
        assert abuse.lookup('8.8.8.8', allow_api=False) == {}
        db.get_threat_cache.assert_called_once_with('8.8.8.8', max_age_days=30)
        http.assert_not_called()


def test_force_refresh_bypasses_both_caches():
    with patch.object(AbuseIPDBEnricher, '_write_stats'), patch('enrichment.requests.get') as http:
        db = MagicMock()
        db.get_config.return_value = None
        abuse = AbuseIPDBEnricher(api_key='test-only', db=db)
        abuse.cache.set('8.8.8.8', {'threat_score': 99})
        http.return_value.status_code = 200
        http.return_value.headers = {}
        http.return_value.json.return_value = {'data': {'abuseConfidenceScore': 5}}
        assert abuse.lookup('8.8.8.8', force_refresh=True)['threat_score'] == 5
        http.assert_called_once()
        db.get_threat_cache.assert_not_called()


def test_live_block_is_cached_only_and_does_not_enqueue(monkeypatch):
    from enrichment import Enricher
    monkeypatch.setattr('enrichment.GeoIPEnricher', MagicMock)
    monkeypatch.setattr('enrichment.AbuseIPDBEnricher', MagicMock)
    monkeypatch.setenv('RDNS_ENABLED', 'false')
    e = Enricher(db=None)
    e._db = MagicMock()
    e.geoip.lookup.return_value = {}
    e.abuseipdb.lookup.return_value = {}
    e.enrich({'log_type': 'firewall', 'rule_action': 'block',
              'src_ip': '8.8.8.8', 'dst_ip': '192.168.1.5'})
    e.abuseipdb.lookup.assert_called_once_with('8.8.8.8', allow_api=False)
    e._db.enqueue_threat_backfill.assert_not_called()


def test_worker_never_drains_or_seeds_historical_queue(monkeypatch):
    from backfill import BackfillTask
    task = BackfillTask(MagicMock(), MagicMock())
    for method in ('_backfill_direction', '_fix_wan_ip_enrichment',
                   '_fix_abuse_hostname_mixing', '_service_name_migration',
                   '_backfill_rule_action', '_orphan_queue_seed',
                   '_process_queue', '_reenrich_stale_threats'):
        monkeypatch.setattr(task, method, MagicMock())
    with patch('threat_refresh.refresh_one') as refresh:
        task._run_once(0)
        refresh.assert_called_once_with(task.db, task.abuseipdb)
    task._orphan_queue_seed.assert_not_called()
    task._process_queue.assert_not_called()
    task._reenrich_stale_threats.assert_not_called()
