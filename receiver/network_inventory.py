from network_basics import *

def assess(dev, sta, wlan, expected, DIR):
    aps = [d for d in dev if d.get('type') == 'uap']
    sws = [d for d in dev if d.get('type') == 'usw']
    names = {d.get('mac'): d.get('name') for d in dev}
    checks = []

    def add(sev, title, detail, items=None):
        checks.append({'severity': sev, 'title': title, 'detail': detail, 'items': items or [], 'why': WHY.get(title, '')})
    off = [d.get('name') for d in dev if d.get('type') in ('uap', 'usw') and d.get('state') != 1]
    add(CRIT if off else OK, 'Devices online', f'{len(off)} device(s) not in connected state' if off else f'all {len(aps) + len(sws)} APs and switches connected', off)
    roots = {d.get('root_switch') for d in sws if d.get('root_switch')}
    bad_roots = []
    for r in roots:
        if r not in names:
            who = next((f"{c.get('hostname') or c.get('name')} ({c.get('ip')})" for c in sta if (c.get('mac') or '').lower() == str(r).lower()), r)
            bad_roots.append(f'{r} = {who}')
    if bad_roots:
        add(CRIT, 'STP root bridge', 'root bridge is NOT a UniFi device — a third-party device is steering spanning tree for the whole LAN', bad_roots)
    else:
        rn = [names.get(r) for r in roots]
        add(OK, 'STP root bridge', f"root is {', '.join((x for x in rn if x))}", [])
    priorities = []
    for device in sws:
        try:
            raw = device.get('stp_priority')
            value = int(raw)
            if isinstance(raw, bool) or str(value) != str(raw) or not 0 <= value <= 65535:
                continue
            priorities.append((device.get('name'), value))
        except (TypeError, ValueError):
            continue
    weak = [f'{name} = {value}' for name, value in priorities if value >= 32768]
    stpv = sorted(value for _, value in priorities)
    add(WARN if weak else (OK if stpv else 'unknown'), 'STP priorities',
        'Switch priorities at or above 32768 can lose root selection to another device.' if weak
        else f'{len(stpv)} switch priorities assessed; {len(sws) - len(stpv)} unavailable or unsupported.', weak)
    TXHIST = DIR + '/aptxhist.json'
    TX_MIN_CLIENTS = 3
    TX_WINDOW = 6
    TX_HIST_MAX = 2016
    TX_BASELINE_MIN = 96
    TX_DROP = 0.5
    try:
        txh = json.load(open(TXHIST))
        if not isinstance(txh.get('aps'), dict):
            raise ValueError
    except Exception:
        txh = {'aps': {}}
    if time.time() - txh.get('sampled_at', 0) > 900:
        txh = {'aps': {}}
    txh['sampled_at'] = int(time.time())
    bad_ratio = []
    assessed_radios = 0
    for a in aps:
        name = str(a.get('name'))
        cl = [c for c in sta if c.get('ap_mac') == a.get('mac') and c.get('radio') == 'na' and ((c.get('rx_rate') or 0) > 0)]
        hist = txh['aps'].get(name) or []
        if len(cl) >= TX_MIN_CLIENTS:
            hist.append(round(statistics.median(((c.get('tx_rate') or 0) / c['rx_rate'] for c in cl)), 3))
        txh['aps'][name] = hist[-TX_HIST_MAX:]
        h = txh['aps'][name]
        now, base = (h[-TX_WINDOW:], h[:-TX_WINDOW])
        if len(now) >= TX_WINDOW and len(base) >= TX_BASELINE_MIN:
            assessed_radios += 1
            cm, bm = (statistics.median(now), statistics.median(base))
            if bm > 0 and cm < bm * TX_DROP:
                bad_ratio.append(f'{name} ratio {cm:.2f} vs its own baseline {bm:.2f} ({cm / bm:.0%} of normal, {len(base)} samples)')
    tmpX = TXHIST + '.tmp'
    json.dump(txh, open(tmpX, 'w'))
    os.replace(tmpX, TXHIST)
    add(WARN if bad_ratio else (OK if assessed_radios else 'unknown'), 'AP transmit health', 'AP(s) transmitting far slower than they receive — a wedged radio. Fix: PoE-cycle the port (a soft reboot does NOT clear it)' if bad_ratio else f'{assessed_radios} AP baselines assessed; other APs need at least 102 recent samples from three or more clients', bad_ratio)
    loads = []
    for a in aps:
        try:
            loads.append((a.get('name'), a.get('model') or '?', float(a.get('sys_stats', {}).get('loadavg_1') or 0), int(a.get('num_sta') or 0)))
        except (TypeError, ValueError):
            pass
    hi = [f'{n} load={v:.2f} (model {m}, ceiling {LOAD_CEILING.get(m, LOAD_DEFAULT)}, {c} clients)' for n, m, v, c in loads if v > LOAD_CEILING.get(m, LOAD_DEFAULT)]
    add(WARN if hi else OK, 'AP load', "AP(s) above their model's load ceiling" if hi else f"all {len(loads)} APs within their model's load ceiling", hi)
    drift = []
    for a in aps:
        exp = expected.get(a.get('name'))
        if not exp:
            continue
        cfg = next((r for r in a.get('radio_table', []) if r.get('radio') == 'na'), {})
        live = next((r for r in a.get('radio_table_stats', []) if r.get('radio') == 'na'), {})
        if exp.get('na') and live.get('channel') != exp['na']:
            drift.append(f"{a.get('name')} 5GHz on {live.get('channel')}, plan says {exp['na']}")
        eng = exp.get('ng')
        lng = next((r for r in a.get('radio_table_stats', []) if r.get('radio') == 'ng'), {})
        if eng and lng.get('channel') != eng:
            drift.append(f"{a.get('name')} 2.4GHz on {lng.get('channel')}, plan says {eng}")
    add(WARN if drift else OK, 'Channel plan', 'live channels differ from the intended plan' if drift else f'all {len(expected)} planned APs on their assigned channels' if expected else 'no expected plan configured', drift)
    vac = []
    for a in aps:
        for band in ('na', 'ng'):
            cfg = next((r for r in a.get('radio_table', []) if r.get('radio') == band), {})
            live = next((r for r in a.get('radio_table_stats', []) if r.get('radio') == band), {})
            if cfg.get('channel') and live.get('channel') and (cfg['channel'] != live['channel']):
                vac.append(f"{a.get('name')} {('5GHz' if band == 'na' else '2.4GHz')}: configured {cfg['channel']}, running {live['channel']}")
    add(WARN if vac else OK, 'DFS radar vacates', 'AP(s) not on their configured channel — usually a radar detection. Repeat offenders should move to non-DFS' if vac else 'all radios on their configured channel', vac)
    tight = []
    for c in sta:
        if c.get('is_wired') or not c.get('ap_mac'):
            continue
        ap = next((a for a in aps if a.get('mac') == c.get('ap_mac')), None)
        if not ap:
            continue
        r = next((x for x in ap.get('radio_table', []) if x.get('radio') == c.get('radio')), {})
        if not r.get('min_rssi_enabled'):
            continue
        sig, mr = (c.get('signal'), r.get('min_rssi'))
        if sig is None or mr is None:
            continue
        if sig - mr <= 4:
            who = c.get('mac') or '?'
            alias = c.get('name') or c.get('hostname')
            if alias and alias.lower() not in ('wlan0', (c.get('mac') or '').lower()):
                who = f'{who} ({alias})'
            tight.append(f"{who} on {ap.get('name')}: {sig} dBm vs threshold {mr} (margin {sig - mr:+d} dB)")
    add(WARN if tight else OK, 'Client eviction margin', 'client(s) within 4 dB of being kicked off by min-RSSI — they will flap' if tight else 'no clients near a min-RSSI threshold', tight[:12])
    slow = []
    for w in wlan:
        if not w.get('enabled') or '2g' not in (w.get('wlan_bands') or []):
            continue
        rate = w.get('minrate_ng_data_rate_kbps') if w.get('minrate_ng_enabled') else 1000
        if (rate or 0) < 6000:
            slow.append(f"{w.get('name')}: 2.4GHz minimum {rate} kbps")
    add(WARN if slow else OK, 'SSID beacon cost', 'SSID(s) beaconing at legacy rates — each costs multiples of the airtime of an 11 Mbps beacon, on every AP on the channel' if slow else 'all 2.4GHz SSIDs at 6 Mbps or better', slow)
    CU_CEILING_AC = 70
    CU_CEILING_U6 = 85
    AC_GEN = ('U7PG2', 'U7IW')
    busy = []
    for a in aps:
        ceil = CU_CEILING_AC if (a.get('model') or '') in AC_GEN else CU_CEILING_U6
        for r in a.get('radio_table_stats', []):
            cu = r.get('cu_total') or 0
            if cu > ceil:
                stx = r.get('cu_self_tx') or 0
                srx = r.get('cu_self_rx') or 0
                busy.append(f"{a.get('name')} {('5GHz' if r.get('radio') == 'na' else '2.4GHz')} ch{r.get('channel')} at {cu}% (self {stx + srx}%, other {cu - stx - srx}%; {a.get('model')} ceiling {ceil}%)")
    add(WARN if busy else OK, 'Channel utilisation', "radio(s) above their generation's airtime ceiling" if busy else f"all radios within their generation's ceiling (AC-gen {CU_CEILING_AC}%, U6/U7-gen {CU_CEILING_U6}%)", busy)
    perr = []
    for s in sws:
        for p in s.get('port_table', []):
            if not p.get('up'):
                continue
            if 'SFP' in str(p.get('name', '')):
                continue
            e = (p.get('rx_errors') or 0) + (p.get('tx_errors') or 0)
            if e > 1000:
                perr.append(f"{s.get('name')} port {p.get('port_idx')}: {e} errors")
    add(WARN if perr else OK, 'Switch port errors', 'copper port(s) with significant error counts' if perr else 'no copper port errors (SFP counters excluded — proven unreliable on this site)', perr)
    return checks
