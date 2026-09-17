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
