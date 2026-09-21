import hashlib
import json
import re
import secrets
import time
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class RouteVersionConflict(Exception):
    pass


class RouteDestinationConflict(Exception):
    pass


class Store:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def migrate(self):
        with self.connect() as db:
            # Serialize concurrent application startups.
            db.execute("SELECT pg_advisory_xact_lock(61739422)")
            db.execute(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))

    def provision(self, device: UUID, room: UUID, token: str, display_name: str = ""):
        if len(token) < 32:
            raise ValueError("Token must contain at least 32 characters")
        if len(display_name) > 120:
            raise ValueError("Room display name is too long")
        with self.connect() as db:
            db.execute("INSERT INTO devices(device_id,token_hash) VALUES(%s,%s) ON CONFLICT(device_id) DO UPDATE SET token_hash=excluded.token_hash, active=true",
                       (device, hashlib.sha256(token.encode()).hexdigest()))
            db.execute("""INSERT INTO rooms(device_id,room_id,display_name) VALUES(%s,%s,%s)
                ON CONFLICT(device_id,room_id) DO UPDATE SET allowed=true,
                display_name=CASE WHEN excluded.display_name<>'' THEN excluded.display_name ELSE rooms.display_name END,
                updated_at=clock_timestamp()""", (device, room, display_name))

    def authenticate(self, token: str):
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute("SELECT device_id,token_hash FROM devices WHERE active=true AND token_hash=%s", (digest,)).fetchone()
        return row["device_id"] if row and secrets.compare_digest(digest, row["token_hash"]) else None

    @staticmethod
    def payload_hash(message):
        return hashlib.sha256(json.dumps(message.model_dump(mode="json"), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

    def ingest(self, device: UUID, items):
        results = []
        # Responses leave this function only after transaction commit succeeds.
        with self.connect() as db:
            if not db.execute("SELECT device_id FROM devices WHERE device_id=%s AND active=true FOR SHARE", (device,)).fetchone():
                raise PermissionError("Device revoked")
            for item in items:
                event = item.event_id
                authorized = db.execute("SELECT allowed FROM rooms WHERE device_id=%s AND room_id=%s FOR SHARE", (device, item.room_id)).fetchone()
                status, reason = "rejected", "room_not_allowed"
                if authorized and authorized["allowed"]:
                    if item.observed_at < int(time.time()*1000) - 7*86400000:
                        reason = "expired"
                    else:
                        digest = self.payload_hash(item)
                        inserted = db.execute("INSERT INTO receipts(device_id,event_id,room_id,payload_hash) VALUES(%s,%s,%s,%s) ON CONFLICT(device_id,event_id) DO NOTHING RETURNING event_id",
                                              (device,event,item.room_id,digest)).fetchone()
                        if inserted:
                            db.execute("INSERT INTO messages(device_id,event_id,room_id,sender_alias,text,source_time,observed_at,urls,quality,parser_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                                       (device,event,item.room_id,item.sender_alias,item.text,item.source_time,item.observed_at,Jsonb(item.urls),item.quality,item.parser_version))
                            status, reason = "accepted", None
                        else:
                            receipt = db.execute("SELECT payload_hash FROM receipts WHERE device_id=%s AND event_id=%s", (device,event)).fetchone()
                            if receipt["payload_hash"] == digest:
                                status, reason = "duplicate", None
                            else:
                                reason = "event_id_conflict"
                results.append({"event_id":str(event), "status":status, "reason":reason})
        return results

    def status(self, device):
        with self.connect() as db:
            total = db.execute("SELECT count(*) AS stored_messages, max(received_at) AS last_received_at FROM messages WHERE device_id=%s", (device,)).fetchone()
            rooms = db.execute("""SELECT r.room_id,r.display_name,r.allowed,r.updated_at,
                count(DISTINCT m.event_id) AS stored_messages,max(m.received_at) AS last_received_at,
                p.observed_through,
                count(DISTINCT j.job_id) FILTER (WHERE j.status IN ('running','retry_wait','paused')) AS analysis_backlog,
                tr.chat_id,tr.message_thread_id,tr.display_name AS route_display_name,
                tr.enabled AS route_enabled,tr.version AS route_version
                FROM rooms r LEFT JOIN messages m USING(device_id,room_id)
                LEFT JOIN delivery_progress p USING(device_id,room_id)
                LEFT JOIN analysis_jobs j USING(device_id,room_id)
                LEFT JOIN telegram_routes tr USING(device_id,room_id)
                WHERE r.device_id=%s GROUP BY r.device_id,r.room_id,p.observed_through,
                tr.chat_id,tr.message_thread_id,tr.display_name,tr.enabled,tr.version
                ORDER BY r.display_name,r.room_id""", (device,)).fetchall()
        return {**total, "rooms": rooms}

    def rooms(self, device):
        return self.status(device)["rooms"]

    def update_room(self, device, room, display_name):
        if not display_name or len(display_name) > 120:
            raise ValueError("Invalid room display name")
        with self.connect() as db:
            row = db.execute("""UPDATE rooms SET display_name=%s,updated_at=clock_timestamp()
                WHERE device_id=%s AND room_id=%s AND allowed RETURNING room_id,display_name,allowed,updated_at""",
                (display_name, device, room)).fetchone()
        return row

    def routes(self, device):
        with self.connect() as db:
            return db.execute("""SELECT tr.room_id,tr.chat_id,tr.message_thread_id,tr.display_name,tr.enabled,tr.version,tr.updated_at
                FROM telegram_routes tr JOIN rooms r USING(device_id,room_id)
                WHERE tr.device_id=%s AND r.allowed ORDER BY tr.display_name,tr.room_id""", (device,)).fetchall()

    def update_route(self, device, room, *, chat_id, message_thread_id, display_name, enabled, expected_version):
        if (not re.fullmatch(r"-?[0-9]{1,20}", str(chat_id or ""))
                or message_thread_id is not None and (type(message_thread_id) is not int or message_thread_id <= 0)
                or len(display_name) > 120 or type(expected_version) is not int or expected_version < 0):
            raise ValueError("Invalid Telegram route")
        with self.connect() as db:
            if not db.execute("SELECT device_id FROM devices WHERE device_id=%s AND active FOR UPDATE", (device,)).fetchone():
                raise PermissionError("Device revoked")
            allowed = db.execute("SELECT room_id,display_name FROM rooms WHERE device_id=%s AND room_id=%s AND allowed FOR UPDATE",
                                 (device, room)).fetchone()
            if not allowed:
                return None
            display_name = display_name or allowed["display_name"]
            current = db.execute("SELECT * FROM telegram_routes WHERE device_id=%s AND room_id=%s FOR UPDATE",
                                 (device, room)).fetchone()
            version = current["version"] if current else 0
            if version != expected_version:
                raise RouteVersionConflict()
            duplicate = db.execute("""SELECT room_id FROM telegram_routes WHERE device_id=%s AND chat_id=%s
                AND COALESCE(message_thread_id,0)=COALESCE(%s,0) AND enabled AND room_id<>%s""",
                (device, chat_id, message_thread_id, room)).fetchone()
            if enabled and duplicate:
                raise RouteDestinationConflict()
            try:
                row = db.execute("""INSERT INTO telegram_routes(device_id,room_id,chat_id,message_thread_id,display_name,enabled,version)
                    VALUES(%s,%s,%s,%s,%s,%s,1)
                    ON CONFLICT(device_id,room_id) DO UPDATE SET chat_id=excluded.chat_id,
                    message_thread_id=excluded.message_thread_id,display_name=excluded.display_name,
                    enabled=excluded.enabled,version=telegram_routes.version+1,updated_at=clock_timestamp()
                    RETURNING room_id,chat_id,message_thread_id,display_name,enabled,version,updated_at""",
                    (device, room, chat_id, message_thread_id, display_name, enabled)).fetchone()
            except UniqueViolation as exc:
                raise RouteDestinationConflict() from exc
            from .delivery_store import DeliveryStore
            pending = db.execute("""SELECT delivery_id FROM delivery_outbox WHERE device_id=%s AND room_id=%s
                AND status IN ('pending','retry_wait') FOR UPDATE""", (device, room)).fetchall()
            for item in pending:
                DeliveryStore._cancel(db, item["delivery_id"], "route_changed")
        return row

    def prune(self):
        with self.connect() as db:
            messages = db.execute("DELETE FROM messages WHERE observed_at < %s", (int(time.time()*1000)-7*86400000,)).rowcount
            receipts = db.execute("DELETE FROM receipts WHERE received_at < now()-interval '30 days'").rowcount
        # Commit raw-data cleanup before acquiring job locks to avoid lock inversion
        # with completion, which checks live sources under its job lease.
        with self.connect() as db:
            summaries = db.execute("DELETE FROM analysis_summaries WHERE created_at < now()-interval '90 days'").rowcount
            jobs = db.execute("DELETE FROM analysis_jobs WHERE created_at < now()-interval '90 days' AND (status<>'running' OR lease_until<clock_timestamp())").rowcount
            usage = db.execute("DELETE FROM analysis_usage WHERE created_at < now()-interval '90 days'").rowcount
        # Commit summary/item cleanup before outbox locks: sends lock outbox then
        # sources, so acquiring these locks in the opposite order could deadlock.
        with self.connect() as db:
            deliveries = db.execute("DELETE FROM delivery_outbox WHERE created_at < now()-interval '90 days' AND (status<>'sending' OR lease_until<clock_timestamp())").rowcount
            attempts = db.execute("DELETE FROM delivery_attempts WHERE created_at < now()-interval '90 days'").rowcount
            db.execute("DELETE FROM delivery_source_receipts WHERE created_at < now()-interval '90 days'")
        return {"expired_messages":messages,"expired_receipts":receipts,
                "expired_summaries":summaries,"expired_jobs":jobs,"expired_usage":usage,
                "expired_deliveries":deliveries,"expired_delivery_attempts":attempts}

    def delete_room(self, device, room):
        # Revoke first in the same transaction; blocked room cannot be repopulated by queued retries.
        with self.connect() as db:
            from .delivery_store import DeliveryStore
            db.execute("SELECT device_id FROM devices WHERE device_id=%s FOR UPDATE", (device,))
            DeliveryStore.cancel_room(db,device,room)
            db.execute("UPDATE rooms SET allowed=false WHERE device_id=%s AND room_id=%s", (device,room))
            db.execute("DELETE FROM telegram_routes WHERE device_id=%s AND room_id=%s", (device,room))
            db.execute("DELETE FROM delivery_progress WHERE device_id=%s AND room_id=%s",(device,room))
            db.execute("DELETE FROM delivery_source_receipts WHERE device_id=%s AND room_id=%s",(device,room))
            db.execute("DELETE FROM analysis_jobs WHERE device_id=%s AND room_id=%s", (device,room))
            count = db.execute("DELETE FROM receipts WHERE device_id=%s AND room_id=%s", (device,room)).rowcount
        return count
