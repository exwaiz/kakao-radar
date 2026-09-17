import copy
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
import psycopg
from fastapi.testclient import TestClient

from radar_server.app import create_app
from radar_server.analysis_models import AnalysisInput, ChargeLimit, ProviderResult, Usage, validate_output
from radar_server.analysis_store import AnalysisStore
from radar_server.providers import ExtractiveProvider, ProviderFailure
from radar_server.topics import prepare_topics
from radar_server.worker import Worker


@pytest.fixture
def setup():
    dsn = os.environ.get("RADAR_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Dedicated PostgreSQL test DB required")
    app = create_app(dsn)
    with TestClient(app) as client:
        store, analysis = app.state.store, app.state.analysis
        device, room, token = uuid4(), uuid4(), "synthetic-fixture-" + str(uuid4())
        store.provision(device, room, token)
        headers = {"Authorization": "Bearer " + token}
        try:
            yield client, store, analysis, device, room, token, headers
        finally:
            with store.connect() as db:
                db.execute("DELETE FROM receipts WHERE device_id=%s", (device,))
                db.execute("DELETE FROM rooms WHERE device_id=%s", (device,))
                db.execute("DELETE FROM devices WHERE device_id=%s", (device,))


def configure(setup, **changes):
    client, _, _, _, _, _, headers = setup
    version = client.get("/v1/profile", headers=headers).json()["version"]
    profile = {"enabled": True, "interests": ["배포"], "daily_token_limit": 1000000,
               "daily_cost_limit_microusd": 10000, "batch_min_messages": 2, **changes}
    response = client.put("/v1/profile", headers=headers, json={"expected_version": version, "profile": profile})
    assert response.status_code == 200, response.text
    return response.json()


def item(room, text="합성 배포 일정 안내", **changes):
    return {"event_id": str(uuid4()), "room_id": str(room), "sender_alias": "a" * 64,
            "text": text, "source_time": 12345, "observed_at": int(time.time() * 1000),
            "urls": [], "quality": "structured", "parser_version": 2, **changes}


def ingest(setup, items):
    client, _, _, _, _, _, headers = setup
    response = client.post("/v1/messages/batch", headers=headers, json={"items": items})
    assert response.status_code == 200
    assert all(r["status"] == "accepted" for r in response.json()["results"])


class StubProvider:
    external = False
    def __init__(self, mutate=None, callback=None, failure=False):
        self.calls = 0
        self.lock = threading.Lock()
        self.mutate, self.callback, self.failure = mutate, callback, failure

    def maximum_charge(self, batch):
        return ChargeLimit(tokens=20, cost_microusd=10)

    def generate(self, batch):
        with self.lock:
            self.calls += 1
        if self.callback:
            self.callback()
        if self.failure:
            raise ProviderFailure("raw-provider-secret-not-a-code")
        output = copy.deepcopy(ExtractiveProvider.render(batch))
        if self.mutate:
            self.mutate(output)
        return ProviderResult(output, Usage(input_tokens=2, output_tokens=3, cost_microusd=10, measured=True), "synthetic-stub-v1")


def test_default_profile_disabled_and_m3_apis_require_auth(setup):
    client, store, analysis, device, room, _, headers = setup
    assert client.get("/v1/profile").status_code == 401
    assert client.get("/v1/analysis/status").status_code == 401
    assert client.get(f"/v1/rooms/{room}/summaries").status_code == 401
    assert client.get(f"/v1/summaries/{uuid4()}/evidence").status_code == 401
    assert client.get("/v1/profile", headers=headers).json()["profile"]["enabled"] is False
    ingest(setup, [item(room)])
    provider = StubProvider()
    assert Worker(analysis, provider).process(device, room, force=True) == "idle"
    assert provider.calls == 0 and store.status(device)["stored_messages"] == 1


