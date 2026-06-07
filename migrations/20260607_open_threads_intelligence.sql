ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'thread_dismissed';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'thread_snoozed';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'thread_progressed';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'thread_link_updated';

ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS thread_type TEXT;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS actionability TEXT;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS next_move TEXT;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS last_progressed_at TIMESTAMP;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS last_resurfaced_at TIMESTAMP;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS snoozed_until TIMESTAMP;

CREATE TABLE IF NOT EXISTS fact_links (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    from_fact_id UUID NOT NULL REFERENCES confirmed_facts(id),
    to_fact_id UUID NULL REFERENCES confirmed_facts(id),
    to_timeline_event_id UUID NULL REFERENCES timeline_events(id),
    to_source_archive_id UUID NULL REFERENCES source_archive(id),
    to_outbox_id UUID NULL REFERENCES outbox(id),
    link_type TEXT NOT NULL,
    confidence FLOAT,
    evidence JSONB DEFAULT '{}'::jsonb,
    created_from JSONB DEFAULT '{}'::jsonb,
    source_type TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_confirmed_facts_thread_type ON confirmed_facts(thread_type);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_actionability ON confirmed_facts(actionability);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_next_move ON confirmed_facts(next_move);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_last_progressed_at ON confirmed_facts(last_progressed_at);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_last_resurfaced_at ON confirmed_facts(last_resurfaced_at);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_snoozed_until ON confirmed_facts(snoozed_until);
CREATE INDEX IF NOT EXISTS idx_fact_links_user_id ON fact_links(user_id);
CREATE INDEX IF NOT EXISTS idx_fact_links_from_fact_id ON fact_links(from_fact_id);
CREATE INDEX IF NOT EXISTS idx_fact_links_to_fact_id ON fact_links(to_fact_id);
CREATE INDEX IF NOT EXISTS idx_fact_links_to_timeline_event_id ON fact_links(to_timeline_event_id);
CREATE INDEX IF NOT EXISTS idx_fact_links_to_source_archive_id ON fact_links(to_source_archive_id);
CREATE INDEX IF NOT EXISTS idx_fact_links_to_outbox_id ON fact_links(to_outbox_id);
CREATE INDEX IF NOT EXISTS idx_fact_links_link_type ON fact_links(link_type);
CREATE INDEX IF NOT EXISTS idx_fact_links_is_active ON fact_links(is_active);
