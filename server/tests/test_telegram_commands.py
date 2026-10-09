import json

import httpx
import pytest
from uuid import UUID

from radar_server.delivery_channels import ChannelConfigurationError
from radar_server.telegram_command_worker import TelegramCommandWorker, parse_command


TOKEN = "123456:synthetic-" + "x" * 30


class StubStore:
    def __init__(self, route=None):
        self.route = route or {"display_name": "기존 이름", "interval_hours": 1}
        self.offset = 0
        self.renames = []
        self.intervals = []

    def telegram_command_offset(self, bot_id):
        assert bot_id == 123456
        return self.offset

    def advance_telegram_command_offset(self, bot_id, offset):
        assert bot_id == 123456
        self.offset = max(self.offset, offset)

    def telegram_destination(self, chat_id, thread_id):
        assert (chat_id, thread_id) == ("-1009876543210", 77)
        return self.route

    def telegram_destinations(self, chat_id, thread_id):
        assert (chat_id, thread_id) == ("-1009876543210", 77)
        return [{**self.route, "room_id": UUID("25485c30-0000-4000-8000-000000000001")}]

    def rename_telegram_room(self, chat_id, thread_id, display_name):
        assert (chat_id, thread_id) == ("-1009876543210", 77)
        self.renames.append(display_name)
        return {"display_name": display_name, "changed": True}

    def set_telegram_interval(self, chat_id, thread_id, hours, room_key=None):
        assert (chat_id, thread_id) == ("-1009876543210", 77)
        self.intervals.append((room_key, hours))
        return {"interval_hours": hours, "changed": True}


def telegram_transport(updates, sent):
    def respond(request):
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content)
        if method == "getMe":
            return httpx.Response(200, json={"ok": True, "result": {
                "id": 123456, "is_bot": True, "username": "KakaoRadarBot"}})
        if method == "getUpdates":
            assert body["offset"] == 0 and body["allowed_updates"] == ["message"]
            return httpx.Response(200, json={"ok": True, "result": updates})
        if method == "sendMessage":
            sent.append(body)
            result = {"message_id": 42, "message_thread_id": body.get("message_thread_id"),
                      "chat": {"id": int(body["chat_id"])}}
            return httpx.Response(200, json={"ok": True, "result": result})
        raise AssertionError(method)
    return httpx.MockTransport(respond)


def update(text, *, sender=987654321, update_id=8):
    return {"update_id": update_id, "message": {
        "message_id": 1, "message_thread_id": 77, "text": text,
        "from": {"id": sender, "is_bot": False},
        "chat": {"id": -1009876543210, "type": "supergroup"}}}


def test_name_command_renames_topic_room_and_confirms_in_same_topic():
    store, sent = StubStore(), []
    worker = TelegramCommandWorker(store, TOKEN, 987654321,
        transport=telegram_transport([update("/name 새 이름")], sent))
    assert worker.run_once(wait=False) == {"renamed": 1}
    assert store.renames == ["새 이름"] and store.offset == 9
    assert sent == [{"chat_id": "-1009876543210", "text": "이름을 변경했습니다: 새 이름",
                     "link_preview_options": {"is_disabled": True}, "message_thread_id": 77}]


def test_name_without_argument_shows_current_name_and_bot_suffix_is_checked():
    assert parse_command("/name@KakaoRadarBot", "KakaoRadarBot") == ("name", "")
    assert parse_command("/name@OtherBot 새 이름", "KakaoRadarBot") is None
    store, sent = StubStore(), []
    worker = TelegramCommandWorker(store, TOKEN, 987654321,
        transport=telegram_transport([update("/name@KakaoRadarBot")], sent))
    assert worker.run_once(wait=False) == {"shown": 1}
    assert "현재 이름: 기존 이름" in sent[0]["text"]
    assert store.renames == []


def test_unauthorized_sender_is_ignored_without_reply_but_cursor_advances():
    store, sent = StubStore(), []
    worker = TelegramCommandWorker(store, TOKEN, 987654321,
        transport=telegram_transport([update("/name 탈취 시도", sender=111)], sent))
    assert worker.run_once(wait=False) == {"unauthorized": 1}
    assert sent == [] and store.renames == [] and store.offset == 9


