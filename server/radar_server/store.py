import hashlib
import json
import secrets
import time
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


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

    def provision(self, device: UUID, room: UUID, token: str):
        if len(token) < 32:
            raise ValueError("Token must contain at least 32 characters")
        with self.connect() as db:
            db.execute("INSERT INTO devices(device_id,token_hash) VALUES(%s,%s) ON CONFLICT(device_id) DO UPDATE SET token_hash=excluded.token_hash, active=true",
                       (device, hashlib.sha256(token.encode()).hexdigest()))
            db.execute("INSERT INTO rooms(device_id,room_id) VALUES(%s,%s) ON CONFLICT(device_id,room_id) DO UPDATE SET allowed=true", (device, room))

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
            return db.execute("SELECT count(*) AS stored_messages, max(received_at) AS last_received_at FROM messages WHERE device_id=%s", (device,)).fetchone()

    def prune(self):
        with self.connect() as db:
            messages = db.execute("DELETE FROM messages WHERE observed_at < %s", (int(time.time()*1000)-7*86400000,)).rowcount
            receipts = db.execute("DELETE FROM receipts WHERE received_at < now()-interval '30 days'").rowcount
        return {"expired_messages":messages,"expired_receipts":receipts}

    def delete_room(self, device, room):
        # Revoke first in the same transaction; blocked room cannot be repopulated by queued retries.
        with self.connect() as db:
            db.execute("UPDATE rooms SET allowed=false WHERE device_id=%s AND room_id=%s", (device,room))
            count = db.execute("DELETE FROM receipts WHERE device_id=%s AND room_id=%s", (device,room)).rowcount
        return count
