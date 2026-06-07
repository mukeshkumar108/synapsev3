## Lifecycle Fields Audit

This note audits the lifecycle and decay-related fields that already exist in Synapse V3 before adding a state decay worker.

Sources inspected:
- `schema.sql`
- `core/candidates.py`
- `core/reconciliation.py`
- `docs/CANDIDATE_CONTENT_SHAPES.md`
- `docs/TASK_3_CHECKPOINT.md`
- `docs/TASK_4_CHECKPOINT.md`

This is an audit of the current implementation, not a proposed schema change.

### 1. `candidates` Table Columns

Current columns in `candidates`:
- `id`
- `user_id`
- `source_id`
- `candidate_type`
- `content`
- `raw_evidence`
- `confidence`
- `needs_confirmation`
- `status`
- `reconciliation_instruction`
- `merge_target_id`
- `created_at`

Notes:
- `updated_at` does not exist.
- `status` uses the existing enum:
  - `pending`
  - `confirmed`
  - `dismissed`
  - `superseded`
  - `expired`
- `reconciliation_instruction` uses:
  - `CREATE`
  - `MERGE`
  - `UPDATE`
  - `DISMISS`

### 2. `candidates.content` Envelope Fields

Current persisted envelope shape is normalized in `core/candidates.py`.

Top-level fields:
- `schema_version`
- `item_type`
- `title`
- `summary`
- `salience`
- `priority`
- `urgency`
- `importance`
- `sensitivity`
- `time`
- `links`
- `lifecycle`
- `evidence`
- `metadata`

`time` currently includes:
- `due_date`
- `reminder_at`
- `date`
- `time`
- `duration`
- `follow_up_after_hours`
- `stale_after_hours`
- `expires_at`

`links` currently includes:
- `people`
- `projects`
- `related_facts`
- `related_threads`

`lifecycle` currently includes:
- `follow_up_after_hours`
- `stale_after_hours`
- `expires_at`

`evidence` currently includes:
- `raw_evidence`
- `source_turn_refs`

`metadata` currently includes:
- `companion_category`
- `agent_item`

Notes:
- `companion_category` does not live at the top level.
- It currently lives at `content.metadata.companion_category`.
- The original agent payload is preserved at `content.metadata.agent_item`.

### 3. `confirmed_facts` Table Columns

Current columns in `confirmed_facts`:
- `id`
- `user_id`
- `fact_type`
- `domain`
- `content`
- `confidence`
- `first_seen_at`
- `last_seen_at`
- `last_confirmed_at`
- `source_ids`
- `status`
- `user_corrected`
- `correction_note`
- `expires_at`

Notes:
- `created_at` does not exist.
- `updated_at` does not exist.
- `status` uses the existing enum:
  - `active`
  - `stale`
  - `historical`
  - `corrected`
  - `dismissed`

### 4. `confirmed_facts.content` Lifecycle Fields

`confirmed_facts.content` stores the normalized candidate envelope copied forward from reconciliation/promotion.

That means confirmed facts can already carry the same structured lifecycle information that first appeared in `candidates.content`.

Relevant fields that may exist inside `confirmed_facts.content`:

Top-level envelope fields:
- `salience`
- `priority`
- `urgency`
- `importance`
- `sensitivity`

`content.lifecycle`:
- `follow_up_after_hours`
- `stale_after_hours`
- `expires_at`

`content.time`:
- `due_date`
- `reminder_at`
- `date`
- `time`
- `duration`
- `follow_up_after_hours`
- `stale_after_hours`
- `expires_at`

`content.metadata`:
- `companion_category`
- `agent_item`

State/provisional markers:
- temporary state is distinguishable via `fact_type = state`
- `content.item_type` may also be `state`
- `content.metadata.agent_item.provisional` is preserved for state-derived items when present

Companion/lifecycle-relevant markers currently available inside confirmed content:
- `content.metadata.companion_category`
- `content.sensitivity`
- `content.salience`
- `content.importance`
- `content.lifecycle.stale_after_hours`
- `content.lifecycle.follow_up_after_hours`
- `content.lifecycle.expires_at`

Also note:
- `confirmed_facts.expires_at` is written separately as a real relational column during promotion.
- `core/reconciliation.py` currently reads that value from `content.lifecycle.expires_at`.

### 5. `timeline_events` Fields Relevant To Decay

Current columns in `timeline_events`:
- `id`
- `user_id`
- `event_type`
- `timeline_type`
- `title`
- `summary`
- `occurred_at`
- `observed_at`
- `source_id`
- `related_fact_ids`
- `status`
- `confidence`

Fields directly relevant to a future decay worker:
- `event_type`
- `timeline_type`
- `occurred_at`
- `observed_at`
- `source_id`
- `related_fact_ids`
- `status`
- `confidence`

Current `event_type` enum values:
- `task_confirmed`
- `event_confirmed`
- `fact_learned`
- `state_change`
- `session`
- `outreach_sent`
- `item_dismissed`
- `user_correction`
- `relationship_update`

