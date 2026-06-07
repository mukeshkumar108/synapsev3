ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS claimed_by_entity_id TEXT;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS subject_entity_id TEXT;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS claim_type TEXT;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS interaction_mode TEXT;

ALTER TABLE candidates ADD COLUMN IF NOT EXISTS claimed_by_entity_id TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS subject_entity_id TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS claim_type TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS claim_status TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS interaction_mode TEXT;

CREATE TABLE IF NOT EXISTS entities (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS entity_aliases (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    entity_id UUID NOT NULL REFERENCES entities(id),
    alias_text TEXT NOT NULL,
    alias_kind TEXT NOT NULL,
    confidence FLOAT,
    is_primary BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS entity_mentions (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    entity_id UUID NOT NULL REFERENCES entities(id),
    surface_text TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_archive_id UUID NULL REFERENCES source_archive(id),
    outbox_id UUID NULL REFERENCES outbox(id),
    timeline_event_id UUID NULL REFERENCES timeline_events(id),
    fact_id UUID NULL REFERENCES confirmed_facts(id),
    candidate_id UUID NULL REFERENCES candidates(id),
    confidence FLOAT,
    original_text TEXT,
    who_said_it TEXT,
    channel TEXT,
    conversation_id TEXT,
    created_from JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS entity_links (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    entity_id UUID NOT NULL REFERENCES entities(id),
    fact_id UUID NULL REFERENCES confirmed_facts(id),
    candidate_id UUID NULL REFERENCES candidates(id),
    timeline_event_id UUID NULL REFERENCES timeline_events(id),
    source_archive_id UUID NULL REFERENCES source_archive(id),
    outbox_id UUID NULL REFERENCES outbox(id),
    link_type TEXT NOT NULL,
    confidence FLOAT,
    evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_from JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_entities_user_id ON entities(user_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(user_id, lower(canonical_name));
CREATE UNIQUE INDEX IF NOT EXISTS uq_entities_user_type_name ON entities(user_id, entity_type, lower(canonical_name));
CREATE INDEX IF NOT EXISTS idx_entity_aliases_user_entity ON entity_aliases(user_id, entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_aliases_text ON entity_aliases(user_id, lower(alias_text));
CREATE UNIQUE INDEX IF NOT EXISTS uq_entity_aliases_user_entity_text ON entity_aliases(user_id, entity_id, lower(alias_text));
CREATE INDEX IF NOT EXISTS idx_entity_mentions_user_id ON entity_mentions(user_id);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_entity_id ON entity_mentions(entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_fact_id ON entity_mentions(fact_id);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_candidate_id ON entity_mentions(candidate_id);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_timeline_event_id ON entity_mentions(timeline_event_id);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_source_archive_id ON entity_mentions(source_archive_id);
CREATE INDEX IF NOT EXISTS idx_entity_mentions_outbox_id ON entity_mentions(outbox_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_user_id ON entity_links(user_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_entity_id ON entity_links(entity_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_fact_id ON entity_links(fact_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_candidate_id ON entity_links(candidate_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_timeline_event_id ON entity_links(timeline_event_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_source_archive_id ON entity_links(source_archive_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_outbox_id ON entity_links(outbox_id);
CREATE INDEX IF NOT EXISTS idx_entity_links_link_type ON entity_links(link_type);
CREATE INDEX IF NOT EXISTS idx_entity_links_is_active ON entity_links(is_active);
