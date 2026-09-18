"""Telegram plain-text delivery. Credentials and API bodies never appear in logs."""
import json
import os
import re
from datetime import datetime,timezone
from zoneinfo import ZoneInfo

import httpx

from .delivery_channels import ChannelConfigurationError, ChannelResult, DigestLinks


class TelegramChannel:
    name = "telegram"
    def __init__(self, token, chat_id, links=None, transport=None):
        if not re.fullmatch(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,100}", token or ""):
            raise ChannelConfigurationError("A Telegram bot token is required")
        if not re.fullmatch(r"-?[0-9]{1,20}", str(chat_id or "")):
            raise ChannelConfigurationError("A numeric Telegram chat ID is required")
        self.token, self.chat_id = token, str(chat_id)
        self.links, self.transport = links or DigestLinks(), transport

    @classmethod
    def from_env(cls):
        return cls(os.environ.get("RADAR_TELEGRAM_BOT_TOKEN", ""),
                   os.environ.get("RADAR_TELEGRAM_CHAT_ID", ""),
                   DigestLinks.from_env() if os.environ.get("RADAR_PUBLIC_URL") else DigestLinks())

    def publish(self, claim):
        # No parse_mode: untrusted chat cannot turn into markup or hidden links.
        text = claim.payload["title"] + "\n\n" + claim.payload["message"]
        if claim.payload.get('topics'):
            lines = [claim.payload['title'], '', '방에서 공유된 주장입니다. 외부 사실 검증은 하지 않았습니다.']
            topics = claim.payload['topics']
            quoted = any(t['payload'].get('quotes') for t in topics)
            point_limit = max(40,min(100 if quoted else 150,(3600//len(topics)-(290 if quoted else 110))//3))
            for index, topic in enumerate(topics,1):
                summary = topic['payload']
                lines.append(f"\n{index}. {summary['title'][:90]}")
                lines.extend('· '+point['text'][:point_limit] for point in summary['points'][:3])
                for quote in summary.get('quotes',[])[:2]:
                    stamp = ''
                    if type(quote.get('observed_at')) is int:
                        observed = datetime.fromtimestamp(quote['observed_at']/1000,timezone.utc).astimezone(ZoneInfo('Asia/Seoul'))
                        stamp = observed.strftime(' (%m/%d %H:%M 수집)')
                    lines.append('원문 인용'+stamp+': “'+quote['text']+'”'+(' …' if quote.get('truncated') else ''))
                if summary['uncertainty'] != 'none':
                    lines.append('미확인 정보 · 문맥 제한')
            text = '\n'.join(lines)
        body = {"chat_id": self.chat_id, "text": text[:4000],
                "link_preview_options": {"is_disabled": True}}
        link = self.links.url(claim.delivery_id)
        if link:
            body["reply_markup"] = {"inline_keyboard": [[{"text": "요약·근거·피드백", "url": link}]]}
        try:
            with httpx.Client(transport=self.transport, timeout=httpx.Timeout(20, connect=5),
                              trust_env=False, follow_redirects=False) as client:
                with client.stream("POST", f"https://api.telegram.org/bot{self.token}/sendMessage", json=body) as response:
                    status = response.status_code
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 65536:
                            return ChannelResult("uncertain", "invalid_response")
            if status in (401, 403):
                return ChannelResult("failed", "channel_auth")
            if status >= 500:
                return ChannelResult("uncertain", "channel_unavailable")
            data = json.loads(raw)
            if status == 429:
                delay = data.get("parameters", {}).get("retry_after", 30)
                return ChannelResult("retry", "rate_limited", retry_after=min(86400, max(1, delay)) if type(delay) is int else 30)
            if 400 <= status < 500:
                return ChannelResult("failed", "channel_rejected")
            result = data.get("result", {})
            message = result.get("message_id")
            if status != 200 or data.get("ok") is not True or type(message) is not int or message < 1:
                return ChannelResult("uncertain", "invalid_response")
            if str(result.get("chat", {}).get("id")) != self.chat_id:
                return ChannelResult("uncertain", "invalid_response")
            return ChannelResult("accepted", message_id=str(message))
        except (httpx.ConnectError, httpx.ConnectTimeout):
            return ChannelResult("retry", "connection_failed")
        except httpx.HTTPError:
            return ChannelResult("uncertain", "response_lost")
        except (ValueError, TypeError, AttributeError):
            return ChannelResult("uncertain", "invalid_response")
