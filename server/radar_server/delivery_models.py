"""M4 delivery policy, local schedules and bounded plain-text digests."""
import hashlib
import json
import re
import unicodedata
from datetime import datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator, model_validator

from .analysis_models import InterestProfile, StrictModel


class DeliveryPolicy(StrictModel):
    enabled: bool = False
    channel: Literal["ntfy"] = "ntfy"
    timezone: str = "Asia/Seoul"
    daily_times: list[str] = Field(default_factory=list, max_length=24)
    quiet_start: str | None = None
    quiet_end: str | None = None
    daily_notification_limit: int = Field(default=0, ge=0, le=24)
    max_topics_per_digest: int = Field(default=5, ge=1, le=10)
    max_summary_age_hours: int = Field(default=72, ge=1, le=2160)
    dedup_hours: int = Field(default=24, ge=1, le=2160)
    max_attempts: int = Field(default=3, ge=1, le=5)

    @field_validator("timezone")
    @classmethod
    def zone(cls, value):
        return InterestProfile.valid_timezone(value)

    @field_validator("daily_times")
    @classmethod
    def times(cls, values):
        for value in values:
            parse_time(value)
        if len(set(values)) != len(values):
            raise ValueError("Duplicate delivery time")
        return sorted(values)

    @field_validator("quiet_start", "quiet_end")
    @classmethod
    def quiet_time(cls, value):
        if value is not None:
            parse_time(value)
        return value

    @model_validator(mode="after")
    def complete_settings(self):
        if (self.quiet_start is None) != (self.quiet_end is None):
            raise ValueError("Both quiet-hour endpoints are required")
        if self.quiet_start is not None and self.quiet_start == self.quiet_end:
            raise ValueError("Quiet hours cannot cover the entire day")
        if self.enabled and (not self.daily_times or self.daily_notification_limit == 0):
            raise ValueError("Enabled delivery requires a schedule and daily limit")
        return self


class DeliveryPolicyUpdate(StrictModel):
    expected_version: int = Field(ge=0)
    policy: DeliveryPolicy


class FeedbackUpdate(StrictModel):
    rating: Literal["useful", "not_interested"]


class DeliveryResolution(StrictModel):
    action: Literal["mark_accepted", "retry"]
    acknowledge_duplicate_risk: bool = False

    @model_validator(mode="after")
    def acknowledge_retry(self):
        if self.action == "retry" and not self.acknowledge_duplicate_risk:
            raise ValueError("Retry requires acknowledging a possible duplicate")
        return self


def parse_time(value):
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
        raise ValueError("Expected HH:MM")
    return time.fromisoformat(value)


def local_instant(day, wall_time, zone):
    """Choose the first fold; move nonexistent wall times to the next valid minute."""
    naive = datetime.combine(day, wall_time)
    for offset in range(181):
        candidate = naive + timedelta(minutes=offset)
        valid = []
        for fold in (0, 1):
            instant = candidate.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
            if instant.astimezone(zone).replace(tzinfo=None) == candidate:
                valid.append(instant)
        if valid:
            return min(valid)
    raise ValueError("Unresolvable local time")


def next_slot(policy, after):
    zone = ZoneInfo(policy.timezone)
    today = after.astimezone(zone).date()
    for delta in range(4):
        slots = sorted(set(local_instant(today + timedelta(days=delta), parse_time(t), zone)
                           for t in policy.daily_times))
        for slot in slots:
            if slot > after:
                return slot
    return None


def is_quiet(policy, instant):
    if policy.quiet_start is None:
        return False
    current = instant.astimezone(ZoneInfo(policy.timezone)).strftime("%H:%M")
    start, end = policy.quiet_start, policy.quiet_end
    return start <= current < end if start < end else current >= start or current < end


def after_quiet(policy, instant):
    if not is_quiet(policy, instant):
        return instant
    candidate = instant.replace(second=0, microsecond=0) + timedelta(minutes=1)
    for _ in range(26 * 60):
        if not is_quiet(policy, candidate):
            return candidate
        candidate += timedelta(minutes=1)
    raise ValueError("Unresolvable quiet hours")


def next_day(policy, instant):
    zone = ZoneInfo(policy.timezone)
    day = instant.astimezone(zone).date() + timedelta(days=1)
    return after_quiet(policy, local_instant(day, time(0), zone))


def plain(value):
    # Content remains text, including model/room instructions. Strip invisible controls.
    return " ".join("".join(c for c in value if not unicodedata.category(c).startswith("C")
                            or c.isspace()).split())


def fingerprint(room, payload):
    normalized = {"room": str(room), "title": plain(payload["title"]).casefold(),
                  "points": [plain(p["text"]).casefold() for p in payload["points"]],
                  "urls": sorted(set(payload["source_urls"])), "uncertainty": payload["uncertainty"]}
    return hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def utf8_excerpt(value, byte_limit):
    raw = plain(value).encode("utf-8")
    if len(raw) <= byte_limit:
        return raw.decode()
    return raw[:byte_limit - 3].decode("utf-8", errors="ignore") + "…"


def render_digest(topics, delivery_id=None):
    lines = ["방에서 공유된 주장입니다. 외부 사실 검증을 수행하지 않았습니다."]
    for index, topic in enumerate(topics, 1):
        payload = topic["payload"]
        lines.append(f"\n{index}. {utf8_excerpt(payload['title'], 90)}")
        lines.append("· " + utf8_excerpt(payload["points"][0]["text"], 150))
        if payload["uncertainty"] != "none":
            lines.append("문맥이 제한되거나 내용이 엇갈립니다. 근거를 확인하세요.")
    if delivery_id:
        lines.append(f"\n전달 ID: {delivery_id}")
    return {"title": f"카톡 레이더 · 관심 주제 {len(topics)}개",
            "message": utf8_excerpt("\n".join(lines), 3800) if len("\n".join(lines).encode()) > 3800
            else "\n".join(lines), "topics": topics}
