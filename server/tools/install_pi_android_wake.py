"""Install the optional pre-delivery KakaoTalk wake timer on a Pi."""
import argparse
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess

from pi_paths import PROJECT_ROOT, STATE_ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--serial', default=os.environ.get('RADAR_ANDROID_SERIAL'), required=not bool(os.environ.get('RADAR_ANDROID_SERIAL')))
    parser.add_argument('--adb-user', default=os.environ.get('SUDO_USER'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit('Run with sudo to install the systemd units.')
    if not args.adb_user:
        raise SystemExit('Pass --adb-user with the Linux account that owns the authorized ADB key.')
    try:
        pwd.getpwnam(args.adb_user)
    except KeyError:
        raise SystemExit('Unknown ADB user.') from None
    if not re.fullmatch(r'[A-Za-z0-9._:-]{1,160}', args.serial or ''):
        raise SystemExit('Invalid ADB serial.')
    if any(char in str(PROJECT_ROOT) for char in '\n\r"'):
        raise SystemExit('Project path cannot be represented in the systemd environment file.')

    config = Path('/etc/default/kakao-radar-adb')
    config.write_text(
        f'RADAR_ANDROID_SERIAL={args.serial}\n'
        f'RADAR_PROJECT_ROOT={PROJECT_ROOT}\n'
        f'RADAR_PYTHON={STATE_ROOT}/venv/bin/python\n',
        encoding='utf-8',
    )
    os.chown(config, 0, 0)
    os.chmod(config, 0o644)
    unit_dir = Path('/etc/systemd/system')
    source_dir = PROJECT_ROOT / 'server/systemd'
    shutil.copyfile(source_dir / 'kakao-radar-adb@.service', unit_dir / 'kakao-radar-adb@.service')
    shutil.copyfile(source_dir / 'kakao-radar-kakao-wake.service', unit_dir / 'kakao-radar-kakao-wake.service')
    shutil.copyfile(source_dir / 'kakao-radar-kakao-wake.timer', unit_dir / 'kakao-radar-kakao-wake.timer')
    for name in ('kakao-radar-adb@.service','kakao-radar-kakao-wake.service','kakao-radar-kakao-wake.timer'):
        os.chown(unit_dir / name, 0, 0)
        os.chmod(unit_dir / name, 0o644)
    subprocess.run(['systemctl','disable','--now','kakao-radar-adb.service'], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['systemctl','daemon-reload'], check=True)
    subprocess.run(['systemctl','enable','--now',f'kakao-radar-adb@{args.adb_user}.service',
                    'kakao-radar-kakao-wake.timer'],check=True)
    print('ADB wake timer enabled; KakaoTalk is opened five minutes before eligible hourly deliveries.')


if __name__ == '__main__':
    main()
