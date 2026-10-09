"""Control the headless Android collector over an authorized ADB transport.

No message text or credentials are passed as Intent extras. The receiver requires
Android's signature DUMP permission, which the adb shell holds.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time


PACKAGE = 'dev.kakaoradar.collector'
RECEIVER = PACKAGE + '/.AdbControlReceiver'
ACTION = PACKAGE + '.CONTROL'


def adb_prefix(args):
    return [args.adb, '-s', args.serial]


def invoke(args, *parts, timeout=45):
    return subprocess.run(adb_prefix(args) + list(parts), text=True,
                          stdin=subprocess.DEVNULL, capture_output=True,
                          timeout=timeout, check=False)


def ensure_link(args):
    for attempt in range(4):
        state = invoke(args, 'get-state', timeout=5)
        if state.returncode == 0 and state.stdout.strip() == 'device':
            break
        subprocess.run([args.adb, 'connect', args.serial], text=True,
                       stdin=subprocess.DEVNULL, capture_output=True, timeout=8, check=False)
        time.sleep(1)
    else:
        raise RuntimeError('phone_not_connected')
    reverse = invoke(args, 'reverse', 'tcp:8443', 'tcp:8443', timeout=8)
    if reverse.returncode != 0:
        raise RuntimeError('adb_reverse_failed')
    listing = invoke(args, 'reverse', '--list', timeout=8)
    if listing.returncode != 0 or 'tcp:8443 tcp:8443' not in listing.stdout:
        raise RuntimeError('adb_reverse_missing')
    return {'adb': 'device', 'reverse_8443': True}


def control(args, command, **extras):
    payload = broadcast(args, command, **extras)
    if payload is None:
        started = invoke(args, 'shell', 'am', 'start', '-W', '-n',
                         PACKAGE + '/.AdbBootstrapActivity', timeout=20)
        if started.returncode != 0 or 'Status: ok' not in started.stdout:
            raise RuntimeError('collector_start_failed')
        payload = broadcast(args, command, **extras)
    if payload is None:
        raise RuntimeError('control_reply_missing')
    return payload


def broadcast(args, command, **extras):
    argv = ['shell', 'am', 'broadcast', '--include-stopped-packages',
            '-a', ACTION, '-n', RECEIVER,
            '--es', 'command', command]
    for key, value in extras.items():
        argv += ['--es', key, value]
    result = invoke(args, *argv, timeout=45)
    if result.returncode != 0:
        raise RuntimeError('control_broadcast_failed')
    line = next((line for line in result.stdout.splitlines()
                 if 'Broadcast completed:' in line), '')
    match = re.search(r'data="(\{.*\})"', line)
    if not match:
        return None
    raw = match.group(1)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        payload = json.loads(raw.replace('\\"', '"'))
    if not isinstance(payload, dict):
        raise RuntimeError('control_reply_invalid')
    return payload


def drain(args):
    processed = 0
    rounds = 0
    pending = None
    for _ in range(args.max_batches):
        result = control(args, 'sync-once')
        if not result.get('ok'):
            raise RuntimeError('sync_' + str(result.get('error', result.get('outcome', 'failed'))))
        rounds += 1
        pending = result.get('pending')
        processed += result.get('processed', 0)
        if result.get('outcome') == 'IDLE' and pending:
            raise RuntimeError('pending_rooms_not_selected')
        if result.get('outcome') == 'IDLE' or pending == 0:
            break
        if result.get('outcome') != 'SENT' or result.get('processed', 0) <= 0:
            raise RuntimeError('sync_no_progress')
    return {'batches': rounds, 'processed': processed, 'pending': pending}


def reconnect_listener(args):
    component = PACKAGE + '/' + PACKAGE + '.CollectorService'
    for command in ('disallow_listener', 'allow_listener'):
        result = invoke(args, 'shell', 'cmd', 'notification', command, component, timeout=10)
        if result.returncode != 0:
            raise RuntimeError('listener_' + command + '_failed')
    control(args, 'listener-rebind')
    for _ in range(5):
        time.sleep(1)
        state = control(args, 'status')
        if state.get('listener_connected'):
            return {'listener_connected': True}
    raise RuntimeError('listener_reconnect_failed')


def export(args, command):
    if not args.output:
        raise RuntimeError('output_path_required')
    result = control(args, command)
    if not result.get('ok'):
        return result
    private_path = result.get('path', '')
    if not re.fullmatch(r'files/exports/radar-[0-9]+-(messages|diagnostics)\.jsonl', private_path):
        raise RuntimeError('export_path_invalid')
    destination = Path(args.output)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            copied = subprocess.run(adb_prefix(args) + ['exec-out', 'run-as', PACKAGE, 'cat', private_path],
                                    stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL,
                                    timeout=120, check=False)
        if copied.returncode != 0:
            destination.unlink(missing_ok=True)
            raise RuntimeError('export_copy_failed')
    finally:
        invoke(args, 'shell', 'run-as', PACKAGE, 'rm', private_path, timeout=10)
    return {'ok': True, 'output': str(destination), 'bytes': destination.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=[
        'link', 'maintain', 'status', 'rooms', 'collection-enable', 'collection-disable',
        'room-select', 'room-remove', 'listener-rebind', 'listener-reconnect',
        'sync-once', 'sync-drain',
        'sync-enable', 'sync-disable', 'sync-reload', 'export-diagnostics',
        'export-messages', 'clear-local'])
    parser.add_argument('value', nargs='?', help='candidate ID or room ID')
    parser.add_argument('--serial', default=os.environ.get('RADAR_ANDROID_SERIAL', ''))
    parser.add_argument('--adb', default='/usr/bin/adb')
    parser.add_argument('--max-batches', type=int, default=40)
    parser.add_argument('--output')
    parser.add_argument('--confirm', default='')
    args = parser.parse_args()
    if not args.serial:
        parser.error('--serial or RADAR_ANDROID_SERIAL is required')
    if not 1 <= args.max_batches <= 100:
        parser.error('--max-batches must be between 1 and 100')
    try:
        if args.command in ('link', 'maintain'):
            link = ensure_link(args)
            if args.command == 'link':
                payload = link
            else:
                state = control(args, 'status')
                listener = (reconnect_listener(args) if state.get('listener_granted') and
                            not state.get('listener_connected') else
                            {'listener_connected': bool(state.get('listener_connected'))})
                upload = drain(args) if state.get('sync_enabled') else {'sync_enabled': False,
                                                                        'pending': state.get('pending')}
                payload = {**link, **listener, **upload}
        elif args.command == 'sync-drain':
            payload = {'ok': True, **drain(args)}
        elif args.command == 'listener-reconnect':
            payload = {'ok': True, **reconnect_listener(args)}
        elif args.command in ('export-diagnostics', 'export-messages'):
            payload = export(args, args.command)
        else:
            extras = {}
            if args.command == 'room-select':
                if not args.value: parser.error('room-select requires a candidate ID')
                extras['candidate_id'] = args.value
            elif args.command == 'room-remove':
                if not args.value: parser.error('room-remove requires a room ID')
                extras['room_id'] = args.value
            elif args.command == 'clear-local':
                extras['confirm'] = args.confirm
            payload = control(args, args.command, **extras)
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0 if payload.get('ok', True) else 1
    except (RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
