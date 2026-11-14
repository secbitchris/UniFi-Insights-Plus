# Network Health migration — BL-1326

The Network Health tab moves the useful Netwatch checks into UniFi Insights.
It reuses the existing UniFi configuration and does not request AbuseIPDB data,
modify controller configuration, or run speed tests. Collection runs every five
minutes in its own worker; API failures do not stop the four DNS checks or the
existing receiver/scheduler. A snapshot older than 15 minutes is visibly stale.

## Coverage

| Legacy coverage | Replacement |
|---|---|
| Device availability, STP root/priorities | Network Health controller checks |
| AP transmit baseline, model-specific load | Network Health; unready baselines explicitly unknown |
| Channel plan, DFS, min RSSI, beacon cost, airtime | Network Health using existing thresholds and imported plan |
| Copper port errors, sustained RF, broadcast deltas, loop protection | Network Health; missing observations unknown |
| DNS resolver, DNS vs WAN, static overrides, DNS egress | Independent Network Health probes; DoT retains hourly cache |
| Watched-client presence/AP/signal and stored speedtest | Network Health snapshot and seven-day summary history |
| Four-location reachability | Existing restricted summary readers displayed in Network Health |
| Old outages, maintenance marks, raw samples and long-term history | Preserved on original hosts/CT113; not purged |

The old WAN-specific dashboard is retired, not its still-useful independent
location probes. Probe/aggregator units remain data producers. No claim is made
that a single ICMP failure proves an ISP outage. Historical maintenance annotations
are retained as evidence rather than silently reclassified.

## Persistent state and private reader

Bind /opt/unifi-logs/network-health on CT138 to /app/data/network-health in the
container. Mode 0700. The existing summary reader and private SSH key remain on
CT113. UniFi Insights reads its already-exposed /json endpoint from a private
reachability-source.json URL. No new listener, SSH grant, or key copy is needed.
The existing CT113 listener retires its HTML view via a redirect and preserves
only the summary route using deploy/retired_netwatch.py. Its service privileges
and port remain unchanged; no new service is created.

Import expected.json, watchlist.json, rfhist.json and dns-egress-state.json from
CT113 before startup. Preserve aptxhist.json as historical evidence: it lacks
sample timestamps, so do not qualify it as a fresh baseline. The new baseline
starts unknown. Retain all original Netwatch files and service units for rollback.

## Acceptance and retirement

Before stopping anything, verify tests and reviewed revision; image/health;
current controller and DNS rows; history surviving container recreation;
watched clients; and current source timestamps for all available vantage readers.
Unreachable sources stay explicitly unknown and cannot be called covered.
Then disable CT113 netwatch-health.timer, netwatch-hist.timer, and
the old HTML view (replace the existing listener executable with the compatibility endpoint). CT113 also runs Sonos: never stop the whole container.
Disable only the obsolete CT113-history backup timer after preserved history is
verified; retain the independent reachability producers and their evidence.
Point dashboard links to the new Network Health tab. Rollback restores the prior
Compose override and enables the old CT113 units; do not delete history or reset
provider quota state. Stop on unexpected deployment drift.
