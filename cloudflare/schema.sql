-- Ejecutar en la consola D1 de Cloudflare, NO en pgAdmin.
CREATE TABLE IF NOT EXISTS commands (
 id TEXT PRIMARY KEY,
 message_id TEXT NOT NULL,
 phone_id TEXT NOT NULL,
 sender TEXT NOT NULL,
 command TEXT NOT NULL,
 requested_at INTEGER NOT NULL,
 received_at INTEGER NOT NULL,
 acknowledged_at INTEGER,
 UNIQUE(phone_id, message_id)
);
CREATE INDEX IF NOT EXISTS commands_pending ON commands(acknowledged_at, requested_at);
