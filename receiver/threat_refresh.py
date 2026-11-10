"""Optional, persisted and paced refresh of recently active suspicious IPs.

Passive flow enrichment and the historical queue never spend /check quota.
Set ABUSEIPDB_BACKGROUND_DAILY_LIMIT=200 to permit at most 200 background
attempts per UTC day, spaced across the day. Zero (default) disables them.
"""
import json
import logging
import os

logger = logging.getLogger('threat_refresh')
STATE_KEY = 'abuseipdb_background_budget'
LOCK_ID = 1238001


def daily_limit():
    try:
        limit = int(os.environ.get('ABUSEIPDB_BACKGROUND_DAILY_LIMIT', '0'))
        return min(200, max(0, limit))
    except ValueError:
        return 0  # Invalid configuration must not enable requests.


def reserve_state(state, now, limit):
    """Return a new reservation, or None. No catch-up bursts after downtime."""
    if limit <= 0:
        return None
    day = int(now // 86400)
    if not state or state.get('day') != day:
        state = {'day': day, 'used': 0, 'next_at': 0}
    if state['used'] >= limit or now < state['next_at']:
        return None
    return {'day': day, 'used': state['used'] + 1,
            'next_at': now + 86400 / limit}


def reserve_slot(db, limit):
    """Commit a slot BEFORE HTTP, shared across restarts and worker processes.

    A timeout/failure still costs a slot: the provider may have counted it.
    Failure to read or persist the budget fails closed without an API call.
    """
    with db.get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout = '2s'")
            cur.execute('SELECT pg_advisory_xact_lock(%s)', [LOCK_ID])
            cur.execute('SELECT EXTRACT(EPOCH FROM clock_timestamp())')
            now = float(cur.fetchone()[0])
            cur.execute('SELECT value FROM system_config WHERE key = %s', [STATE_KEY])
            row = cur.fetchone()
            state = reserve_state(row[0] if row else None, now, limit)
            if state is None:
                return False
            cur.execute(
                'INSERT INTO system_config (key, value, updated_at) '
                'VALUES (%s, %s::jsonb, NOW()) ON CONFLICT (key) DO UPDATE '
                'SET value = EXCLUDED.value, updated_at = NOW()',
                [STATE_KEY, json.dumps(state)],
            )
    return True


def refresh_one(db, abuseipdb):
    """Refresh only a recently observed, suspicious, week-old score.

    Do not backdate or delete the cached result before HTTP: a failed refresh
    must leave existing intelligence intact. A force-refresh bypasses hot cache.
    """
    limit = daily_limit()
    if not limit or not abuseipdb.enabled or not abuseipdb._check_rate_limit():
        return
    try:
        with db.get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT host(ip) FROM ip_threats "
                    "WHERE threat_score >= 25 "
                    "AND last_seen_at > NOW() - INTERVAL '24 hours' "
                    "AND looked_up_at < NOW() - INTERVAL '7 days' "
                    "ORDER BY threat_score DESC, last_seen_at DESC LIMIT 1"
                )
                row = cur.fetchone()
        if not row or not reserve_slot(db, limit):
            return
        result = abuseipdb.lookup(row[0], force_refresh=True)
        if result and 'threat_score' in result:
            from db import get_wan_ips_from_config
            db.patch_from_cache_for_ips([row[0]], get_wan_ips_from_config(db))
            db.patch_abuse_fields_for_ips([row[0]], get_wan_ips_from_config(db))
            logger.info('Paced threat refresh completed (daily cap %d)', limit)
    except Exception:
        logger.exception('Paced threat refresh failed; no automatic retry burst')
