# Lab 3.7.0 quota repair

This overlay retains upstream revision b4617fd and its deployed base image.
Build only from the reviewed, pushed lab-3.7 commit. It changes no credentials,
network policy, database schema, or existing log retention settings.

Passive blocked-flow and Pi-hole enrichment read cached intelligence up to 30
days old without individual API checks. Existing historical queue rows are
retained but neither seeded nor drained. Manual Lookup can refresh existing
scores and preserves the previous cache entry if the request fails.

Optional automatic checks default off. The deployment override enables a shared
maximum of 200 attempts per UTC day, spaced by at least 432 seconds. The five-minute
worker may achieve fewer (about 144 with both lanes busy). Reservations persist
under the existing PostgreSQL transaction advisory lock before HTTP; failed
requests count, and redeploying does not reset prior usage or pacing.

Two of every three due slots favor discovery of unknown public IPs with at least
ten blocked firewall events, or at least three blocked events across three
destination ports, in the last 24 hours. The third slot favors refresh of cached
scores older than seven days and seen in blocked traffic in the same window,
including prior scores of zero. Refresh priority grows with both age and risk:
age in days times (1 + score / 100). Empty lanes lend their slot to the other;
all attempts share the same daily ceiling, pacing and one-hour per-IP cooldown.
Private, multicast, WAN and gateway addresses are excluded. Future-dated log
records cannot qualify candidates. Candidate selection runs only when a slot is
due, uses the existing action/time index, and has a five-second query timeout.
It adds no database schema, queue writes, or per-event API calls.

The existing budget record accepts the new per-lane counters without resetting
its used count or next attempt time. Quota resets retain pacing and cooldowns
across midnight. The daily blacklist continues using its separate provider quota.

Scheduled jobs catch failures independently, including auth connection acquisition.
The scheduler retries failed ticks. Health returns 503 when its atomic heartbeat
is absent or over five minutes old. Allow startup time for database initialization
and the first blacklist download before expecting a healthy service.

## Deployment

From a verified archive of the reviewed lab-3.7 commit on CT138:

```
docker build -f Dockerfile.lab --build-arg SOURCE_REVISION=<commit> -t unifi-insights-lab:bl1286 .
```

Keep the original private Compose file in place. Save a private local backup of
any existing override before installing deploy/lab-quota.override.yml as
/opt/unifi-logs/docker-compose.override.yml. Check the merged Compose service:
only its image, pull policy, and background-budget environment setting should
change. Recreate only unifi-log-insight with `docker compose up -d --no-deps
unifi-log-insight` from /opt/unifi-logs. Never print the rendered configuration:
it contains credentials. Confirm image revision, scheduler health, fresh blacklist
cache, log ingestion, and retained provider pause/counters.

Rollback: restore the saved override (or remove only this task's override if none
existed), then recreate this service with the unchanged original Compose file.
The previous lab image and private configuration must remain available. No queue
or cache deletion is needed. Restoring the lab.1 override restores the prior
refresh-only policy with the same budget and working scheduler.

Provider counters and pause state must remain intact through deployment.
Do not clear quota state or force a check request for validation.
