"""Provider-neutral M3 contracts. Monetary values are integer micro-USD."""
import json
from dataclasses import dataclass
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PROMPT_VERSION = "m3-v1"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class InterestProfile(StrictModel):
    enabled: bool = False
    interests: list[str] = Field(default_factory=list, max_length=30)
    exclude_topics: list[str] = Field(default_factory=list, max_length=30)
    positive_examples: list[str] = Field(default_factory=list, max_length=10)
    negative_examples: list[str] = Field(default_factory=list, max_length=10)
    relevance_threshold: int = Field(default=70, ge=0, le=100)
    timezone: str = "Asia/Seoul"
    daily_token_limit: int = Field(default=0, ge=0, le=100_000_000)
    daily_cost_limit_microusd: int = Field(default=0, ge=0, le=1_000_000_000)
    batch_min_messages: int = Field(default=500, ge=1, le=10000)
    batch_max_messages: int = Field(default=100, ge=1, le=500)
    max_wait_seconds: int = Field(default=10800, ge=60, le=86400)
    max_input_chars: int = Field(default=64000, ge=16000, le=1_000_000)
    max_output_tokens: int = Field(default=4096, ge=256, le=32000)
    max_attempts: int = Field(default=3, ge=1, le=5)

    @field_validator("interests", "exclude_topics", "positive_examples", "negative_examples")
    @classmethod
    def bounded_terms(cls, values):
        if any(not value.strip() or len(value) > 500 for value in values):
            raise ValueError("Invalid profile terms")
        return list(dict.fromkeys(value.strip() for value in values))

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Invalid timezone") from None
        return value

    @model_validator(mode="after")
    def enabled_requires_limits(self):
        if self.enabled and (not self.interests or self.daily_token_limit == 0):
            raise ValueError("Enabled profiles need interests and a token budget")
        return self


class ProfileUpdate(StrictModel):
    expected_version: int = Field(ge=0)
    profile: InterestProfile


@dataclass(frozen=True)
class CapturedMessage:
    event_id: str
    text: str
    source_time: int | None
    observed_at: int
    urls: tuple[str, ...]
    quality: str


@dataclass(frozen=True)
class Topic:
    topic_id: str
    messages: tuple[CapturedMessage, ...]


@dataclass(frozen=True)
class AnalysisInput:
    topics: tuple[Topic, ...]
    profile: InterestProfile
    profile_version: int
    prompt_version: str = PROMPT_VERSION

    def wire_payload(self):
        # Chat content is data. This contract supplies no tools or credentials.
        return {
            "prompt_version": self.prompt_version,
            "profile_version": self.profile_version,
            "profile": self.profile.model_dump(),
            "untrusted_topics": [
                {"topic_id": t.topic_id, "messages": [
                    {"event_id": m.event_id, "text": m.text, "urls": list(m.urls),
                     "quality": m.quality, "source_time": m.source_time}
                    for m in t.messages
                ]} for t in self.topics
            ],
        }

    def serialized(self):
        return json.dumps(self.wire_payload(), ensure_ascii=False, separators=(",", ":"))


class SummaryPoint(StrictModel):
    text: str = Field(min_length=1, max_length=600)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("evidence_ids")
    @classmethod
    def event_ids(cls, values):
        if len(set(values)) != len(values):
            raise ValueError("Duplicate evidence")
        for value in values:
            if str(UUID(value)) != value:
                raise ValueError("Invalid evidence ID")
        return values


class SummaryTopic(StrictModel):
    topic_id: str = Field(pattern=r"^[a-f0-9]{64}$")
    title: str = Field(min_length=1, max_length=120)
    points: list[SummaryPoint] = Field(min_length=1, max_length=8)
    relevance: int = Field(ge=0, le=100)
    importance: int = Field(ge=0, le=100)
    uncertainty: Literal["none", "limited_context", "conflicting_messages"]
    source_urls: list[str] = Field(default_factory=list, max_length=50)


class AnalysisOutput(StrictModel):
    topics: list[SummaryTopic] = Field(max_length=500)


class Usage(StrictModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_microusd: int = Field(ge=0)
    measured: bool

    @property
    def tokens(self):
        return self.input_tokens + self.output_tokens


class ChargeLimit(StrictModel):
    tokens: int = Field(ge=0)
    cost_microusd: int = Field(ge=0)


@dataclass(frozen=True)
class ProviderResult:
    output: dict
    usage: Usage
    model: str


def validate_output(data: dict, batch: AnalysisInput) -> AnalysisOutput:
    result = AnalysisOutput.model_validate(data)
    expected = {t.topic_id: t for t in batch.topics}
    returned = [t.topic_id for t in result.topics]
    if len(set(returned)) != len(returned) or set(returned) != set(expected):
        raise ValueError("Invalid topic set")
    for summary in result.topics:
        topic = expected[summary.topic_id]
        sources = {m.event_id: m for m in topic.messages}
        cited = {event for point in summary.points for event in point.evidence_ids}
        if not cited.issubset(sources):
            raise ValueError("Invalid evidence scope")
        urls = {url for event in cited for url in sources[event].urls}
        if len(set(summary.source_urls)) != len(summary.source_urls) or not set(summary.source_urls).issubset(urls):
            raise ValueError("Invalid source URLs")
        if any(m.quality != "structured" or m.source_time is None for m in topic.messages) and summary.uncertainty == "none":
            raise ValueError("Uncertain source requires a caveat")
    return result