def test_profile_version_conflict_and_safe_validation(setup):
    client, _, _, _, _, _, headers = setup
    assert configure(setup)["version"] == 1
    response = client.put("/v1/profile", headers=headers, json={"expected_version": 0, "profile": {}})
    assert response.status_code == 409
    secret = "synthetic-private-invalid"
    response = client.put("/v1/profile", headers=headers, json={"expected_version": 1, "profile": {"timezone": secret}})
    assert response.status_code == 422 and secret not in response.text
    assert client.put("/v1/profile", headers=headers, content=b"x" * 32769).status_code == 413
    assert client.get("/v1/analysis/jobs?limit=1000", headers=headers).status_code == 422


def test_profile_updates_are_serialized(setup):
    client, _, _, _, _, _, headers = setup
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: client.put("/v1/profile", headers=headers, json={"expected_version": 0, "profile": {}}).status_code, range(2)))
    assert sorted(results) == [200, 409]


def test_profile_to_summary_to_authenticated_evidence(setup):
    client, _, analysis, device, room, _, headers = setup
    configure(setup)
    now = int(time.time() * 1000)
    a = item(room, "합성 배포 일정은 내일입니다", observed_at=now-1000, urls=["https://example.com/synthetic?version=1"])
    b = item(room, "아니요, 취소되었습니다", observed_at=now)
    ingest(setup, [a, b])
    assert Worker(analysis, ExtractiveProvider()).process(device, room) == "completed"
    summaries = client.get(f"/v1/rooms/{room}/summaries", headers=headers).json()["items"]
    assert len(summaries) == 1 and summaries[0]["is_candidate"]
    assert summaries[0]["payload"]["uncertainty"] == "conflicting_messages"
    evidence = client.get(f"/v1/summaries/{summaries[0]['summary_id']}/evidence", headers=headers).json()["evidence"]
    assert {r["event_id"] for r in evidence} == {a["event_id"], b["event_id"]}
    assert all(r["availability"] == "available" for r in evidence)
    assert analysis.status(device)["usage"]["simulated_calls"] == 1
    assert analysis.status(device)["jobs"] == {"completed": 1}


def test_count_and_time_trigger_concurrently_run_once(setup):
    _, store, analysis, device, room, _, _ = setup
    configure(setup)
    ingest(setup, [item(room), item(room)])
    with store.connect() as db:
        db.execute("UPDATE messages SET received_at=now()-interval '4 hours' WHERE device_id=%s", (device,))
    provider = StubProvider()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: Worker(analysis, provider).process(device, room), range(8)))
    assert results.count("completed") == 1 and provider.calls == 1
    assert len(analysis.jobs(device)) == 1


def test_time_trigger_runs_below_count_threshold(setup):
    _, store, analysis, device, room, _, _ = setup
    configure(setup, batch_min_messages=500)
    ingest(setup, [item(room)])
    worker = Worker(analysis, StubProvider())
    assert worker.process(device, room) == "idle"
    with store.connect() as db:
        db.execute("UPDATE messages SET received_at=now()-interval '4 hours' WHERE device_id=%s", (device,))
    assert worker.process(device, room) == "completed"


def test_batch_tail_drains_and_late_source_time_is_not_skipped(setup):
    _, _, analysis, device, room, _, _ = setup
    configure(setup, batch_min_messages=3, batch_max_messages=2)
    ingest(setup, [item(room), item(room), item(room)])
    worker = Worker(analysis, StubProvider())
    assert worker.process(device, room) == "completed"
    assert worker.process(device, room) == "completed"
    assert sorted(j["target_count"] for j in analysis.jobs(device)) == [1, 2]
    late = item(room, "합成 배포 지연 업로드", source_time=100)
    ingest(setup, [late])
    assert worker.process(device, room, force=True) == "completed"
    assert any(late["event_id"] in p["evidence_ids"] for s in analysis.summaries(device, room) for p in s["payload"]["points"])


