import os
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from radar_server.analysis_models import ProfileUpdate
from radar_server.app import create_app
from radar_server.delivery_channels import ChannelResult, DigestLinks, NtfyChannel
from radar_server.delivery_worker import DeliveryWorker
from radar_server.providers import ExtractiveProvider
from radar_server.worker import Worker


@pytest.fixture
def setup():
    dsn = os.environ.get("RADAR_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Dedicated PostgreSQL test DB required")
    links = DigestLinks("https://radar.example.com", "synthetic-secret-" + "s" * 32)
    app = create_app(dsn, digest_links=links)
    with TestClient(app) as client:
        store, analysis, delivery = app.state.store, app.state.analysis, app.state.delivery
        device, room, token = uuid4(), uuid4(), "synthetic-fixture-" + str(uuid4())
        store.provision(device, room, token)
        headers = {"Authorization": "Bearer " + token}
        analysis.update_profile(device, ProfileUpdate.model_validate({"expected_version":0,"profile":{
            "enabled":True,"interests":["배포"],"daily_token_limit":1000000}}))
        try:
            yield client, store, analysis, delivery, device, room, headers, links
        finally:
            with store.connect() as db:
                db.execute("DELETE FROM receipts WHERE device_id=%s", (device,))
                db.execute("DELETE FROM rooms WHERE device_id=%s", (device,))
                db.execute("DELETE FROM devices WHERE device_id=%s", (device,))


def policy(setup, **changes):
    client, _, _, _, _, _, headers, _ = setup
    version = client.get("/v1/delivery/policy", headers=headers).json()["version"]
    response = client.put("/v1/delivery/policy", headers=headers, json={"expected_version":version,
        "policy":{"enabled":True,"daily_times":["09:00","18:00"],"daily_notification_limit":10,**changes}})
    assert response.status_code == 200, response.text
    return response.json()


def due(setup):
    _, store, _, _, device, _, _, _ = setup
    with store.connect() as db:
        db.execute("UPDATE delivery_settings SET next_due_at=now()-interval '1 minute' WHERE device_id=%s", (device,))


def summary(setup, title="합성 배포 일정", room=None, observed_at=None, **changes):
    client, store, analysis, _, device, selected_room, headers, _ = setup
    room = room or selected_room
    identifier, job = uuid4(), uuid4()
    version = analysis.profile(device)["version"]
    payload = {"topic_id":"a"*64,"title":title,"points":[{"text":title + "이 공유됐습니다.","evidence_ids":[str(uuid4())]}],
        "relevance":90,"importance":60,"uncertainty":"limited_context","source_urls":["https://example.com/synthetic"],
        "notice":"방에서 공유된 주장입니다. 외부 사실 검증을 수행하지 않았습니다.",**changes}
    with store.connect() as db:
        latest=db.execute('SELECT coalesce(max(observed_at),0) AS stamp FROM messages WHERE device_id=%s',(device,)).fetchone()['stamp']
        existing={str(row['event_id']) for row in db.execute('SELECT event_id FROM messages WHERE device_id=%s',(device,)).fetchall()}
    stamp=observed_at if observed_at is not None else max(int(time.time()*1000),latest+1)
    messages=[]
    for point in payload['points']:
        for event in point['evidence_ids']:
            if event in existing:
                continue
            messages.append({'event_id':event,'room_id':str(room),'sender_alias':'a'*64,'text':point['text'],
                'source_time':stamp,'observed_at':stamp,'urls':payload['source_urls'],'quality':'structured','parser_version':2})
            existing.add(event)
    if messages:
        response=client.post('/v1/messages/batch',headers=headers,json={'items':messages})
        assert response.status_code==200,response.text
    with store.connect() as db:
        db.execute("""INSERT INTO analysis_jobs(job_id,device_id,room_id,profile_version,prompt_version,status,completed_at)
            VALUES(%s,%s,%s,%s,'synthetic-test','completed',now())""", (job, device, room, version))
        db.execute("INSERT INTO analysis_summaries(summary_id,job_id,topic_id,payload,is_candidate,provider_model) VALUES(%s,%s,%s,%s,true,'synthetic-test')",
                   (identifier, job, "a" * 64, Jsonb(payload)))
    return identifier


class StubChannel:
    name = "ntfy"
    def __init__(self, result=None, callback=None):
        self.result = result or ChannelResult("accepted", message_id="syntheticId1")
        self.callback, self.calls = callback, 0

    def publish(self, claim):
        self.calls += 1
        if self.callback:
            self.callback(claim)
        return self.result


def test_urgent_threshold_schedule_and_cooldown(setup):
    _, store, _, delivery, device, _, _, _ = setup
    policy(setup, urgent_enabled=True)
    summary(setup, importance=89)
    assert delivery.plan(device) is None
    summary(setup, title="합성 긴급 변경", importance=95)
    before = delivery.policy(device)["next_due_at"]
    identifier = delivery.plan(device)
    assert identifier and delivery.policy(device)["next_due_at"] == before
    with store.connect() as db:
        row = db.execute("SELECT kind,payload FROM delivery_outbox WHERE delivery_id=%s", (identifier,)).fetchone()
        assert row["kind"] == "urgent" and len(row["payload"]["topics"]) == 1
    assert DeliveryWorker(delivery, StubChannel()).process(device) == "accepted"
    summary(setup, title="합성 추가 긴급 변경", importance=99)
    assert delivery.plan(device) is None


