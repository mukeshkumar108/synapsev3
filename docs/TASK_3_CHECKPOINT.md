## Task 3 Checkpoint

### 1. What Task 3 Built

Task 3 established the extraction layer for Synapse V3.

It now supports:
- triage-driven routing from raw source material
- domain-specific extraction into candidates
- candidate persistence outside agents
- shared candidate envelope normalization in Python
- companion-relevant memory primitives inside the existing V3 architecture

Extraction remains LLM-led. Persistence, validation, routing, and traceability remain in Python.

### 2. Which Agents Now Exist

The following Task 3 extraction agents now exist:
- `agents/task_agent.py`
- `agents/event_agent.py`
- `agents/fact_agent.py`
- `agents/state_agent.py`
- `agents/thread_agent.py`

Task 2 agents already in place and still used:
- `agents/triage_agent.py`
- `agents/session_summary_agent.py`

### 3. Candidate Envelope Shape

Persisted `candidates.content` uses the shared normalized envelope from `docs/CANDIDATE_CONTENT_SHAPES.md`:

```json
{
  "schema_version": "v1",
  "item_type": "task|event|fact|state|thread|invitation",
  "title": "short label or null",
  "summary": "compact summary or null",
  "salience": "high|medium|low|null",
  "priority": "high|medium|low|null",
  "urgency": "high|medium|low|null",
  "importance": "high|medium|low|null",
  "sensitivity": "high|medium|low|null",
  "time": {
    "due_date": null,
    "reminder_at": null,
    "date": null,
    "time": null,
    "duration": null,
    "follow_up_after_hours": null,
    "stale_after_hours": null,
    "expires_at": null
  },
  "links": {
    "people": [],
    "projects": [],
    "related_facts": [],
    "related_threads": []
  },
  "lifecycle": {
    "follow_up_after_hours": null,
    "stale_after_hours": null,
    "expires_at": null
  },
  "evidence": {
    "raw_evidence": "exact quote",
    "source_turn_refs": []
  },
  "metadata": {
    "companion_category": null,
    "agent_item": {}
  }
}
```

### 4. How `companion_category` Works

Companion memory is represented without changing the six-table schema.

- Agents still emit their domain-native item shapes.
- Companion-specific meaning is carried in `companion_category`.
- Python preserves that value in `candidates.content.metadata.companion_category`.
- Broad V3-compatible types remain in relational routing and broad item fields.

Examples:
- communication preference:
  - `candidate_type = fact`
  - `fact_type = preference`
  - `metadata.companion_category = communication_preference`
- avoid topic boundary:
  - `candidate_type = fact`
  - `fact_type = constraint`
  - `metadata.companion_category = avoid_topic`
- ask about later:
  - `candidate_type = thread`
  - `metadata.companion_category = ask_about_later`

This keeps the schema stable while preserving richer companion semantics.

### 5. What Tests Exist

The suite now covers:
- triage output shape and routing discipline
- session summary output shape
- task/event/fact/state/thread domain separation
- companion primitive extraction cases
- candidate envelope normalization
- candidate persistence metadata preservation
- deterministic pipeline-routing tests with fake database persistence

Companion-oriented coverage includes:
- win/accomplishment
- low/struggle
- aspiration
- fear/worry
- inside joke
- communication preference
- avoid topic / sensitivity boundary
- ask about later

### 6. Known Caveats Remain

- temporal grounding still needs hardening
- `test_pipeline.py` full run is verbose/long and may need a focused mode
- live LLM output can still vary, so deterministic tests remain important
- reconciliation must not promote every pending candidate blindly
- companion memory must preserve sensitivity and avoid-topic boundaries carefully

Additional practical caveats:
- some live relative-date outputs are still not reliably grounded to the provided current date
- live model outputs can still over- or under-extract around borderline cases, even when unit tests are stable

### 7. What Must Be Considered In Task 4

Task 4 should build on Task 3 rather than re-open its architecture.

Requirements for Task 4:
- keep the V3 build spec as source of truth
- keep the six-table schema intact
- treat candidates as untrusted until reconciliation decides CREATE, MERGE, UPDATE, or DISMISS
- preserve raw evidence and traceability
- preserve sensitivity-aware handling for companion memories
- do not lose `companion_category` during reconciliation or promotion
- ensure avoid-topic and sensitivity-boundary memories are respected conservatively
- use deterministic tests alongside live runs because reconciliation quality is model-sensitive

Task 4 should assume:
- extraction is structurally complete enough
- candidate persistence is in place
- routing and companion memory primitives are present
- temporal hardening is still a separate quality track
