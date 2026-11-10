"""Failure isolation and liveness for the shared daily scheduler."""
import logging
from pathlib import Path
import time

logger = logging.getLogger('scheduler')
HEARTBEAT = Path('/tmp/scheduler_heartbeat')


def guard_job(callback, **kwargs):
    """Return normally on failure so schedule advances this job's next run."""
    try:
        return callback(**kwargs)
    except Exception:
        logger.exception('Scheduled job %s failed; other jobs remain active', callback.__name__)


def tick_with_heartbeat(callback, db):
    """A transient tick failure must not terminate the scheduler thread."""
    try:
        callback(db)
        temporary = HEARTBEAT.with_suffix('.next')
        temporary.write_text(str(time.time()))
        temporary.replace(HEARTBEAT)
    except Exception:
        logger.exception('Scheduler tick failed; retrying in 10 seconds')


def scheduler_healthy():
    try:
        age = time.time() - float(HEARTBEAT.read_text())
        return 0 <= age <= 300
    except (OSError, ValueError):
        return False