def test_correction_across_batches_keeps_previous_context(setup):
    _, _, analysis, device, room, _, _ = setup
    configure(setup, batch_min_messages=2, batch_max_messages=1)
    now = int(time.time() * 1000)
    a, b = item(room, "합성 배포 일정 공지", observed_at=now-1000), item(room, "취소", observed_at=now)
    ingest(setup, [a, b])
    worker = Worker(analysis, ExtractiveProvider())
    assert worker.process(device, room) == "completed"
    assert worker.process(device, room) == "completed"
    revised = [s for s in analysis.summaries(device, room) if s["payload"]["uncertainty"] == "conflicting_messages"]
    assert len(revised) == 1
    assert {e for p in revised[0]["payload"]["points"] for e in p["evidence_ids"]} == {a["event_id"], b["event_id"]}


def test_chatter_only_batch_does_not_call_provider(setup):
    _, _, analysis, device, room, _, _ = setup
    configure(setup)
    ingest(setup, [item(room, "ㅋㅋㅋ"), item(room, "ㅎㅎ")])
    provider = StubProvider(failure=True)
    assert Worker(analysis, provider).process(device, room) == "completed"
    assert provider.calls == 0 and analysis.status(device)["usage"]["tokens_committed"] == 0


def test_daily_token_budget_pauses_without_consuming_attempts(setup):
    _, _, analysis, device, room, _, _ = setup
    configure(setup, daily_token_limit=10)
    ingest(setup, [item(room)])
    provider = StubProvider()
    assert Worker(analysis, provider).process(device, room, force=True) == "deferred"
    job = analysis.jobs(device)[0]
    assert job["status"] == "paused" and job["attempts"] == 0 and provider.calls == 0


def test_shared_daily_cost_limit_across_concurrent_rooms(setup):
    _, store, analysis, device, room, token, _ = setup
    configure(setup, daily_cost_limit_microusd=10, batch_min_messages=1)
    other_room = uuid4()
    store.provision(device, other_room, token)
    ingest(setup, [item(room), item(other_room)])
    provider = StubProvider()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda r: Worker(analysis, provider).process(device, r), [room, other_room]))
    assert sorted(results) == ["completed", "deferred"]
    assert provider.calls == 1 and analysis.status(device)["usage"]["cost_committed_microusd"] == 10


def test_unknown_billing_keeps_reservation_during_retry(setup):
    _, store, analysis, device, room, _, _ = setup
    configure(setup, daily_token_limit=30)
    ingest(setup, [item(room)])
    provider = StubProvider(failure=True)
    worker = Worker(analysis, provider)
    assert worker.process(device, room, force=True) == "failed"
    assert worker.process(device, room, force=True) == "idle"
    with store.connect() as db:
        db.execute("UPDATE analysis_jobs SET not_before=now()-interval '1 second' WHERE device_id=%s", (device,))
    assert worker.process(device, room, force=True) == "deferred"
    status = analysis.status(device)
    assert status["usage"]["tokens_reserved"] == 20 and status["usage"]["unresolved_calls"] == 1
    assert analysis.jobs(device)[0]["attempts"] == 1 and provider.calls == 1
    assert "raw-provider-secret" not in str(analysis.jobs(device))


def test_invalid_outputs_charge_usage_and_stop_after_three_calls(setup):
    _, store, analysis, device, room, _, _ = setup
    configure(setup)
    ingest(setup, [item(room)])
    provider = StubProvider(mutate=lambda o: o["topics"][0]["points"][0].update(evidence_ids=[str(uuid4())]))
    worker = Worker(analysis, provider)
    for _ in range(3):
        assert worker.process(device, room, force=True) == "failed"
        with store.connect() as db:
            db.execute("UPDATE analysis_jobs SET not_before=now()-interval '1 second' WHERE device_id=%s", (device,))
    assert worker.process(device, room, force=True) == "idle"
    assert provider.calls == 3 and analysis.jobs(device)[0]["status"] == "failed"
    assert analysis.status(device)["usage"]["tokens_reported"] == 15
    assert analysis.summaries(device, room) == []


