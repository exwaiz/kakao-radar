"""Conservative grouping: retain IDs and corrections; never fetch links."""
import hashlib
import json
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from .analysis_models import CapturedMessage, Topic

CORRECTIONS = ("아니요", "아니오", "취소", "정정", "변경", "철회", "수정", "아닙니다", "cancel", "correction")
CHATTER = re.compile(r"^(?:[ㅋㅎㅠㅜ\s!?~.]+|안녕(?:하세요)?[!~. ]*|좋은\s*(?:아침|밤)[!~. ]*)$")


def normalize(text):
    return unicodedata.normalize("NFKC", text).casefold()


def canonical_url(url):
    try:
        parts = urlsplit(url)
        if parts.scheme.lower() not in ("http", "https") or not parts.hostname or parts.username:
            return url
        # Preserve path, query (including order) and fragment; they can carry meaning.
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, parts.fragment))
    except ValueError:
        return url


def is_correction(text):
    return any(term in normalize(text) for term in CORRECTIONS)


def tokens(text):
    text = re.sub(r"https?://\S+", " ", normalize(text))
    return set(re.findall(r"[a-z0-9_]{2,}|[가-힣]{2,}", text)) - {"그리고", "그런데", "오늘", "the", "and"}


def prepare_topics(messages: list[CapturedMessage], preserve_reactions=False) -> tuple[Topic, ...]:
    groups: list[list[CapturedMessage]] = []
    for message in messages:
        if CHATTER.fullmatch(message.text.strip()) and not message.urls:
            if preserve_reactions and groups and re.fullmatch(r"[ㅋㅎ\s!?~.]+", message.text.strip()) and abs(message.observed_at-groups[-1][-1].observed_at)<=120000:
                # Visible laughter is context, not a reaction-button count or consensus.
                groups[-1].append(message)
            continue
        urls = {canonical_url(u) for u in message.urls}
        words = tokens(message.text)
        match = None
        for group in reversed(groups):
            previous = group[-1]
            gap = abs(message.observed_at - previous.observed_at)
            shared_url = urls & {canonical_url(u) for m in group for u in m.urls}
            previous_words = tokens(previous.text)
            common = words & previous_words
            similar = len(common) >= 2 and len(common) / max(1, len(words | previous_words)) >= 0.4
            correction = len(message.text) <= 180 and is_correction(message.text) and not urls
            if (gap <= 1800000 and shared_url) or (gap <= 300000 and (similar or (correction and group is groups[-1]))):
                match = group
                break
        if match is None:
            groups.append([message])
        else:
            match.append(message)
    return tuple(Topic(
        hashlib.sha256(json.dumps([m.event_id for m in group], separators=(",", ":")).encode()).hexdigest(),
        tuple(group),
    ) for group in groups)


def excluded(topic: Topic, terms: list[str]):
    text = normalize("\n".join(m.text for m in topic.messages))
    return any(normalize(term) in text for term in terms)
