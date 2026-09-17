"""PostgreSQL leases, immutable targets and reservations shared across rooms."""
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from .analysis_models import (
    PROMPT_VERSION, AnalysisInput, AnalysisOutput, CapturedMessage, ChargeLimit,
    InterestProfile, Usage,
)
from .topics import excluded


class VersionConflict(Exception):
    pass


@dataclass(frozen=True)
class Claim:
    job_id: UUID
    owner: UUID
    device: UUID
    room: UUID
    profile_version: int
    profile: InterestProfile


class AnalysisStore:
    def __init__(self, store, lease_seconds=180):
        self.store = store
        self.lease_seconds = lease_seconds

    @staticmethod
    def _now(db):
        return db.execute("SELECT clock_timestamp() AS instant").fetchone()["instant"]

    @staticmethod
    def _profile(db, device):
        row = db.execute("SELECT version,config FROM interest_profiles WHERE device_id=%s ORDER BY version DESC LIMIT 1", (device,)).fetchone()
        return (row["version"], InterestProfile.model_validate(row["config"])) if row else (0, InterestProfile())

    @staticmethod
    def _active(db, device, exclusive=False):
        lock = "FOR UPDATE" if exclusive else "FOR SHARE"
        return db.execute("SELECT device_id FROM devices WHERE device_id=%s AND active=true " + lock, (device,)).fetchone()

    def profile(self, device):
        with self.store.connect() as db:
            version, profile = self._profile(db, device)
        return {"version": version, "profile": profile.model_dump()}

    def update_profile(self, device, update):
        with self.store.connect() as db:
            if not self._active(db, device, exclusive=True):
                raise PermissionError("Device revoked")
            version, _ = self._profile(db, device)
            if version != update.expected_version:
                raise VersionConflict()
            db.execute("INSERT INTO interest_profiles(device_id,version,config) VALUES(%s,%s,%s)",
                       (device, version + 1, Jsonb(update.profile.model_dump())))
            db.execute("UPDATE analysis_jobs SET status='cancelled',owner_token=NULL,lease_until=NULL,last_error='profile_changed' WHERE device_id=%s AND status NOT IN ('completed','cancelled')", (device,))
            db.execute("DELETE FROM analysis_items i USING analysis_jobs j WHERE i.job_id=j.job_id AND j.device_id=%s AND j.status='cancelled'", (device,))
        return {"version": version + 1, "profile": update.profile.model_dump()}

    def rooms(self):
        with self.store.connect() as db:
            return db.execute("""SELECT r.device_id,r.room_id FROM rooms r JOIN devices d USING(device_id)
                JOIN (SELECT DISTINCT ON(device_id) device_id,config FROM interest_profiles ORDER BY device_id,version DESC) p USING(device_id)
                WHERE d.active AND r.allowed AND (p.config->>'enabled')::boolean
                ORDER BY r.device_id,r.room_id""").fetchall()

    def claim(self, device, room, force=False):
        with self.store.connect() as db:
            if not self._active(db, device):
                return None
            allowed = db.execute("SELECT room_id FROM rooms WHERE device_id=%s AND room_id=%s AND allowed FOR UPDATE SKIP LOCKED", (device, room)).fetchone()
            if not allowed:
                return None
            version, profile = self._profile(db, device)
            if not profile.enabled:
                return None
            now = self._now(db)
            job = db.execute("SELECT * FROM analysis_jobs WHERE device_id=%s AND room_id=%s AND status IN ('running','retry_wait','paused') FOR UPDATE", (device, room)).fetchone()
            if job:
                if job["status"] == "running" and job["lease_until"] > now:
                    return None
                if job["status"] == "retry_wait" and job["not_before"] > now:
                    return None
                if job["attempts"] >= profile.max_attempts:
                    db.execute("UPDATE analysis_jobs SET status='failed',owner_token=NULL,lease_until=NULL,last_error='attempt_limit' WHERE job_id=%s", (job["job_id"],))
                    return None
                job_id = job["job_id"]
            else:
                pending = db.execute("""SELECT count(*) AS n,min(m.received_at) AS first FROM messages m
                    WHERE m.device_id=%s AND m.room_id=%s AND NOT EXISTS
                    (SELECT 1 FROM analysis_items i WHERE i.device_id=m.device_id AND i.event_id=m.event_id)""", (device, room)).fetchone()
                if pending["n"] == 0:
                    return None
                last = db.execute("SELECT completed_at,trigger_cutoff FROM analysis_jobs WHERE device_id=%s AND room_id=%s AND status='completed' ORDER BY completed_at DESC LIMIT 1", (device, room)).fetchone()
                draining = bool(last and pending["first"] <= last["trigger_cutoff"])
                baseline = min(last["completed_at"], pending["first"]) if last else pending["first"]
                due = draining or pending["n"] >= profile.batch_min_messages or now - baseline >= timedelta(seconds=profile.max_wait_seconds)
                if not force and not due:
                    return None
                # Bound each output batch; the trigger still uses the full unfiltered count.
                size = min(profile.batch_max_messages, max(1, profile.max_output_tokens // 512))
                rows = db.execute("""SELECT m.event_id,length(m.text) AS chars FROM messages m WHERE m.device_id=%s AND m.room_id=%s
                    AND NOT EXISTS(SELECT 1 FROM analysis_items i WHERE i.device_id=m.device_id AND i.event_id=m.event_id)
                    ORDER BY m.received_at,m.observed_at,m.event_id LIMIT %s""", (device, room, size)).fetchall()
                targets, chars = [], 0
                for row in rows:
                    if targets and chars + row["chars"] > profile.max_input_chars // 2:
                        break
                    targets.append(row["event_id"])
                    chars += row["chars"]
                job_id = uuid4()
                cutoff = last["trigger_cutoff"] if draining else now
                db.execute("INSERT INTO analysis_jobs(job_id,device_id,room_id,profile_version,prompt_version,status,trigger_cutoff) VALUES(%s,%s,%s,%s,%s,'running',%s)", (job_id, device, room, version, PROMPT_VERSION, cutoff))
                for event in targets:
                    db.execute("INSERT INTO analysis_items(job_id,device_id,event_id) VALUES(%s,%s,%s)", (job_id, device, event))
            owner = uuid4()
            db.execute("UPDATE analysis_jobs SET status='running',owner_token=%s,lease_until=%s,last_error=NULL WHERE job_id=%s", (owner, now + timedelta(seconds=self.lease_seconds), job_id))
            return Claim(job_id, owner, device, room, version, profile)

    def messages(self, claim):
        with self.store.connect() as db:
            rows = db.execute("""SELECT m.* FROM messages m JOIN analysis_items i USING(device_id,event_id)
                WHERE i.job_id=%s ORDER BY m.received_at,m.observed_at,m.event_id""", (claim.job_id,)).fetchall()
            count = db.execute("SELECT count(*) AS n FROM analysis_items WHERE job_id=%s", (claim.job_id,)).fetchone()["n"]
            context = []
            if rows:
                first = rows[0]
                context = db.execute("""SELECT m.* FROM messages m JOIN analysis_items i USING(device_id,event_id)
                    JOIN analysis_jobs j USING(job_id) WHERE m.device_id=%s AND m.room_id=%s AND j.status='completed'
                    AND (m.received_at,m.observed_at,m.event_id)<(%s,%s,%s)
                    ORDER BY m.received_at DESC,m.observed_at DESC,m.event_id DESC LIMIT 3""",
                    (claim.device,claim.room,first["received_at"],first["observed_at"],first["event_id"])).fetchall()
        if not count or len(rows) != count:
            return None
        return [CapturedMessage(str(r["event_id"]), r["text"], r["source_time"], r["observed_at"], tuple(r["urls"]), r["quality"]) for r in list(reversed(context))+rows]

    def targets(self, claim):
        with self.store.connect() as db:
            return {str(r["event_id"]) for r in db.execute("SELECT event_id FROM analysis_items WHERE job_id=%s", (claim.job_id,)).fetchall()}

    @staticmethod
    def _owned(db, claim):
        return db.execute("SELECT * FROM analysis_jobs WHERE job_id=%s AND owner_token=%s AND status='running' AND lease_until>clock_timestamp() FOR UPDATE", (claim.job_id, claim.owner)).fetchone()

    @staticmethod
    def _usage(db, device, day):
        return db.execute("""SELECT
            coalesce(sum(coalesce(tokens_used,tokens_reserved)),0) AS tokens_committed,
            coalesce(sum(coalesce(cost_used,cost_reserved)),0) AS cost_committed_microusd,
            coalesce(sum(tokens_reserved) FILTER(WHERE tokens_used IS NULL),0) AS tokens_reserved,
            coalesce(sum(cost_reserved) FILTER(WHERE cost_used IS NULL),0) AS cost_reserved_microusd,
            coalesce(sum(tokens_used),0) AS tokens_reported,
            coalesce(sum(cost_used),0) AS cost_reported_microusd,
            count(*) FILTER(WHERE measured=true) AS measured_calls,
            count(*) FILTER(WHERE measured=false) AS simulated_calls,
            count(*) FILTER(WHERE tokens_used IS NULL) AS unresolved_calls
            FROM analysis_usage WHERE device_id=%s AND budget_day=%s""", (device, day)).fetchone()

    def reserve(self, claim, limit: ChargeLimit):
        with self.store.connect() as db:
            if not self._active(db, claim.device, exclusive=True):
                return None
            allowed = db.execute("SELECT room_id FROM rooms WHERE device_id=%s AND room_id=%s AND allowed FOR SHARE", (claim.device, claim.room)).fetchone()
            if not allowed or not self._owned(db, claim):
                return None
            day = self._now(db).astimezone(ZoneInfo(claim.profile.timezone)).date()
            usage = self._usage(db, claim.device, day)
            if usage["tokens_committed"] + limit.tokens > claim.profile.daily_token_limit or usage["cost_committed_microusd"] + limit.cost_microusd > claim.profile.daily_cost_limit_microusd:
                db.execute("UPDATE analysis_jobs SET status='paused',last_error='daily_budget',owner_token=NULL,lease_until=NULL WHERE job_id=%s", (claim.job_id,))
                return None
            call_id = uuid4()
            db.execute("INSERT INTO analysis_usage(call_id,job_id,device_id,budget_day,tokens_reserved,cost_reserved) VALUES(%s,%s,%s,%s,%s,%s)", (call_id, claim.job_id, claim.device, day, limit.tokens, limit.cost_microusd))
            db.execute("UPDATE analysis_jobs SET attempts=attempts+1 WHERE job_id=%s", (claim.job_id,))
        return call_id

    def settle(self, call_id, usage: Usage):
        with self.store.connect() as db:
            row = db.execute("SELECT device_id FROM analysis_usage WHERE call_id=%s", (call_id,)).fetchone()
            if not row:
                return False
            # Same lock as reserve; uncertain reservations survive job cancellation/deletion.
            db.execute("SELECT device_id FROM devices WHERE device_id=%s FOR UPDATE", (row["device_id"],))
            reservation = db.execute("SELECT * FROM analysis_usage WHERE call_id=%s FOR UPDATE", (call_id,)).fetchone()
            if not reservation or reservation["tokens_used"] is not None:
                return False
            db.execute("UPDATE analysis_usage SET tokens_used=%s,cost_used=%s,measured=%s WHERE call_id=%s", (usage.tokens, usage.cost_microusd, usage.measured, call_id))
            return usage.tokens <= reservation["tokens_reserved"] and usage.cost_microusd <= reservation["cost_reserved"]

    def fail(self, claim, code, permanent=False):
        safe_codes = {"provider_unavailable", "invalid_output", "invalid_usage", "input_too_large", "output_limit", "source_expired", "budget_overrun"}
        code = code if code in safe_codes else "provider_unavailable"
        with self.store.connect() as db:
            job = self._owned(db, claim)
            if not job:
                return
            final = permanent or job["attempts"] >= claim.profile.max_attempts
            delay = min(3600, 30 * 2 ** min(job["attempts"], 6))
            db.execute("UPDATE analysis_jobs SET status=%s,last_error=%s,owner_token=NULL,lease_until=NULL,not_before=%s WHERE job_id=%s", ("failed" if final else "retry_wait", code, self._now(db) + timedelta(seconds=delay), claim.job_id))

    def complete(self, claim, batch: AnalysisInput, output: AnalysisOutput, model):
        with self.store.connect() as db:
            if not self._active(db, claim.device):
                return False
            if not db.execute("SELECT room_id FROM rooms WHERE device_id=%s AND room_id=%s AND allowed FOR SHARE", (claim.device, claim.room)).fetchone():
                return False
            if not self._owned(db, claim):
                return False
            sources = db.execute("""SELECT m.event_id FROM messages m JOIN analysis_items i USING(device_id,event_id)
                WHERE i.job_id=%s FOR SHARE OF m""", (claim.job_id,)).fetchall()
            count = db.execute("SELECT count(*) AS n FROM analysis_items WHERE job_id=%s", (claim.job_id,)).fetchone()["n"]
            if len(sources) != count:
                db.execute("UPDATE analysis_jobs SET status='failed',last_error='source_expired',owner_token=NULL,lease_until=NULL WHERE job_id=%s", (claim.job_id,))
                return False
            cited_sources = {UUID(m.event_id) for topic in batch.topics for m in topic.messages}
            if cited_sources:
                live = db.execute("SELECT event_id FROM messages WHERE device_id=%s AND room_id=%s AND event_id=ANY(%s) FOR SHARE", (claim.device,claim.room,list(cited_sources))).fetchall()
                if len(live) != len(cited_sources):
                    db.execute("UPDATE analysis_jobs SET status='failed',last_error='source_expired',owner_token=NULL,lease_until=NULL WHERE job_id=%s", (claim.job_id,))
                    return False
            topics = {t.topic_id: t for t in batch.topics}
            for summary in output.topics:
                candidate = summary.relevance >= claim.profile.relevance_threshold and not excluded(topics[summary.topic_id], claim.profile.exclude_topics)
                payload = {**summary.model_dump(), "notice": "방에서 공유된 주장입니다. 외부 사실 검증을 수행하지 않았습니다."}
                db.execute("INSERT INTO analysis_summaries(summary_id,job_id,topic_id,payload,is_candidate,provider_model) VALUES(%s,%s,%s,%s,%s,%s)", (uuid4(), claim.job_id, summary.topic_id, Jsonb(payload), candidate, model))
            db.execute("UPDATE analysis_jobs SET status='completed',completed_at=now(),owner_token=NULL,lease_until=NULL WHERE job_id=%s", (claim.job_id,))
        return True

    def status(self, device):
        with self.store.connect() as db:
            _, profile = self._profile(db, device)
            day = self._now(db).astimezone(ZoneInfo(profile.timezone)).date()
            states = db.execute("SELECT status,count(*) AS count FROM analysis_jobs WHERE device_id=%s GROUP BY status", (device,)).fetchall()
            usage = self._usage(db, device, day)
        return {"jobs": {r["status"]: r["count"] for r in states}, "budget_day": str(day),
                "timezone": profile.timezone, "enabled": profile.enabled, "usage": usage,
                "limits": {"tokens": profile.daily_token_limit, "cost_microusd": profile.daily_cost_limit_microusd}}

    def jobs(self, device, limit=20, offset=0):
        with self.store.connect() as db:
            return db.execute("""SELECT j.job_id,j.room_id,j.profile_version,j.prompt_version,j.status,j.attempts,j.last_error,
                j.created_at,j.completed_at,(SELECT count(*) FROM analysis_items i WHERE i.job_id=j.job_id) AS target_count
                FROM analysis_jobs j WHERE device_id=%s ORDER BY created_at DESC,job_id LIMIT %s OFFSET %s""", (device, limit, offset)).fetchall()

    def summaries(self, device, room, limit=20, offset=0, candidates_only=False):
        with self.store.connect() as db:
            return db.execute("""SELECT s.summary_id,s.payload,s.is_candidate,s.provider_model,s.created_at,j.profile_version,j.prompt_version
                FROM analysis_summaries s JOIN analysis_jobs j USING(job_id)
                WHERE j.device_id=%s AND j.room_id=%s AND (NOT %s OR s.is_candidate)
                ORDER BY s.created_at DESC,s.summary_id LIMIT %s OFFSET %s""", (device, room, candidates_only, limit, offset)).fetchall()

    def evidence(self, device, summary_id):
        with self.store.connect() as db:
            summary = db.execute("SELECT s.payload FROM analysis_summaries s JOIN analysis_jobs j USING(job_id) WHERE s.summary_id=%s AND j.device_id=%s", (summary_id, device)).fetchone()
            if not summary:
                return None
            ids = list(dict.fromkeys(e for p in summary["payload"]["points"] for e in p["evidence_ids"]))
            rows = db.execute("SELECT event_id,text,source_time,observed_at,urls,quality FROM messages WHERE device_id=%s AND event_id=ANY(%s)", (device, [UUID(e) for e in ids])).fetchall()
        found = {str(r["event_id"]): r for r in rows}
        return {"summary_id": str(summary_id), "evidence": [
            {**found[e], "availability": "available"} if e in found else {"event_id": e, "availability": "raw_expired"}
            for e in ids
        ]}
