CREATE TABLE IF NOT EXISTS schema_versions (version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS devices (
 device_id UUID PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE,
 active BOOLEAN NOT NULL DEFAULT TRUE, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS rooms (
 device_id UUID REFERENCES devices(device_id), room_id UUID NOT NULL,
 allowed BOOLEAN NOT NULL DEFAULT TRUE, PRIMARY KEY(device_id, room_id)
);
-- Receipts contain no original text and survive message expiry for bounded retry protection.
CREATE TABLE IF NOT EXISTS receipts (
 device_id UUID REFERENCES devices(device_id), event_id UUID NOT NULL, room_id UUID NOT NULL,
 payload_hash TEXT NOT NULL, received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(device_id, event_id)
);
CREATE TABLE IF NOT EXISTS messages (
 device_id UUID NOT NULL, event_id UUID NOT NULL, room_id UUID NOT NULL,
 sender_alias TEXT NOT NULL, text TEXT NOT NULL, source_time BIGINT,
 observed_at BIGINT NOT NULL, urls JSONB NOT NULL, quality TEXT NOT NULL,
 parser_version INTEGER NOT NULL, received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 PRIMARY KEY(device_id, event_id),
 FOREIGN KEY(device_id, event_id) REFERENCES receipts(device_id, event_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS messages_room_time ON messages(device_id,room_id,observed_at);
INSERT INTO schema_versions(version) VALUES(1) ON CONFLICT DO NOTHING;

-- M3 is additive: existing M2 events and receipts are not rewritten.
CREATE TABLE IF NOT EXISTS interest_profiles (
 device_id UUID REFERENCES devices(device_id) ON DELETE CASCADE,
 version INTEGER NOT NULL, config JSONB NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), PRIMARY KEY(device_id,version)
);
CREATE TABLE IF NOT EXISTS analysis_jobs (
 job_id UUID PRIMARY KEY, device_id UUID REFERENCES devices(device_id) ON DELETE CASCADE,
 room_id UUID NOT NULL, profile_version INTEGER NOT NULL, prompt_version TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('running','retry_wait','paused','completed','failed','cancelled')),
 attempts INTEGER NOT NULL DEFAULT 0, owner_token UUID, lease_until TIMESTAMPTZ,
 not_before TIMESTAMPTZ NOT NULL DEFAULT now(), last_error TEXT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(), completed_at TIMESTAMPTZ,
 trigger_cutoff TIMESTAMPTZ NOT NULL DEFAULT now(),
 FOREIGN KEY(device_id,room_id) REFERENCES rooms(device_id,room_id) ON DELETE CASCADE,
 FOREIGN KEY(device_id,profile_version) REFERENCES interest_profiles(device_id,version) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS analysis_one_active_room
 ON analysis_jobs(device_id,room_id) WHERE status IN ('running','retry_wait','paused');
CREATE TABLE IF NOT EXISTS analysis_items (
 job_id UUID REFERENCES analysis_jobs(job_id) ON DELETE CASCADE,
 device_id UUID NOT NULL, event_id UUID NOT NULL,
 PRIMARY KEY(job_id,event_id), UNIQUE(device_id,event_id)
);
CREATE TABLE IF NOT EXISTS analysis_summaries (
 summary_id UUID PRIMARY KEY, job_id UUID REFERENCES analysis_jobs(job_id) ON DELETE CASCADE,
 topic_id TEXT NOT NULL, payload JSONB NOT NULL, is_candidate BOOLEAN NOT NULL,
 provider_model TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 UNIQUE(job_id,topic_id)
);
CREATE TABLE IF NOT EXISTS analysis_usage (
 call_id UUID PRIMARY KEY, job_id UUID REFERENCES analysis_jobs(job_id) ON DELETE SET NULL,
 device_id UUID REFERENCES devices(device_id) ON DELETE CASCADE, budget_day DATE NOT NULL,
 tokens_reserved BIGINT NOT NULL CHECK(tokens_reserved >= 0),
 cost_reserved BIGINT NOT NULL CHECK(cost_reserved >= 0),
 tokens_used BIGINT CHECK(tokens_used >= 0), cost_used BIGINT CHECK(cost_used >= 0),
 measured BOOLEAN, created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS analysis_usage_day ON analysis_usage(device_id,budget_day);
CREATE INDEX IF NOT EXISTS analysis_jobs_room ON analysis_jobs(device_id,room_id,created_at);
CREATE INDEX IF NOT EXISTS messages_received ON messages(device_id,room_id,received_at,event_id);
INSERT INTO schema_versions(version) VALUES(2) ON CONFLICT DO NOTHING;
