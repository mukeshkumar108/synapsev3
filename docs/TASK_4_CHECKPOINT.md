## Task 4 Checkpoint

### 1. What Task 4 Built

Task 4 established the reconciliation and confirmation layer for Synapse V3.

It now supports:
- agent-based reconciliation decisions over pending candidates
- Python-side reconciliation orchestration
- conservative candidate confirmation rules
- promotion from `candidates` into `confirmed_facts`
- timeline side effects for confirmed writes
- deterministic tests for CREATE, MERGE, UPDATE, DISMISS, confirmation gating, and temporal safety

This layer sits between extraction and future surfacing.

### 2. How `reconciliation_agent` Works

`agents/reconciliation_agent.py` is a judgement agent.

Role:
- Sophie’s memory editor for Cortex

Input:
- `new_candidates`: pending candidate packets
- `existing_facts`: up to 10 relevant confirmed facts supplied by Python

Output:
- an instruction per candidate:
  - `CREATE`
  - `MERGE`
  - `UPDATE`
  - `DISMISS`

Validation rules:
- only candidate IDs present in `new_candidates` are allowed
- only target IDs present in `existing_facts` are allowed
- `MERGE` and `UPDATE` require a valid target
- `CREATE` and `DISMISS` must use `target_id = null`
- output schema is strictly validated in Python

Prompt design:
- role-specific, not generic
- conservative by default
- treats bad memory as worse than missing memory
- preserves `companion_category` meaning
- handles sensitive boundaries carefully

### 3. How `core/reconciliation.py` Works

`core/reconciliation.py` is the Python service layer for Task 4.

It handles:
- fetching pending candidates
- fetching active confirmed facts for the same user
- placeholder relevance retrieval with a limit of 10
- calling `reconciliation_agent`
- writing reconciliation instructions back to candidates
- deciding whether a candidate is eligible for auto-confirmation
- promoting eligible candidates into `confirmed_facts`
- writing `timeline_events` side effects

It also contains:
- fact-type mapping from candidate semantics into the existing `confirmed_facts.fact_type` enum
- domain mapping into the existing `fact_domain` enum
- temporal suspicion checks
- sensitivity-aware confirmation checks

### 4. How `CREATE` / `MERGE` / `UPDATE` / `DISMISS` Are Handled

#### `CREATE`
- candidate gets reconciliation instruction `CREATE`
- if auto-confirmation rules pass:
  - create new `confirmed_facts` row
  - mark candidate `confirmed`
  - write one `timeline_events` row
- if auto-confirmation rules fail:
  - candidate remains `pending`

#### `MERGE`
- candidate gets reconciliation instruction `MERGE`
- target existing fact must exist
- if auto-confirmation rules pass:
  - append `source_id`
  - adjust confidence with `confidence_delta`
  - update `last_seen_at` and `last_confirmed_at`
  - mark candidate `confirmed`
  - write one `timeline_events` row
- no duplicate `confirmed_facts` row is created

#### `UPDATE`
- candidate gets reconciliation instruction `UPDATE`
- target existing fact must exist
- if auto-confirmation rules pass:
  - replace or refine `content`
  - append `source_id`
  - adjust confidence with `confidence_delta`
  - update `last_seen_at` and `last_confirmed_at`
  - mark candidate `confirmed`
  - write one `timeline_events` row

#### `DISMISS`
- candidate gets reconciliation instruction `DISMISS`
- candidate status becomes `dismissed`
- no confirmed fact is written
- no timeline event is written

### 5. How `confirmed_facts` Writes Work

Confirmed writes are performed in Python, never by agents.

On creation:
- `user_id` comes from candidate
- `fact_type` is mapped conservatively from candidate type and content
- `domain` is mapped conservatively from candidate type, content, and links
- `content` stores the normalized candidate envelope
- `confidence` starts from candidate confidence
- `first_seen_at` comes from candidate `created_at`
- `last_seen_at` is set to write time
- `last_confirmed_at` is set for auto-confirmed items
- `source_ids` starts with the candidate `source_id`
- `status` is `active`
- `user_corrected` is `false`
- `expires_at` comes from candidate lifecycle when present

On merge/update:
- `source_ids` appends new evidence source
- `last_seen_at` updates
- `last_confirmed_at` updates
- confidence changes by bounded `confidence_delta`

### 6. How `timeline_events` Side Effects Work

Every confirmed `CREATE`, `MERGE`, or `UPDATE` writes a `timeline_events` row.

This is a Python-side side effect, never an agent responsibility.

Current mapping examples:
- confirmed task -> `task_confirmed`
- confirmed event/invitation -> `event_confirmed`
- confirmed fact -> `fact_learned`
- confirmed state -> `state_change`
- confirmed relationship fact -> `relationship_update`

Timeline rows include:
- `user_id`
- `event_type`
- `timeline_type`
- `title`
- `summary`
- `occurred_at`
- `observed_at`
- `source_id`
- `related_fact_ids`
- `status = current`
- `confidence`

### 7. How Sensitive Companion Memories and `avoid_topic` Boundaries Are Handled

Task 4 treats sensitive companion memories conservatively.

Important rules:
- sensitive inferred memories should not be promoted casually
- explicit user-stated preferences and boundaries have higher authority
- `avoid_topic` and `sensitivity_boundary` memories preserve `companion_category`
- `companion_category` is not flattened away during reconciliation or promotion
- explicit high-sensitivity boundaries can auto-confirm if evidence is explicit and `needs_confirmation = false`

This keeps companion memory useful without weakening user trust.

### 8. How Temporal Suspicious Candidates Are Gated

Task 4 includes a simple temporal safety gate before auto-confirmation.

Candidates are not auto-confirmed when:
- temporal fields look suspicious relative to current time
- unresolved time text or resolution-basis fields imply ambiguity
- malformed or impossible temporal values are present
- old example-like dates appear inconsistent with current context

This is intentionally conservative.

Temporal gating currently prevents promotion rather than attempting repair.

### 9. What Tests Exist

The Task 4 suite includes deterministic coverage for:
- reconciliation agent output validation
- invalid target ID rejection
- invalid instruction rejection
- unknown candidate ID rejection
- `CREATE`
- `DISMISS`
- `MERGE`
- `UPDATE`
- `needs_confirmation` gating
- explicit high-sensitivity boundary auto-confirm behavior
- suspicious temporal candidate gating
- placeholder active-fact retrieval limit behavior

These tests complement the earlier Task 2 and Task 3 suites.

### 10. Known Caveats Before Task 5

- existing-fact retrieval is placeholder-grade, not vector search yet
- temporal grounding validation is simple and should be hardened later
- live LLM output still needs evals
- reconciliation prompt is role-refined but should be evaluated with real candidate batches
- Task 5 surfacing must not treat `confirmed_facts` as a dump of things to mention
- Sophie runtime owns final voice and tone; Cortex only prepares intelligence

Additional practical caveats:
- domain mapping is intentionally conservative and still fairly simple
- confirmed-fact promotion is safe enough for pipeline flow, but retrieval and ranking quality are still limited
- evaluation with real mixed companion/productivity batches is still needed before trusting reconciliation behavior at scale
