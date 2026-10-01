CREATE TABLE IF NOT EXISTS leads (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ref        TEXT NOT NULL UNIQUE,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  intent     TEXT NOT NULL CHECK (intent IN ('demo','contact','sponsor')),
  name       TEXT NOT NULL,
  email      TEXT NOT NULL,
  org        TEXT,
  topic      TEXT,
  message    TEXT NOT NULL,
  lang       TEXT,
  country    TEXT,
  ip_hash    TEXT,
  ua         TEXT,
  status     TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new','read','replied','archived'))
);
CREATE INDEX IF NOT EXISTS idx_leads_created ON leads (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_leads_ip ON leads (ip_hash, created_at);
