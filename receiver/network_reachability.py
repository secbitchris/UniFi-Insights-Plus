"""Read existing location summaries without moving SSH credentials."""
import json
from pathlib import Path
import time
import urllib.request


def collect(root):
    try:
        url = json.loads((Path(root) / 'reachability-source.json').read_text())['url']
        with urllib.request.urlopen(url, timeout=45) as response:
            body = response.read(2_000_001)
        if len(body) > 2_000_000:
            raise ValueError('Oversized location summary')
        data = json.loads(body)
        if not isinstance(data.get('vantages'), list) or len(data['vantages']) > 8:
            raise ValueError('Invalid location summary')
        rows = []
        for item in data['vantages']:
            summary = item.get('data', {})
            rows.append({'name': item['source'], 'status': 'received' if 'generated' in summary else 'unknown',
                         'fetched_at': int(time.time()),
                         'summary': {k: summary[k] for k in ('generated', 'latest') if k in summary}})
        return rows
    except Exception as exc:
        return [{'name': 'Location summaries', 'status': 'unknown', 'error': type(exc).__name__}]
