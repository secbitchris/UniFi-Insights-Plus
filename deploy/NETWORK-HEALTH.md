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

## Evidence improvements (BL-1327)

Disabled radios are listed separately from channel drift. Enabled radios without
a channel observation stay unknown. Port alerts use new errors between comparable
samples; resets and long gaps invalidate rates, while lifetime totals remain
visible context. Device last-seen times and explicit expected/retired policy are
local monitor state. Retired excludes a device only from the offline alert; it
does not delete or change it in UniFi. Settings writes use settings.write auth.

The UI separates fetch time from source sample time, hides stale latency, shows
warning status-since and clear transitions, and charts the last 24 hours or seven
days. Check explanations and device links accompany the evidence. Existing older
history has aggregate counts; per-check transitions begin after this upgrade.

For a headless Mac, deploy/study-probe/install.py installs the existing probe and
aggregator as system LaunchDaemons with UserName set to the existing non-root
account. It preserves the login-agent plists and refuses duplicates. Run locally
with sudo after reviewing the installer. No reboot or network change is performed.
Rollback: boot out the two com.unifi-insights.study-* jobs, remove their matching
LaunchDaemon plists, and restore the saved user LaunchAgent plists when desired.

### Planned offline state and link expectations

`intentionally_offline` is distinct from `retired`: the device remains in use but
is not expected online at present. Both remain visible and are excluded from the
offline alarm. Changing to `expected` restores offline alerting. These are local
monitor classifications and do not change UniFi configuration.

The policy can record `expected_speed_mbps`; later status-only updates preserve
it. Link metadata uses the newer device/parent observation and identifies its
source, avoiding a stale parent snapshot overriding a fresh reconnect report.
Expected speed is a monitoring value, never a forced negotiation setting.

## Ethernet evidence (BL-1331)

A separate read-only worker samples stat/device once per minute. It retains ten
preceding samples per device and captures an incident when a fresh connected
link reports 100 Mbps or less against an explicit gigabit-or-faster expectation
or a previously observed faster baseline on that same uplink. Explicit 100 Mbps,
intentionally offline and retired policies do not create incidents.

Captures include allowlisted AP and parent-switch identity, firmware, uptime,
port negotiation, PoE status, errors, drops, link-down counts, and derived
transitions. Both endpoints are saved. Counter resets, unchanged source
timestamps, stale observations, long gaps and changed uplinks cannot be treated
as measured error deltas. Native controller event logs are not collected: the
timeline describes observations between polls, not exact event times.
Transitions shorter than a poll interval may be missed.

State is atomically persisted in link-evidence.json on the existing volume.
The UI warns about unresolved incidents, shows the latest ten with active
incidents first, and exports incident or full retained evidence as JSON.
Each incident keeps its trigger and up to 59 later samples, plus ten preceding
samples. Retention is thirty days, capped at 100 incidents and 1000 transitions.
Active incidents survive API failures, missing inventory, and app restarts;
only observed speed recovery or an expectation change closes them. All
collection failures become stale/unknown within three minutes, preserving
prior evidence. No automatic reboot, PoE cycle, port change, or extra
AbuseIPDB lookup is performed.

## Native controller events (BL-1333)

The minute observer also queries the read-only v2 system-log/all API (POST is
the query method). It requests device, Ethernet-port, power and software-update
categories, excluding security and client activity. Startup queries seven days;
later queries overlap the previous successful time by ten minutes. Each poll
is capped at two 100-row pages and 1 MiB per response. Limit hits are explicitly
partial; failures preserve retained records and report unavailable status.

Normalized native records retain controller millisecond timestamps, IDs,
message templates and selected parameter fields. They are deduplicated and
limited to seven days/1000 records. Incidents retain up to 100 matching records
for the AP or parent switch, from ten minutes before detection to two minutes
after recovery. Native and sampled records remain separate in the UI and JSON.
A matching event is context, not proof of the physical cause. The controller may
not emit an event for every Ethernet renegotiation. No logging settings, device
configuration or credentials are changed.

## FE phone notifications (BL-1334)

The collector saves incident evidence before attempting notification. An
operator-owned notification-config.json in the existing private network-health
volume selects a local Home Assistant webhook; no general HA token is copied.
The dedicated HA automation forwards to the chosen mobile_app notification
service, with the incident ID as the notification tag and an app link.

Delivery state is atomic and persists across restarts. Existing incidents are
not replayed when enabling/re-enabling. One pending attempt is made per poll;
failures retry with exponential delays, at most five attempts. Success is not
resent. A lost HTTP acknowledgement can still cause a retry; the stable mobile
notification tag replaces that incident's previous notification. Delivery
status and failure count are visible in Network Health. No recovery or periodic
unchanged-state notifications are sent. A destination test is explicitly
labeled and uses a separate ID.
