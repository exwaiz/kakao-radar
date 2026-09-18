"""Telegram text with explicit formatting entities; quotes remain literal text."""
import json
import os
import re
from datetime import datetime,timezone
from zoneinfo import ZoneInfo

import httpx

from .delivery_channels import ChannelConfigurationError, ChannelResult, DigestLinks


def utf16_length(text):
    return len(text.encode('utf-16-le'))//2


def excerpt(text,limit):
    return text.encode('utf-16-le')[:limit*2].decode('utf-16-le',errors='ignore')


def format_message(payload):
    lines=[]
    entities=[]
    units=0
    def append(text,bold=False):
        nonlocal units
        if lines:
            units+=1
        if bold and text:
            entities.append({'type':'bold','offset':units,'length':utf16_length(text)})
        lines.append(text)
        units+=utf16_length(text)
    append('📡 '+excerpt(payload['title'],120),True)
    topics=payload.get('topics',[])
    if not topics:
        append('')
        append(excerpt(payload['message'],3800-units))
        return '\n'.join(lines),entities
    append('방에서 공유된 주장입니다. 외부 사실 검증은 하지 않았습니다.')
    per_topic=(3900-units)//len(topics)
    for index,topic in enumerate(topics,1):
        summary=topic['payload']
        quotes=summary.get('quotes',[])[:2 if len(topics)<=5 else 1]
        point_limit=max(16,min(100 if quotes else 150,(per_topic-(440 if len(quotes)==2 else 320 if quotes else 185))//3))
        append('')
        icon='🔥' if summary.get('importance',0)>=90 else '📌'
        append(f"{icon} {index}. "+excerpt(summary['title'],90),True)
        if type(topic.get('source_from')) is int and type(topic.get('source_through')) is int:
            zone=ZoneInfo('Asia/Seoul')
            first=datetime.fromtimestamp(topic['source_from']/1000,timezone.utc).astimezone(zone)
            last=datetime.fromtimestamp(topic['source_through']/1000,timezone.utc).astimezone(zone)
            append('🕒 '+first.strftime('%m/%d %H:%M')+'–'+last.strftime('%m/%d %H:%M')+' 수집')
        for number,point in enumerate(summary['points'][:3]):
            append('· '+excerpt(point['text'],point_limit),bold=number==0)
        for quote in quotes:
            stamp=''
            if type(quote.get('observed_at')) is int:
                observed=datetime.fromtimestamp(quote['observed_at']/1000,timezone.utc).astimezone(ZoneInfo('Asia/Seoul'))
                stamp=observed.strftime(' (%m/%d %H:%M 수집)')
            snippet=excerpt(quote['text'],80)
            append('💬 원문 인용'+stamp+': “'+snippet+'”'+(' …' if quote.get('truncated') or snippet!=quote['text'] else ''))
        if summary['uncertainty']!='none':
            append('⚠️ 미확인 정보 · 문맥 제한')
    text='\n'.join(lines)
    if utf16_length(text)>4000:
        raise ValueError('Digest exceeds Telegram text limit')
    return text,entities


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
        # Explicit UTF-16 entities style our own text; source HTML/Markdown is never parsed.
        text,entities=format_message(claim.payload)
        body = {"chat_id": self.chat_id, "text": text, 'entities':entities,
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
