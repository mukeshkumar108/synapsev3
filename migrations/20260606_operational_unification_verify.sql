WITH required_columns(table_name, column_name) AS (
    VALUES
        ('confirmed_facts', 'structured_content'),
        ('confirmed_facts', 'source_type'),
        ('confirmed_facts', 'primary_source_id'),
        ('confirmed_facts', 'who_said_it'),
        ('confirmed_facts', 'original_text'),
        ('confirmed_facts', 'channel'),
        ('confirmed_facts', 'conversation_id'),
        ('confirmed_facts', 'created_from'),
        ('confirmed_facts', 'provenance'),
        ('confirmed_facts', 'starts_at'),
        ('confirmed_facts', 'ends_at'),
        ('confirmed_facts', 'due_at'),
        ('confirmed_facts', 'remind_at'),
        ('confirmed_facts', 'timezone'),
        ('confirmed_facts', 'recurrence_rule'),
        ('confirmed_facts', 'completed_at'),
        ('confirmed_facts', 'cancelled_at'),
        ('confirmed_facts', 'priority'),
        ('confirmed_facts', 'follow_up_needed'),
        ('candidates', 'fact_type'),
        ('candidates', 'structured_content'),
        ('candidates', 'starts_at'),
        ('candidates', 'ends_at'),
        ('candidates', 'due_at'),
        ('candidates', 'remind_at'),
        ('candidates', 'timezone'),
        ('candidates', 'recurrence_rule'),
        ('candidates', 'completed_at'),
        ('candidates', 'cancelled_at'),
        ('candidates', 'priority'),
        ('candidates', 'source_type'),
        ('candidates', 'who_said_it'),
        ('candidates', 'original_text'),
        ('candidates', 'channel'),
        ('candidates', 'conversation_id'),
        ('candidates', 'created_from'),
        ('candidates', 'provenance'),
        ('candidates', 'follow_up_needed')
),
required_indexes(index_name) AS (
    VALUES
        ('idx_confirmed_facts_fact_type'),
        ('idx_confirmed_facts_status'),
        ('idx_confirmed_facts_starts_at'),
        ('idx_confirmed_facts_ends_at'),
        ('idx_confirmed_facts_due_at'),
        ('idx_confirmed_facts_remind_at'),
        ('idx_confirmed_facts_completed_at'),
        ('idx_confirmed_facts_cancelled_at'),
        ('idx_confirmed_facts_priority'),
        ('idx_confirmed_facts_follow_up_needed'),
        ('idx_confirmed_facts_source_type'),
        ('idx_confirmed_facts_primary_source_id'),
        ('idx_confirmed_facts_conversation_id'),
        ('idx_confirmed_facts_structured_content'),
        ('idx_confirmed_facts_provenance'),
        ('idx_candidates_fact_type'),
        ('idx_candidates_status'),
        ('idx_candidates_starts_at'),
        ('idx_candidates_ends_at'),
        ('idx_candidates_due_at'),
        ('idx_candidates_remind_at'),
        ('idx_candidates_source_type'),
        ('idx_candidates_conversation_id'),
        ('idx_candidates_follow_up_needed'),
        ('idx_candidates_structured_content'),
        ('idx_candidates_provenance')
),
required_enum_values(type_name, enum_label) AS (
    VALUES
        ('candidate_type', 'habit'),
        ('candidate_type', 'reminder'),
        ('fact_type', 'habit'),
        ('fact_type', 'reminder'),
        ('event_type', 'task_completed'),
        ('event_type', 'reminder_dismissed'),
        ('event_type', 'habit_completed'),
        ('event_type', 'habit_missed'),
        ('event_type', 'habit_partial'),
        ('event_type', 'thread_resolved')
)
SELECT
    'columns' AS check_type,
    rc.table_name AS object_name,
    rc.column_name AS detail,
    EXISTS (
        SELECT 1
        FROM information_schema.columns c
        WHERE c.table_schema = 'public'
          AND c.table_name = rc.table_name
          AND c.column_name = rc.column_name
    ) AS present
FROM required_columns rc
UNION ALL
SELECT
    'indexes' AS check_type,
    'public' AS object_name,
    ri.index_name AS detail,
    EXISTS (
        SELECT 1
        FROM pg_indexes i
        WHERE i.schemaname = 'public'
          AND i.indexname = ri.index_name
    ) AS present
FROM required_indexes ri
UNION ALL
SELECT
    'enum_values' AS check_type,
    rev.type_name AS object_name,
    rev.enum_label AS detail,
    EXISTS (
        SELECT 1
        FROM pg_type t
        JOIN pg_enum e ON e.enumtypid = t.oid
        WHERE t.typname = rev.type_name
          AND e.enumlabel = rev.enum_label
    ) AS present
FROM required_enum_values rev
ORDER BY check_type, object_name, detail;
