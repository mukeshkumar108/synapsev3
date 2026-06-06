BEGIN;

ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'task_updated';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'reminder_updated';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'reminder_archived';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'habit_created';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'habit_updated';
ALTER TYPE event_type ADD VALUE IF NOT EXISTS 'habit_archived';

COMMIT;
