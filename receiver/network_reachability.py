"""Read existing command-restricted reachability summaries; no host commands."""
import json
from pathlib import Path
import subprocess
import time

SOURCES = [('pvecore', 'root@192.168.1.25'), ('pvemacmini', 'root@192.168.1.32'),
           ('Study', 'chris@192.168.1.232'), ('Studio', 'chris@192.168.1.7')]


def collect(root):
    root = Path(root)
    key = root / 'ssh' / 'id_ed25519'
    known = root / 'ssh' / 'known_hosts'
    result = []
    for name, target in SOURCES:
        row = {'name': name, 'status': 'unknown'}
        try:
            if not key.is_file() or not known.is_file():
                raise ValueError('summary reader not configured')
            # No command: the existing authorized key forces the summary reader.
            p = subprocess.run(['ssh', '-F', '/dev/null', '-i', str(key),
                '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
                '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known),
                '-o', 'ConnectTimeout=3', target], capture_output=True, text=True, timeout=8)
            if p.returncode or len(p.stdout) > 2_000_000:
                raise ValueError('summary read failed')
            data = next(json.loads(line) for line in p.stdout.splitlines() if line.lstrip().startswith('{'))
            if not isinstance(data, dict):
                raise ValueError('invalid summary')
            row.update(status='received', summary=data, fetched_at=int(time.time()))
        except Exception as exc:
            row['error'] = type(exc).__name__
        result.append(row)
    return result