def test_stale_owner_cannot_commit_after_lease_recovery(setup):
    _, store, analysis, device, room, _, _ = setup
    configure(setup)
    ingest(setup, [item(room)])
    first = analysis.claim(device, room, force=True)
    call = analysis.reserve(first, ChargeLimit(tokens=20, cost_microusd=10))
    messages = analysis.messages(first)
    batch = AnalysisInput(prepare_topics(messages), first.profile, first.profile_version)
    with store.connect() as db:
        db.execute("UPDATE analysis_jobs SET lease_until=now()-interval '1 second' WHERE job_id=%s", (first.job_id,))
    recovered = AnalysisStore(store).claim(device, room, force=True)
    assert recovered.job_id == first.job_id and recovered.owner != first.owner
    assert analysis.status(device)["usage"]["tokens_reserved"] == 20
    result = ExtractiveProvider.render(batch)
    output = validate_output(result, batch)
    assert not analysis.complete(first, batch, output, "synthetic-stub-v1")
    assert analysis.complete(recovered, batch, output, "synthetic-stub-v1")
    assert not analysis.complete(recovered, batch, output, "synthetic-stub-v1")
    assert len(analysis.summaries(device, room)) == 1
    assert analysis.settle(call, Usage(input_tokens=2, output_tokens=3, cost_microusd=10, measured=True))
    assert not analysis.settle(call, Usage(input_tokens=0, output_tokens=0, cost_microusd=0, measured=True))


def test_profile_revision_cancels_inflight_result_and_releases_targets(setup):
    _, _, analysis, device, room, _, _ = setup
    configure(setup)
    ingest(setup, [item(room)])
    provider = StubProvider(callback=lambda: configure(setup, interests=["공연"]))
    assert Worker(analysis, provider).process(device, room, force=True) == "superseded"
    assert analysis.summaries(device, room) == []
    assert analysis.status(device)["usage"]["tokens_reported"] == 5
    assert Worker(analysis, StubProvider()).process(device, room, force=True) == "completed"


def test_room_delete_during_call_cannot_resurrect_summaries(setup):
    _, store, analysis, device, room, _, _ = setup
    configure(setup)
    ingest(setup, [item(room)])
    provider = StubProvider(callback=lambda: store.delete_room(device, room))
    assert Worker(analysis, provider).process(device, room, force=True) == "superseded"
    assert analysis.jobs(device) == [] and analysis.summaries(device, room) == []
    assert analysis.status(device)["usage"]["cost_reported_microusd"] == 10
    assert store.status(device)["stored_messages"] == 0


def test_raw_expiry_retains_summary_and_marks_missing_evidence(setup):
    client, store, analysis, device, room, _, headers = setup
    configure(setup)
    ingest(setup, [item(room)])
    assert Worker(analysis, StubProvider()).process(device, room, force=True) == "completed"
    summary = analysis.summaries(device, room)[0]
    with store.connect() as db:
        db.execute("UPDATE messages SET observed_at=%s WHERE device_id=%s", (int(time.time()*1000)-8*86400000,device))
    store.prune()
    evidence = client.get(f"/v1/summaries/{summary['summary_id']}/evidence", headers=headers).json()["evidence"]
    assert evidence[0]["availability"] == "raw_expired" and "text" not in evidence[0]
    assert len(analysis.summaries(device, room)) == 1
    with store.connect() as db:
        db.execute("UPDATE analysis_summaries SET created_at=now()-interval '91 days' WHERE summary_id=%s", (summary["summary_id"],))
    assert store.prune()["expired_summaries"] == 1