Current `timeline_type` enum values:
- `interaction`
- `user_life`
- `calendar`
- `relationship`
- `system`

Current `timeline_status` enum values:
- `current`
- `stale`
- `historical`
- `corrected`

Important caveat:
- timeline rows can already be written when a decay worker changes a fact status
- but the current `event_type` enum is more natural for state decay than for a generic “fact became stale” event
- `state_change` is a reasonable fit for stale/current transitions of state facts
- there is no dedicated `fact_staled` or `item_staled` event type today

### 6. Gaps Before A Decay Worker

#### Can state/provisional facts be marked stale using existing status values?

Yes.

`confirmed_facts.status = stale` already exists and is the simplest current mechanism.

For state decay, this is the most natural status transition:
- `active` -> `stale`

#### Can expired facts be marked using existing status values?

Yes, partially.

Existing confirmed-fact statuses do not include `expired`, but there are still workable options:
- use `expires_at` to determine expiry
- set `confirmed_facts.status = stale` when the fact should no longer be treated as current
- optionally use `historical` for facts that should remain true in the record but are no longer operationally current

So:
- explicit expiration can be represented with `confirmed_facts.expires_at`
- the current status outcome would likely be `stale` or `historical`, not a dedicated `expired` state

#### Can we distinguish temporary state from durable facts?

Yes.

Current signals already available:
- `confirmed_facts.fact_type = state`
- `confirmed_facts.domain = state`
- `content.item_type = state`
- `content.metadata.agent_item.provisional = true` when preserved from `state_agent`
- state items often carry `stale_after_hours`

This is sufficient to implement a state-first decay worker without schema changes.

#### Can we preserve sensitive `avoid_topic` and `sensitivity_boundary` memories from accidental decay?

Yes, with worker rules.

Current signals already available:
- `content.metadata.companion_category`
- `content.sensitivity`
- `fact_type`
- `domain`

That means the worker can explicitly exempt or treat specially:
- `avoid_topic`
- `sensitivity_boundary`
- communication/comfort/tone preferences

These items should not be treated like provisional state.

#### Can we decay low-salience state faster than high-salience state?

Yes.

Current fields already support this in Python logic:
- `content.salience`
- `content.importance`
- `content.lifecycle.stale_after_hours`
- `content.time.stale_after_hours`

So the worker can:
- use explicit `stale_after_hours` when present
- otherwise fall back to salience-based defaults

No schema change is required for that policy.

#### Can we write `timeline_events` when decay changes a fact status?

Yes, with one limitation.

The worker can already insert a `timeline_events` row using existing columns.

What is easy now:
- for stale state facts, write a `state_change` event
- use `timeline_type = system` or `interaction`
- link the affected fact via `related_fact_ids`

What is less clean now:
- there is no dedicated event type for generic non-state decay
- so a broader decay worker would either:
  - log only state decay at first, or
  - reuse a semantically imperfect existing `event_type`

That is a design limitation, not a hard blocker.

### 7. Simplest Decay Worker Design Using Current Schema

The simplest worker can be implemented using only the current schema.

Recommended initial scope:
- operate only on `confirmed_facts`
- focus first on `fact_type = state` and other clearly provisional facts
- do not touch `candidates`

Recommended selection logic:
- fetch `confirmed_facts` where `status = active`
- focus on rows where:
  - `fact_type = state`, or
  - `content.metadata.agent_item.provisional = true`, or
  - `content.lifecycle.stale_after_hours` exists, or
  - `confirmed_facts.expires_at` is set

Recommended decay rules:
- if `expires_at` has passed, mark the fact `stale`
- else if `content.lifecycle.stale_after_hours` exists, use it
- else if `content.time.stale_after_hours` exists, use it
- else apply a simple default for state facts, such as 48 hours from `last_seen_at`
- optionally use salience-aware defaults:
  - low salience state -> shorter stale window
  - high salience state -> longer stale window

Recommended exclusions:
- do not decay durable profile facts on the same path as state
- do not decay:
  - `avoid_topic`
  - `sensitivity_boundary`
  - communication preferences
  - comfort preferences
  - tone preferences
  - encouragement style
  - durable relationship/identity memories

Recommended write behavior:
- update `confirmed_facts.status` from `active` to `stale`
- do not overwrite `source_ids`
- do not erase `content`
- do not remove `companion_category`

Recommended timeline behavior:
- for state facts only, write a `timeline_events` row using:
  - `event_type = state_change`
  - `timeline_type = system`
  - `related_fact_ids = [fact_id]`
  - `status = current`
- defer generic non-state decay timeline logging until event semantics are clearer

### Recommendation

No schema change is required to build a first-pass state decay worker.

The cleanest approach with the current schema is:
1. decay only `confirmed_facts`, not candidates
2. start with `fact_type = state` and clearly provisional facts
3. use `status = stale`
4. use `expires_at`, `stale_after_hours`, `last_seen_at`, and `salience` as the decision inputs
5. explicitly exempt sensitive durable boundaries and communication preferences
6. write `timeline_events` only for state transitions at first, because existing `event_type` values fit that case best
