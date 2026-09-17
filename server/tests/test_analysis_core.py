import copy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from radar_server.analysis_models import AnalysisInput, CapturedMessage, InterestProfile, validate_output
from radar_server.providers import ExtractiveProvider, ProviderFailure
from radar_server.topics import canonical_url, prepare_topics


def captured(text, time=1000, urls=(), quality="structured", source=1000):
    return CapturedMessage(str(uuid4()), text, source, time, tuple(urls), quality)


def batch(messages, **profile):
    return AnalysisInput(prepare_topics(messages), InterestProfile(interests=["배포"], **profile), 1)


def test_url_query_and_fragment_are_preserved():
    assert canonical_url("HTTPS://Example.COM/doc?a=1&b=2#section") == "https://example.com/doc?a=1&b=2#section"
    assert canonical_url("https://example.com/doc?version=1") != canonical_url("https://example.com/doc?version=2")
    assert canonical_url("https://[invalid") == "https://[invalid"


def test_shared_url_groups_updates_but_different_query_does_not():
    a = captured("합성 배포 공지", urls=["https://example.com/?version=1"])
    b = captured("합성 상세 안내", time=2000, urls=["https://EXAMPLE.COM/?version=1"])
    c = captured("합성 별도 일정", time=3000, urls=["https://example.com/?version=2"])
    topics = prepare_topics([a, b, c])
    assert [len(t.messages) for t in topics] == [2, 1]
    assert [m.event_id for m in topics[0].messages] == [a.event_id, b.event_id]


def test_chatter_removed_and_short_correction_preserved():
    messages = [captured("ㅋㅋㅋ"), captured("합성 배포 일정은 내일입니다"), captured("아니요, 취소", time=2000)]
    topics = prepare_topics(messages)
    assert len(topics) == 1 and len(topics[0].messages) == 2
    result = ExtractiveProvider().generate(batch(messages))
    assert result.output["topics"][0]["uncertainty"] == "conflicting_messages"
    assert result.output["topics"][0]["points"][-1]["text"] == "아니요, 취소"


def test_identical_sentences_keep_distinct_ids():
    a, b = captured("합성 배포 일정 공지"), captured("합성 배포 일정 공지", time=2000)
    topic = prepare_topics([a, b])[0]
    assert [m.event_id for m in topic.messages] == [a.event_id, b.event_id]


def test_reference_provider_labels_simulated_usage_and_exclusions():
    provider = ExtractiveProvider()
    data = batch([captured("합성 배포 할인 광고")], exclude_topics=["광고"])
    result = provider.generate(data)
    assert result.output["topics"][0]["relevance"] == 0
    assert result.usage.measured is False and result.usage.cost_microusd == 0
    assert result.usage.tokens <= provider.maximum_charge(data).tokens
    validate_output(result.output, data)


@pytest.mark.parametrize("mutate", [
    lambda s: s.update(relevance=101),
    lambda s: s.update(relevance="90"),
    lambda s: s.update(importance=True),
    lambda s: s["points"][0].update(evidence_ids=[str(uuid4())]),
    lambda s: s["points"][0].update(evidence_ids=[]),
    lambda s: s.update(source_urls=["https://invented.invalid"]),
    lambda s: s.update(secret="untrusted instruction"),
])
def test_invalid_output_is_rejected(mutate):
    data = batch([captured("합성 배포 안내")])
    output = copy.deepcopy(ExtractiveProvider().generate(data).output)
    mutate(output["topics"][0])
    with pytest.raises((ValueError, ValidationError)):
        validate_output(output, data)


def test_evidence_from_another_topic_is_rejected():
    data = batch([captured("합성 배포 공지"), captured("합성 공연 시작")])
    output = ExtractiveProvider().generate(data).output
    output["topics"][0]["points"][0]["evidence_ids"] = [data.topics[1].messages[0].event_id]
    with pytest.raises(ValueError):
        validate_output(output, data)


def test_missing_or_duplicate_topics_are_rejected():
    data = batch([captured("합성 배포 공지")])
    output = ExtractiveProvider().generate(data).output
    with pytest.raises(ValueError):
        validate_output({"topics": []}, data)
    with pytest.raises(ValueError):
        validate_output({"topics": output["topics"] * 2}, data)


def test_uncertain_source_cannot_be_presented_as_certain():
    data = batch([captured("합성 배포 안내", source=None, quality="fallback_no_message_time")])
    output = ExtractiveProvider().generate(data).output
    validate_output(output, data)
    output["topics"][0]["uncertainty"] = "none"
    with pytest.raises(ValueError):
        validate_output(output, data)


@pytest.mark.parametrize("changes", [
    {"enabled": True}, {"timezone": "Invalid/Timezone"}, {"interests": [""]},
    {"daily_token_limit": -1}, {"daily_cost_limit_microusd": "10"},
])
def test_invalid_profiles_are_rejected(changes):
    with pytest.raises(ValidationError):
        InterestProfile.model_validate(changes)


def test_input_bound_is_checked_before_a_call():
    data = batch([captured("합成 메시지" * 5000)], max_input_chars=16000)
    with pytest.raises(ProviderFailure) as error:
        ExtractiveProvider().maximum_charge(data)
    assert error.value.code == "input_too_large" and error.value.permanent