def test_sources_expiring_during_call_prevent_summary_commit(setup):
    _, store, analysis, device, room, _, _ = setup
    configure(setup)
    ingest(setup, [item(room)])
    def expire():
        with store.connect() as db:
            db.execute("UPDATE messages SET observed_at=%s WHERE device_id=%s", (int(time.time()*1000)-8*86400000,device))
        store.prune()
    assert Worker(analysis, StubProvider(callback=expire)).process(device, room, force=True) == "superseded"
    assert analysis.jobs(device)[0]["last_error"] == "source_expired"
    assert analysis.summaries(device, room) == []


def test_other_device_cannot_view_profile_summaries_or_evidence(setup):
    client, store, analysis, device, room, _, headers = setup
    configure(setup)
    ingest(setup, [item(room)])
    Worker(analysis, StubProvider()).process(device, room, force=True)
    summary = analysis.summaries(device, room)[0]
    other, token = uuid4(), "synthetic-other-" + str(uuid4())
    store.provision(other, room, token)
    try:
        other_headers = {"Authorization": "Bearer " + token}
        assert client.get("/v1/profile", headers=other_headers).json()["version"] == 0
        assert client.get(f"/v1/rooms/{room}/summaries", headers=other_headers).json()["items"] == []
        assert client.get(f"/v1/summaries/{summary['summary_id']}/evidence", headers=other_headers).status_code == 404
        assert client.delete(f"/v1/rooms/{room}/data", headers=other_headers).json()["deleted_events"] == 0
        assert len(analysis.summaries(device, room)) == 1
    finally:
        with store.connect() as db:
            db.execute("DELETE FROM rooms WHERE device_id=%s", (other,))
            db.execute("DELETE FROM devices WHERE device_id=%s", (other,))


def test_budget_overrun_is_accounted_and_result_withheld(setup):
    _, _, analysis, device, room, _, _ = setup
    configure(setup)
    ingest(setup, [item(room)])
    class Overrun(StubProvider):
        def generate(self, batch):
            result = super().generate(batch)
            return ProviderResult(result.output, Usage(input_tokens=30,output_tokens=0,cost_microusd=10,measured=True), result.model)
    assert Worker(analysis, Overrun()).process(device, room, force=True) == "failed"
    assert analysis.jobs(device)[0]["last_error"] == "budget_overrun"
    assert analysis.status(device)["usage"]["tokens_reported"] == 30
    assert analysis.summaries(device, room) == []


def test_repeated_migration_preserves_m2_messages_and_receipts(setup):
    _, store, _, device, room, _, _ = setup
    ingest(setup, [item(room)])
    store.migrate()
    store.migrate()
    assert store.status(device)["stored_messages"] == 1
    with store.connect() as db:
        assert db.execute("SELECT count(*) AS n FROM receipts WHERE device_id=%s", (device,)).fetchone()["n"] == 1
        assert db.execute("SELECT max(version) AS v FROM schema_versions").fetchone()["v"] == 3


def test_summary_and_job_completion_roll_back_together(setup):
    _, store, analysis, device, room, _, _ = setup
    configure(setup)
    now = int(time.time()*1000)
    ingest(setup,[item(room,"합성 배포 첫 번째",observed_at=now-1000),item(room,"force-rollback-synthetic",observed_at=now)])
    constraint = "fixture_"+uuid4().hex
    with store.connect() as db:
        db.execute(f"ALTER TABLE analysis_summaries ADD CONSTRAINT {constraint} CHECK (payload->>'title' != 'force-rollback-synthetic')")
    try:
        with pytest.raises(psycopg.Error):
            Worker(analysis,StubProvider()).process(device,room)
        assert analysis.summaries(device,room) == []
        assert analysis.jobs(device)[0]["status"] == "running"
        assert analysis.status(device)["usage"]["tokens_reported"] == 5
    finally:
        with store.connect() as db:
            db.execute(f"ALTER TABLE analysis_summaries DROP CONSTRAINT {constraint}")
            db.execute("UPDATE analysis_jobs SET lease_until=now()-interval '1 second' WHERE device_id=%s",(device,))
    assert Worker(analysis,StubProvider()).process(device,room) == "completed"
    assert len(analysis.summaries(device,room)) == 2