def test_urgent_disabled_and_old_candidates_are_not_fast_sent(setup):
    _, store, _, delivery, device, _, _, _ = setup
    policy(setup)
    identifier = summary(setup, importance=99)
    assert delivery.plan(device) is None
    with store.connect() as db:
        db.execute("UPDATE analysis_summaries SET created_at=now()-interval '20 minutes' WHERE summary_id=%s", (identifier,))
    policy(setup, urgent_enabled=True)
    assert delivery.plan(device) is None
    due(setup)
    assert delivery.plan(device)


def test_manual_verification_preserves_schedule_and_shares_daily_quota(setup):
    _, store, _, delivery, device, _, _, _ = setup
    policy(setup, daily_notification_limit=1, urgent_enabled=True)
    summary(setup)
    before=delivery.policy(device)["next_due_at"]
    assert delivery.plan(device,manual=True)
    assert DeliveryWorker(delivery,StubChannel()).process(device)=="accepted"
    assert delivery.policy(device)["next_due_at"]==before
    summary(setup,title="합성 긴급 추가",importance=99)
    assert delivery.plan(device)
    assert delivery.begin_send(device) is None
    assert delivery.history(device)[0]["last_error"]=="daily_limit"


def test_limited_digest_selects_important_information_first(setup):
    _, store, _, delivery, device, _, _, _=setup
    policy(setup,max_topics_per_digest=1)
    summary(setup,title="합성 일반 정보",importance=60)
    important=summary(setup,title="합성 놓치면 안 될 정보",importance=95)
    due(setup)
    identifier=delivery.plan(device)
    with store.connect() as db:
        assert db.execute('SELECT summary_id FROM delivery_items WHERE delivery_id=%s',(identifier,)).fetchone()['summary_id']==important


def test_temporary_half_hour_schedule_expires_and_cancels_old_queue(setup):
    from datetime import datetime,timedelta,timezone
    client,store,_,delivery,device,_,headers,_=setup
    deadline=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
    policy(setup,daily_times=[f'{h:02}:{m:02}' for h in range(24) for m in (0,30)],daily_notification_limit=48,
        test_mode_until=deadline,resume_daily_times=['23:00'],resume_daily_notification_limit=1,include_source_quotes=True,
        max_topics_per_digest=3,resume_max_topics_per_digest=5)
    summary(setup)
    due(setup)
    assert delivery.plan(device)
    with store.connect() as db:
        config=db.execute('SELECT config FROM delivery_settings WHERE device_id=%s',(device,)).fetchone()['config']
        config['test_mode_until']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat()
        db.execute('UPDATE delivery_settings SET config=%s WHERE device_id=%s',(Jsonb(config),device))
    restored=client.get('/v1/delivery/policy',headers=headers).json()
    assert restored['policy']['daily_times']==['23:00']
    assert restored['policy']['daily_notification_limit']==1 and restored['policy']['include_source_quotes']
    assert restored['policy']['test_mode_until'] is None
    assert restored['policy']['max_topics_per_digest']==5 and restored['policy']['resume_max_topics_per_digest'] is None
    assert delivery.history(device)[0]['status']=='cancelled'


def test_quotes_are_exact_live_source_and_not_persisted_in_outbox(setup):
    client,store,_,delivery,device,room,headers,_=setup
    event=uuid4()
    original='합성 당시 대사: 일정이 화요일로 바뀌었어요. 다들 공지 한번 확인해 주세요. '+('추가 합성 문맥 '*20)
    message={'event_id':str(event),'room_id':str(room),'sender_alias':'a'*64,'text':original,
        'source_time':12345,'observed_at':int(time.time()*1000),'urls':[],'quality':'structured','parser_version':2}
    assert client.post('/v1/messages/batch',headers=headers,json={'items':[message]}).status_code==200
    policy(setup,include_source_quotes=True)
    summary(setup,points=[{'text':'합성 변경된 일정 안내','evidence_ids':[str(event)]}])
    due(setup)
    identifier=delivery.plan(device)
    claim=delivery.begin_send(device)
    quote=claim.payload['topics'][0]['payload']['quotes'][0]
    assert quote['text']==original[:80] and quote['truncated']
    assert quote['observed_at']==message['observed_at']
    with store.connect() as db:
        stored=db.execute('SELECT payload FROM delivery_outbox WHERE delivery_id=%s',(identifier,)).fetchone()['payload']
        assert 'quotes' not in stored['topics'][0]['payload']


def test_quote_lookup_never_reads_another_room(setup):
    client,store,_,delivery,device,room,headers,_=setup
    other,event=uuid4(),uuid4()
    store.provision(device,other,headers['Authorization'][7:])
    message={'event_id':str(event),'room_id':str(other),'sender_alias':'a'*64,'text':'다른 방 합성 비공개 대사',
        'source_time':12345,'observed_at':int(time.time()*1000),'urls':[],'quality':'structured','parser_version':2}
    assert client.post('/v1/messages/batch',headers=headers,json={'items':[message]}).status_code==200
    policy(setup,include_source_quotes=True)
    summary(setup,points=[{'text':'합성 잘못 연결된 근거','evidence_ids':[str(event)]}])
    due(setup)
    assert delivery.plan(device) is None
    assert delivery.begin_send(device) is None


