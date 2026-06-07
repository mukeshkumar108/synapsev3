## Task 8.5 Core Quality Gate

This pass audited Tasks 1-8 for brittle happy-path behavior, fake-green tests, user leakage, weak assumptions, temporal safety gaps, and runtime-path failures.

### Tests Added

Added `tests/test_quality_gate_core.py` with focused cross-cutting checks for:
- missing `DATABASE_URL` failure path
- high-sensitivity inferred memory auto-confirm safety
- explicit high-sensitivity boundary confirmation path
- stale state-like fact suppression in instruction packets
- runtime recall trigger safety for `remember to ...`
- pipeline failure status + raw transcript preservation
- recall user isolation across facts, summaries, and timeline
- calendar import isolation for same `external_id` across users/calendars

### Bugs Found

1. High-sensitivity inferred memories could auto-confirm too easily.
   - `core/reconciliation.should_auto_confirm(...)` treated `needs_confirmation=false` as effectively "explicit", which was too weak.
   - Result: inferred sensitive memories could be promoted even when they were not explicit user-stated boundaries.

2. Stale state suppression was too narrow.
   - `core/serving._fact_is_stale_state(...)` only recognized `fact_type = state`.
   - Result: state-like or provisional facts stored via `domain = state`, `content.item_type = state`, or `metadata.agent_item.provisional = true` could still leak into the startup packet.

3. Runtime recall could misfire on task phrasing.
   - `runtime.sophie_runtime.RECALL_PATTERNS` matched bare `remember`, which also matches `remember to call Ashley tomorrow`.
   - Result: Sophie could call recall on an action request instead of a memory question.

4. Missing-DB-config tests were vulnerable to local `.env` leakage.
   - This was primarily a test-harness issue, but it hid the real failure path unless dotenv loading was disabled in the test.

### Bugs Fixed

1. Reconciliation high-sensitivity gating hardened.
   - High-sensitivity candidates no longer auto-confirm by default.
   - Narrow exception retained for explicit `avoid_topic` / `sensitivity_boundary` memories with clear user-stated wording.

2. Stale state detection widened to state-like facts.
   - Suppression now recognizes:
     - `fact_type = state`
     - `domain = state`
     - `content.item_type = state`
     - `content.metadata.agent_item.provisional = true`

3. Runtime recall trigger narrowed.
   - `remember to ...` no longer triggers recall.
   - Explicit recall prompts such as `Do you remember Ashley?` still do.

4. DB-config quality-gate test hardened.
   - The missing-`DATABASE_URL` path is now tested without accidental `.env` rescue.

### Known Remaining Risks

1. Pipeline rerun idempotency is still weak.
   - Re-running the same `outbox` item can still duplicate `session_summaries`, `candidates`, and potentially `confirmed_facts` depending on reconciliation output.
   - This is not solved in Task 8.5.

2. Temporal grounding is still only partially hardened.
   - Reconciliation blocks some suspicious temporal values.
   - However, extraction and promotion still rely on incomplete date grounding for relative language across task/event flows.

3. Recall is better but still lexical.
   - Punctuation, simple typos, transpositions, phrase matches, and stopwords are handled.
   - Nicknames, aliases, and true semantic recall are still not solved.

4. Entity linking is still shallow.
   - Candidate `links.people` / `links.projects` are preserved.
   - There is still no canonical alias/entity layer, so same-name disambiguation remains unresolved.

5. Daily overview is still lightweight.
   - It is serviceable for V1, but not yet a dedicated briefing-quality planner view.

### Blockers Before Task 9

Current blockers I would treat as real before moving into the next major capability:

1. Pipeline rerun idempotency
   - Memory duplication on replay is a real-world failure mode, not just a test artifact.

2. Temporal grounding hardening
   - Relative-date handling remains a known correctness gap in real conversation usage.

### Recommendation

`safe_to_start_task_9 = false`

Reason:
- The current system is structurally sound and the test suite is strong enough to catch several brittle paths.
- But replay/idempotency and temporal grounding are still meaningful real-world correctness risks.
