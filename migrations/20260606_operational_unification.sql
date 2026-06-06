BEGIN;

ALTER TYPE candidate_type ADD VALUE IF NOT EXISTS 'habit';
ALTER TYPE candidate_type ADD VALUE IF NOT EXISTS 'reminder';

ALTER TYPE fact_type ADD VALUE IF NOT EXISTS 'habit';
ALTER TYPE fact_type ADD VALUE IF NOT EXISTS 'reminder';

ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'task_completed';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'reminder_dismissed';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'habit_completed';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'habit_missed';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'habit_partial';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'thread_resolved';

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

ALTER TABLE confirmed_facts ALTER COLUMN follow_up_needed SET DEFAULT FALSE;
ALTER TABLE candidates ALTER COLUMN follow_up_needed SET DEFAULT FALSE;

UPDATE confirmed_facts
SET
    structured_content = COALESCE(structured_content, '{}'::jsonb),
    created_from = COALESCE(created_from, '{}'::jsonb),
    provenance = COALESCE(provenance, '{}'::jsonb),
    follow_up_needed = COALESCE(follow_up_needed, FALSE)
WHERE
    structured_content IS NULL
    OR created_from IS NULL
    OR provenance IS NULL
    OR follow_up_needed IS NULL;

UPDATE candidates
SET
    structured_content = COALESCE(structured_content, '{}'::jsonb),
    created_from = COALESCE(created_from, '{}'::jsonb),
    provenance = COALESCE(provenance, '{}'::jsonb),
    follow_up_needed = COALESCE(follow_up_needed, FALSE)
WHERE
    structured_content IS NULL
    OR created_from IS NULL
    OR provenance IS NULL
    OR follow_up_needed IS NULL;

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

COMMIT;
