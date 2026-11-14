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
WHY = {'Devices online': 'Read-only devices online assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'STP root bridge': 'Read-only stp root bridge assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'STP priorities': 'Read-only stp priorities assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'AP transmit health': 'Read-only ap transmit health assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'AP load': 'Read-only ap load assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'Channel plan': 'Read-only channel plan assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'DFS radar vacates': 'Read-only dfs radar vacates assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'Client eviction margin': 'Read-only client eviction margin assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'SSID beacon cost': 'Read-only ssid beacon cost assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'Channel utilisation': 'Read-only channel utilisation assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'Switch port errors': 'Read-only switch port errors assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'RF interference (sustained)': 'Read-only rf interference (sustained) assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'Broadcast storm (forensic)': 'Read-only broadcast storm (forensic) assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'Loop-risk port protection': 'Read-only loop-risk port protection assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'DNS resolver': 'Read-only dns resolver assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'DNS or WAN (attribution)': 'Read-only dns or wan (attribution) assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'DNS override integrity': 'Read-only dns override integrity assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.', 'DNS egress policy': 'Read-only dns egress policy assessment. Missing evidence is not proof of health; expand the result for scope and current measurements.'}

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
CRIT, WARN, INFO, OK = ('critical', 'warning', 'info', 'ok')