def test_latency_auth_scope_and_first_open_are_measured(setup):
    client, store, _, delivery, device, _, headers, links = setup
    assert client.get("/v1/latency").status_code == 401
    identifier, _ = prepare(setup)
    assert DeliveryWorker(delivery, StubChannel()).process(device) == "accepted"
    url = links.url(identifier)
    from urllib.parse import urlsplit
    signature = urlsplit(url).fragment
    # The fragment format is documented by DigestLinks; extract its token.
    signature = signature.removeprefix("key=")
    auth = {"Authorization":"Digest " + signature}
    path = f"/v1/digests/{identifier}/opened"
    assert client.post(path).status_code == 404
    assert client.post(path, headers=auth).status_code == 200
    with store.connect() as db:
        first = db.execute("SELECT opened_at FROM delivery_outbox WHERE delivery_id=%s", (identifier,)).fetchone()["opened_at"]
    assert client.post(path, headers=auth).status_code == 200
    with store.connect() as db:
        assert db.execute("SELECT opened_at FROM delivery_outbox WHERE delivery_id=%s", (identifier,)).fetchone()["opened_at"] == first
    result = client.get("/v1/latency", headers=headers).json()
    assert result["delivery"]["accepted"] == result["delivery"]["opened"] == 1
    assert result["handset_notification_display_measured"] is False


def prepare(setup, **settings):
    policy(setup, **settings)
    identifier = summary(setup)
    due(setup)
    delivery = setup[3].plan(setup[4])
    assert delivery
    return delivery, identifier


def test_disabled_defaults_and_all_delivery_routes_require_auth(setup):
    client, _, _, delivery, device, _, headers, _ = setup
    for path in ["/v1/delivery/policy","/v1/delivery/status","/v1/delivery/history","/v1/delivery/preview","/v1/feedback"]:
        assert client.get(path).status_code == 401
    assert client.put("/v1/delivery/policy",json={}).status_code == 401
    assert client.put(f"/v1/summaries/{uuid4()}/feedback",json={"rating":"useful"}).status_code == 401
    assert client.post(f"/v1/delivery/{uuid4()}/resolve",json={"action":"mark_accepted"}).status_code == 401
    assert client.get("/v1/delivery/policy",headers=headers).json()["policy"]["enabled"] is False
    summary(setup)
    assert delivery.plan(device) is None and delivery.begin_send(device) is None


def test_policy_version_conflict_validation_and_size_limits(setup):
    client, _, _, _, _, _, headers, _ = setup
    assert policy(setup)["version"] == 1
    assert client.put("/v1/delivery/policy",headers=headers,json={"expected_version":0,"policy":{}}).status_code == 409
    result = client.put("/v1/delivery/policy",headers=headers,json={"expected_version":1,"policy":{"timezone":"synthetic-private-invalid"}})
    assert result.status_code == 422 and "synthetic-private-invalid" not in result.text
    assert client.put("/v1/delivery/policy",headers=headers,content=b"x"*32769).status_code == 413
    assert client.get("/v1/delivery/history?limit=101",headers=headers).status_code == 422


def test_policy_updates_are_serialized(setup):
    client, _, _, _, _, _, headers, _ = setup
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.put("/v1/delivery/policy",headers=headers,
            json={"expected_version":0,"policy":{}}).status_code, range(2)))
    assert sorted(results) == [200,409]


def test_schedule_wait_and_empty_slot_never_publishes(setup):
    _, _, _, delivery, device, _, _, _ = setup
    policy(setup)
    assert delivery.plan(device) is None
    due(setup)
    channel = StubChannel()
    assert DeliveryWorker(delivery,channel).process(device) == "idle" and channel.calls == 0
    assert delivery.status(device)["next_due_at"] is not None


def test_full_m2_m3_m4_path_and_main_phone_feedback(setup):
    client, store, analysis, delivery, device, room, headers, links = setup
    policy(setup)
    message = {"event_id":str(uuid4()),"room_id":str(room),"sender_alias":"a"*64,"text":"합성 배포 일정은 다음 주입니다.",
        "source_time":12345,"observed_at":int(time.time()*1000),"urls":[],"quality":"structured","parser_version":2}
    assert client.post("/v1/messages/batch",headers=headers,json={"items":[message]}).status_code == 200
    assert Worker(analysis,ExtractiveProvider()).process(device,room,force=True) == "completed"
    preview = client.get("/v1/delivery/preview",headers=headers).json()
    assert preview["preview"] and len(preview["topics"]) == 1
    assert delivery.history(device) == []
    due(setup)
    requests = []
    def receive(request):
        requests.append(request)
        return httpx.Response(200,json={"id":"syntheticId1","event":"message","topic":"synthetic-topic"})
    channel = NtfyChannel("https://ntfy.example.com","synthetic-topic","synthetic-private-token",links,httpx.MockTransport(receive))
    assert DeliveryWorker(delivery,channel).process(device) == "accepted"
    assert len(requests) == 1 and delivery.status(device)["attempts_today"] == 1
    row = delivery.history(device)[0]
    scoped = {"Authorization":"Digest " + links.token(row["delivery_id"])}
    digest = client.get(f"/v1/digests/{row['delivery_id']}",headers=scoped)
    assert digest.status_code == 200 and "device_id" not in digest.json()
    assert digest.headers["cache-control"] == "no-store"
    topic = digest.json()["topics"][0]
    assert topic["evidence"][0]["text"] == message["text"]
    result = client.put(f"/v1/digests/{row['delivery_id']}/summaries/{topic['summary_id']}/feedback",headers=scoped,json={"rating":"useful"})
    assert result.status_code == 200 and result.json()["rating"] == "useful"
    assert client.get("/v1/feedback",headers=headers).json()["items"][0]["rating"] == "useful"
    due(setup)
    assert DeliveryWorker(delivery,channel).process(device) == "idle" and len(requests) == 1


