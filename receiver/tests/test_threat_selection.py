"""Behavioral coverage for discovery, refresh fairness and budget migration."""
import json
from unittest.mock import MagicMock, patch

import pytest

from threat_refresh import reserve_candidate, reserve_state, select_candidate, refresh_one


ROWS = [
    ('8.8.8.8', 15, 1, None, None),     # repeated unknown
    ('8.8.4.4', 3, 3, None, None),      # unknown scan across ports
    ('1.1.1.1', 2, 1, None, None),      # one-off noise below threshold
    ('9.9.9.9', 12, 2, 0, 60),         # previously clean, very old
    ('208.67.222.222', 20, 3, 100, 10), # known risky, more recent
]


def test_two_discovery_slots_then_old_score_refresh():
    selected = [select_candidate(ROWS, {'used': n}, 1000) for n in range(6)]
    assert [kind for ip, kind in selected] == ['discovery', 'discovery', 'refresh'] * 2
    assert selected[0][0] == '8.8.8.8'
    assert selected[2] == ('9.9.9.9', 'refresh')  # low score does not disqualify


def test_scanning_unknown_qualifies_but_one_off_noise_does_not():
    assert select_candidate(ROWS[1:3], {'used': 0}, 1000) == ('8.8.4.4', 'discovery')
    assert select_candidate(ROWS[2:3], {'used': 0}, 1000) is None


def test_empty_lane_lends_slot_without_starving_the_other():
    assert select_candidate(ROWS[:1], {'used': 2}, 1000)[1] == 'discovery'
    assert select_candidate(ROWS[3:], {'used': 0}, 1000)[1] == 'refresh'


def test_private_owned_and_cooling_ips_are_skipped():
    rows = [('192.168.1.1', 999, 100, None, None)] + ROWS
    state = {'used': 0, 'recent_attempts': {'8.8.8.8': 1001}}
    assert select_candidate(rows, state, 1000, excluded=['8.8.4.4'])[1] == 'refresh'
    assert select_candidate(rows, state, 1001, excluded=['8.8.4.4'])[0] == '8.8.8.8'


def test_age_and_risk_both_increase_refresh_priority():
    rows = [('8.8.8.8', 12, 1, 0, 10), ('9.9.9.9', 12, 1, 80, 10)]
    assert select_candidate(rows, {'used': 2}, 1000)[0] == '9.9.9.9'
    rows[0] = ('8.8.8.8', 12, 1, 0, 30)
    assert select_candidate(rows, {'used': 2}, 1000)[0] == '8.8.8.8'


def fake_db(state, now=1000, rows=ROWS):
    db = MagicMock()
    cur = db.get_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
    cur.fetchone.side_effect = [(now,), (state,) if state else None]
    cur.fetchall.return_value = rows
    return db, cur


def test_legacy_budget_migration_preserves_count_and_pacing():
    old = {'day': 0, 'used': 125, 'next_at': 999}
    db, cur = fake_db(old)
    assert reserve_candidate(db, 200) == ('9.9.9.9', 'refresh')
    persisted = json.loads(cur.execute.call_args.args[1][1])
    assert persisted['used'] == 126
    assert persisted['refresh_used'] == 126
    assert persisted['discovery_used'] == 0
    assert persisted['next_at'] == 1432
    assert persisted['recent_attempts'] == {'9.9.9.9': 4600}
    db.get_conn.return_value.__exit__.assert_called_once()


@pytest.mark.parametrize('state', [
    {'day': 0, 'used': 200, 'next_at': 0},
    {'day': 0, 'used': 125, 'next_at': 1001},
])
def test_no_candidate_scan_or_reservation_when_exhausted_or_not_due(state):
    db, cur = fake_db(state)
    assert reserve_candidate(db, 200) is None
    cur.fetchall.assert_not_called()
    assert not any('INSERT' in call.args[0] for call in cur.execute.call_args_list)


def test_no_eligible_ip_does_not_spend_budget():
    db, cur = fake_db(None, rows=ROWS[2:3])
    assert reserve_candidate(db, 200) is None
    assert not any('INSERT' in call.args[0] for call in cur.execute.call_args_list)


def test_midnight_resets_usage_without_resetting_cooldown_or_spacing():
    state = {'day': 0, 'used': 200, 'next_at': 86430,
             'recent_attempts': {'8.8.8.8': 87000}, 'discovery_used': 140}
    assert reserve_state(state, 86400, 200) is None
    new = reserve_state(state, 86430, 200)
    assert new['used'] == 1 and new['recent_attempts'] == state['recent_attempts']
    assert 'discovery_used' not in new


def test_committed_failed_attempt_is_retained_on_retry(monkeypatch):
    monkeypatch.setenv('ABUSEIPDB_BACKGROUND_DAILY_LIMIT', '200')
    db, cur = fake_db(None)
    abuse = MagicMock()
    abuse.lookup.return_value = {}  # Timeout / provider failure
    with patch('db.get_wan_ips_from_config', return_value=[]), patch('threat_refresh.reserve_candidate', wraps=lambda *args: reserve_candidate(db, 200)):
        refresh_one(db, abuse)
    abuse.lookup.assert_called_once_with('8.8.8.8', force_refresh=True)
    saved = json.loads(cur.execute.call_args.args[1][1])
    assert saved['used'] == 1 and saved['recent_attempts']['8.8.8.8'] == 4600
    db.patch_from_cache_for_ips.assert_not_called()
    db2, _ = fake_db(saved, now=1100)
    assert reserve_candidate(db2, 200) is None


def test_commit_failure_prevents_http(monkeypatch):
    monkeypatch.setenv('ABUSEIPDB_BACKGROUND_DAILY_LIMIT', '200')
    db, cur = fake_db(None)
    db.get_conn.return_value.__exit__.side_effect = RuntimeError('commit failed')
    abuse = MagicMock()
    with patch('db.get_wan_ips_from_config', return_value=[]):
        refresh_one(db, abuse)
    abuse.lookup.assert_not_called()