def test_private_chat_id_can_supply_admin_but_group_id_cannot(monkeypatch):
    monkeypatch.setenv("RADAR_TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.delenv("RADAR_TELEGRAM_ADMIN_USER_ID", raising=False)
    monkeypatch.setenv("RADAR_TELEGRAM_CHAT_ID", "987654321")
    assert TelegramCommandWorker.from_env(StubStore()).admin_user_id == 987654321
    monkeypatch.setenv("RADAR_TELEGRAM_CHAT_ID", "-1009876543210")
    with pytest.raises(ChannelConfigurationError):
        TelegramCommandWorker.from_env(StubStore())


def test_rooms_command_lists_selector_for_shared_private_chat():
    class SharedStore(StubStore):
        def telegram_destinations(self, chat_id, thread_id):
            return [
                {"room_id": UUID("25485c30-0000-4000-8000-000000000001"),
                 "display_name": "카카오방 A"},
                {"room_id": UUID("5a4a05f6-0000-4000-8000-000000000002"),
                 "display_name": "카카오방 B"},
            ]

    store, sent = SharedStore(), []
    worker = TelegramCommandWorker(store, TOKEN, 987654321,
        transport=telegram_transport([update("/rooms")], sent))
    assert worker.run_once(wait=False) == {"rooms": 1}
    assert "25485c30  카카오방 A" in sent[0]["text"]
    assert "/name 방코드 새 이름" in sent[0]["text"]


def test_shared_private_chat_name_uses_room_selector():
    class SharedStore(StubStore):
        def telegram_destinations(self, chat_id, thread_id):
            return [
                {"room_id": UUID("25485c30-0000-4000-8000-000000000001"),
                 "display_name": "카카오방 A"},
                {"room_id": UUID("5a4a05f6-0000-4000-8000-000000000002"),
                 "display_name": "카카오방 B"},
            ]

        def telegram_destination(self, chat_id, thread_id):
            from radar_server.store import RouteDestinationAmbiguous
            raise RouteDestinationAmbiguous()

        def rename_telegram_room_by_key(self, chat_id, thread_id, room_key, display_name):
            assert (room_key, display_name) == ("25485c30", "광교 아파트")
            self.renames.append(display_name)
            return {"changed": True}

    store, sent = SharedStore(), []
    worker = TelegramCommandWorker(store, TOKEN, 987654321,
        transport=telegram_transport([update("/name 25485c30 광교 아파트")], sent))
    assert worker.run_once(wait=False) == {"renamed": 1}
    assert store.renames == ["광교 아파트"]
    assert sent[0]["text"] == "이름을 변경했습니다: 광교 아파트"


def test_interval_command_changes_single_topic_and_rejects_invalid_or_unauthorized():
    assert parse_command("/interval@KakaoRadarBot 5h", "KakaoRadarBot") == ("interval", "5h")
    store, sent = StubStore(), []
    worker = TelegramCommandWorker(store, TOKEN, 987654321,
        transport=telegram_transport([update("/interval 5h")], sent))
    assert worker.run_once(wait=False) == {"interval_changed": 1}
    assert store.intervals == [(None, 5)]
    assert "5시간" in sent[0]["text"]
    assert worker._process_update(update("/interval 25h")) == "invalid_interval"
    assert worker._process_update(update("/interval 2h", sender=111)) == "unauthorized"
    assert store.intervals == [(None, 5)]


def test_interval_shared_chat_requires_room_code():
    class SharedStore(StubStore):
        def telegram_destinations(self, chat_id, thread_id):
            return [{"room_id": UUID("25485c30-0000-4000-8000-000000000001"),
                     "display_name": "fixture A", "interval_hours": 1},
                    {"room_id": UUID("5a4a05f6-0000-4000-8000-000000000002"),
                     "display_name": "fixture B", "interval_hours": 1}]

    store, sent = SharedStore(), []
    worker = TelegramCommandWorker(store, TOKEN, 987654321,
        transport=telegram_transport([update("/interval 25485c30 5h")], sent))
    assert worker.run_once(wait=False) == {"interval_changed": 1}
    assert store.intervals == [("25485c30", 5)]
    assert worker._process_update(update("/interval")) == "rooms"
    assert "5h" in sent[-1]["text"]