def test_next_budget_day_can_resume_a_paused_job(setup):
    _, store, analysis, device, room, _, _ = setup
    configure(setup,daily_token_limit=20)
    ingest(setup,[item(room)])
    provider = StubProvider(failure=True)
    worker = Worker(analysis,provider)
    assert worker.process(device,room,force=True) == "failed"
    with store.connect() as db:
        db.execute("UPDATE analysis_jobs SET not_before=now()-interval '1 second' WHERE device_id=%s",(device,))
    assert worker.process(device,room,force=True) == "deferred"
    # Simulate the previous reservation belonging to yesterday. Do not refund it.
    with store.connect() as db:
        db.execute("UPDATE analysis_usage SET budget_day=budget_day-1 WHERE device_id=%s",(device,))
    assert worker.process(device,room,force=True) == "failed"
    assert provider.calls == 2 and analysis.status(device)["usage"]["tokens_reserved"] == 20
    with store.connect() as db:
        assert db.execute("SELECT sum(tokens_reserved) AS n FROM analysis_usage WHERE device_id=%s",(device,)).fetchone()["n"] == 40


def test_invalid_usage_does_not_release_the_reservation(setup):
    _, _, analysis, device, room, _, _ = setup
    configure(setup)
    ingest(setup,[item(room)])
    class InvalidUsage(StubProvider):
        def generate(self,batch):
            result = super().generate(batch)
            return ProviderResult(result.output,{"input_tokens":-1,"output_tokens":0,"cost_microusd":0,"measured":True},result.model)
    assert Worker(analysis,InvalidUsage()).process(device,room,force=True) == "failed"
    assert analysis.jobs(device)[0]["last_error"] == "invalid_usage"
    assert analysis.status(device)["usage"]["tokens_reserved"] == 20
    assert analysis.summaries(device,room) == []


def test_server_exclusion_guard_ignores_a_provider_high_score(setup):
    _, _, analysis, device, room, _, _ = setup
    configure(setup,exclude_topics=["광고"])
    ingest(setup,[item(room,"합성 배포 광고")])
    provider = StubProvider(mutate=lambda o:o["topics"][0].update(relevance=100))
    assert Worker(analysis,provider).process(device,room,force=True) == "completed"
    assert not analysis.summaries(device,room)[0]["is_candidate"]
    assert analysis.summaries(device,room,candidates_only=True) == []


def test_revoking_a_device_during_call_withholds_results(setup):
    client, store, analysis, device, room, _, headers = setup
    configure(setup)
    ingest(setup,[item(room)])
    def revoke():
        with store.connect() as db:
            db.execute("UPDATE devices SET active=false WHERE device_id=%s",(device,))
    assert Worker(analysis,StubProvider(callback=revoke)).process(device,room,force=True) == "superseded"
    assert analysis.summaries(device,room) == []
    assert client.get("/v1/profile",headers=headers).status_code == 401


def test_openapi_documents_the_profile_wire_contract(setup):
    client,*_ = setup
    schema = client.get("/openapi.json").json()["paths"]["/v1/profile"]["put"]["requestBody"]["content"]["application/json"]["schema"]
    assert "expected_version" in schema["required"]
    assert schema["properties"]["profile"]["properties"]["enabled"]["default"] is False


def test_unpriced_external_provider_is_blocked_before_generate(setup):
    _, _, analysis, device, room, _, _ = setup
    configure(setup)
    ingest(setup,[item(room)])
    class Unpriced(StubProvider):
        external = True
        def maximum_charge(self,batch):
            return ChargeLimit(tokens=20,cost_microusd=0)
    provider = Unpriced()
    assert Worker(analysis,provider).process(device,room,force=True) == "failed"
    assert provider.calls == 0 and analysis.status(device)["usage"]["tokens_committed"] == 0