def test_concurrent_planners_and_workers_send_once(setup):
    _, _, _, delivery, device, _, _, _ = setup
    policy(setup)
    summary(setup)
    due(setup)
    with ThreadPoolExecutor(max_workers=4) as pool:
        deliveries = list(pool.map(lambda _: delivery.plan(device), range(8)))
    assert sum(d is not None for d in deliveries) == 1
    channel = StubChannel()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: DeliveryWorker(delivery,channel).process(device), range(8)))
    assert results.count("accepted") == 1 and channel.calls == 1
    assert delivery.status(device)["attempts_today"] == 1


def test_quiet_hours_defer_without_using_attempts(setup):
    _, store, _, delivery, device, _, _, _ = setup
    with store.connect() as db:
        quiet = db.execute("SELECT to_char(clock_timestamp() AT TIME ZONE 'UTC','HH24:MI') AS start").fetchone()["start"]
    # A 23h quiet window includes the current minute, including midnight.
    hour, minute = map(int,quiet.split(":"))
    end = f"{(hour+23)%24:02d}:{minute:02d}"
    prepare(setup,timezone="UTC",quiet_start=quiet,quiet_end=end)
    channel = StubChannel()
    assert DeliveryWorker(delivery,channel).process(device) == "idle"
    assert channel.calls == 0 and delivery.status(device)["attempts_today"] == 0
    assert delivery.history(device)[0]["status"] == "pending"


def test_daily_cap_defers_next_digest_and_recovers_next_day(setup):
    _, store, _, delivery, device, _, _, _ = setup
    prepare(setup,daily_notification_limit=1)
    channel = StubChannel()
    assert DeliveryWorker(delivery,channel).process(device) == "accepted"
    summary(setup,title="합성 다른 배포")
    due(setup)
    assert DeliveryWorker(delivery,channel).process(device) == "idle"
    assert channel.calls == 1 and delivery.status(device)["attempts_today"] == 1
    pending = next(r for r in delivery.history(device) if r["status"] == "pending")
    assert pending["last_error"] == "daily_limit"
    with store.connect() as db:
        db.execute("UPDATE delivery_attempts SET created_at=created_at-interval '1 day' WHERE device_id=%s",(device,))
        db.execute("UPDATE delivery_outbox SET not_before=clock_timestamp()-interval '1 second' WHERE delivery_id=%s",(pending["delivery_id"],))
    assert DeliveryWorker(delivery,channel).process(device) == "accepted" and channel.calls == 2


def test_timezone_changes_do_not_reset_recent_quota(setup):
    _, store, _, delivery, device, _, _, _ = setup
    prepare(setup,daily_notification_limit=1)
    assert DeliveryWorker(delivery,StubChannel()).process(device) == "accepted"
    policy(setup,timezone="America/New_York",daily_notification_limit=1)
    assert delivery.status(device)["attempts_today"] == 1
    # Audit labels from a prior timezone must never determine the current limit.
    with store.connect() as db:
        db.execute("UPDATE delivery_attempts SET quota_day=quota_day-1 WHERE device_id=%s",(device,))
    assert delivery.status(device)["attempts_today"] == 1


def test_content_dedup_preserves_corrections_and_distinct_rooms(setup):
    _, store, _, delivery, device, room, _, _ = setup
    prepare(setup)
    assert DeliveryWorker(delivery,StubChannel()).process(device) == "accepted"
    summary(setup)  # New event IDs alone do not make the same text a new notification.
    summary(setup,title="합성 배포 일정",points=[{"text":"합성 일정이 취소됐습니다.","evidence_ids":[str(uuid4())]}])
    other_room = uuid4()
    with store.connect() as db:
        db.execute("INSERT INTO rooms(device_id,room_id) VALUES(%s,%s)",(device,other_room))
    summary(setup,room=other_room)
    due(setup)
    assert DeliveryWorker(delivery,StubChannel()).process(device) == "accepted"
    assert delivery.history(device)[0]["topic_count"] == 2


def test_old_non_candidate_and_old_profile_summaries_are_excluded(setup):
    _, store, analysis, delivery, device, _, _, _ = setup
    policy(setup,max_summary_age_hours=1)
    old = summary(setup)
    unwanted = summary(setup,title="合成 비후보")
    with store.connect() as db:
        db.execute("UPDATE analysis_summaries SET created_at=now()-interval '2 hours' WHERE summary_id=%s",(old,))
        db.execute("UPDATE analysis_summaries SET is_candidate=false WHERE summary_id=%s",(unwanted,))
    assert delivery.preview(device)["topics"] == []
    summary(setup,title="합성 이전 프로필")
    profile = analysis.profile(device)
    analysis.update_profile(device,ProfileUpdate.model_validate({"expected_version":profile["version"],"profile":profile["profile"]}))
    due(setup)
    assert delivery.plan(device) is None


