from network_basics import *

def assess(dev, sta, wlan, expected, DIR):
    aps = [d for d in dev if d.get('type') == 'uap']
    sws = [d for d in dev if d.get('type') == 'usw']
    names = {d.get('mac'): d.get('name') for d in dev}
    checks = []

    def add(sev, title, detail, items=None):
        checks.append({'severity': sev, 'title': title, 'detail': detail, 'items': items or [], 'why': WHY.get(title, '')})
    HIST = DIR + '/rfhist.json'
    try:
        hist = json.load(open(HIST))
        if not isinstance(hist.get('samples'), list):
            raise ValueError
    except Exception:
        hist = {'samples': []}
    hist['samples'] = [s for s in hist['samples'] if 0 <= time.time() - s.get('t', 0) <= 7 * 86400]
    snap = {}
    for a in aps:
        for s in a.get('radio_table_stats', []):
            band = '2.4' if s.get('radio') == 'ng' else '5'
            tot = s.get('cu_total') or 0
            srx = s.get('cu_self_rx') or 0
            other = tot - srx - (s.get('cu_self_tx') or 0)
            ncl = sum((1 for c in sta if c.get('ap_mac') == a.get('mac') and c.get('radio') == s.get('radio')))
            trust = 1 if srx > 0 or ncl == 0 else 0
            snap[str(a.get('name')) + '|' + band] = [tot, max(other, 0), s.get('channel'), trust]
    prev = hist['samples'][-1] if hist['samples'] else None
    bsnap = {}
    for d in sws:
        for p in d.get('port_table', []):
            if not p.get('up'):
                continue
            bsnap[str(d.get('name')) + '|' + str(p.get('port_idx'))] = [(p.get('rx_broadcast') or 0) + (p.get('tx_broadcast') or 0), (p.get('rx_multicast') or 0) + (p.get('tx_multicast') or 0)]
    hist['samples'].append({'t': int(time.time()), 'r': snap, 'b': bsnap})
    hist['samples'] = hist['samples'][-2016:]
    tmpH = HIST + '.tmp'
    json.dump(hist, open(tmpH, 'w'))
    os.replace(tmpH, HIST)
    excl = sorted((k for k, v in snap.items() if len(v) > 3 and (not v[3])))
    ex24 = sum((1 for k in excl if k.endswith('|2.4')))
    ex5 = len(excl) - ex24
    recent = hist['samples'][-24:]
    noisy, skipped = ([], set())
    if len(recent) >= 6:
        keys = set()
        for smp in recent:
            keys |= set(smp['r'])
        for kk in sorted(keys):
            recs = [smp['r'][kk] for smp in recent if kk in smp['r']]
            if not recs or not all((len(x) > 3 and x[3] for x in recs)):
                skipped.add(kk)
                continue
            vals = [x[1] for x in recs]
            if len(vals) < 6:
                continue
            med = statistics.median(vals)
            if med >= 30:
                ch = (recent[-1]['r'].get(kk) or [0, 0, '?'])[2]
                nm, bd = kk.rsplit('|', 1)
                noisy.append(nm + ' ' + bd + 'GHz ch' + str(ch) + ': median ' + str(round(med)) + '% external airtime over ' + str(len(vals)) + ' samples (min ' + str(min(vals)) + '% max ' + str(max(vals)) + '%)')
    add(WARN if noisy else (OK if len(recent) >= 6 and len(snap) > len(excl) else 'unknown'), 'RF interference (sustained)', 'radio(s) losing sustained airtime to energy that is NOT our traffic — this is not client congestion, so more capacity or a wider channel will not help' if noisy else 'no radio above 30% sustained external airtime. ' + str(len(snap) - len(excl)) + ' of ' + str(len(snap)) + ' radios covered, ' + str(len(hist['samples'])) + ' samples banked. NOT COVERED this run: ' + str(ex24) + 'x 2.4GHz, ' + str(ex5) + 'x 5GHz - cu_self_rx reads 0 while clients are associated, so total-minus-self would misread own traffic as interference. Set varies per run as clients move.', noisy)
    BCAST_STORM_PPS = 500
    storm = []
    covered = 0
    if prev and prev.get('b'):
        el = max(1, int(time.time()) - int(prev.get('t', 0)))
        for k, cur in bsnap.items():
            old = prev['b'].get(k)
            if not old:
                continue
            db, dm = (cur[0] - old[0], cur[1] - old[1])
            if db < 0 or dm < 0:
                continue
            covered += 1
            if db / el > BCAST_STORM_PPS:
                sw, pi = k.rsplit('|', 1)
                storm.append(sw + ' port ' + pi + ': ' + str(round(db / el)) + ' bcast/s over ' + str(el) + 's (storm threshold ' + str(BCAST_STORM_PPS) + '/s; mcast ' + str(round(dm / el)) + '/s)')
    add(WARN if storm else (OK if covered else 'unknown'), 'Broadcast storm (forensic)', 'broadcast rate at storm level — check for a loop, especially behind the two Flex switches, which cannot break one' if storm else 'no port above ' + str(BCAST_STORM_PPS) + ' bcast/s. ' + str(covered) + ' port(s) rate-compared against the previous sample. FORENSIC ONLY: this host shares a broadcast domain with what it polls, so it may not run during a storm — cumulative counters mean the next good poll still shows it. Not a substitute for storm control, which is off fleet-wide.' if covered else 'no previous broadcast sample yet — first run after deploy, or history was reset. A rate needs two samples; this will report properly next run.', storm)
    noloop = [d for d in sws if not d.get('stp_version')]
    unprot, undisc, prot = ([], [], [])
    for d in noloop:
        up = d.get('uplink') or {}
        pname, pidx = (up.get('uplink_device_name'), up.get('uplink_remote_port'))
        parent = next((s for s in sws if s.get('name') == pname), None) if pname else None
        if parent is None or pidx is None:
            undisc.append(str(d.get('name')) + ' (uplink not resolvable: dev=' + str(pname) + ' port=' + str(pidx) + ')')
            continue
        ov = next((o for o in parent.get('port_overrides', []) if o.get('port_idx') == pidx), None)
        where = str(pname) + ' p' + str(pidx) + ' -> ' + str(d.get('name'))
        if ov and ov.get('stormctrl_bcast_enabled'):
            lvl = ov.get('stormctrl_bcast_level')
            rt = ov.get('stormctrl_bcast_rate')
            prot.append(where + ' (' + (str(lvl) + '%' if ov.get('stormctrl_type') == 'level' else str(rt) + 'pps') + ')')
        else:
            unprot.append(where + ' — broadcast storm control NOT enabled on the parent port')
    bad = unprot + undisc
    add(WARN if bad else OK, 'Loop-risk port protection', 'port(s) feeding an STP-incapable switch have no broadcast cap — a loop behind one has nothing to break it AND nothing to limit it. Re-check after any port-mode change, which is known to discard these settings silently' if bad else 'all ' + str(len(prot)) + ' port(s) feeding STP-incapable switches have broadcast storm control: ' + '; '.join(prot) + '. Asserts the CONTROL EXISTS, which a rate check cannot — a cap that silently evaporated looks identical to one that works.', bad if bad else prot)
    return checks
