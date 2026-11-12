"""Paced discovery and refresh share a persisted maximum of 200 checks/day.

Two slots favor unknown IPs with repeated blocks or scan-like activity; every
third favors aging scores of any value. Empty lanes lend their slot. Passive
flows and historical backfill never spend quota. Zero (default) disables checks.
"""
import ipaddress
import json
import logging
import os

logger = logging.getLogger('threat_refresh')
STATE_KEY = 'abuseipdb_background_budget'
LOCK_ID = 1238001

# Executed only when a persisted slot is due, not on every worker poll. Bound
# by statement_timeout and the existing rule_action/timestamp index. Timestamps
# in the future are excluded so malformed syslog cannot qualify an inactive IP.
CANDIDATE_SQL = """
WITH seen AS (
    SELECT remote_ip, COUNT(*) AS hits, COUNT(DISTINCT dst_port) AS ports
    FROM logs
    WHERE timestamp >= NOW() - INTERVAL '24 hours' AND timestamp <= NOW()
      AND log_type = 'firewall' AND rule_action = 'block'
      AND remote_ip IS NOT NULL
    GROUP BY remote_ip
)
SELECT host(s.remote_ip), s.hits, s.ports, t.threat_score,
       EXTRACT(EPOCH FROM NOW() - t.looked_up_at)/86400 AS age_days
FROM seen s LEFT JOIN ip_threats t ON t.ip = s.remote_ip
WHERE (t.ip IS NULL AND (s.hits >= 10 OR (s.hits >= 3 AND s.ports >= 3)))
   OR t.looked_up_at < NOW() - INTERVAL '7 days'
"""


def daily_limit():
    try:
        return min(200, max(0, int(os.environ.get('ABUSEIPDB_BACKGROUND_DAILY_LIMIT', '0'))))
    except ValueError:
        return 0


def reserve_state(state, now, limit):
    """No catch-up bursts; preserve pacing/cooldowns across midnight and restart."""
    if limit <= 0:
        return None
    day = int(now // 86400)
    if not state or state.get('day') != day:
        previous = state or {}
        state = {'day': day, 'used': 0, 'next_at': previous.get('next_at', 0)}
        if previous.get('recent_attempts'):
            state['recent_attempts'] = previous['recent_attempts']
    if state['used'] >= limit or now < state['next_at']:
        return None
    return {**state, 'used': state['used'] + 1, 'next_at': now + 86400 / limit}


def select_candidate(rows, state, now, excluded=()):
    """Rows: (IP, blocked-event count, destination-port count, score, age_days).

    Existing low scores can change; age increases their refresh priority too.
    A failed request has a persisted one-hour per-IP cooldown, preventing one
    failing host from monopolizing a lane. The shared daily cap still applies.
    """
    lanes = {'discovery': [], 'refresh': []}
    excluded = {str(ipaddress.ip_address(ip)) for ip in excluded}
    recent = state.get('recent_attempts', {})
    for ip, hits, ports, score, age in rows:
        address = ipaddress.ip_address(ip)
        ip = str(address)
        if not address.is_global or address.is_multicast or ip in excluded:
            continue
        if now < recent.get(ip, 0):
            continue
        if score is None and (hits >= 10 or (hits >= 3 and ports >= 3)):
            lanes['discovery'].append(((hits, ports, ip), ip))
        elif score is not None and age is not None and float(age) > 7:
            priority = float(age) * (1 + max(0, min(score, 100)) / 100)
            lanes['refresh'].append(((priority, hits, ip), ip))
    preferred = 'refresh' if state['used'] % 3 == 2 else 'discovery'
    other = 'discovery' if preferred == 'refresh' else 'refresh'
    kind = preferred if lanes[preferred] else other
    if not lanes[kind]:
        return None
    return max(lanes[kind])[1], kind


def reserve_candidate(db, limit, excluded=()):
    """Select and COMMIT a due attempt before HTTP under the existing DB lock.

    Fail closed on read/query/commit errors. No refund after timeout: the provider
    may have counted it. Legacy state keeps its used count and next-at timestamp.
    """
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '2s'")
            cur.execute("SET LOCAL statement_timeout = '5s'")
            cur.execute('SELECT pg_advisory_xact_lock(%s)', [LOCK_ID])
            cur.execute('SELECT EXTRACT(EPOCH FROM clock_timestamp())')
            now = float(cur.fetchone()[0])
            cur.execute('SELECT value FROM system_config WHERE key = %s', [STATE_KEY])
            row = cur.fetchone()
            prior = row[0] if row else None
            state = reserve_state(prior, now, limit)
            if state is None:
                return None
            # Use normalized pre-reservation count for the 2:1 rotation.
            before = {**state, 'used': state['used'] - 1}
            cur.execute(CANDIDATE_SQL)
            candidate = select_candidate(cur.fetchall(), before, now, excluded)
            if candidate is None:
                return None
            ip, kind = candidate
            discovery = before.get('discovery_used', 0)
            refresh = before.get('refresh_used', before['used'] - discovery)
            state['discovery_used'] = discovery + (kind == 'discovery')
            state['refresh_used'] = refresh + (kind == 'refresh')
            state['recent_attempts'] = {
                key: until for key, until in state.get('recent_attempts', {}).items()
                if until > now
            }
            state['recent_attempts'][ip] = now + 3600
            cur.execute(
                'INSERT INTO system_config (key, value, updated_at) '
                'VALUES (%s, %s::jsonb, NOW()) ON CONFLICT (key) DO UPDATE '
                'SET value = EXCLUDED.value, updated_at = NOW()',
                [STATE_KEY, json.dumps(state)],
            )
    return candidate


def refresh_one(db, abuseipdb):
    """One paced discovery or refresh; never backdate/delete the prior score."""
    limit = daily_limit()
    if not limit or not abuseipdb.enabled or not abuseipdb._check_rate_limit():
        return
    try:
        from db import get_wan_ips_from_config
        wan_ips = get_wan_ips_from_config(db)
        excluded = set(wan_ips) | set(db.get_config('gateway_ips') or [])
        excluded.update(abuseipdb._excluded_ips)
        candidate = reserve_candidate(db, limit, excluded)
        if not candidate:
            return
        ip, kind = candidate
        result = abuseipdb.lookup(ip, force_refresh=True)
        if result and 'threat_score' in result:
            db.patch_from_cache_for_ips([ip], wan_ips)
            db.patch_abuse_fields_for_ips([ip], wan_ips)
            logger.info('Paced threat %s completed (daily cap %d)', kind, limit)
    except Exception:
        logger.exception('Paced threat lookup failed; no automatic retry burst')