def test_definite_failure_backoff_retry_and_attempt_limit(setup):
    _, store, _, delivery, device, _, _, _ = setup
    identifier, _ = prepare(setup,max_attempts=2)
    channel = StubChannel(ChannelResult("retry","rate_limited",retry_after=600))
    assert DeliveryWorker(delivery,channel).process(device) == "retry"
    row = delivery.history(device)[0]
    assert row["status"] == "retry_wait" and row["attempts"] == 1
    assert DeliveryWorker(delivery,channel).process(device) == "idle" and channel.calls == 1
    with store.connect() as db:
        db.execute("UPDATE delivery_outbox SET not_before=now()-interval '1 second' WHERE delivery_id=%s",(identifier,))
    assert DeliveryWorker(delivery,channel).process(device) == "retry"
    assert delivery.history(device)[0]["status"] == "failed" and delivery.status(device)["attempts_today"] == 2
    assert DeliveryWorker(delivery,channel).process(device) == "idle" and channel.calls == 2


def test_unknown_outcome_does_not_auto_retry_and_manual_retry_is_explicit(setup):
    client, _, _, delivery, device, _, headers, _ = setup
    identifier, _ = prepare(setup)
    channel = StubChannel(ChannelResult("uncertain","response_lost"))
    assert DeliveryWorker(delivery,channel).process(device) == "uncertain"
    assert DeliveryWorker(delivery,channel).process(device) == "idle" and channel.calls == 1
    assert client.post(f"/v1/delivery/{identifier}/resolve",headers=headers,json={"action":"retry"}).status_code == 422
    assert client.post(f"/v1/delivery/{identifier}/resolve",headers=headers,
        json={"action":"retry","acknowledge_duplicate_risk":True}).status_code == 200
    assert DeliveryWorker(delivery,StubChannel()).process(device) == "accepted"
    assert delivery.status(device)["attempts_today"] == 2


def test_manual_confirmation_preserves_unknown_attempt_reservation(setup):
    client, _, _, delivery, device, _, headers, _ = setup
    identifier, _ = prepare(setup)
    assert DeliveryWorker(delivery,StubChannel(ChannelResult("uncertain","response_lost"))).process(device) == "uncertain"
    response = client.post(f"/v1/delivery/{identifier}/resolve",headers=headers,json={"action":"mark_accepted"})
    assert response.status_code == 200 and delivery.status(device)["attempts_today"] == 1
    assert delivery.history(device)[0]["last_error"] == "manually_confirmed"


def test_worker_interruption_owner_expiry_and_stale_response(setup):
    _, store, _, delivery, device, _, _, _ = setup
    identifier, _ = prepare(setup)
    claim = delivery.begin_send(device)
    with store.connect() as db:
        db.execute("UPDATE delivery_outbox SET lease_until=clock_timestamp()-interval '1 second' WHERE delivery_id=%s",(identifier,))
    assert delivery.status(device)["deliveries"] == {"uncertain":1}
    assert not delivery.finish(claim,"accepted",message_id="staleId1")
    assert delivery.begin_send(device) is None
    with store.connect() as db:
        assert db.execute("SELECT outcome FROM delivery_attempts WHERE attempt_id=%s",(claim.attempt_id,)).fetchone()["outcome"] == "uncertain"


def test_channel_exception_is_safe_and_preserves_quota(setup):
    _, _, _, delivery, device, _, _, _ = setup
    prepare(setup)
    def explode(_):
        raise RuntimeError("synthetic-raw-channel-secret")
    assert DeliveryWorker(delivery,StubChannel(callback=explode)).process(device) == "uncertain"
    assert "synthetic-raw-channel-secret" not in str(delivery.history(device))
    assert delivery.status(device)["attempts_today"] == 1


def test_pending_settings_change_and_disabled_profile_cancel_send(setup):
    _, _, analysis, delivery, device, _, _, _ = setup
    prepare(setup)
    policy(setup,enabled=False)
    channel = StubChannel()
    assert DeliveryWorker(delivery,channel).process(device) == "idle"
    assert delivery.history(device)[0]["status"] == "cancelled" and channel.calls == 0
    policy(setup)
    due(setup)
    assert delivery.plan(device)
    profile = analysis.profile(device)
    profile["profile"]["enabled"] = False
    analysis.update_profile(device,ProfileUpdate.model_validate({"expected_version":profile["version"],"profile":profile["profile"]}))
    assert DeliveryWorker(delivery,channel).process(device) == "idle"
    assert delivery.history(device)[0]["status"] == "cancelled" and channel.calls == 0


def test_inflight_settings_change_records_actual_acceptance_without_resending(setup):
    _, _, _, delivery, device, _, _, _ = setup
    prepare(setup)
    assert DeliveryWorker(delivery,StubChannel(callback=lambda _:policy(setup,enabled=False))).process(device) == "accepted"
    assert delivery.history(device)[0]["status"] == "accepted"
    assert delivery.status(device)["attempts_today"] == 1


