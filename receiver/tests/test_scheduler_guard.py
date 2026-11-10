from unittest.mock import MagicMock

import scheduler_guard as guard


def test_heartbeat_and_expiry(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, 'HEARTBEAT', tmp_path / 'heartbeat')
    monkeypatch.setattr(guard.time, 'time', lambda: 1000)
    assert not guard.scheduler_healthy()
    callback = MagicMock()
    guard.tick_with_heartbeat(callback, 'db')
    callback.assert_called_once_with('db')
    assert guard.scheduler_healthy()
    monkeypatch.setattr(guard.time, 'time', lambda: 1301)
    assert not guard.scheduler_healthy()


def test_tick_failure_does_not_publish_success(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, 'HEARTBEAT', tmp_path / 'heartbeat')
    guard.tick_with_heartbeat(MagicMock(side_effect=ConnectionError('db down')), 'db')
    assert not guard.HEARTBEAT.exists()
