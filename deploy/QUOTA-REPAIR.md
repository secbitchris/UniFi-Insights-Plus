# Lab 3.7.0 quota repair

This overlay retains upstream revision b4617fd and its deployed base image.
Build only from the reviewed, pushed lab-3.7 commit. It changes no credentials,
network policy, database schema, or existing log retention settings.

Passive blocked-flow and Pi-hole enrichment read cached intelligence up to 30
days old without individual API checks. Existing historical queue rows are
retained but neither seeded nor drained. Manual Lookup can refresh existing
scores and preserves the previous cache entry if the request fails.

Optional background refresh defaults off. The deployment override enables up to
200 attempts per UTC day, spaced by at least 432 seconds. The five-minute worker
may achieve fewer. Only scores >=25 seen in the past 24 hours and checked more
than seven days ago qualify. Reservations are committed under a PostgreSQL
transaction advisory lock before HTTP, survive restarts, and count failed attempts.
The daily blacklist uses its separate provider quota and refreshes normally.

Scheduled jobs catch failures independently, including auth connection acquisition.
The scheduler retries failed ticks. Health returns 503 when its atomic heartbeat
is absent or over five minutes old. Allow startup time for database initialization
and the first blacklist download before expecting a healthy service.

## Deployment

From a verified archive of the reviewed lab-3.7 commit on CT138:

```
docker build -f Dockerfile.lab --build-arg SOURCE_REVISION=<commit> -t unifi-insights-lab:bl1238 .
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
The original image and private configuration must remain available. No queue or
cache deletion is needed. This restores the prior quota behavior and scheduler bug.

The existing provider allowance remains exhausted until its normal reset; the
repair must not clear pause state or force a check request for validation.
