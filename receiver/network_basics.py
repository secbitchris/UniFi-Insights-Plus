"""Retained Netwatch thresholds and measurement caveats (BL-1326)."""
import json, os, ssl, time, socket, statistics, urllib.request
DNS_PROBE = 'ui.com'
DNS_PUBLIC = '8.8.8.8'
DNS_REACH = '1.1.1.1'
DNS_TIMEOUT = 2.0
DNS_BLOCK_TIMEOUT = 1.5
DOT_PROBE_INTERVAL = 3600
LOAD_CEILING = {'UAP6MP': 4.0, 'UAPA6A5': 2.0, 'U6M': 2.0, 'UALR6v2': 1.5, 'UAPL6': 1.5, 'U7PG2': 1.5, 'U7IW': 1.5}
LOAD_DEFAULT = 2.0
WHY = {'Devices online': 'The cheapest possible check, and the one that catches a switch or AP that has dropped off entirely rather than degraded. Everything else here assumes the device is reachable, so this runs first.', 'STP root bridge': 'In August 2026 a Sonos BOOST was the spanning-tree root bridge for the entire wired LAN. Sonos advertises priority ~32768 and every switch sat at 61440, so a consumer speaker won the election and steered the whole fabric. This asserts the root is a UniFi device. Critical rather than warning because a third-party root affects every path in the network at once.', 'STP priorities': "The companion to the root check: it catches the condition BEFORE a Sonos device can win, rather than after. USW Aggregation is pinned to 4096 and Core US-24 to 8192, with access switches at 16384 — all below Sonos's ~32768. A switch that is factory-reset or newly adopted returns to 61440 and silently re-opens the door. It also names the two Flex switches that have no STP at all, so their absence is stated rather than inferred from a missing row.", 'AP transmit health': "A Studio U6-Pro once wedged with a downlink/uplink PHY ratio of 0.15 — it received normally but transmitted far slower, so clients associated fine and then crawled. It presents as 'the wifi is slow', not as a fault. A PoE cycle clears it; a soft reboot does not. Judged against each AP's OWN baseline, because the ratio is not comparable across APs: tx_rate is AP->client and rx_rate is client->AP, so an AP serving a camera and a thermostat sits at 0.16 forever while one with general-purpose clients sits at 1.00. Three absolute-threshold versions all convicted a healthy Living Room U6-LR — by mean of one sample, by sustained median, and by stability — the last because the controller leaves PHY rates FROZEN between refreshes, so 'stable' measured reporting latency rather than radio health. A wedge is a DEPARTURE from an AP's own normal, not a value: it fires below 50% of baseline, needs ~8 h of history first, and detects onset rather than a wedge left in place for a week.", 'AP load': "Was a flat loadavg > 2.0 across six different SoCs, which was wrong in both directions at once: it flagged the only U6-Pro forever (it idles ~3.0 and reproduced that across a cold boot, so it is baseline, not a fault) while staying silent on an AC Pro at 1.5, a genuine 5x excursion above its normal 0.02-0.84. Now judged against each model's own ceiling.", 'Channel plan': 'After a mass channel reassignment at 01:53, radios silently ended up somewhere other than the intended plan. The plan in expected.json is the intent; this reports drift from it. 2.4GHz here has only TWO usable channels, not three — channel 6 is reserved for the 30-device SonosNet mesh — so drift matters more than it would on a normal site.', 'DFS radar vacates': 'On DFS channels a radar detection moves the radio silently and immediately. The configured channel and the live channel then disagree, clients re-associate, and nothing in the UI announces it. This compares the two.', 'Client eviction margin': 'min-RSSI evicts a client below a threshold. It is a ROAMING aid — it assumes the client can move to a better AP — and roughly 87% of this network is stationary IoT that cannot. Every client that has ever been near the threshold here was fixed, never mobile. A Ring doorbell sat 2 dB above the floor and flapped. Thresholds are now a uniform -85 fleet-wide.', 'SSID beacon cost': 'The gentlework SSID beaconed at 1 Mbps while others ran 11 Mbps. A 1 Mbps beacon occupies ~2.2 ms versus ~0.28 ms, and with six APs on a channel that single dormant SSID with one client was burning ~13% of the band. Raising it dropped mean 2.4GHz utilisation across all 11 APs by 12.2 points.', 'Channel utilisation': 'cu_total does not mean the same thing on every AP here, so one threshold cannot either. AC-gen radios report mostly their own traffic; U6/U7-gen report mostly ambient energy. Outdoor U6M sits ~50% while serving ONE client, whereas Bike Shed with one client reads 1%. Thresholded per generation. Same-AP-over-time comparison is valid; cross-AP is not.', 'Switch port errors': 'Deliberately EXCLUDES SFP rx_error counters, which were proven to be false positives on this site — they accumulate without any corresponding fault. A check that cries wolf gets ignored, so the noisy counter is left out rather than explained away every time someone looks.', 'RF interference (sustained)': "Distinguishes 'the band is busy with our own clients' from 'the band is busy with someone else's energy', which need opposite responses — more capacity helps the first and nothing helps the second. Judged on a ~2h median because point samples swung 17 points in 60 seconds. Radios whose cu_self_rx counter reads 0 while clients are associated are EXCLUDED and counted, because on those the subtraction would misread our own traffic as interference.", 'Broadcast storm (forensic)': "Two Flex switches have no STP at all — hardware limit — so a loop behind one has nothing to break it. FORENSIC, NOT PREVENTIVE: this collector shares a broadcast domain with every switch it polls, so a storm may stop it running. Counters are cumulative, so the next successful poll still shows the whole delta. It answers 'the link dropped at 03:00, was it a storm and on which switch', not 'is one happening now'. Threshold is a storm-scale absolute, not a baseline.", 'Loop-risk port protection': 'Broadcast storm control was set on the two ports feeding the STP-incapable Flex switches, and a later port-mode change SILENTLY DISCARDED it — the write rewrote the override without carrying the stormctrl keys forward. Nothing reported it: the UI looked right, the network was healthy, and the rate check stayed green because the rates were fine. A cap that has evaporated and a cap that works look identical from a rate check, so this asserts the control still EXISTS. Ports are derived from topology, not hardcoded, so it follows a Flex that moves.', 'DNS resolver': 'Nothing on this page covered DNS at all until 2026-08-12, while every device on the LAN — all 44 containers included — is handed 192.168.1.1 and nothing else. A resolver that stops answering takes the whole site down and would have shown up here only as unrelated symptoms. Probes the gateway directly rather than through getaddrinfo, so it measures THE resolver and not a local cache.', 'DNS or WAN (attribution)': '🔴 THE REASON THIS GROUP EXISTS. The UDM decides WAN up/down from a DNS probe: `dns_verification` resolves ui.com against 1.1.1.1 and 8.8.8.8, and on 2026-08-12 it marked eth8 DOWN at 16:26:33 off the DNS monitors — four seconds BEFORE the ICMP monitor alarmed. So a pure DNS fault is recorded as an ISP outage, and the availability figures quoted from those probes (1.1.1.1 66%, ping.ui.com 12.5% that day) are DNS-weighted, not reachability. ping.ui.com scores worst of all because it has to be RESOLVED before it can be pinged. This check splits the two by pairing resolution against a non-DNS reachability leg, so an outage gets attributed to the right layer before it reaches a Verizon report.', 'DNS override integrity': 'Four public names are overridden to private IPs here, including fleet.product.corelight.io — a vendor domain pointed at 192.168.7.10. When one of these goes stale it fails as a BLACK HOLE, not an error: the name still resolves, packets go to an address nobody answers on, and every layer above reports a timeout. Records are read from the controller each run instead of hardcoded, so this follows an override that is added or retargeted in the UI.', 'DNS egress policy': "Plaintext 53 and DoT 853 to public resolvers are blocked (101,657 and 25,521 hits in six days), and a firewall rule can be deleted or reordered without anything on this network noticing — normal traffic looks identical either way. ⭐ ALWAYS READ WITH ITS CONTROL: a silent drop is what an enforced block AND a dead network both look like, so this reports UNRESOLVED rather than OK whenever 'DNS resolver' is also failing. ⚠️ Scope is deliberately narrow — DoH on 443 is wide open and this check does NOT cover it, so a green result here means the plaintext block holds, not that DNS is locked down."}