@pytest.mark.parametrize("stage", ["pending","sending","accepted"])
def test_room_deletion_wipes_snapshots_links_feedback_and_keeps_quota(setup,stage):
    client, store, _, delivery, device, room, headers, links = setup
    identifier, selected = prepare(setup)
    claim = delivery.begin_send(device) if stage != "pending" else None
    if stage == "accepted":
        assert delivery.finish(claim,"accepted",message_id="syntheticId1")
        assert delivery.feedback(device,selected,"useful")
    assert client.delete(f"/v1/rooms/{room}/data",headers=headers).status_code == 200
    assert delivery.history(device)[0]["status"] == "cancelled"
    with store.connect() as db:
        assert db.execute("SELECT payload FROM delivery_outbox WHERE delivery_id=%s",(identifier,)).fetchone()["payload"] == {}
        assert db.execute("SELECT count(*) AS n FROM summary_feedback WHERE device_id=%s",(device,)).fetchone()["n"] == 0
    assert client.get(f"/v1/digests/{identifier}",headers={"Authorization":"Digest "+links.token(identifier)}).status_code == 404
    assert delivery.status(device)["attempts_today"] == (0 if stage == "pending" else 1)
    if stage == "sending":
        assert not delivery.finish(claim,"accepted",message_id="staleId1")


def test_room_deletion_also_wipes_snapshot_after_summary_expiry(setup):
    _, store, _, delivery, device, room, _, _ = setup
    identifier, selected = prepare(setup)
    with store.connect() as db:
        db.execute("DELETE FROM analysis_summaries WHERE summary_id=%s",(selected,))
    store.delete_room(device,room)
    with store.connect() as db:
        assert db.execute("SELECT payload FROM delivery_outbox WHERE delivery_id=%s",(identifier,)).fetchone()["payload"] == {}


def test_pending_summary_expiry_prevents_publish(setup):
    _, store, _, delivery, device, _, _, _ = setup
    _, selected = prepare(setup)
    with store.connect() as db:
        db.execute("DELETE FROM analysis_summaries WHERE summary_id=%s",(selected,))
    channel = StubChannel()
    assert DeliveryWorker(delivery,channel).process(device) == "idle" and channel.calls == 0
    assert delivery.history(device)[0]["last_error"] == "source_unavailable"


def test_feedback_is_upserted_and_excludes_pending_topic(setup):
    client, _, _, delivery, device, _, headers, _ = setup
    identifier, selected = prepare(setup)
    assert client.put(f"/v1/summaries/{selected}/feedback",headers=headers,json={"rating":"useful"}).status_code == 200
    assert client.put(f"/v1/summaries/{selected}/feedback",headers=headers,json={"rating":"not_interested"}).status_code == 200
    assert len(delivery.feedback_list(device)) == 1
    assert DeliveryWorker(delivery,StubChannel()).process(device) == "idle"
    assert delivery.history(device)[0]["status"] == "cancelled"
    assert delivery.preview(device)["topics"] == []


def test_scoped_link_cannot_read_other_digest_or_feedback_on_other_summary(setup):
    client, _, _, delivery, device, _, _, links = setup
    identifier, selected = prepare(setup)
    assert DeliveryWorker(delivery,StubChannel()).process(device) == "accepted"
    scoped = {"Authorization":"Digest "+links.token(identifier)}
    assert client.get(f"/v1/digests/{uuid4()}",headers=scoped).status_code == 404
    other_summary = summary(setup,title="합성 별도 주제")
    assert client.put(f"/v1/digests/{identifier}/summaries/{other_summary}/feedback",headers=scoped,json={"rating":"useful"}).status_code == 404
    assert client.get("/v1/delivery/history",headers=scoped).status_code == 401


def test_expired_link_and_revoked_device_stop_digest_access(setup):
    client, store, _, delivery, device, _, _, links = setup
    identifier, _ = prepare(setup)
    assert DeliveryWorker(delivery,StubChannel()).process(device) == "accepted"
    scoped = {"Authorization":"Digest "+links.token(identifier)}
    with store.connect() as db:
        db.execute("UPDATE delivery_outbox SET link_expires_at=clock_timestamp()-interval '1 second' WHERE delivery_id=%s",(identifier,))
    assert client.get(f"/v1/digests/{identifier}",headers=scoped).status_code == 404
    with store.connect() as db:
        db.execute("UPDATE delivery_outbox SET link_expires_at=clock_timestamp()+interval '1 day' WHERE delivery_id=%s",(identifier,))
        db.execute("UPDATE devices SET active=false WHERE device_id=%s",(device,))
    assert client.get(f"/v1/digests/{identifier}",headers=scoped).status_code == 404


def test_other_device_history_feedback_and_resolution_are_scoped(setup):
    client, store, _, delivery, device, room, _, _ = setup
    identifier, selected = prepare(setup)
    assert DeliveryWorker(delivery,StubChannel(ChannelResult("uncertain","response_lost"))).process(device) == "uncertain"
    other, token = uuid4(), "synthetic-other-"+str(uuid4())
    store.provision(other,room,token)
    headers = {"Authorization":"Bearer "+token}
    try:
        assert client.get("/v1/delivery/history",headers=headers).json()["items"] == []
        assert client.put(f"/v1/summaries/{selected}/feedback",headers=headers,json={"rating":"useful"}).status_code == 404
        assert client.post(f"/v1/delivery/{identifier}/resolve",headers=headers,json={"action":"mark_accepted"}).status_code == 404
    finally:
        with store.connect() as db:
            db.execute("DELETE FROM rooms WHERE device_id=%s",(other,))
            db.execute("DELETE FROM devices WHERE device_id=%s",(other,))


