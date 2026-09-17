"""ntfy JSON adapter and narrowly scoped digest links. Never log response bodies."""
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx


class ChannelConfigurationError(Exception):
    pass


def https_root(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ChannelConfigurationError("A server HTTPS root URL is required")
    try:
        parsed.port
    except ValueError:
        raise ChannelConfigurationError("Invalid server port") from None
    return value.rstrip("/")


class DigestLinks:
    def __init__(self, base_url=None, secret=None):
        self.base_url, self.secret = None, None
        if base_url or secret:
            if not base_url or not secret or len(secret) < 32:
                raise ChannelConfigurationError("Both digest URL and a 32+ character secret are required")
            self.base_url = https_root(base_url)
            self.secret = secret.encode()

    @classmethod
    def from_env(cls):
        return cls(os.environ.get("RADAR_PUBLIC_URL"), os.environ.get("RADAR_DIGEST_LINK_SECRET"))

    @property
    def enabled(self):
        return self.secret is not None

    def token(self, delivery):
        if not self.enabled:
            return None
        return hmac.new(self.secret, ("m4-digest:" + str(delivery)).encode(), hashlib.sha256).hexdigest()

    def verify(self, delivery, token):
        return bool(self.enabled and token and re.fullmatch(r"[a-f0-9]{64}", token)
                    and hmac.compare_digest(self.token(delivery), token))

    def url(self, delivery):
        # Fragments are never sent in the HTTP request target or normal access logs.
        return f"{self.base_url}/digest/{delivery}#key={self.token(delivery)}" if self.enabled else None


@dataclass(frozen=True)
class ChannelResult:
    outcome: str
    code: str | None = None
    message_id: str | None = None
    retry_after: int = 0


class NtfyChannel:
    name = "ntfy"

    def __init__(self, base_url, topic, token, links=None, transport=None):
        self.base_url = https_root(base_url)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", topic or ""):
            raise ChannelConfigurationError("Invalid ntfy topic")
        if not token or len(token) > 512 or not token.isascii() or any(c.isspace() or ord(c) < 32 for c in token):
            raise ChannelConfigurationError("An ntfy access token is required")
        self.topic, self.token = topic, token
        self.links = links or DigestLinks()
        self.transport = transport

    @classmethod
    def from_env(cls):
        return cls(os.environ.get("RADAR_NTFY_URL", ""), os.environ.get("RADAR_NTFY_TOPIC", ""),
                   os.environ.get("RADAR_NTFY_TOKEN", ""), DigestLinks.from_env())

    @staticmethod
    def _retry_after(value):
        try:
            return min(86400, max(0, int(value)))
        except (ValueError, TypeError):
            try:
                date = parsedate_to_datetime(value)
                return min(86400, max(0, int((date - datetime.now(timezone.utc)).total_seconds())))
            except (ValueError, TypeError, OverflowError):
                return 0

    def publish(self, claim):
        body = {"topic": self.topic, "title": claim.payload["title"], "message": claim.payload["message"],
                "priority": 3, "tags": ["memo"]}
        link = self.links.url(claim.delivery_id)
        if link:
            body.update(click=link, actions=[{"action": "view", "label": "요약·근거·피드백", "url": link}])
        # delivery_id is stable across retries; sequence updates are deliberately not
        # treated as an exactly-once API. Unknown outcomes never auto-retry.
        try:
            with httpx.Client(transport=self.transport, timeout=httpx.Timeout(15, connect=5),
                              follow_redirects=False, trust_env=False) as client:
                start = time.monotonic()
                with client.stream("POST", self.base_url + "/", json=body,
                                   headers={"Authorization": "Bearer " + self.token}) as response:
                    if response.status_code == 429:
                        return ChannelResult("retry", "rate_limited", retry_after=self._retry_after(response.headers.get("Retry-After")))
                    if response.status_code in (401, 403):
                        return ChannelResult("failed", "channel_auth")
                    if 400 <= response.status_code < 500:
                        return ChannelResult("failed", "channel_rejected")
                    if not 200 <= response.status_code < 300:
                        return ChannelResult("uncertain", "channel_unavailable")
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 16384 or time.monotonic() - start > 25:
                            return ChannelResult("uncertain", "invalid_response")
                    try:
                        data = json.loads(raw)
                        message_id = data.get("id") if isinstance(data, dict) else None
                        if (not isinstance(message_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", message_id)
                                or data.get("event") != "message" or data.get("topic") != self.topic):
                            raise ValueError()
                    except (ValueError, UnicodeError):
                        return ChannelResult("uncertain", "invalid_response")
                    return ChannelResult("accepted", message_id=message_id)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return ChannelResult("retry", "connection_failed")
        except httpx.HTTPError:
            return ChannelResult("uncertain", "response_lost")


def channel_readiness():
    try:
        channel = NtfyChannel.from_env()
        return {"configured": True, "digest_links_configured": channel.links.enabled}
    except (ChannelConfigurationError, ValueError):
        return {"configured": False, "digest_links_configured": False}