def _dns_pack(name, qid=20055):
    q = b''.join((bytes([len(l)]) + l.encode() for l in name.split('.'))) + b'\x00'
    return qid.to_bytes(2, 'big') + b'\x01\x00' + b'\x00\x01' + b'\x00\x00' * 3 + q + b'\x00\x01\x00\x01'

def _dns_parse_a(resp):
    rcode = resp[3] & 15
    qd, an = (int.from_bytes(resp[4:6], 'big'), int.from_bytes(resp[6:8], 'big'))

    def skip(i):
        while True:
            n = resp[i]
            if n == 0:
                return i + 1
            if n & 192 == 192:
                return i + 2
            i += 1 + n
    i = 12
    for _ in range(qd):
        i = skip(i) + 4
    ips = []
    for _ in range(an):
        i = skip(i)
        rtype = int.from_bytes(resp[i:i + 2], 'big')
        i += 8
        rdlen = int.from_bytes(resp[i:i + 2], 'big')
        i += 2
        if rtype == 1 and rdlen == 4:
            ips.append('.'.join((str(b) for b in resp[i:i + rdlen])))
        i += rdlen
    return (rcode, ips)

def dns_query(server, name, timeout=DNS_TIMEOUT):
    """A-record query aimed at `server`. Returns (rcode, [ips], ms).

    🔴 RAISES ON TIMEOUT, AND A TIMEOUT IS AMBIGUOUS BY CONSTRUCTION. On this LAN a
    silent drop is what a WORKING egress block looks like and what a DEAD resolver
    looks like. No caller may read a timeout as "DNS is broken" without a control —
    see the "DNS egress policy" check, which resolves through the gateway first.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    t0 = time.monotonic()
    try:
        s.sendto(_dns_pack(name), (server, 53))
        resp, _ = s.recvfrom(2048)
    finally:
        s.close()
    rcode, ips = _dns_parse_a(resp)
    return (rcode, ips, (time.monotonic() - t0) * 1000)

def tcp_open(host, port, timeout=DNS_TIMEOUT):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False

CRIT, WARN, INFO, OK = "critical", "warning", "info", "ok"
