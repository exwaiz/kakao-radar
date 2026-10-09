"""Briefly wake KakaoTalk five minutes before a scheduled Telegram digest."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from datetime import timedelta
from uuid import UUID

from pi_paths import DATABASE_URL, STATE_ROOT

SERVER_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER_ROOT))

from radar_server.analysis_store import AnalysisStore
from radar_server.delivery_store import DeliveryStore
from radar_server.store import Store


def pending_digest(delivery, analysis, device):
    with delivery.store.connect() as db:
        delivery._device(db, device)
        _, policy, due = delivery._settings(db, device)
        now = delivery._now(db)
        if not policy.enabled or due is None:
            return None, "delivery_disabled"
        seconds = (due - now).total_seconds()
        if not 240 <= seconds <= 360:
            return None, "outside_wake_window"
        if due.astimezone(__import__('zoneinfo').ZoneInfo(policy.timezone)).strftime('%H:%M') not in policy.daily_times:
            return None, "not_a_scheduled_slot"
        profile_version, profile = analysis._profile(db, device)
        if not profile.enabled:
            return None, "analysis_disabled"
        pending = db.execute("""SELECT 1 FROM delivery_outbox WHERE device_id=%s
            AND status IN ('pending','retry_wait') AND not_before<=%s LIMIT 1""", (device, due)).fetchone()
        if pending:
            return due, "pending_outbox"
        for route in delivery._routes(db, device):
            if delivery._topics(db, device, policy, profile_version, now, room=route['room_id']):
                return due, "eligible_summaries"
    return None, "no_sendable_summary"


def invoke(adb, serial, activity):
    result = subprocess.run(
        [adb, '-s', serial, 'shell', 'am', 'start', '-W', '-n', activity],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=25, check=False, env=os.environ.copy(),
    )
    return result.returncode == 0 and b'Status: ok' in result.stdout


def go_home(adb, serial):
    result = subprocess.run(
        [adb, '-s', serial, 'shell', 'am', 'start', '-W', '-a',
         'android.intent.action.MAIN', '-c', 'android.intent.category.HOME'],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=25, check=False, env=os.environ.copy(),
    )
    return result.returncode == 0 and b'Status: ok' in result.stdout


def remember_slot(path, slot):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.kakao-wake-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(slot.isoformat() + '\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--adb', default='/usr/bin/adb')
    parser.add_argument('--serial', default=os.environ.get('RADAR_ANDROID_SERIAL', ''))
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not args.serial:
        print('wake_skipped=adb_serial_missing', flush=True)
        return 0

    state = json.loads((STATE_ROOT / 'device.json').read_text(encoding='utf-8'))
    device = UUID(state['device'])
    store = Store(DATABASE_URL)
    delivery = DeliveryStore(store)
    due, reason = pending_digest(delivery, AnalysisStore(store), device)
    if due is None:
        print('wake_skipped=' + reason, flush=True)
        return 0

    last_path = STATE_ROOT / 'kakao-wake-last-slot'
    if last_path.exists() and last_path.read_text(encoding='utf-8').strip() == due.isoformat():
        print('wake_skipped=already_attempted', flush=True)
        return 0
    if args.dry_run:
        print('wake_due=' + due.isoformat() + ' reason=' + reason, flush=True)
        return 0

    if not invoke(args.adb, args.serial, 'com.kakao.talk/.activity.SplashActivity'):
        print('wake_result=kakao_launch_failed', flush=True)
        return 1
    remember_slot(last_path, due)
    time.sleep(3)
    if not go_home(args.adb, args.serial):
        print('wake_result=kakao_opened_home_restore_failed', flush=True)
        return 1
    print('wake_result=completed', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
