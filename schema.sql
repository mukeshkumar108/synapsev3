CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

DO $$ BEGIN
    CREATE TYPE outbox_source_type AS ENUM ('chat', 'whatsapp', 'email', 'calendar', 'sms');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE outbox_status AS ENUM ('pending', 'processing', 'done', 'failed');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE message_buffer_source_type AS ENUM ('whatsapp', 'sms', 'dm');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE message_buffer_status AS ENUM ('accumulating', 'sealed', 'processed');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE candidate_type AS ENUM ('task', 'event', 'fact', 'state', 'thread', 'invitation', 'habit', 'reminder');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
ALTER TYPE candidate_type ADD VALUE IF NOT EXISTS 'habit';
ALTER TYPE candidate_type ADD VALUE IF NOT EXISTS 'reminder';

DO $$ BEGIN
    CREATE TYPE candidate_status AS ENUM ('pending', 'confirmed', 'dismissed', 'superseded', 'expired');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE reconciliation_instruction AS ENUM ('CREATE', 'MERGE', 'UPDATE', 'DISMISS');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE fact_type AS ENUM ('task', 'event', 'preference', 'relationship', 'state', 'thread', 'identity', 'habit', 'reminder');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
ALTER TYPE fact_type ADD VALUE IF NOT EXISTS 'habit';
ALTER TYPE fact_type ADD VALUE IF NOT EXISTS 'reminder';

DO $$ BEGIN
    CREATE TYPE fact_domain AS ENUM ('profile', 'people', 'goals', 'workstreams', 'habits', 'obligations', 'events', 'state', 'opportunities');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE fact_status AS ENUM ('active', 'stale', 'historical', 'corrected', 'dismissed');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE event_type AS ENUM ('task_confirmed', 'event_confirmed', 'fact_learned', 'state_change', 'session', 'outreach_sent', 'item_dismissed', 'user_correction', 'relationship_update', 'task_completed', 'reminder_dismissed', 'habit_completed', 'habit_missed', 'habit_partial', 'thread_resolved', 'task_created', 'reminder_created', 'event_created', 'task_archived', 'event_updated', 'event_cancelled', 'task_updated', 'reminder_updated', 'reminder_archived', 'habit_created', 'habit_updated', 'habit_archived');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'task_completed';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'reminder_dismissed';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'habit_completed';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'habit_missed';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'habit_partial';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'thread_resolved';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'task_created';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'reminder_created';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'event_created';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'task_archived';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'event_updated';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'event_cancelled';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'task_updated';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'reminder_updated';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'reminder_archived';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'habit_created';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'habit_updated';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'habit_archived';

DO $$ BEGIN
    CREATE TYPE timeline_type AS ENUM ('interaction', 'user_life', 'calendar', 'relationship', 'system');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE timeline_status AS ENUM ('current', 'stale', 'historical', 'corrected');
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS outbox (
    id UUID PRIMARY KEY,
    user_id TEXT,
    source_type outbox_source_type,
    raw_content TEXT,
    received_at TIMESTAMP,
    status outbox_status,
    retry_count INT,
    metadata JSONB
);

CREATE TABLE IF NOT EXISTS source_archive (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_external_id TEXT NULL,
    session_id TEXT NULL,
    conversation_id TEXT NULL,
    occurred_at TIMESTAMP NULL,
    captured_at TIMESTAMP NOT NULL DEFAULT now(),
    payload JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT now()
);

ALTER TABLE outbox
ADD COLUMN IF NOT EXISTS source_archive_id UUID NULL;

DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND table_name = 'outbox'
          AND constraint_name = 'outbox_source_archive_id_fkey'
    ) THEN
        ALTER TABLE outbox
        ADD CONSTRAINT outbox_source_archive_id_fkey
        FOREIGN KEY (source_archive_id) REFERENCES source_archive(id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS message_buffer (
    id UUID PRIMARY KEY,
    user_id TEXT,
    source_type message_buffer_source_type,
    messages JSONB[],
    last_message_at TIMESTAMP,
    status message_buffer_status,
    sealed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS confirmed_facts (
    id UUID PRIMARY KEY,
    user_id TEXT,
    fact_type fact_type,
    domain fact_domain,
    content JSONB,
    structured_content JSONB,
    confidence FLOAT,
    first_seen_at TIMESTAMP,
    last_seen_at TIMESTAMP,
    last_confirmed_at TIMESTAMP,
    source_ids UUID[],
    source_type TEXT,
    primary_source_id UUID,
    who_said_it TEXT,
    original_text TEXT,
    channel TEXT,
    conversation_id TEXT,
    created_from JSONB,
    provenance JSONB,
    status fact_status,
    starts_at TIMESTAMP,
    ends_at TIMESTAMP,
    due_at TIMESTAMP,
    remind_at TIMESTAMP,
    timezone TEXT,
    recurrence_rule TEXT,
    completed_at TIMESTAMP,
    cancelled_at TIMESTAMP,
    priority TEXT,
    follow_up_needed BOOLEAN DEFAULT FALSE,
    user_corrected BOOLEAN,
    correction_note TEXT,
    expires_at TIMESTAMP
);

ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS structured_content JSONB;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS source_type TEXT;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS primary_source_id UUID;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS who_said_it TEXT;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS original_text TEXT;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS channel TEXT;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS conversation_id TEXT;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS created_from JSONB;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS provenance JSONB;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS starts_at TIMESTAMP;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS ends_at TIMESTAMP;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS due_at TIMESTAMP;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS remind_at TIMESTAMP;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS timezone TEXT;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS recurrence_rule TEXT;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS priority TEXT;
ALTER TABLE confirmed_facts ADD COLUMN IF NOT EXISTS follow_up_needed BOOLEAN DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS session_summaries (
    id UUID PRIMARY KEY,
    user_id TEXT,
    source_id UUID REFERENCES outbox(id),
    summary TEXT,
    tags TEXT[],
    open_items JSONB,
    key_decisions JSONB,
    emotional_tone TEXT,
    occurred_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS candidates (
    id UUID PRIMARY KEY,
    user_id TEXT,
    source_id UUID REFERENCES outbox(id),
    candidate_type candidate_type,
    fact_type fact_type,
    content JSONB,
    structured_content JSONB,
    raw_evidence TEXT,
    confidence FLOAT,
    needs_confirmation BOOLEAN,
    status candidate_status,
    reconciliation_instruction reconciliation_instruction,
    merge_target_id UUID REFERENCES confirmed_facts(id),
    created_at TIMESTAMP,
    starts_at TIMESTAMP,
    ends_at TIMESTAMP,
    due_at TIMESTAMP,
    remind_at TIMESTAMP,
    timezone TEXT,
    recurrence_rule TEXT,
    completed_at TIMESTAMP,
    cancelled_at TIMESTAMP,
    priority TEXT,
    source_type TEXT,
    who_said_it TEXT,
    original_text TEXT,
    channel TEXT,
    conversation_id TEXT,
    created_from JSONB,
    provenance JSONB,
    follow_up_needed BOOLEAN DEFAULT FALSE
);

ALTER TABLE candidates ADD COLUMN IF NOT EXISTS fact_type fact_type;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS structured_content JSONB;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS starts_at TIMESTAMP;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS ends_at TIMESTAMP;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS due_at TIMESTAMP;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS remind_at TIMESTAMP;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS timezone TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS recurrence_rule TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS completed_at TIMESTAMP;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS cancelled_at TIMESTAMP;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS priority TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS source_type TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS who_said_it TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS original_text TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS channel TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS conversation_id TEXT;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS created_from JSONB;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS provenance JSONB;
ALTER TABLE candidates ADD COLUMN IF NOT EXISTS follow_up_needed BOOLEAN DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS timeline_events (
    id UUID PRIMARY KEY,
    user_id TEXT,
    event_type event_type,
    timeline_type timeline_type,
    title TEXT,
    summary TEXT,
    occurred_at TIMESTAMP,
    observed_at TIMESTAMP,
    source_id UUID,
    related_fact_ids UUID[],
    status timeline_status,
    confidence FLOAT
);

CREATE TABLE IF NOT EXISTS retrieval_embeddings (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_id UUID NOT NULL,
    source_archive_id UUID NULL,
    chunk_index INT NULL,
    text TEXT NOT NULL,
    embedding VECTOR(__EMBEDDING_DIMENSION__) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    updated_at TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_source_archive_user_id ON source_archive(user_id);
CREATE INDEX IF NOT EXISTS idx_source_archive_source_type ON source_archive(source_type);
CREATE INDEX IF NOT EXISTS idx_source_archive_session_id ON source_archive(session_id);
CREATE INDEX IF NOT EXISTS idx_source_archive_conversation_id ON source_archive(conversation_id);
CREATE INDEX IF NOT EXISTS idx_source_archive_source_external_id ON source_archive(source_external_id);
CREATE INDEX IF NOT EXISTS idx_source_archive_captured_at ON source_archive(captured_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_source_archive_user_type_session
ON source_archive(user_id, source_type, session_id)
WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_confirmed_facts_subject ON confirmed_facts(subject_entity_id);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_claimed_by ON confirmed_facts(claimed_by_entity_id);
CREATE INDEX IF NOT EXISTS idx_candidates_subject ON candidates(subject_entity_id);
CREATE INDEX IF NOT EXISTS idx_candidates_claimed_by ON candidates(claimed_by_entity_id);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_fact_type ON confirmed_facts(fact_type);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_status ON confirmed_facts(status);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_starts_at ON confirmed_facts(starts_at);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_ends_at ON confirmed_facts(ends_at);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_due_at ON confirmed_facts(due_at);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_remind_at ON confirmed_facts(remind_at);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_completed_at ON confirmed_facts(completed_at);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_cancelled_at ON confirmed_facts(cancelled_at);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_priority ON confirmed_facts(priority);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_follow_up_needed ON confirmed_facts(follow_up_needed);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_source_type ON confirmed_facts(source_type);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_primary_source_id ON confirmed_facts(primary_source_id);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_conversation_id ON confirmed_facts(conversation_id);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_structured_content ON confirmed_facts USING GIN(structured_content);
CREATE INDEX IF NOT EXISTS idx_confirmed_facts_provenance ON confirmed_facts USING GIN(provenance);
CREATE INDEX IF NOT EXISTS idx_candidates_fact_type ON candidates(fact_type);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON candidates(status);
CREATE INDEX IF NOT EXISTS idx_candidates_starts_at ON candidates(starts_at);
CREATE INDEX IF NOT EXISTS idx_candidates_ends_at ON candidates(ends_at);
CREATE INDEX IF NOT EXISTS idx_candidates_due_at ON candidates(due_at);
CREATE INDEX IF NOT EXISTS idx_candidates_remind_at ON candidates(remind_at);
CREATE INDEX IF NOT EXISTS idx_candidates_source_type ON candidates(source_type);
CREATE INDEX IF NOT EXISTS idx_candidates_conversation_id ON candidates(conversation_id);
CREATE INDEX IF NOT EXISTS idx_candidates_follow_up_needed ON candidates(follow_up_needed);
CREATE INDEX IF NOT EXISTS idx_candidates_structured_content ON candidates USING GIN(structured_content);
CREATE INDEX IF NOT EXISTS idx_candidates_provenance ON candidates USING GIN(provenance);

CREATE INDEX IF NOT EXISTS idx_retrieval_embeddings_user_id ON retrieval_embeddings(user_id);
CREATE INDEX IF NOT EXISTS idx_retrieval_embeddings_source_type ON retrieval_embeddings(source_type);
CREATE INDEX IF NOT EXISTS idx_retrieval_embeddings_source_id ON retrieval_embeddings(source_id);
CREATE INDEX IF NOT EXISTS idx_retrieval_embeddings_source_archive_id ON retrieval_embeddings(source_archive_id);
CREATE INDEX IF NOT EXISTS idx_retrieval_embeddings_created_at ON retrieval_embeddings(created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_retrieval_embeddings_identity
ON retrieval_embeddings(user_id, source_type, source_id, COALESCE(chunk_index, -1));
CREATE INDEX IF NOT EXISTS idx_retrieval_embeddings_embedding_cosine
ON retrieval_embeddings USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
