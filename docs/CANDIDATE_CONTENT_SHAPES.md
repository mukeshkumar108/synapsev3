## Candidate Content Shapes

The `candidates` table keeps one JSON `content` payload per extracted item.

The database schema does not change for this. The shared structure is enforced in Python before persistence.

### Shared Envelope

Every persisted `candidates.content` payload should be normalized into this envelope:

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
    "agent_item": {}
  }
}
```

### Purpose

- Make downstream reconciliation and surfacing read a consistent top-level shape.
- Preserve the original agent output without forcing every agent to emit the same fields.
- Keep traceability explicit through `evidence` and `metadata.agent_item`.

### Agent Output vs Persisted Shape

- Agents still return simple type-specific item objects.
- Python normalizes those items into the shared envelope before writing to `candidates.content`.
- The original item stays available under `metadata.agent_item`.

### Notes

- `candidate_type` still lives in the relational column and remains the canonical routing type.
- `raw_evidence`, `confidence`, and `needs_confirmation` still remain duplicated in top-level columns for fast filtering and traceability.
- `schema_version` allows future envelope evolution without changing the table schema.
