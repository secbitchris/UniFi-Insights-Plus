
import json
from unittest.mock import Mock
import pytest
import blacklist_guard as guard
from blacklist import BlacklistFetcher

@pytest.fixture
def clock(tmp_path,monkeypatch):
    now=[1794682000.0]
    monkeypatch.setenv('NETWORK_HEALTH_DIR',str(tmp_path))
    monkeypatch.setattr(guard.time,'time',lambda:now[0])
    return now

def test_success_survives_restart_and_expires(clock):
    with guard.attempt() as ticket:
        assert ticket
        guard.completed(ticket,10000)
    clock[0]+=60
    with guard.attempt() as ticket: assert ticket is None
    clock[0]+=86400
    with guard.attempt() as ticket: assert ticket

def test_failed_attempt_persists_backoff(clock):
    with guard.attempt() as ticket: assert ticket
    clock[0]+=30
    with guard.attempt() as ticket: assert ticket is None
    clock[0]+=3600
    with guard.attempt() as ticket: assert ticket

def test_rate_limit_persists_reset(clock,tmp_path):
    with guard.attempt() as ticket:
        guard.rate_limited(ticket,{'Retry-After':'90000'})
    state=json.loads((tmp_path/'blacklist-download.json').read_text())
    assert state['next_attempt']==clock[0]+90000
    clock[0]+=86400
    with guard.attempt() as ticket: assert ticket is None

def test_fetcher_avoids_second_provider_request(clock,monkeypatch):
    db=Mock()
    db.get_config.return_value=[]
    db.bulk_upsert_threats.return_value=1
    response=Mock(status_code=200)
    response.json.return_value={'data':[{'ipAddress':'203.0.113.1','abuseConfidenceScore':95}]}
    get=Mock(return_value=response)
    monkeypatch.setattr('blacklist.requests.get',get)
    monkeypatch.setattr('blacklist.get_wan_ips_from_config',lambda db:[])
    monkeypatch.setattr('blacklist.get_config',lambda *a:[])
    assert BlacklistFetcher(db,'synthetic').fetch_and_store()==1
    assert BlacklistFetcher(db,'synthetic').fetch_and_store()==0
    get.assert_called_once()

def test_corrupt_state_fails_closed(clock,tmp_path,monkeypatch):
    (tmp_path/'blacklist-download.json').write_text('invalid')
    get=Mock();monkeypatch.setattr('blacklist.requests.get',get)
    assert BlacklistFetcher(Mock(),'synthetic').fetch_and_store()==0
    get.assert_not_called()
