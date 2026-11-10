"""Manual investigations remain available and preserve cached data on failure."""
import sys
from unittest.mock import MagicMock

import pytest


@pytest.mark.parametrize('result,status', [({}, 502), ({'threat_score': 42}, 200)])
def test_manual_force_refresh_does_not_backdate_cache(monkeypatch, result, status):
    for name in list(sys.modules):
        if name.startswith('routes'):
            monkeypatch.delitem(sys.modules, name, raising=False)
    deps = MagicMock()
    deps.abuseipdb.enabled = True
    deps.abuseipdb.lookup.return_value = result
    deps.abuseipdb.remaining_budget = 800
    deps.enricher_db.get_config.return_value = []
    monkeypatch.setitem(sys.modules, 'deps', deps)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import abuseipdb
    monkeypatch.setattr(abuseipdb, 'get_abuseipdb_stats', lambda db: None)
    monkeypatch.setattr(abuseipdb, 'get_wan_ips_from_config', lambda db: [])
    app = FastAPI()
    app.include_router(abuseipdb.router)
    response = TestClient(app).post('/api/enrich/8.8.8.8')
    assert response.status_code == status
    deps.abuseipdb.lookup.assert_called_once_with('8.8.8.8', force_refresh=True)
    if status == 502:
        deps.enricher_db.get_conn.assert_not_called()
    else:
        calls = deps.enricher_db.get_conn.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value.execute.call_args_list
        assert all('looked_up_at' not in call.args[0] for call in calls)
