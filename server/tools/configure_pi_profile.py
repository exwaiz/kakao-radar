import json
import os
from pathlib import Path
import sys
from uuid import UUID

from pi_paths import DATABASE_URL, PRIVATE_ENV, SERVER_ROOT, STATE_ROOT
root=Path(__file__).resolve().parents[2]
server=SERVER_ROOT
sys.path.insert(0,str(server))
from radar_server.store import Store
from radar_server.analysis_store import AnalysisStore
from radar_server.analysis_models import InterestProfile, ProfileUpdate
from radar_server.delivery_store import DeliveryStore
from radar_server.delivery_models import DeliveryPolicy, DeliveryPolicyUpdate
device=json.loads((STATE_ROOT/'device.json').read_text())
identifier=UUID(device['device'])
rooms=[UUID(value) for value in device.get('rooms',[device['room']] if 'room' in device else [])]
store=Store(DATABASE_URL)
store.migrate()
analysis=AnalysisStore(store)
profile=InterestProfile(enabled=True,interests=['삼성전자 관련 정보','많은 사람들이 공감하고 좋아하고 웃은 정보와 반응','반도체 산업','산업의 흐름','회사의 분위기','재밌는 이벤트','놓치면 안 될 정보','gossip 및 소문 (미확인 표시)','부동산 정보'],
    daily_token_limit=2_000_000,daily_cost_limit_microusd=1_000_000,
    batch_min_messages=30,batch_max_messages=10,max_wait_seconds=300,max_output_tokens=4096)
current=analysis.profile(identifier)
if current['profile']!=profile.model_dump():
    analysis.update_profile(identifier,ProfileUpdate(expected_version=current['version'],profile=profile))
delivery=DeliveryStore(store)
policy=DeliveryPolicy(enabled=True,channel='telegram',daily_times=[f'{hour:02}:00' for hour in range(24)],daily_notification_limit=24,urgent_enabled=False,include_source_quotes=True)
current=delivery.policy(identifier)
if not current['policy'].get('test_mode_until') and current['policy']!=policy.model_dump():
    delivery.update_policy(identifier,DeliveryPolicyUpdate(expected_version=current['version'],policy=policy))
if '--analyze' in sys.argv:
    from radar_server.openai_provider import OpenAIProvider
    from radar_server.worker import Worker
    for line in PRIVATE_ENV.read_text(encoding='utf-8').splitlines():
        name,sep,value=line.partition('=')
        if sep and name=='OPENAI_API_KEY': os.environ[name]=value.strip().strip('"').strip("'")
    worker=Worker(analysis,OpenAIProvider(os.environ['OPENAI_API_KEY']))
    outcomes={}
    for room in rooms:
        for _ in range(16):
            result=worker.process(identifier,room,force=True)
            outcomes[result]=outcomes.get(result,0)+1
            if result!='completed': break
    print(json.dumps({'analysis_outcomes':outcomes}))
print('Authorized interests, $1/day cap and hourly Asia/Seoul Telegram schedule configured; urgent disabled')
