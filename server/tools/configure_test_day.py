import json
import argparse
from datetime import datetime,time,timedelta
from pathlib import Path
import sys
from uuid import UUID
from zoneinfo import ZoneInfo
root=Path('/mnt/c/Users/exwai/Documents/Codex/2026-09-16/new-chat')
server=root/'outputs/kakao-radar-wsl/server'
sys.path.insert(0,str(server))
from radar_server.store import Store
from radar_server.delivery_store import DeliveryStore
from radar_server.delivery_models import DeliveryPolicy,DeliveryPolicyUpdate
parser=argparse.ArgumentParser()
parser.add_argument('--interval-minutes',type=int,choices=[10,30],default=30)
parser.add_argument('--max-topics',type=int,choices=range(1,11),default=5)
args=parser.parse_args()
interval=args.interval_minutes
store=Store('postgresql:///radar?user=kakaoradar&host=/var/run/postgresql')
device=UUID(json.loads((server/'.state/device.json').read_text())['device'])
delivery=DeliveryStore(store)
current=delivery.policy(device)
zone=ZoneInfo('Asia/Seoul')
with store.connect() as db:
    now=db.execute('SELECT clock_timestamp() AS instant').fetchone()['instant'].astimezone(zone)
deadline=datetime.combine(now.date()+timedelta(days=1),time(0),zone)
normal=current['policy']
policy=DeliveryPolicy.model_validate({**normal,'include_source_quotes':True,
    'daily_times':[f'{hour:02}:{minute:02}' for hour in range(24) for minute in range(0,60,interval)],
    'daily_notification_limit':24*60//interval,'test_mode_until':deadline.isoformat(),
    'max_topics_per_digest':args.max_topics,
    'resume_max_topics_per_digest':normal.get('resume_max_topics_per_digest') or normal['max_topics_per_digest'],
    'resume_daily_times':normal.get('resume_daily_times') or normal['daily_times'],
    'resume_daily_notification_limit':normal.get('resume_daily_notification_limit') or normal['daily_notification_limit']})
result=delivery.update_policy(device,DeliveryPolicyUpdate(expected_version=current['version'],policy=policy))
print(json.dumps({'test_interval_minutes':interval,'test_until':deadline.isoformat(),'next_due_at':str(result['next_due_at']),
    'quotes_from_real_evidence':True,'daily_test_limit':policy.daily_notification_limit,'max_topics_per_digest':policy.max_topics_per_digest,'resume_max_topics_per_digest':policy.resume_max_topics_per_digest,'resume_daily_times':policy.resume_daily_times,
    'resume_daily_notification_limit':policy.resume_daily_notification_limit}))
