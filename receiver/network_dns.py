from network_basics import *

def assess(HOST, DIR, get_static):
    DOT_STATE = str(DIR) + '/dns-egress-state.json'
    checks = []

    def add(sev, title, detail, items=None):
        checks.append({'severity': sev, 'title': title, 'detail': detail, 'items': items or [], 'why': WHY.get(title, '')})
    gw_ok, gw_ms, gw_ips, gw_err = (False, None, [], None)
    try:
        rc, gw_ips, gw_ms = dns_query(HOST, DNS_PROBE)
        gw_ok = rc == 0 and bool(gw_ips)
        if not gw_ok:
            gw_err = f'rcode={rc} answers={len(gw_ips)}'
    except Exception as e:
        gw_err = type(e).__name__
    add(OK if gw_ok else CRIT, 'DNS resolver', f"{HOST} resolved {DNS_PROBE} in {gw_ms:.0f} ms -> {', '.join(gw_ips[:3])}" if gw_ok else f'{HOST} did NOT resolve {DNS_PROBE} ({gw_err}) — this is the resolver every client on this LAN is handed by DHCP', [] if gw_ok else [f'{DNS_PROBE} via {HOST}: {gw_err}'])
    reach_ok = tcp_open(DNS_REACH, 443)
    if gw_ok and reach_ok:
        add(OK, 'DNS or WAN (attribution)', 'resolution and egress both healthy — nothing to attribute', [])
    elif not gw_ok and reach_ok:
        add(CRIT, 'DNS or WAN (attribution)', f"DNS FAULT, NOT A WAN FAULT: the path out is up (TCP 443 to {DNS_REACH} succeeded) but {DNS_PROBE} will not resolve. The gateway's own wan-failover monitor reads this same condition as 'Internet Down' and will count it against WAN uptime. Do not attribute this one to the ISP.", [f'resolve {DNS_PROBE} via {HOST}: FAIL ({gw_err})', f'TCP {DNS_REACH}:443: OK'])
    elif not gw_ok and (not reach_ok):
        add(WARN, 'DNS or WAN (attribution)', 'DNS and the external TCP probe both failed. WAN, routing, firewall policy or the probe target may be responsible; cause is unconfirmed.', [f'resolve {DNS_PROBE} via {HOST}: FAIL ({gw_err})', f'TCP {DNS_REACH}:443: FAIL'])
    else:
        add(WARN, 'DNS or WAN (attribution)', f'DNS resolves but TCP 443 to {DNS_REACH} does not — egress path or policy problem that name resolution alone would not have shown', [])
    try:
        recs = [r for r in get_static() if r.get('enabled') and r.get('record_type') == 'A']
    except Exception as e:
        recs = None
        add(INFO, 'DNS override integrity', f'could not read static-dns from the controller ({type(e).__name__}) — overrides unverified this run', [])
    if recs is not None:
        drift = []
        for r in recs:
            want, host = (r.get('value'), r.get('key'))
            try:
                rc, ips, _ = dns_query(HOST, host)
                if rc != 0 or want not in ips:
                    drift.append(f"{host}: configured {want}, resolver returned {', '.join(ips) or f'rcode={rc}'}")
            except Exception as e:
                drift.append(f'{host}: lookup failed ({type(e).__name__})')
        add(WARN if drift else OK, 'DNS override integrity', 'static DNS override(s) no longer resolve to their configured target — a split-horizon name pointing at the wrong place fails as a black hole, not an error' if drift else f'all {len(recs)} static A override(s) resolve to their configured target: ' + '; '.join((f"{r['key']}->{r['value']}" for r in recs)), drift if drift else [f"{r['key']} -> {r['value']}" for r in recs])
    leaks, unresolved = ([], [])
    try:
        rc, ips, _ = dns_query(DNS_PUBLIC, DNS_PROBE, timeout=DNS_BLOCK_TIMEOUT)
        leaks.append(f"plaintext 53 to {DNS_PUBLIC} ANSWERED (rcode={rc}) — 'Block External DNS' is not holding")
    except socket.timeout:
        pass
    except Exception as e:
        unresolved.append(f'53 probe inconclusive ({type(e).__name__})')
    now = int(time.time())
    try:
        st = json.load(open(DOT_STATE))
    except Exception:
        st = {}
    age = now - st.get('checked_at', 0)
    if age >= DOT_PROBE_INTERVAL or 'dot_leak' not in st:
        st = {'checked_at': now, 'dot_leak': tcp_open(DNS_PUBLIC, 853, timeout=DNS_BLOCK_TIMEOUT)}
        age = 0
        try:
            tmp = DOT_STATE + '.tmp'
            json.dump(st, open(tmp, 'w'))
            os.replace(tmp, DOT_STATE)
        except Exception:
            pass
    dot_age = 'just now' if age < 60 else f'{age // 60} min ago'
    if st.get('dot_leak'):
        leaks.append(f"DoT 853 to {DNS_PUBLIC} CONNECTED ({dot_age}) — 'Block External DoT' is not holding")
    if leaks:
        add(CRIT, 'DNS egress policy', 'egress DNS block has regressed', leaks + unresolved)
    elif not gw_ok or unresolved:
        add(INFO, 'DNS egress policy', "UNRESOLVED — 53 and 853 to a public resolver both failed, but the gateway resolver is also failing, so this run cannot tell an enforced block from a dead network. Re-reads as OK once 'DNS resolver' recovers.", unresolved)
    else:
        add(OK, 'DNS egress policy', f'plaintext 53 refused just now and DoT 853 refused {dot_age}, both to {DNS_PUBLIC}, while {HOST} resolves normally — the block is enforced, verified against a working control. DoT is probed hourly on purpose: each probe mints an amber security alert, so its cost sets its cadence. ⚠️ NOT a full DNS lockdown: DoH on 443 is open by design and unmeasured.', unresolved)
    return checks
