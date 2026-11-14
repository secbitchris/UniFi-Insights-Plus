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


@router.get('/api/unifi/network-health/events')
def network_health_events():
    try:
        return json.loads((ROOT / 'events.json').read_text())[-200:]
    except (OSError, ValueError):
        return []


import fcntl
import re
import time
from typing import Literal
from pydantic import BaseModel, Field
from fastapi import HTTPException
from network_health import write_json


class DevicePolicy(BaseModel):
    status: Literal['expected', 'retired']
    reason: str = Field(default='', max_length=200)


@router.put('/api/settings/network-health/devices/{mac}')
def set_device_policy(mac: str, policy: DevicePolicy):
    mac = mac.lower()
    if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', mac):
        raise HTTPException(status_code=400, detail='Invalid device MAC')
    current = read_snapshot()
    if mac not in {d['mac'] for d in current.get('devices', [])}:
        raise HTTPException(status_code=404, detail='Device not present in the latest inventory')
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / 'device-policy.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            policies = json.loads((ROOT / 'device-policy.json').read_text())
        except (OSError, ValueError):
            policies = {}
        policies[mac] = {'status': policy.status, 'reason': policy.reason.strip(), 'updated': int(time.time())}
        write_json(ROOT / 'device-policy.json', policies)
    return {'saved': policies[mac], 'message': 'Applied at the next scheduled collection. Controller settings are unchanged.'}
