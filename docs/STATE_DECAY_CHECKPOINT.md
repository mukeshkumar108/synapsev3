## State Decay Checkpoint

### 1. What `core/decay.py` Does

`core/decay.py` implements the first-pass decay worker/service for Synapse V3.

Its job is narrow:
- inspect active `confirmed_facts`
- identify temporary or provisional state-like memories that should no longer be treated as current
- mark those rows `stale`
- write a `timeline_events` side effect for each stale transition

It does not touch:
- `candidates`
- schema
- external integrations
- message buffering
- task completion
- event lifecycle beyond explicit `expires_at`

### 2. What Kinds Of `confirmed_facts` It Decays

The worker only considers `confirmed_facts` with:
- `status = active`

And at least one of:
- `fact_type = state`
- `domain = state`
- `content.item_type = state`
- `content.metadata.agent_item.provisional = true`
- `content.lifecycle.stale_after_hours` present
- `content.time.stale_after_hours` present
- `expires_at` present

This keeps the scope focused on state/provisional memory rather than generic memory lifecycle management.

### 3. What It Explicitly Excludes

The worker explicitly excludes companion/profile memories that should not decay on the same path as temporary state.

Excluded `companion_category` values:
- `avoid_topic`
- `sensitivity_boundary`
- `communication_preference`
- `comfort_preference`
- `tone_preference`
- `encouragement_style`

It also avoids decaying durable non-state facts by default, especially:
- durable profile facts
- durable relationship facts
- durable identity/context facts

Those are intentionally out of scope for this first pass unless a later worker introduces separate rules.

### 4. How `stale_after_hours`, `expires_at`, And Salience Defaults Work

The decay decision order is:

1. If `expires_at` has passed:
- mark the fact stale

2. Else if `content.lifecycle.stale_after_hours` exists:
- compare `now` against `last_seen_at`

3. Else if `content.time.stale_after_hours` exists:
- compare `now` against `last_seen_at`

4. Else if the fact is state-like:
- use a salience-based default window

Current salience defaults:
- low salience state: `24h`
- medium salience state: `48h`
- high salience state: `72h`

Anchor time:
- `last_seen_at`
- fallback to `last_confirmed_at`
- fallback to `first_seen_at`

The worker preserves:
- `content`
- `source_ids`
- `companion_category`
- other fact metadata

It only changes:
- `confirmed_facts.status`

### 5. How `dry_run` Works

`decay_state_memories(..., dry_run=True)` evaluates the same decay rules without writing to the database.

In `dry_run` mode it:
- returns the list of facts that would be marked stale
- includes the reason for decay
- does not update `confirmed_facts.status`
- does not write `timeline_events`

This is useful for:
- debugging
- validating policy
- observing the effect of stale windows before enabling writes

### 6. How `timeline_events` Are Written

For each fact that is actually marked stale, the worker writes one `timeline_events` row.

Current write behavior:
- `event_type = state_change`
- `timeline_type = system`
- `title = content.title` when present, otherwise a generic stale-state label
- `summary = concise reason the state memory was marked stale`
- `occurred_at = now`
- `observed_at = now`
- `source_id = null`
- `related_fact_ids = [fact_id]`
- `status = current`
- `confidence = existing fact confidence`

This uses the current schema as-is.

### 7. What Tests Exist

`tests/test_decay.py` currently covers:
- active state older than `stale_after_hours` becomes stale
- active recent state does not become stale
- explicit `expires_at` in the past becomes stale
- low salience state uses the shorter default window
- high salience state uses the longer default window
- `avoid_topic` is not decayed
- `communication_preference` is not decayed
- durable non-state fact is not decayed
- stale transition writes a `timeline_events` row
- `dry_run` returns would-decay rows without writing

### 8. Known Limitations

- not generic memory decay
- only first-pass state/provisional decay
- no scheduler or cron is wired yet
- does not handle task completion or event expiry workflows
- does not decay durable profile or relationship facts

Additional practical limitations:
- generic non-state decay timeline semantics are still weak because the current `event_type` enum is state-oriented here
- the worker is intentionally conservative and narrow rather than complete

### 9. Recommended Future Worker Schedule

Recommended initial schedule:
- run every 1 to 6 hours

Practical rollout suggestion:
- start with `dry_run=True` in debugging or ops inspection
- inspect which rows would be decayed
- switch to write mode once the observed behavior looks correct

This is ready for periodic operation, but the scheduling layer itself is not yet wired.
