import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from radar_server.delivery_channels import (ChannelConfigurationError, DigestLinks,
                                            NtfyChannel)
from radar_server.delivery_models import (DeliveryPolicy, DeliveryResolution, after_quiet,
                                          fingerprint, is_quiet, next_slot, render_digest)
from radar_server.delivery_store import SendClaim


def instant(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def topic(**changes):
    return {"title": "합성 배포 일정", "points": [{"text": "합성 일정이 다음 주로 변경됐습니다.", "evidence_ids": [str(uuid4())]}],
            "source_urls": ["https://example.com/synthetic"], "uncertainty": "limited_context", **changes}


@pytest.mark.parametrize("changes", [
    {"enabled": True}, {"daily_times": ["8:30"]}, {"daily_times": ["24:00"]},
    {"daily_times": ["08:00", "08:00"]}, {"quiet_start": "23:00"},
    {"quiet_start": "00:00", "quiet_end": "00:00"}, {"timezone": "synthetic-invalid-zone"},
    {"channel": "telegram"}, {"daily_notification_limit": True},
])
def test_invalid_policy(changes):
    with pytest.raises(ValidationError):
        DeliveryPolicy(**changes)


def test_policy_disabled_defaults_and_explicit_activation():
    policy = DeliveryPolicy()
    assert not policy.enabled and policy.daily_times == [] and policy.daily_notification_limit == 0
    active = DeliveryPolicy(enabled=True, daily_times=["20:30", "08:00"], daily_notification_limit=2)
    assert active.daily_times == ["08:00", "20:30"]


def test_quiet_hours_overnight_and_same_day_boundaries():
    policy = DeliveryPolicy(quiet_start="23:00", quiet_end="08:00")
    assert is_quiet(policy, instant("2026-09-17T14:00:00"))
    assert after_quiet(policy, instant("2026-09-17T15:35:22")) == instant("2026-09-17T23:00:00")
    assert not is_quiet(policy, instant("2026-09-17T23:00:00"))
    policy = DeliveryPolicy(timezone="UTC", quiet_start="12:00", quiet_end="13:00")
    assert after_quiet(policy, instant("2026-09-17T12:15:00")) == instant("2026-09-17T13:00:00")


def test_schedule_and_midnight():
    policy = DeliveryPolicy(daily_times=["00:00", "08:30"])
    assert next_slot(policy, instant("2026-09-17T14:59:59")) == instant("2026-09-17T15:00:00")
    assert next_slot(policy, instant("2026-09-17T15:00:00")) == instant("2026-09-17T23:30:00")


def test_dst_missing_time_moves_forward_and_repeated_time_runs_once():
    policy = DeliveryPolicy(timezone="America/New_York", daily_times=["02:30"])
    assert next_slot(policy, instant("2026-03-08T05:00:00")) == instant("2026-03-08T07:00:00")
    policy = DeliveryPolicy(timezone="America/New_York", daily_times=["01:30"])
    assert next_slot(policy, instant("2026-11-01T04:00:00")) == instant("2026-11-01T05:30:00")
    assert next_slot(policy, instant("2026-11-01T05:31:00")) == instant("2026-11-02T06:30:00")


def test_dedup_ignores_new_evidence_ids_but_preserves_corrections_and_rooms():
    room = uuid4()
    first, repeated = topic(), topic()
    assert fingerprint(room, first) == fingerprint(room, repeated)
    assert fingerprint(room, first) != fingerprint(uuid4(), first)
    corrected = topic(points=[{"text": "합성 배포는 취소됐습니다.", "evidence_ids": [str(uuid4())]}])
    assert fingerprint(room, first) != fingerprint(room, corrected)
    assert fingerprint(room, first) != fingerprint(room, topic(source_urls=["https://example.com/synthetic?v=2"]))


def test_unicode_digest_stays_text_and_under_ntfy_message_limit():
    topics = [{"summary_id": str(uuid4()), "room_id": str(uuid4()),
               "payload": topic(title="合成🌸" * 100, points=[{"text": "중국어合成🌸" * 200, "evidence_ids": [str(uuid4())]}])} for _ in range(10)]
    delivery = uuid4()
    result = render_digest(topics, delivery)
    assert len(result["message"].encode("utf-8")) <= 3800
    assert "10." in result["message"] and str(delivery) in result["message"]
    assert "외부 사실 검증" in result["message"] and "문맥" in result["message"]


def test_scoped_digest_links_and_rotation():
    links = DigestLinks("https://radar.example.com", "synthetic-secret-" + "s" * 32)
    delivery = uuid4()
    token = links.token(delivery)
    assert links.verify(delivery, token)
    assert not links.verify(uuid4(), token)
    assert not DigestLinks("https://radar.example.com", "rotated-secret-" + "s" * 32).verify(delivery, token)
    assert "?" not in links.url(delivery) and "#key=" in links.url(delivery)
    assert not DigestLinks().verify(delivery, token)
    assert not links.verify(delivery, "합" * 64)


@pytest.mark.parametrize("url", ["http://ntfy.example.com", "https://user:secret@ntfy.example.com", "https://ntfy.example.com/topic", "https://ntfy.example.com?auth=synthetic", "https://ntfy.example.com/#synthetic"])
def test_channel_rejects_unsafe_configuration(url):
    with pytest.raises(ChannelConfigurationError):
        NtfyChannel(url, "synthetic-topic", "synthetic-token")


def claim():
    return SendClaim(uuid4(), uuid4(), uuid4(), uuid4(), {"title": "합성 요약", "message": "합성 메시지"})


def adapter(handler, links=None):
    return NtfyChannel("https://ntfy.example.com", "synthetic-topic", "synthetic-private-token",
                       links=links, transport=httpx.MockTransport(handler))


def test_ntfy_json_request_auth_priority_and_scoped_click():
    attempt = claim()
    links = DigestLinks("https://radar.example.com", "s" * 32)
    def handler(request):
        assert str(request.url) == "https://ntfy.example.com/"
        assert request.headers["Authorization"] == "Bearer synthetic-private-token"
        body = json.loads(request.content)
        assert body["topic"] == "synthetic-topic" and body["priority"] == 3
        assert body["message"] == "합성 메시지" and body["click"] == links.url(attempt.delivery_id)
        assert body["actions"][0]["action"] == "view"
        return httpx.Response(200, json={"id": "syntheticId1", "event": "message", "topic": "synthetic-topic"})
    result = adapter(handler, links).publish(attempt)
    assert result.outcome == "accepted" and result.message_id == "syntheticId1"


@pytest.mark.parametrize("status,outcome,code", [(429,"retry","rate_limited"), (401,"failed","channel_auth"),
    (403,"failed","channel_auth"), (400,"failed","channel_rejected"), (500,"uncertain","channel_unavailable"),
    (302,"uncertain","channel_unavailable")])
def test_channel_http_outcomes_and_safe_errors(status, outcome, code):
    result = adapter(lambda _: httpx.Response(status, text="synthetic-raw-secret", headers={"Retry-After":"60"})).publish(claim())
    assert result.outcome == outcome and result.code == code
    assert "synthetic-raw-secret" not in str(result)
    if status == 429:
        assert result.retry_after == 60


@pytest.mark.parametrize("exception,outcome", [(httpx.ConnectError,"retry"), (httpx.ReadTimeout,"uncertain"),
    (httpx.WriteError,"uncertain")])
def test_connection_failures_and_unknown_outcomes(exception, outcome):
    def handler(request):
        raise exception("synthetic-raw-secret", request=request)
    result = adapter(handler).publish(claim())
    assert result.outcome == outcome and "synthetic-raw-secret" not in str(result)


@pytest.mark.parametrize("body", [b"not-json", b"x" * 17000, b'{"id":"synthetic-raw-secret"}', b'[]'])
def test_channel_invalid_success_responses_remain_uncertain(body):
    assert adapter(lambda _: httpx.Response(200, content=body)).publish(claim()).outcome == "uncertain"


def test_manual_retry_requires_explicit_duplicate_acknowledgement():
    with pytest.raises(ValidationError):
        DeliveryResolution(action="retry")
    assert DeliveryResolution(action="retry", acknowledge_duplicate_risk=True).action == "retry"


def test_worker_default_is_disabled_without_database_or_credentials(monkeypatch, capsys):
    from radar_server.delivery_worker import main
    monkeypatch.delenv("RADAR_DELIVERY_PROVIDER", raising=False)
    monkeypatch.delenv("RADAR_DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["delivery_worker"])
    main()
    assert "Delivery disabled" in capsys.readouterr().out


def test_worker_unknown_environment_provider_does_not_enable_delivery(monkeypatch):
    from radar_server.delivery_worker import main
    monkeypatch.setenv("RADAR_DELIVERY_PROVIDER", "synthetic-invalid")
    monkeypatch.delenv("RADAR_DATABASE_URL", raising=False)
    monkeypatch.setattr("sys.argv", ["delivery_worker"])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 1
