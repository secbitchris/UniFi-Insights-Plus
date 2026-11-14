#!/usr/bin/env python3
"""Install existing per-user probe scripts as non-root system launchd jobs.

Run with sudo on the target Mac: python3 install.py USERNAME.
Does not reboot, change interfaces/credentials, or replace probe source.
"""
import hashlib
import os
from pathlib import Path
import plistlib
import pwd
import shutil
import subprocess
import sys


def definitions(user, home):
    directory = str(home / 'netwatch')
    common = {'UserName': user, 'GroupName': 'staff', 'RunAtLoad': True,
              'WorkingDirectory': directory,
              'EnvironmentVariables': {'HOME': str(home), 'NETWATCH_DIR': directory},
              'StandardOutPath': '/dev/null'}
    ping = dict(common, Label='com.unifi-insights.study-pingwatch',
                ProgramArguments=['/bin/bash', directory + '/pingwatch.sh'],
                KeepAlive=True, ThrottleInterval=10,
                StandardErrorPath=directory + '/pingwatch.err')
    agg = dict(common, Label='com.unifi-insights.study-aggregate',
               ProgramArguments=['/usr/bin/python3', directory + '/summary2.py'],
               StartInterval=120, StandardErrorPath=directory + '/agg.err')
    agg['EnvironmentVariables'] = dict(common['EnvironmentVariables'], NETWATCH_LABELS=
        'LAN-gw-UDM,WAN-gw-ISP,Internet-IP,Internet-DNS,WiFi-gw-UDM,WiFi-WAN-ISP,WiFi-Internet-IP,WiFi-Internet-DNS')
    return [ping, agg]


def main(user):
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo; jobs themselves run as the named user.')
    account = pwd.getpwnam(user)
    if account.pw_uid == 0:
        raise SystemExit('Refusing root as the probe user')
    home = Path(account.pw_dir)
    directory = home / 'netwatch'
    jobs = definitions(user, home)
    targets = [Path('/Library/LaunchDaemons') / (job['Label'] + '.plist') for job in jobs]
    if any(target.exists() for target in targets):
        raise SystemExit('Study daemon already installed; inspect launchctl rather than overwriting it.')
    for filename in ['pingwatch.sh', 'summary2.py']:
        source = directory / filename
        if source.is_symlink() or not source.is_file() or source.stat().st_uid != account.pw_uid:
            raise SystemExit('Expected a regular probe script owned by the selected user: ' + str(source))
    old = [home / 'Library/LaunchAgents' / ('com.netwatch.' + name + '.plist') for name in ['pingwatch', 'agg']]
    backup = directory / 'launchagent-backup'
    if backup.exists():
        raise SystemExit('Backup directory already exists; inspect prior attempt before retrying.')
    # Check the old jobs before mutations, so the two schedulers cannot overlap.
    for name in ['pingwatch', 'agg']:
        result = subprocess.run(['launchctl', 'print', f'gui/{account.pw_uid}/com.netwatch.{name}'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0:
            raise SystemExit('Old login agent is loaded. Stop it before installing the boot job.')
    backup.mkdir(mode=0o700)
    os.chown(backup, account.pw_uid, account.pw_gid)
    installed = []
    moved = []
    try:
        for source in old:
            if source.exists():
                destination = backup / source.name
                shutil.move(str(source), str(destination))
                moved.append((source, destination))
        for job, target in zip(jobs, targets):
            target.write_bytes(plistlib.dumps(job))
            os.chmod(target, 0o644)
            os.chown(target, 0, 0)
            installed.append((job, target))
            subprocess.run(['plutil', '-lint', str(target)], check=True)
        for job, target in installed:
            subprocess.run(['launchctl', 'bootstrap', 'system', str(target)], check=True)
        for job, target in installed:
            subprocess.run(['launchctl', 'print', 'system/' + job['Label']], check=True)
    except Exception:
        for job, target in installed:
            subprocess.run(['launchctl', 'bootout', 'system/' + job['Label']], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            target.unlink(missing_ok=True)
        for source, destination in moved:
            shutil.move(str(destination), str(source))
        raise
    print('Installed boot jobs as ' + user + '. Original login plists retained at ' + str(backup))
    print('Verify pingwatch.csv advances and summary.json updates within two minutes. No reboot performed.')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('Usage: sudo python3 install.py USERNAME')
    main(sys.argv[1])
