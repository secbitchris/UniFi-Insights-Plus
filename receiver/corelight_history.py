"""Read the bounded, private snapshot published by the pvecore collector."""
import json
import time
from network_health import ROOT


def read_history():
    path = ROOT / 'corelight-history.json'
    try:
        if path.stat().st_size > 8 * 1024 * 1024:
            raise ValueError('oversized snapshot')
        data = json.loads(path.read_text())
        if not isinstance(data.get('samples'), list):
            raise ValueError('invalid snapshot')
        generated = float(data['generated'])
        return {**data, 'stale': not -60 <= time.time() - generated <= 180}
    except (OSError, ValueError, TypeError, KeyError):
        return {'generated': None, 'stale': True, 'samples': [], 'error': 'Capture history unavailable'}