def test_raw_evidence_expiry_preserves_digest_with_explicit_missing_evidence(setup):
    client, store, _, delivery, device, _, _, links = setup
    identifier, _ = prepare(setup)
    assert DeliveryWorker(delivery,StubChannel()).process(device) == "accepted"
    with store.connect() as db:
        db.execute('DELETE FROM messages WHERE device_id=%s',(device,))
    result = client.get(f"/v1/digests/{identifier}",headers={"Authorization":"Digest "+links.token(identifier)}).json()
    assert result["topics"][0]["evidence"][0]["availability"] == "raw_expired"


def test_delivery_retention_deletes_snapshots_and_attempts(setup):
    _, store, _, delivery, device, _, _, _ = setup
    identifier, _ = prepare(setup)
    assert DeliveryWorker(delivery,StubChannel()).process(device) == "accepted"
    with store.connect() as db:
        db.execute("UPDATE delivery_outbox SET created_at=now()-interval '91 days' WHERE delivery_id=%s",(identifier,))
        db.execute("UPDATE delivery_attempts SET created_at=now()-interval '91 days' WHERE device_id=%s",(device,))
    result = store.prune()
    assert result["expired_deliveries"] == 1 and result["expired_delivery_attempts"] == 1
    assert delivery.history(device) == []


def test_digest_assets_have_private_headers_and_no_inline_room_html(setup):
    client = setup[0]
    response = client.get(f"/digest/{uuid4()}")
    assert response.status_code == 200 and response.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    script = client.get("/assets/digest.js")
    assert script.status_code == 200 and "textContent" in script.text and "innerHTML" not in script.text
    assert client.get("/assets/unknown").status_code == 404


def test_delivery_openapi_has_valid_nested_policy_schema(setup):
    schema = setup[0].get("/openapi.json").json()
    policy_schema = schema["paths"]["/v1/delivery/policy"]["put"]["requestBody"]["content"]["application/json"]["schema"]
    assert policy_schema["properties"]["policy"]["properties"]["daily_times"]["type"] == "array"


def test_repeated_migration_preserves_m4_outbox_quota_and_feedback(setup):
    _, store, _, delivery, device, _, _, _ = setup
    identifier, selected = prepare(setup)
    assert DeliveryWorker(delivery,StubChannel()).process(device) == "accepted"
    assert delivery.feedback(device,selected,"useful")
    store.migrate()
    store.migrate()
    assert delivery.history(device)[0]["delivery_id"] == identifier
    assert delivery.history(device)[0]["status"] == "accepted"
    assert delivery.status(device)["attempts_today"] == 1
    assert delivery.feedback_list(device)[0]["rating"] == "useful"


def test_later_reports_never_return_to_old_sources_even_with_higher_importance(setup):
    _,store,_,delivery,device,room,_,_=setup
    policy(setup,max_topics_per_digest=1)
    morning=int(time.time()*1000)-600000
    summary(setup,title='합성 오늘 아침 정보',observed_at=morning,importance=99)
    summary(setup,title='합성 어젯밤 정보',observed_at=morning-8*3600000,importance=90)
    due(setup)
    assert DeliveryWorker(delivery,StubChannel()).process(device)=='accepted'
    summary(setup,title='합성 늦게 분석된 어젯밤 정보',observed_at=morning-7*3600000,importance=100)
    due(setup)
    assert delivery.plan(device) is None
    fresh=summary(setup,title='합성 이후 새 공지',observed_at=morning+1000,importance=60)
    due(setup)
    identifier=delivery.plan(device)
    with store.connect() as db:
        assert db.execute('SELECT summary_id FROM delivery_items WHERE delivery_id=%s',(identifier,)).fetchone()['summary_id']==fresh
        assert db.execute('SELECT observed_through FROM delivery_progress WHERE device_id=%s AND room_id=%s',(device,room)).fetchone()['observed_through']==morning


def test_different_summary_wording_cannot_repeat_the_same_source_or_copied_text(setup):
    _,store,_,delivery,device,_,_,_=setup
    identifier,_=prepare(setup)
    with store.connect() as db:
        original=db.execute('SELECT payload FROM delivery_outbox WHERE delivery_id=%s',(identifier,)).fetchone()['payload']['topics'][0]['payload']
    assert DeliveryWorker(delivery,StubChannel()).process(device)=='accepted'
    summary(setup,title='합성 모델이 다르게 붙인 제목',points=[{'text':'합성 같은 내용을 다시 요약한 문장',
        'evidence_ids':original['points'][0]['evidence_ids']}])
    summary(setup,title='합성 재노출 알림의 다른 제목',points=original['points'])
    # A new event carrying identical text is also excluded, independent of its summary text.
    event=uuid4()
    client,_,_,_,_,room,headers,_=setup
    with store.connect() as db:
        stamp=db.execute('SELECT max(observed_at)+1000 AS stamp FROM messages WHERE device_id=%s',(device,)).fetchone()['stamp']
    message={'event_id':str(event),'room_id':str(room),'sender_alias':'a'*64,'text':original['points'][0]['text'],
        'source_time':stamp,'observed_at':stamp,'urls':[],'quality':'structured','parser_version':2}
    assert client.post('/v1/messages/batch',headers=headers,json={'items':[message]}).status_code==200
    summary(setup,title='합성 동일 원문 새 요약',points=[{'text':'합성 표현만 달라진 요약','evidence_ids':[str(event)]}])
    due(setup)
    assert delivery.plan(device) is None


