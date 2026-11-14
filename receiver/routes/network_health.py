"""Read-only network-health snapshots, behind existing unifi.read auth."""
import json
from fastapi import APIRouter
from network_health import ROOT, read_snapshot

router = APIRouter()


@router.get('/api/unifi/network-health')
def network_health():
    return read_snapshot()


@router.get('/api/unifi/network-health/history')
def network_health_history():
    try:
        return json.loads((ROOT / 'history.json').read_text())[-2016:]
    except (OSError, ValueError):
        return []


@router.get('/api/unifi/network-health/reachability')
def network_reachability():
    try:
        return json.loads((ROOT / 'reachability.json').read_text())
    except (OSError, ValueError):
        return []
