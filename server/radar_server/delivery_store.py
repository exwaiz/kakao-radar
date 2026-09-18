"""Transactional M4 outbox. Network I/O always happens outside DB transactions."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from copy import deepcopy
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from .analysis_store import AnalysisStore, VersionConflict
from .delivery_models import (DeliveryPolicy, after_quiet, fingerprint, next_day,
                              next_slot, render_digest)


class DeliveryConflict(Exception):
    pass


@dataclass(frozen=True)
class SendClaim:
    delivery_id: UUID
    device: UUID
    owner: UUID
    attempt_id: UUID
    payload: dict


class DeliveryStore:
    def __init__(self, store, lease_seconds=90):
        self.store, self.lease_seconds = store, lease_seconds

    @staticmethod
    def _now(db):
        return db.execute("SELECT clock_timestamp() AS instant").fetchone()["instant"]

    @staticmethod
    def _device(db, device):
        if not db.execute("SELECT device_id FROM devices WHERE device_id=%s AND active FOR UPDATE", (device,)).fetchone():
            raise PermissionError("Device revoked")

    @classmethod
    def _settings(cls, db, device):
        row = db.execute("SELECT * FROM delivery_settings WHERE device_id=%s", (device,)).fetchone()
        if not row:
            return 0, DeliveryPolicy(), None
        policy = DeliveryPolicy.model_validate(row['config'])
        now = cls._now(db)
        if policy.test_mode_until and now >= datetime.fromisoformat(policy.test_mode_until):
            policy = DeliveryPolicy.model_validate({**policy.model_dump(),
                'daily_times':policy.resume_daily_times,'daily_notification_limit':policy.resume_daily_notification_limit,
                'max_topics_per_digest':policy.resume_max_topics_per_digest or policy.max_topics_per_digest,
                'test_mode_until':None,'resume_daily_times':None,'resume_daily_notification_limit':None,'resume_max_topics_per_digest':None})
            row['version'] += 1
            row['next_due_at'] = next_slot(policy,now) if policy.enabled else None
            db.execute('UPDATE delivery_settings SET version=%s,config=%s,next_due_at=%s,updated_at=clock_timestamp() WHERE device_id=%s',
                (row['version'],Jsonb(policy.model_dump()),row['next_due_at'],device))
            pending = db.execute("SELECT delivery_id FROM delivery_outbox WHERE device_id=%s AND status IN ('pending','retry_wait')",(device,)).fetchall()
            for entry in pending:
                cls._cancel(db,entry['delivery_id'],'test_period_ended')
        return row['version'],policy,row['next_due_at']

    def policy(self, device):
        with self.store.connect() as db:
            self._device(db, device)
            version, policy, due = self._settings(db, device)
        return {"version": version, "policy": policy.model_dump(), "next_due_at": due}

    @staticmethod
    def _cancel(db, delivery, reason):
        db.execute("""UPDATE delivery_outbox SET status='cancelled',payload='{}'::jsonb,
            last_error=%s,owner_token=NULL,lease_until=NULL,link_expires_at=clock_timestamp()
            WHERE delivery_id=%s""", (reason, delivery))
        db.execute("DELETE FROM delivery_items WHERE delivery_id=%s", (delivery,))

    def update_policy(self, device, update):
        with self.store.connect() as db:
            self._device(db, device)
            version, _, _ = self._settings(db, device)
            if version != update.expected_version:
                raise VersionConflict()
            now = self._now(db)
            due = next_slot(update.policy, now) if update.policy.enabled else None
            db.execute("""INSERT INTO delivery_settings(device_id,version,config,next_due_at) VALUES(%s,%s,%s,%s)
                ON CONFLICT(device_id) DO UPDATE SET version=excluded.version,config=excluded.config,
                next_due_at=excluded.next_due_at,updated_at=clock_timestamp()""",
                       (device, version + 1, Jsonb(update.policy.model_dump()), due))
            rows = db.execute("SELECT delivery_id FROM delivery_outbox WHERE device_id=%s AND status IN ('pending','retry_wait') FOR UPDATE", (device,)).fetchall()
            for row in rows:
                self._cancel(db, row["delivery_id"], "settings_changed")
        return {"version": version + 1, "policy": update.policy.model_dump(), "next_due_at": due}

    def devices(self):
        with self.store.connect() as db:
            rows = db.execute("""SELECT d.device_id FROM devices d JOIN delivery_settings s USING(device_id)
                WHERE d.active AND (s.config->>'enabled')::boolean ORDER BY d.device_id""").fetchall()
        return [row["device_id"] for row in rows]

    @staticmethod
    def _topics(db, device, policy, version, now, urgent=False):
        rows = db.execute("""SELECT s.summary_id,j.room_id,s.payload,s.created_at
            FROM analysis_summaries s JOIN analysis_jobs j USING(job_id)
            JOIN rooms r ON r.device_id=j.device_id AND r.room_id=j.room_id
            WHERE j.device_id=%s AND r.allowed AND j.status='completed' AND j.profile_version=%s
            AND s.is_candidate AND s.created_at >= %s
            AND (NOT %s OR ((s.payload->>'importance')::int >= %s AND s.created_at >= %s))
            AND NOT EXISTS(SELECT 1 FROM delivery_items i WHERE i.device_id=%s AND i.summary_id=s.summary_id)
            AND NOT EXISTS(SELECT 1 FROM summary_feedback f WHERE f.device_id=%s AND f.summary_id=s.summary_id AND f.rating='not_interested')
            ORDER BY (s.payload->>'importance')::int DESC,(s.payload->>'relevance')::int DESC,s.created_at DESC,s.summary_id LIMIT 1000""",
                          (device, version, now - timedelta(hours=policy.max_summary_age_hours), urgent,
                           policy.urgent_importance_threshold, now - timedelta(minutes=15), device, device)).fetchall()
        recent = db.execute("""SELECT i.fingerprint FROM delivery_items i JOIN delivery_outbox o USING(delivery_id)
            WHERE i.device_id=%s AND o.created_at >= %s AND o.status IN ('pending','sending','retry_wait','accepted','uncertain')""",
                            (device, now - timedelta(hours=policy.dedup_hours))).fetchall()
        seen, topics = {r["fingerprint"] for r in recent}, []
        for row in rows:
            signature = fingerprint(row["room_id"], row["payload"])
            if signature in seen:
                continue
            seen.add(signature)
            topics.append({"summary_id": str(row["summary_id"]), "room_id": str(row["room_id"]),
                           "payload": row["payload"], "fingerprint": signature})
            if len(topics) == policy.max_topics_per_digest:
                break
        return topics

    def preview(self, device):
        with self.store.connect() as db:
            self._device(db, device)
            _, policy, _ = self._settings(db, device)
            version, profile = AnalysisStore._profile(db, device)
            topics = self._topics(db, device, policy, version, self._now(db)) if profile.enabled else []
        return {"preview": True, **render_digest(topics)}

    def plan(self, device, *, manual=False):
        with self.store.connect() as db:
            self._device(db, device)
            version, policy, due = self._settings(db, device)
            profile_version, profile = AnalysisStore._profile(db, device)
            now = self._now(db)
            if not policy.enabled or not profile.enabled or due is None:
                return None
            scheduled = due <= now
            if not scheduled and not manual and not policy.urgent_enabled:
                return None
            if db.execute("SELECT 1 FROM delivery_outbox WHERE device_id=%s AND status IN ('pending','sending','retry_wait')", (device,)).fetchone():
                return None
            if not scheduled and not manual and db.execute("""SELECT 1 FROM delivery_outbox WHERE device_id=%s AND kind='urgent'
                AND created_at>=%s AND status IN ('pending','sending','retry_wait','accepted','uncertain')""",
                    (device, now - timedelta(seconds=policy.urgent_cooldown_seconds))).fetchone():
                return None
            topics = self._topics(db, device, policy, profile_version, now, urgent=not scheduled and not manual)
            # Downtime produces one catch-up digest, never one notification per missed slot.
            if scheduled:
                db.execute("UPDATE delivery_settings SET next_due_at=%s WHERE device_id=%s", (next_slot(policy, now), device))
            if not topics:
                return None
            delivery = uuid4()
            payload = render_digest(topics, delivery)
            db.execute("""INSERT INTO delivery_outbox(delivery_id,device_id,settings_version,profile_version,status,payload,slot_at,not_before,kind)
                VALUES(%s,%s,%s,%s,'pending',%s,%s,%s,%s)""",
                       (delivery, device, version, profile_version, Jsonb(payload), due if scheduled else now,
                        after_quiet(policy, now), 'manual' if manual else ('scheduled' if scheduled else 'urgent')))
            for topic in topics:
                db.execute("INSERT INTO delivery_items(delivery_id,device_id,summary_id,room_id,fingerprint) VALUES(%s,%s,%s,%s,%s)",
                           (delivery, device, UUID(topic["summary_id"]), UUID(topic["room_id"]), topic["fingerprint"]))
        return delivery

    def _recover(self, db, device, now):
        rows = db.execute("""UPDATE delivery_outbox SET status='uncertain',last_error='worker_interrupted',owner_token=NULL,lease_until=NULL
            WHERE device_id=%s AND status='sending' AND lease_until<=%s RETURNING delivery_id""", (device, now)).fetchall()
        for row in rows:
            db.execute("UPDATE delivery_attempts SET outcome='uncertain' WHERE delivery_id=%s AND outcome='started'", (row["delivery_id"],))

    def begin_send(self, device):
        with self.store.connect() as db:
            self._device(db, device)
            version, policy, _ = self._settings(db, device)
            now = self._now(db)
            self._recover(db, device, now)
            profile_version, profile = AnalysisStore._profile(db, device)
            stale = db.execute("""SELECT delivery_id FROM delivery_outbox WHERE device_id=%s
                AND status IN ('pending','retry_wait') AND (NOT %s OR NOT %s OR settings_version<>%s OR profile_version<>%s)
                FOR UPDATE""",(device,policy.enabled,profile.enabled,version,profile_version)).fetchall()
            for entry in stale:
                self._cancel(db,entry['delivery_id'],'configuration_changed')
            row = db.execute("""SELECT * FROM delivery_outbox WHERE device_id=%s AND status IN ('pending','retry_wait')
                AND not_before<=%s ORDER BY created_at,delivery_id LIMIT 1 FOR UPDATE""", (device, now)).fetchone()
            if not row:
                return None
            profile_version, profile = AnalysisStore._profile(db, device)
            if not policy.enabled or version != row["settings_version"] or not profile.enabled or profile_version != row["profile_version"]:
                self._cancel(db, row["delivery_id"], "configuration_changed")
                return None
            live = db.execute("""SELECT i.summary_id FROM delivery_items i JOIN analysis_summaries s USING(summary_id)
                JOIN rooms r ON r.device_id=i.device_id AND r.room_id=i.room_id
                WHERE i.delivery_id=%s AND r.allowed AND s.created_at>=%s
                AND NOT EXISTS(SELECT 1 FROM summary_feedback f WHERE f.device_id=i.device_id AND f.summary_id=i.summary_id AND f.rating='not_interested')
                FOR SHARE OF s,r""", (row["delivery_id"], now - timedelta(hours=policy.max_summary_age_hours))).fetchall()
            if len(live) != len(row["payload"].get("topics", [])) or not live:
                self._cancel(db, row["delivery_id"], "source_unavailable")
                return None
            allowed_at = after_quiet(policy, now)
            day = now.astimezone(ZoneInfo(policy.timezone)).date()
            usage = db.execute("SELECT count(*) AS n FROM delivery_attempts WHERE device_id=%s AND (created_at AT TIME ZONE %s)::date=%s", (device, policy.timezone, day)).fetchone()["n"]
            if usage >= policy.daily_notification_limit:
                allowed_at = max(allowed_at, next_day(policy, now))
            if allowed_at > now:
                db.execute("UPDATE delivery_outbox SET not_before=%s,last_error=%s WHERE delivery_id=%s",
                           (allowed_at, "daily_limit" if usage >= policy.daily_notification_limit else "quiet_hours", row["delivery_id"]))
                return None
            if row["attempts"] >= policy.max_attempts:
                db.execute("UPDATE delivery_outbox SET status='failed',last_error='attempt_limit' WHERE delivery_id=%s", (row["delivery_id"],))
                return None
            owner, attempt = uuid4(), uuid4()
            db.execute("""UPDATE delivery_outbox SET status='sending',attempts=attempts+1,owner_token=%s,
                lease_until=%s,last_error=NULL WHERE delivery_id=%s""",
                       (owner, now + timedelta(seconds=self.lease_seconds), row["delivery_id"]))
            db.execute("INSERT INTO delivery_attempts(attempt_id,delivery_id,device_id,quota_day,outcome) VALUES(%s,%s,%s,%s,'started')",
                       (attempt, row["delivery_id"], device, day))
            outgoing = deepcopy(row['payload'])
            if policy.include_source_quotes:
                from .source_quotes import attach_quotes
                attach_quotes(db,device,outgoing)
        return SendClaim(row["delivery_id"], device, owner, attempt, outgoing)

    def finish(self, claim, outcome, code=None, message_id=None, retry_after=0):
        if outcome not in ("accepted", "retry", "failed", "uncertain"):
            raise ValueError("Invalid delivery outcome")
        codes = {None, "connection_failed", "rate_limited", "channel_auth", "channel_rejected",
                 "channel_unavailable", "response_lost", "invalid_response", "worker_interrupted"}
        if code not in codes:
            code = "channel_unavailable"
        with self.store.connect() as db:
            # Serialize with settings, deletion and quota reservation, including revocation.
            db.execute("SELECT device_id FROM devices WHERE device_id=%s FOR UPDATE", (claim.device,))
            now = self._now(db)
            row = db.execute("SELECT * FROM delivery_outbox WHERE delivery_id=%s FOR UPDATE", (claim.delivery_id,)).fetchone()
            if not row or row["status"] != "sending" or row["owner_token"] != claim.owner or row["lease_until"] <= now:
                return False
            _, policy, _ = self._settings(db, claim.device)
            state = "retry_wait" if outcome == "retry" and row["attempts"] < policy.max_attempts else "failed" if outcome == "retry" else outcome
            delay = min(86400, max(30 * 2 ** (row["attempts"] - 1), retry_after))
            db.execute("""UPDATE delivery_outbox SET status=%s,last_error=%s,provider_message_id=%s,
                accepted_at=CASE WHEN %s='accepted' THEN %s ELSE accepted_at END,not_before=%s,
                owner_token=NULL,lease_until=NULL WHERE delivery_id=%s""",
                       (state, code, message_id, state, now, now + timedelta(seconds=delay), claim.delivery_id))
            db.execute("UPDATE delivery_attempts SET outcome=%s WHERE attempt_id=%s",
                       ("accepted" if outcome == "accepted" else "uncertain" if outcome == "uncertain" else "rejected", claim.attempt_id))
        return True

    def resolve(self, device, delivery, resolution):
        with self.store.connect() as db:
            self._device(db, device)
            now = self._now(db)
            self._recover(db, device, now)
            row = db.execute("SELECT * FROM delivery_outbox WHERE delivery_id=%s AND device_id=%s FOR UPDATE", (delivery, device)).fetchone()
            if not row:
                return None
            if row["status"] not in ("uncertain", "failed"):
                raise DeliveryConflict()
            if resolution.action == "mark_accepted":
                if row["status"] != "uncertain":
                    raise DeliveryConflict()
                db.execute("UPDATE delivery_outbox SET status='accepted',accepted_at=%s,last_error='manually_confirmed' WHERE delivery_id=%s", (now, delivery))
            else:
                version, policy, _ = self._settings(db, device)
                profile_version, profile = AnalysisStore._profile(db, device)
                if not policy.enabled or not profile.enabled or version != row["settings_version"] or profile_version != row["profile_version"] or row["attempts"] >= policy.max_attempts:
                    raise DeliveryConflict()
                if db.execute("SELECT 1 FROM delivery_outbox WHERE device_id=%s AND status IN ('pending','sending','retry_wait')", (device,)).fetchone():
                    raise DeliveryConflict()
                db.execute("UPDATE delivery_outbox SET status='retry_wait',not_before=%s,last_error='manual_retry' WHERE delivery_id=%s", (after_quiet(policy, now), delivery))
        return {"delivery_id": str(delivery), "status": "accepted" if resolution.action == "mark_accepted" else "retry_wait"}

    def history(self, device, limit=20, offset=0):
        with self.store.connect() as db:
            return db.execute("""SELECT delivery_id,status,attempts,last_error,slot_at,not_before,created_at,accepted_at,
                provider_message_id,jsonb_array_length(COALESCE(payload->'topics','[]'::jsonb)) AS topic_count
                FROM delivery_outbox WHERE device_id=%s ORDER BY created_at DESC,delivery_id LIMIT %s OFFSET %s""", (device, limit, offset)).fetchall()

    def status(self, device):
        with self.store.connect() as db:
            self._device(db, device)
            version, policy, due = self._settings(db, device)
            now = self._now(db)
            self._recover(db, device, now)
            day = now.astimezone(ZoneInfo(policy.timezone)).date()
            used = db.execute("SELECT count(*) AS n FROM delivery_attempts WHERE device_id=%s AND (created_at AT TIME ZONE %s)::date=%s", (device, policy.timezone, day)).fetchone()["n"]
            rows = db.execute("SELECT status,count(*) AS n FROM delivery_outbox WHERE device_id=%s GROUP BY status", (device,)).fetchall()
        return {"enabled": policy.enabled, "version": version, "timezone": policy.timezone, "next_due_at": due,
                "quota_day": str(day), "attempts_today": used, "daily_notification_limit": policy.daily_notification_limit,
                "deliveries": {row["status"]: row["n"] for row in rows}}

    def feedback(self, device, summary, rating, delivery=None):
        with self.store.connect() as db:
            self._device(db, device)
            row = db.execute("""SELECT s.summary_id FROM analysis_summaries s JOIN analysis_jobs j USING(job_id)
                JOIN rooms r ON r.device_id=j.device_id AND r.room_id=j.room_id
                WHERE s.summary_id=%s AND j.device_id=%s AND r.allowed FOR SHARE OF s,r""", (summary, device)).fetchone()
            if not row or (delivery is not None and not db.execute("""SELECT 1 FROM delivery_items i JOIN delivery_outbox o USING(delivery_id)
                WHERE i.delivery_id=%s AND i.summary_id=%s AND o.device_id=%s
                AND o.status IN ('sending','accepted','uncertain') AND o.link_expires_at>clock_timestamp()""", (delivery, summary, device)).fetchone()):
                return None
            db.execute("""INSERT INTO summary_feedback(device_id,summary_id,rating) VALUES(%s,%s,%s)
                ON CONFLICT(device_id,summary_id) DO UPDATE SET rating=excluded.rating,updated_at=clock_timestamp()""", (device, summary, rating))
        return {"summary_id": str(summary), "rating": rating}

    def feedback_list(self, device, limit=20, offset=0):
        with self.store.connect() as db:
            return db.execute("SELECT summary_id,rating,updated_at FROM summary_feedback WHERE device_id=%s ORDER BY updated_at DESC,summary_id LIMIT %s OFFSET %s", (device, limit, offset)).fetchall()

    @staticmethod
    def cancel_room(db, device, room):
        rows = db.execute("""SELECT o.delivery_id FROM delivery_outbox o WHERE o.device_id=%s
            AND EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(o.payload->'topics','[]'::jsonb)) t
                       WHERE t->>'room_id'=%s) FOR UPDATE""", (device, str(room))).fetchall()
        for row in rows:
            db.execute("UPDATE delivery_attempts SET outcome='uncertain' WHERE delivery_id=%s AND outcome='started'", (row["delivery_id"],))
            DeliveryStore._cancel(db, row["delivery_id"], "room_deleted")

    def digest(self, delivery):
        """Called only after verifying the scoped link signature; check live ownership too."""
        with self.store.connect() as db:
            row = db.execute("SELECT device_id FROM delivery_outbox WHERE delivery_id=%s", (delivery,)).fetchone()
            if not row:
                return None
            try:
                self._device(db, row["device_id"])
            except PermissionError:
                return None
            row = db.execute("""SELECT * FROM delivery_outbox WHERE delivery_id=%s AND link_expires_at>clock_timestamp()
                AND status IN ('sending','accepted','uncertain')""", (delivery,)).fetchone()
            if not row:
                return None
            live = db.execute("""SELECT i.summary_id FROM delivery_items i JOIN analysis_summaries s USING(summary_id)
                JOIN rooms r ON r.device_id=i.device_id AND r.room_id=i.room_id WHERE i.delivery_id=%s AND r.allowed FOR SHARE OF s,r""", (delivery,)).fetchall()
            if len(live) != len(row["payload"].get("topics", [])) or not live:
                return None
            topics = []
            for topic in row["payload"]["topics"]:
                ids = list(dict.fromkeys(e for p in topic["payload"]["points"] for e in p["evidence_ids"]))
                sources = db.execute("""SELECT event_id,text,source_time,observed_at,urls,quality FROM messages
                    WHERE device_id=%s AND room_id=%s AND event_id=ANY(%s) FOR SHARE""", (row["device_id"], UUID(topic["room_id"]), [UUID(e) for e in ids])).fetchall()
                found = {str(s["event_id"]): s for s in sources}
                feedback = db.execute("SELECT rating FROM summary_feedback WHERE device_id=%s AND summary_id=%s", (row["device_id"], UUID(topic["summary_id"]))).fetchone()
                topics.append({"summary_id": topic["summary_id"], "payload": topic["payload"],
                               "rating": feedback["rating"] if feedback else None,
                               "evidence": [{**found[e], "availability": "available"} if e in found else {"event_id": e, "availability": "raw_expired"} for e in ids]})
        return {"delivery_id": str(delivery), "device_id": row["device_id"], "status": row["status"],
                "title": row["payload"]["title"], "topics": topics}