def test_digest_consumes_completed_interval_and_does_not_drip_leftover_old_topics(setup):
    _,store,_,delivery,device,room,_,_=setup
    policy(setup,max_topics_per_digest=1)
    stamp=int(time.time()*1000)-60000
    summary(setup,title='합성 가장 중요한 첫 소식',importance=99,observed_at=stamp)
    summary(setup,title='합성 같은 구간의 덜 중요한 소식',importance=70,observed_at=stamp+1000)
    due(setup)
    assert DeliveryWorker(delivery,StubChannel()).process(device)=='accepted'
    with store.connect() as db:
        assert db.execute('SELECT observed_through FROM delivery_progress WHERE device_id=%s AND room_id=%s',(device,room)).fetchone()['observed_through']==stamp+1000
    due(setup)
    assert delivery.plan(device) is None


def test_mixed_old_and_new_context_only_emits_fully_new_points_and_quotes(setup):
    _,store,_,delivery,device,_,_,_=setup
    identifier,_=prepare(setup,include_source_quotes=True)
    with store.connect() as db:
        old=db.execute('SELECT payload FROM delivery_outbox WHERE delivery_id=%s',(identifier,)).fetchone()['payload']['topics'][0]['payload']['points'][0]['evidence_ids'][0]
    assert DeliveryWorker(delivery,StubChannel()).process(device)=='accepted'
    new=str(uuid4())
    summary(setup,title='합성 새 정정 내용',points=[
        {'text':'합성 이전 이야기 반복','evidence_ids':[old]},
        {'text':'합성 이전과 새 근거를 섞은 문장','evidence_ids':[old,new]},
        {'text':'합성 일정이 취소됐다는 새 안내','evidence_ids':[new]}])
    due(setup)
    assert delivery.plan(device)
    claim=delivery.begin_send(device)
    payload=claim.payload['topics'][0]['payload']
    assert len(payload['points'])==1 and payload['points'][0]['evidence_ids']==[new]
    assert all(quote['evidence_id']==new for quote in payload['quotes'])


def test_rejected_or_cancelled_delivery_does_not_advance_progress(setup):
    _,store,_,delivery,device,_,_,_=setup
    identifier,_=prepare(setup)
    assert DeliveryWorker(delivery,StubChannel(ChannelResult('retry','connection_failed'))).process(device)=='retry'
    with store.connect() as db:
        assert db.execute('SELECT count(*) AS n FROM delivery_progress WHERE device_id=%s',(device,)).fetchone()['n']==0
        db.execute("UPDATE delivery_outbox SET not_before=clock_timestamp()-interval '1 second' WHERE delivery_id=%s",(identifier,))
    assert DeliveryWorker(delivery,StubChannel()).process(device)=='accepted'
    with store.connect() as db:
        assert db.execute('SELECT count(*) AS n FROM delivery_progress WHERE device_id=%s',(device,)).fetchone()['n']==1


def test_existing_out_of_order_deliveries_seed_highest_source_time_once(setup):
    _,store,_,delivery,device,room,_,_=setup
    policy(setup,max_topics_per_digest=1)
    stamp=int(time.time()*1000)-60000
    summary(setup,title='합성 아침 전달',observed_at=stamp)
    due(setup)
    assert DeliveryWorker(delivery,StubChannel()).process(device)=='accepted'
    old=summary(setup,title='합성 뒤늦게 전달한 어젯밤 정보',observed_at=stamp-3600000)
    with store.connect() as db:
        original=db.execute('SELECT payload FROM analysis_summaries WHERE summary_id=%s',(old,)).fetchone()['payload']
        payload={'topics':[{'room_id':str(room),'payload':original}]}
        db.execute('''INSERT INTO delivery_outbox(delivery_id,device_id,settings_version,profile_version,status,payload,slot_at,not_before)
            VALUES(%s,%s,1,1,'accepted',%s,now(),now())''',(uuid4(),device,Jsonb(payload)))
        db.execute('DELETE FROM delivery_progress WHERE device_id=%s',(device,))
        db.execute('DELETE FROM delivery_source_receipts WHERE device_id=%s',(device,))
        db.execute('DELETE FROM schema_versions WHERE version=5')
    store.migrate()
    store.migrate()
    with store.connect() as db:
        row=db.execute('SELECT observed_through FROM delivery_progress WHERE device_id=%s AND room_id=%s',(device,room)).fetchone()
        assert row['observed_through']==stamp
    summary(setup,title='합성 뒤늦게 생성된 어젯밤 요약',observed_at=stamp-3600000)
    due(setup)
    assert delivery.plan(device) is None


def test_accepted_progress_survives_outbox_retention_but_room_delete_wipes_it(setup):
    _,store,_,delivery,device,room,_,_=setup
    identifier,_=prepare(setup)
    assert DeliveryWorker(delivery,StubChannel()).process(device)=='accepted'
    with store.connect() as db:
        db.execute('DELETE FROM delivery_outbox WHERE delivery_id=%s',(identifier,))
        assert db.execute('SELECT count(*) AS n FROM delivery_progress WHERE device_id=%s',(device,)).fetchone()['n']==1
    store.delete_room(device,room)
    with store.connect() as db:
        assert db.execute('SELECT count(*) AS n FROM delivery_progress WHERE device_id=%s',(device,)).fetchone()['n']==0
        assert db.execute('SELECT count(*) AS n FROM delivery_source_receipts WHERE device_id=%s',(device,)).fetchone()['n']==0
