"""Bounded native UniFi system-log queries and incident correlation."""
import hashlib
import json
import math
import re

CATEGORIES = ('UNIFI_ETHERNET_PORTS', 'UNIFI_DEVICES', 'POWER', 'SOFTWARE_UPDATES')
FIELDS = ('id', 'name', 'model', 'model_name', 'version')
MAC = re.compile(r'^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$', re.I)


def normalize(entry, now):
    stamp = entry.get('timestamp')
    if not isinstance(stamp, (int, float)) or isinstance(stamp, bool) or not math.isfinite(stamp):
        return None
    at = stamp / 1000
    if not now-7*86400 <= at <= now+60 or entry.get('category') not in CATEGORIES:
        return None
    params = {}
    raw_params = entry.get('parameters') or {}
    if not isinstance(raw_params, dict):
        raw_params = {}
    for key, value in list(raw_params.items())[:50]:
        if not isinstance(value, dict):
            continue
        safe = {k: str(value[k])[:300] for k in FIELDS if k in value and isinstance(value[k], (str, int, float))}
        if safe:
            params[str(key)[:100]] = safe
    record = {k: str(entry[k])[:2000] for k in
              ('id', 'event', 'key', 'category', 'subcategory', 'severity', 'type', 'title_raw', 'message_raw')
              if isinstance(entry.get(k), str)}
    record.update(at=at, timestamp_ms=stamp, parameters=params, source='native controller system log')
    record.setdefault('id', hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest())
    record['message'] = re.sub(r'\{(\w+)\}', lambda m: params.get(m[1], {}).get('name', m[0]), record.get('message_raw', ''))[:4000]
    record['device_macs'] = sorted({v['id'].lower() for v in params.values() if MAC.fullmatch(v.get('id', ''))})
    return record


def query(client, start, end):
    # POST is the v2 API's read/query method, not a controller mutation.
    prefix = '/proxy/network' if client._controller_type == 'unifi_os' else ''
    url = client.host + prefix + '/v2/api/site/' + client.site + '/system-log/all'
    records, truncated = [], False
    for page in range(2):
        body = {'timestampFrom': int(start*1000), 'timestampTo': int(end*1000),
                'pageNumber': page, 'pageSize': 100, 'categories': list(CATEGORIES)}
        response = client._get_session().post(url, json=body, timeout=10, stream=True)
        try:
            response.raise_for_status()
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 1024*1024:
                    raise ValueError('System-log response exceeds bound')
                chunks.append(chunk)
            data = json.loads(b''.join(chunks))
        finally:
            response.close()
        if not isinstance(data, dict) or not isinstance(data.get('data'), list):
            raise ValueError('Invalid system-log response')
        records.extend(x for x in data['data'][:100] if isinstance(x, dict))
        pages = data.get('total_page_count')
        more = page+1 < pages if isinstance(pages, int) else len(data['data']) >= 100
        if not more:
            break
        truncated = page == 1
    return records, truncated


def correlate(state, now):
    native = state.get('native', {})
    for incident in state.get('incidents', []):
        identities = {incident['mac'].lower()}
        for sample in incident.get('before', []) + incident.get('samples', []):
            for role in ('device', 'parent'):
                mac = sample.get(role, {}).get('mac')
                if isinstance(mac, str):
                    identities.add(mac.lower())
        start = incident['detected_at']-600
        end = incident.get('closed_at', now)+120
        matches = [event for event in native.get('events', [])
                   if start <= event['at'] <= end and identities.intersection(event['device_macs'])]
        existing = {x['id']: x for x in incident.get('native_events', [])}
        existing.update({x['id']: x for x in matches})
        incident['native_events'] = sorted(existing.values(), key=lambda x: x['at'])[-100:]
        incident['native_event_history'] = {
            k: native.get(k) for k in ('status', 'last_success', 'window_start', 'window_end', 'truncated', 'error')}
        incident['native_event_history']['note'] = 'Device or parent-switch match in incident window; correlation is not proof of cause.'


def capture(client, state, now, fetch=query):
    native = state.setdefault('native', {})
    if now-native.get('last_attempt', 0) < 60:
        correlate(state, now)
        return
    start = max(now-7*86400, native.get('last_success', now-7*86400)-600)
    native['last_attempt'] = now
    try:
        records, truncated = fetch(client, start, now)
        events = {x['id']: x for x in native.get('events', []) if now-7*86400 <= x['at'] <= now+60}
        for entry in records:
            event = normalize(entry, now)
            if event:
                events[event['id']] = event
        native.update(status='partial' if truncated else 'ok', error=None,
                      http_status=200, last_success=now, window_start=start, window_end=now,
                      truncated=truncated, events=sorted(events.values(), key=lambda x: x['at'])[-1000:])
    except Exception as exc:
        native.update(status='unavailable', error=type(exc).__name__,
                      http_status=getattr(getattr(exc, 'response', None), 'status_code', None))
    correlate(state, now)
