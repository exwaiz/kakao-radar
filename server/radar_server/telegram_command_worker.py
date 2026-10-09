"""Long-poll Telegram commands for renaming the room mapped to a forum topic."""
import argparse
import json
import os
import re
import time

import httpx
import psycopg

from .delivery_channels import ChannelConfigurationError
from .store import RouteDestinationAmbiguous, Store, normalize_display_name


TOKEN_PATTERN = re.compile(r"[0-9]{5,20}:[A-Za-z0-9_-]{20,100}")
COMMAND_PATTERN = re.compile(r"^/(name|rooms|interval|help|start)(?:@([A-Za-z0-9_]{5,32}))?(?:\s+([\s\S]*))?$")
INTERVAL_PATTERN = re.compile(r"^([1-9][0-9]?)(?:h|시간)?$", re.IGNORECASE)


class TelegramCommandError(Exception):
    pass


def parse_command(text, bot_username):
    if not isinstance(text, str) or len(text) > 4096:
        return None
    match = COMMAND_PATTERN.fullmatch(text.strip())
    if not match:
        return None
    command, target, argument = match.groups()
    if target and target.casefold() != bot_username.casefold():
        return None
    return command, (argument or "").strip()


class TelegramCommandWorker:
    def __init__(self, store, token, admin_user_id, transport=None, poll_timeout=25):
        if not TOKEN_PATTERN.fullmatch(token or ""):
            raise ChannelConfigurationError("A Telegram bot token is required")
        try:
            admin_user_id = int(admin_user_id)
        except (TypeError, ValueError):
            raise ChannelConfigurationError("A Telegram admin user ID is required") from None
        if admin_user_id <= 0:
            raise ChannelConfigurationError("A positive Telegram admin user ID is required")
        self.store = store
        self.token = token
        self.bot_id = int(token.partition(":")[0])
        self.admin_user_id = admin_user_id
        self.transport = transport
        self.poll_timeout = max(0, min(50, int(poll_timeout)))
        self.bot_username = None

    @classmethod
    def from_env(cls, store, transport=None, poll_timeout=25):
        chat_id = os.environ.get("RADAR_TELEGRAM_CHAT_ID", "")
        admin = os.environ.get("RADAR_TELEGRAM_ADMIN_USER_ID", "")
        # Existing private-chat deployments already use the user's positive ID as chat_id.
        if not admin and re.fullmatch(r"[1-9][0-9]{0,19}", chat_id):
            admin = chat_id
        return cls(store, os.environ.get("RADAR_TELEGRAM_BOT_TOKEN", ""), admin,
                   transport=transport, poll_timeout=poll_timeout)

    def _request(self, method, body, *, timeout):
        try:
            with httpx.Client(transport=self.transport,
                              timeout=httpx.Timeout(timeout, connect=5),
                              trust_env=False, follow_redirects=False) as client:
                with client.stream("POST", f"https://api.telegram.org/bot{self.token}/{method}",
                                   json=body) as response:
                    status = response.status_code
                    raw = bytearray()
                    for chunk in response.iter_bytes():
                        raw.extend(chunk)
                        if len(raw) > 1024 * 1024:
                            raise TelegramCommandError("invalid_response")
            if status in (401, 403):
                raise TelegramCommandError("channel_auth")
            if status == 409:
                raise TelegramCommandError("webhook_or_polling_conflict")
            if status == 429:
                raise TelegramCommandError("rate_limited")
            if status >= 500:
                raise TelegramCommandError("channel_unavailable")
            data = json.loads(raw)
            if status != 200 or not isinstance(data, dict) or data.get("ok") is not True:
                raise TelegramCommandError("channel_rejected")
            return data.get("result")
        except (httpx.ConnectError, httpx.ConnectTimeout):
            raise TelegramCommandError("connection_failed") from None
        except httpx.HTTPError:
            raise TelegramCommandError("response_lost") from None
        except (ValueError, TypeError, UnicodeError):
            raise TelegramCommandError("invalid_response") from None

    def identify(self):
        result = self._request("getMe", {}, timeout=10)
        if (not isinstance(result, dict) or result.get("id") != self.bot_id
                or result.get("is_bot") is not True
                or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", result.get("username", ""))):
            raise TelegramCommandError("invalid_response")
        self.bot_username = result["username"]
        return self.bot_username

    def _send(self, chat_id, thread_id, text):
        body = {"chat_id": str(chat_id), "text": text,
                "link_preview_options": {"is_disabled": True}}
        if thread_id is not None:
            body["message_thread_id"] = thread_id
        result = self._request("sendMessage", body, timeout=20)
        if (not isinstance(result, dict) or type(result.get("message_id")) is not int
                or str(result.get("chat", {}).get("id")) != str(chat_id)
                or thread_id is not None and result.get("message_thread_id") != thread_id):
            raise TelegramCommandError("invalid_response")

    @staticmethod
    def _room_list(routes):
        if not routes:
            return "이 채팅에 연결된 Kakao 방이 없습니다."
        lines = ["연결된 Kakao 방:"]
        for route in routes:
            key = str(route["room_id"])[:8]
            lines.append(f"• {key}  {route['display_name'] or '(이름 없음)'} · {route.get('interval_hours', 1)}시간")
        lines += ["", "이름: /name 방코드 새 이름", "발송 간격: /interval 방코드 5h"]
        return "\n".join(lines)

    def _interval(self, chat_id, thread_id, argument, routes):
        if not argument:
            if len(routes) == 1:
                route = routes[0]
                self._send(chat_id, thread_id,
                           f"현재 발송 간격: {route['interval_hours']}시간\n변경: /interval 5h")
                return "interval_shown"
            self._send(chat_id, thread_id, self._room_list(routes))
            return "rooms"
        parts = argument.split()
        if len(routes) == 1 and len(parts) == 1:
            room_key, value = None, parts[0]
        elif len(parts) == 2:
            room_key, value = parts
        else:
            self._send(chat_id, thread_id, "사용법: /interval 방코드 5h (포럼 토픽: /interval 5h)")
            return "invalid_interval"
        match = INTERVAL_PATTERN.fullmatch(value)
        if not match or not 1 <= int(match[1]) <= 24:
            self._send(chat_id, thread_id, "발송 간격은 1~24시간의 정수로 지정해주세요. 예: /interval 방코드 5h")
            return "invalid_interval"
        if room_key is None and len(routes) != 1:
            self._send(chat_id, thread_id, self._room_list(routes))
            return "select_room"
        try:
            changed = self.store.set_telegram_interval(chat_id, thread_id, int(match[1]), room_key)
        except (ValueError, RouteDestinationAmbiguous):
            self._send(chat_id, thread_id, "방코드가 올바르지 않거나 중복됩니다. /rooms로 다시 확인해주세요.")
            return "invalid_interval"
        if changed is None:
            self._send(chat_id, thread_id, "해당 방을 찾지 못했습니다. /rooms로 다시 확인해주세요.")
            return "not_mapped"
        prefix = "발송 간격을 변경했습니다" if changed["changed"] else "이미 설정된 발송 간격입니다"
        self._send(chat_id, thread_id, f"{prefix}: {changed['interval_hours']}시간")
        return "interval_changed" if changed["changed"] else "interval_unchanged"

    def _process_update(self, update):
        message = update.get("message") if isinstance(update, dict) else None
        if not isinstance(message, dict):
            return "ignored"
        sender = message.get("from")
        chat = message.get("chat")
        if (not isinstance(sender, dict) or type(sender.get("id")) is not int
                or sender["id"] != self.admin_user_id or sender.get("is_bot") is True
                or not isinstance(chat, dict) or type(chat.get("id")) is not int):
            return "unauthorized"
        thread_id = message.get("message_thread_id")
        if thread_id is not None and (type(thread_id) is not int or thread_id <= 0):
            return "ignored"
        parsed = parse_command(message.get("text"), self.bot_username)
        if parsed is None:
            return "ignored"
        command, argument = parsed
        chat_id = str(chat["id"])
        if command in ("help", "start"):
            self._send(chat_id, thread_id,
                       "방 목록: /rooms\n"
                       "개인 채팅에서 변경: /name 방코드 새 이름\n"
                       "포럼 토픽에서 변경: /name 새 이름\n"
                       "발송 간격: /interval 방코드 5h (포럼 토픽: /interval 5h)\n"
                       "현재 설정 확인: /rooms 또는 /interval")
            return "help"
        routes = self.store.telegram_destinations(chat_id, thread_id)
        if command == "rooms":
            self._send(chat_id, thread_id, self._room_list(routes))
            return "rooms"
        if command == "interval":
            return self._interval(chat_id, thread_id, argument, routes)
        try:
            route = self.store.telegram_destination(chat_id, thread_id)
        except RouteDestinationAmbiguous:
            if not argument:
                self._send(chat_id, thread_id, self._room_list(routes))
                return "rooms"
            room_key, separator, display_name = argument.partition(" ")
            if not separator or not display_name.strip():
                self._send(chat_id, thread_id, self._room_list(routes))
                return "select_room"
            try:
                renamed = self.store.rename_telegram_room_by_key(
                    chat_id, thread_id, room_key, display_name.strip())
            except (ValueError, RouteDestinationAmbiguous):
                self._send(chat_id, thread_id, "방코드나 이름이 올바르지 않습니다. /rooms로 다시 확인해주세요.")
                return "invalid_name"
            if renamed is None:
                self._send(chat_id, thread_id, "해당 방코드를 찾지 못했습니다. /rooms로 다시 확인해주세요.")
                return "not_mapped"
            prefix = "이름을 변경했습니다" if renamed["changed"] else "이미 같은 이름입니다"
            self._send(chat_id, thread_id, f"{prefix}: {display_name.strip()}")
            return "renamed" if renamed["changed"] else "unchanged"
        if route is None:
            self._send(chat_id, thread_id, "이 토픽에 연결된 Kakao 방이 없습니다.")
            return "not_mapped"
        if not argument:
            current = route["display_name"] or "(이름 없음)"
            self._send(chat_id, thread_id,
                       f"현재 이름: {current}\n변경: /name 새 이름")
            return "shown"
        try:
            display_name = normalize_display_name(argument)
            renamed = self.store.rename_telegram_room(chat_id, thread_id, display_name)
        except ValueError:
            self._send(chat_id, thread_id, "이름은 공백이 아닌 120자 이하의 일반 텍스트로 보내주세요.")
            return "invalid_name"
        except RouteDestinationAmbiguous:
            self._send(chat_id, thread_id, "이 토픽에 여러 방이 연결되어 있어 이름을 바꾸지 않았습니다.")
            return "ambiguous"
        if renamed is None:
            self._send(chat_id, thread_id, "라우트가 변경되어 이름을 바꾸지 못했습니다. 다시 시도해주세요.")
            return "not_mapped"
        prefix = "이름을 변경했습니다" if renamed["changed"] else "이미 같은 이름입니다"
        self._send(chat_id, thread_id, f"{prefix}: {display_name}")
        return "renamed" if renamed["changed"] else "unchanged"

    def run_once(self, *, wait=True):
        if self.bot_username is None:
            self.identify()
        offset = self.store.telegram_command_offset(self.bot_id)
        result = self._request("getUpdates", {
            "offset": offset,
            "timeout": self.poll_timeout if wait else 0,
            "limit": 50,
            "allowed_updates": ["message"],
        }, timeout=self.poll_timeout + 10 if wait else 10)
        if not isinstance(result, list):
            raise TelegramCommandError("invalid_response")
        counts = {}
        for update in sorted(result, key=lambda item: item.get("update_id", -1)
                             if isinstance(item, dict) else -1):
            update_id = update.get("update_id") if isinstance(update, dict) else None
            if type(update_id) is not int or update_id < offset:
                continue
            outcome = self._process_update(update)
            self.store.advance_telegram_command_offset(self.bot_id, update_id + 1)
            offset = update_id + 1
            counts[outcome] = counts.get(outcome, 0) + 1
        return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    store = Store(os.environ["RADAR_DATABASE_URL"])
    store.migrate()
    try:
        worker = TelegramCommandWorker.from_env(store)
    except ChannelConfigurationError:
        parser.exit(1, "Telegram command configuration is incomplete or invalid\n")
    while True:
        try:
            result = worker.run_once(wait=not args.once)
            if args.once:
                print(result)
                return
        except TelegramCommandError as error:
            print({"telegram_commands": "temporarily_unavailable", "reason": str(error)}, flush=True)
            if args.once:
                raise SystemExit(1) from None
            time.sleep(10)
        except psycopg.Error:
            print({"telegram_commands": "storage_temporarily_unavailable"}, flush=True)
            if args.once:
                raise SystemExit(1) from None
            time.sleep(10)


if __name__ == "__main__":
    main()
