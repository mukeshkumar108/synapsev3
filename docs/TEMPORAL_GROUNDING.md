## Temporal Grounding

This note defines how Synapse V3 should handle relative and calendar language before any implementation pass.

### Core Rule

Every agent that resolves dates or times must receive temporal context explicitly.

Required context fields:
- `current_date`
- `current_datetime`
- `timezone`

### Agent Rules

- Agents must never use hardcoded dates.
- Agents must never reuse example dates from prompts as if they were real output values.
- Relative dates such as `tomorrow`, `Monday`, `next week`, and `this weekend` must be resolved from `context.current_datetime`.
- If a date or time cannot be resolved safely, the agent must return:
  - `null` for the resolved field
  - `time_text` with the original natural-language phrase when useful
  - `date_resolution_basis` describing why the value is unresolved or how it was derived
  - `needs_confirmation=true`

### Persistence Rules

Python should validate suspicious or impossible temporal values before persistence.

Examples:
- dates clearly inconsistent with the supplied context
- malformed ISO values
- impossible calendar dates
- reminders or due dates that appear to come from prompt examples rather than transcript/context grounding

### Candidate Envelope Time Fields

The candidate envelope `time` object should preserve:
- `due_date`
- `reminder_at`
- `date`
- `time`
- `time_text`
- `date_resolution_basis`
- `timezone`

This keeps both the normalized value and the reasoning trace needed for later validation, confirmation, and reconciliation.

### Testing Rule

Tests should use fixed `current_datetime` fixtures so relative-date behavior is deterministic.

This applies especially to:
- task extraction
- event extraction
- reminder handling
- deadline handling
- any agent or persistence path that converts natural-language time into structured values

### Status

This is a design note only.

Implementation should happen later:
- either as a dedicated Task 3 temporal hardening pass
- or alongside later companion/memory primitives
