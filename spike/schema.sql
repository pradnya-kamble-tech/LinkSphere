-- LinkSphere Spike 0 Database Schema
-- Run this in the Neon SQL Editor or local PostgreSQL

CREATE TABLE IF NOT EXISTS spike_clicks (
    id SERIAL PRIMARY KEY,
    code VARCHAR(50) NOT NULL,
    kind VARCHAR(20) NOT NULL, -- 'sync' or 'background'
    clicked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index on kind to speed up group-by count queries
CREATE INDEX IF NOT EXISTS idx_spike_clicks_kind ON spike_clicks(kind);
