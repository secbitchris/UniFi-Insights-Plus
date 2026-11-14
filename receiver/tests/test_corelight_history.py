import json
import corelight_history as history


def test_fresh_stale_and_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(history, 'ROOT', tmp_path)
    monkeypatch.setattr(history.time, 'time', lambda: 1000)
    assert history.read_history()['stale']
    path = tmp_path / 'corelight-history.json'
    path.write_text(json.dumps({'generated': 900, 'samples': [{'at': 800, 'loss': 2}]}))
    assert not history.read_history()['stale']
    path.write_text(json.dumps({'generated': 700, 'samples': []}))
    assert history.read_history()['stale']
    path.write_text('{broken')
    assert history.read_history()['samples'] == []
