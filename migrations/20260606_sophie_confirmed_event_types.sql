BEGIN;

ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'task_created';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'reminder_created';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'event_created';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'task_archived';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'event_updated';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'event_cancelled';

COMMIT;
