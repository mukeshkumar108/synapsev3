# V2 Memory And Startup Behaviour Audit

This document describes what Synapse V2 actually did for:

- memory recall
- session startup / handover
- open loops
- user model / entity profile
- day brief / daily agenda
- session ingest

This is based on actual V2 code, route handlers, helpers, response models, tests, and scripts in the old repo.

It is not a V3 design document.

---

# 1. Executive Summary

## What V2 genuinely did well

V2 had real, useful behavior in six places:

- evidence-gated factual recall from canonical claims
- embedding-assisted episodic recall over transcript windows
- derived continuity recall as a separate lane
- compact startup handover packets built from recent summaries, loops, and entity hints
- deterministic day planning from calendar and action records
- durable session ingest with transcript persistence, outbox enqueueing, and idempotency

The strongest parts were:

- factual recall refused to return claim rows without evidence links
- episodic recall used a real ranking model, not just “latest session”
- startup handover enforced compact, non-drifting prose
- loop ranking combined salience, importance, urgency, and recency
- action and calendar records had coherent canonical shapes
- ingest persisted transcript state before downstream work

## What was bloated or legacy

- `POST /memory/query` was a compatibility shell over the newer V2 lane service
- `GET /session/brief` overlapped heavily with `GET /session/startbrief`
- `GET /day/brief` and `GET /actions/daily-agenda` overlapped
- `GET /user/model` exposed a monolithic blob with mixed narrative and derived state
- `GET /review-queue` and `GET /daily-candidates` leaked staging-table structure
- several tests and scripts still referenced older response assumptions

## What behaviors users likely relied on

- “What do we know for sure?” recall returning evidence-backed facts
- “What were we talking about?” episodic recall pulling the right past conversation
- startup continuity: time gap, latest thread, top loops, active tensions
- open-loop memory surviving across sessions
- day planning that combined due items, reminders, overdue items, and schedule
- ingest that did not lose transcripts and did not duplicate work on retry

---

# 2. Behaviour Map By Area

## A. Memory Recall

### Routes and files inspected

- Route: `POST /memory/query`
- Route handler: `memory_query`
- File: [src/main.py](/opt/synapse/src/main.py:13982)
- Adapter: `_memory_query_legacy_adapter`
- V2 service: `_memory_query_v2_service`
- Lane collectors:
  - `_v2_collect_factual_items`
  - `_v2_collect_episodic_items`
  - `_v2_collect_continuity_items`
- Supporting functions:
  - `_pg_search_facts`
  - `_pg_search_continuity_facts`
  - `_build_episodic_recall_items`
  - `search_episode_embedding_candidates` in [src/episodic_memory.py](/opt/synapse/src/episodic_memory.py:251)
- Models: [src/models.py](/opt/synapse/src/models.py:120)
- Tests:
  - [tests/test_t11_legacy_adapter.py](/opt/synapse/tests/test_t11_legacy_adapter.py:1)
  - [tests/test_v2_memory_query.py](/opt/synapse/tests/test_v2_memory_query.py:1)
  - [tests/test_internal_auth_recovery.py](/opt/synapse/tests/test_internal_auth_recovery.py:1)
- Scripts:
  - [scripts/contract_startbrief_memory.sh](/opt/synapse/scripts/contract_startbrief_memory.sh:1)
  - [scripts/smoke_synapse_contract.sh](/opt/synapse/scripts/smoke_synapse_contract.sh:1)

### Inputs

Request model: `MemoryQueryRequest`

- `tenantId`
- `userId`
- `query`
- `limit`
- `memoryIntent`: `exact|episodic|hybrid`
- `referenceTime`
- `includeContext`
- `focusQuery`

Important implementation notes:

- `focusQuery` exists on the request model but is not used by `_memory_query_legacy_adapter` or `_memory_query_v2_service`.
- `includeContext` is not supported in the T11 adapter path. It only changes `metadata.responseMode` and adds a compatibility notice.
- `referenceTime` is passed through to the V2 service and used differently by each lane.

### How `exact`, `episodic`, and `hybrid` differed

Legacy `/memory/query` mapped `memoryIntent` to V2 lanes using `_legacy_intent_to_v2_lane`:

- `exact` -> `factual`
- `episodic` -> `episodic`
- `hybrid` -> `hybrid`

Behavior differences:

- `exact` returned only evidence-backed canonical claim rows.
- `episodic` returned only episodic recall items.
- `hybrid` returned:
  - factual items
  - episodic items
  - continuity items
  - and additionally mapped continuity items into `facts` / `factItems` as explicitly derived facts

### Which tables and services were searched

#### 1. Factual lane

Function: `_v2_collect_factual_items`

Searched tables:

- `claims`
- `claim_evidence`
- `turns_v2`
- `entities` for subject canonical names

What it did:

- fetched active claims across `tenant_scope`
- aggregated evidence rows into `evidence_links`
- built a canonical display line with `_canonical_claim_line`
- dropped any claim with no evidence links

Important constraint:

- factual retrieval is not semantic in the current V2 path
- it does not call `_pg_search_facts`
- it does not perform vector retrieval

#### 2. Episodic lane

Function: `_v2_collect_episodic_items`

Delegated to `_build_episodic_recall_items`, which used:

- `search_episode_embedding_candidates` from `episodic_memory_embeddings`
- `_pg_get_recent_episodes` over:
  - `session_transcript`
  - `session_classifications`

Embedding candidate source:

- `episodic_memory_embeddings`
- query embedded with `embed_texts`
- vector similarity search ordered by `embedding <=> query_vec`

Recent episode source:

- transcript-backed session candidates
- summary from:
  - `one_line_summary`
  - `thread_signals`
  - `tension_signal`
  - transcript fallback

#### 3. Continuity lane

Function: `_v2_collect_continuity_items`

Delegated to `_pg_search_continuity_facts`, which assembled derived recall rows from:

- `entity_profiles`
- `open_threads`
- `session_classifications`
- `claims` with evidence counts

Important detail:

- continuity lane hard-filters to derived-only rows in the final collector
- canonical factual rows are dropped from the continuity lane even if `_pg_search_continuity_facts` can assemble canonical claim lines for mixed/debug use

### Was search semantic, keyword, hybrid, or lane-specific?

Yes, and it was lane-specific.

#### Factual lane

- not vector search
- not semantic expansion
- effectively structured claim retrieval plus lexical scoring of the canonical claim text

Ranking signal:

- `_score_text_match`
- inputs:
  - canonical claim line
  - `_query_terms(query)`
  - `updated_at`
  - base score derived from truth confidence

#### Episodic lane

- true hybrid retrieval
- vector candidate retrieval from `episodic_memory_embeddings`
- lexical overlap scoring over summary + transcript content
- recency scoring
- anchor/entity overlap scoring
- user-density scoring from embedding metadata

#### Continuity lane

- assembled text rows
- lexical query-term overlap via `_score_text_match`
- recency weighting
- no vector retrieval

### Was there query expansion or multiple query generation?

No evidence of multiple query generation or LLM query expansion in the current V2 recall path.

What did exist:

- `_query_terms(query)` tokenization
- episodic query profiling:
  - `relationship`
  - `reflective`
  - `continuation`
  - `default`

This was not query expansion. It changed scoring weights and thresholds based on the raw query text.

### Was there reranking?

Yes, but custom reranking, not a separate reranker model.

#### Factual

- scored by `_score_text_match`
- sorted by `score desc`, then `claim_event_key`

#### Episodic

Scoring components depended on query profile:

- `embeddingSimilarity`
- `lexicalOverlap`
- `recency`
- `linkedEntityOverlap`
- `userTurnDensity`
- `continuationIntentBonus`

It then applied:

- hard low-signal gating
- session diversity pass
- transcript evidence backfill when top rows lacked evidence

#### Continuity

- scored by `_score_text_match`
- deduped by normalized text
- sorted by `relevance`, then `valid_at`, then `text`

### How were weak/no results handled?

#### Factual

- no special weak-recall surface
- items simply dropped if:
  - no evidence links
  - no canonical line
  - score too low

#### Episodic

`_build_episodic_recall_items` computed an audit object with:

- `weakRecall`
- `weakRecallReason`
- `topScore`
- `topEmbeddingSimilarity`
- `topLexicalOverlap`
- `topAnchorScore`
- `topUserDensityScore`
- `candidatesSeen`
- `candidatesRanked`
- `diverseSessions`
- `embeddingRowsMatched`

But important implementation detail:

- `_v2_collect_episodic_items` discards that audit
- neither `/v2/memory/query` nor legacy `/memory/query` returns `weakRecall` or `episodicWeakRecall` to Sophie

So weak recall existed internally, but was not surfaced in the actual endpoint response.

#### Continuity

- low-score rows were filtered
- dedupe and derived-only filter applied
- no explicit weak-recall flag surfaced

### What exactly was returned to Sophie?

Legacy `/memory/query` returned `MemoryQueryResponse`:

- `facts`
- `factItems`
- `entities`
- `episodes`
- `metadata`

Actual current behavior:

- `entities` is always `[]` in the adapter path
- `openLoops`, `commitments`, `contextAnchors`, `userStatedState`, `currentFocus`, `recallSheet`, `supplementalContext` remain on the model but are not actively populated by the T11 adapter

`metadata` included:

- `query`
- `memoryIntent`
- `responseMode`: `recall` or `context`
- `adapter.mode`
- `adapter.v2Lane`
- `adapter.legacyMixedAuthorityFallback`
- `adapter.continuityMappedAsDerivedFacts`
- `adapter.includeContextSupported`
- `v2Metadata`
- counts for facts / episodes / continuity facts
- optional `contextCompatibilityNotice`
- rollout metadata

### Evidence and source refs

#### Factual items

- `claimEvidenceId`
- `sessionId`
- `turnIndex`
- `charStart`
- `charEnd`
- `evidenceText`

#### Episodic items

- only flattened evidence lines in legacy `/memory/query`
- richer per-item evidence rows in `/v2/memory/query`

#### Continuity items

- no evidence rows
- explicitly marked derived

### `metadata.responseMode`

This existed only on legacy `/memory/query`.

Behavior:

- `includeContext=false` -> `responseMode="recall"`
- `includeContext=true` -> `responseMode="context"`

But this was compatibility labeling only.

The adapter also set:

- `includeContextSupported=false`
- `contextCompatibilityNotice="Legacy includeContext is not available in T11 adapter mode."`

So V2 did not actually produce richer context-mode recall in the current implementation.

### Tests, fixtures, and scripts that verify recall behavior

#### Strongly relevant tests

- [tests/test_t11_legacy_adapter.py](/opt/synapse/tests/test_t11_legacy_adapter.py:1)
  - confirms legacy `/memory/query` routes only through V2
  - confirms no old mixed-authority fallback
  - confirms hybrid maps continuity into derived facts

- [tests/test_v2_memory_query.py](/opt/synapse/tests/test_v2_memory_query.py:1)
  - factual lane requires evidence-backed claims
  - continuity lane stays derived-only
  - episodic lane returns episodic items only
  - hybrid preserves lane labels

#### Auth/contract tests

- [tests/test_internal_auth_recovery.py](/opt/synapse/tests/test_internal_auth_recovery.py:1)
  - verifies internal-token gate

#### Scripts

- [scripts/smoke_synapse_contract.sh](/opt/synapse/scripts/smoke_synapse_contract.sh:1)
  - checks `/memory/query` returns `facts` and `metadata`

- [scripts/contract_startbrief_memory.sh](/opt/synapse/scripts/contract_startbrief_memory.sh:1)
  - checks `/memory/query.metadata.responseMode`

Important drift:

- that script still expects an older `/session/startbrief` shape and is not authoritative for current startup output

### User-facing behaviors enabled

- “Who is Ashley?” -> evidence-backed factual answer
- “What did we discuss?” -> episodic recall from transcript-backed past sessions
- “What should I resume?” -> hybrid mode combining facts, episodes, and derived continuity
- reduced hallucination risk in exact recall because claims without evidence were dropped

### Must-preserve behaviors for parity

- exact recall must remain evidence-gated
- episodic recall must remain embedding-assisted, not just latest-session lookup
- hybrid recall must preserve lane distinctions
- continuity results must remain explicitly derived, not mixed with canonical truth
- recall metadata must clearly indicate what type of thing was returned

---

## B. Session Startup / Handover

### Routes and files inspected

- Route: `GET /session/startbrief`
- Handler: `session_startbrief`
- File: [src/main.py](/opt/synapse/src/main.py:15414)
- Route: `GET /session/brief`
- Handler: `session_brief`
- File: [src/main.py](/opt/synapse/src/main.py:15303)
- Supporting functions:
  - `_get_latest_session_id`
  - `_load_recent_session_summaries`
  - `_build_startbrief_entity_hints_from_profiles`
  - `select_startbrief_ingredients`
  - `compose_ops_context`
  - `_build_recent_high_signal_changes`
  - `_compose_structured_handover_text`
  - `_get_session_ingest_freshness`
- Tests:
  - [tests/test_session_startbrief.py](/opt/synapse/tests/test_session_startbrief.py:1)
  - [tests/test_derived_endpoint_golden.py](/opt/synapse/tests/test_derived_endpoint_golden.py:1)
  - [tests/test_internal_auth_recovery.py](/opt/synapse/tests/test_internal_auth_recovery.py:1)

### Inputs

`GET /session/startbrief`

- `tenantId`
- `userId`
- `now`
- `sessionId`
- `personaId`
- `timezone`

`GET /session/brief`

- `tenantId`
- `userId`
- `now`

### How V2 determined last session and time gap

Current `session_startbrief` logic:

- resolved `session_id` from request or `_get_latest_session_id`
- loaded recent summaries from `_load_recent_session_summaries`
- chose `last_activity_time` as the newest summary `created_at` not later than `reference_now`
- computed:
  - hours since last spoke
  - minutes since last spoke

`time_gap_human` rules:

- if `hours > 0`: `"{hours} hours since last spoke"`
- else: `"{minutes} minutes since last spoke"`

`session_brief` used a similar approach over recent summaries and built:

- `timeGapDescription`
- `timeOfDayLabel`

### How it decided continuation vs today vs yesterday vs multi-day

Functionally, startup depth was determined by `gap_minutes`:

- `<= 30` -> `continuation`
- `<= 360` -> `today`
- `<= 1440` -> `yesterday`
- else -> `multi_day`

This logic appears both in `session_startbrief` and in `select_startbrief_ingredients`.

### What recent data it used

Primary sources:

- `session_summaries` via `fetch_recent_session_summaries`
- fallback to `session_classifications` via `_load_recent_session_summaries_from_classifications`
- top loops from `loops.get_top_loops_for_startbrief`
- `identity_profile`
- `entity_profiles`
- `daily_analysis` fields in `ops_context`
- ingest freshness via outbox state

Important implementation detail:

- current `session_startbrief` is “strict cutover source: Postgres-derived session classifications only”
- it no longer uses Graphiti search as startup authority

### How startbrief chose summaries and loops

#### Summaries

`select_startbrief_ingredients`:

- considered recent summaries, with focus on last 24h when possible
- scored each summary by:
  - recency
  - salience
  - importance
  - confidence
  - contradiction penalty
- selected up to 2 summaries
- minimum score gate later enforced in `session_startbrief`:
  - `STARTBRIEF_MIN_CLAIM_SCORE = 0.50`

Summary importance specifically used:

- recurrence across recent summaries
- overlap with active loop texts

#### Loops

`select_startbrief_ingredients` filtered out:

- low-value loops
- weak commitments that were not durable

Then scored loops by:

- recency
- salience
- importance
- confidence
- contradiction penalty

Minimum loop score gate:

- `STARTBRIEF_MIN_LOOP_SCORE = 0.55`

Top-k:

- `STARTBRIEF_TOPK_CLAIMS = 2`
- `STARTBRIEF_TOPK_LOOPS = 2`

### What open loops were included

There were two startup surfaces for loop-like state:

#### 1. `ops_context.top_loops_today`

Built by `compose_ops_context`

Returned per loop:

- `text`
- `type`
- `time_horizon`
- `salience`

#### 2. `ops_context.recent_changes`

Built by `_build_recent_high_signal_changes`

Used:

- high-signal summary facts
- top loops
- optional loop reason text

Also present:

- `ops_context.waiting_on`, currently returned as `[]`

### What entity hints and profiles were included

Current startbrief behavior:

- `entity_hints` built from active `entity_profiles`
- `entity_profiles` returned as an empty legacy compatibility array

Entity hint fields:

- `entityId`
- `name`
- `type`
- `role`
- `importance`
- `salience`
- `lastSeenAt`
- `source`
- `confidence`
- `updatedAt`

Selection logic:

- active only
- ordered by `salience_score`, then `last_updated_at`
- excluded assistant/system entities
- required serving content

### What fields Sophie actually received

Current `SessionStartBriefResponse` fields:

- `handover_text`
- `narrative` -> always `None` in current route
- `handover_depth`
- `time_context`
- `resume`
- `ops_context`
- `evidence`
- `entity_hints`
- `entity_profiles` -> legacy compatibility, currently empty

`time_context` currently included:

- `local_time`
- `time_of_day`
- `gap_minutes`
- `sessions_today`
- `first_session_today`

Notably:

- current `time_context` does not return `time_gap_human` directly
- that string is used to build the prose, and logged, but not emitted as a first-class field

`resume` currently included:

- `use_bridge`
- `bridge_text`

Important implementation detail:

- in current `session_startbrief`, `resume_use_bridge` is initialized `False`
- `resume_bridge_text` is initialized `None`
- the current code path does not set them later
- so the live route currently returns:
  - `resume.use_bridge = false`
  - `resume.bridge_text = null`

This is a significant difference from older expectations and some stale tests/scripts.

### Anti-drift and startup behavior in tests

Tests in [tests/test_session_startbrief.py](/opt/synapse/tests/test_session_startbrief.py:1) assert:

- continuation depth within short gap windows
- no advice words like `should`, `try`, `maybe`
- no hallucinated continuity
- no steering note leakage into `handover_text`
- no bureaucratic phrasing like timestamps in prose
- no “you felt / you seemed” psychologizing
- placeholder normalization from bad summary node shapes
- evidence IDs retained even when summary content is empty

Golden test in [tests/test_derived_endpoint_golden.py](/opt/synapse/tests/test_derived_endpoint_golden.py:1) asserts:

- `handover_depth`
- presence of entity hints
- `ops_context` containing recent changes
- derived-only provenance assumptions

Important drift between tests/scripts and implementation:

- some tests still stub `_generate_startbrief_bridge_llm`
- current `session_startbrief` does not call `_generate_startbrief_bridge_llm`
- [scripts/contract_startbrief_memory.sh](/opt/synapse/scripts/contract_startbrief_memory.sh:1) expects older keys like `bridgeText` and `items`
- current route returns `handover_text`, `resume`, `ops_context`, `entity_hints`, `evidence`

### Useful behavior versus legacy cruft

Useful:

- compact deterministic handover text
- strict startup anti-drift guardrails
- startup depth classification
- top loops and recent changes
- entity hints
- evidence/freshness/debug bundle

Legacy or bloated:

- `entity_profiles` in the response
- `narrative`
- stale bridge/Graphiti assumptions in tests/scripts
- duplicated startup surface via `/session/brief`

### Must-preserve behaviors for parity

- time-gap aware startup depth
- deterministic handover text constrained against advice and hallucinated continuity
- use of recent summaries plus top loops, not loops alone
- entity hints in startup
- evidence/freshness traceability for startup packet construction

---

## C. Open Loops

### Routes and files inspected

- Route: `GET /memory/loops`
- Handler: `memory_loops`
- File: [src/main.py](/opt/synapse/src/main.py:14038)
- Loop service: `get_top_loops_for_startbrief`
- File: [src/loops.py](/opt/synapse/src/loops.py:346)

### How loops were stored and retrieved

The `loops` table stored:

- `type`
- `status`
- `text`
- `confidence`
- `salience`
- `time_horizon`
- `due_date`
- `entity_refs`
- `tags`
- `last_seen_at`
- `metadata`

`metadata` was important for:

- `domain`
- `importance`
- `urgency`

### How top loops were ranked

`get_top_loops_for_startbrief` in `src/loops.py`:

1. applied staleness policy first
2. fetched candidate rows ordered by:
   - `salience desc`
   - `last_seen_at desc`
   - `updated_at desc`
3. mapped rows into `Loop` models
4. re-sorted using `_loop_priority_score`

`_loop_priority_score`:

- `salience * 2.0`
- `importance * 2.0`
- `urgency * 1.5`
- `domain_bonus = 0.1` for non-`general`
- `review_penalty = -1.0` if `status == "needs_review"`

So startbrief loop ranking was not simple recency. It used:

- salience
- importance
- urgency
- status penalty
- minor domain bonus

### How loops entered session startup

`session_startbrief` called `loops.get_top_loops_for_startbrief(... limit=5 ...)`

Those loop rows then fed:

- `select_startbrief_ingredients`
- `compose_ops_context`
- `_build_recent_high_signal_changes`
- final `ops_context.top_loops_today`
- final deterministic handover text

### What `/memory/loops` returned

Fields returned in `MemoryLoopItem`:

- `id`
- `type`
- `text`
- `status`
- `salience`
- `timeHorizon`
- `dueDate`
- `lastSeenAt`
- `domain`
- `importance`
- `urgency`
- `tags`
- `personaId`

Important behavior:

- `personaId` query param was accepted but ignored
- optional `domain` filtering happened after retrieval

### Must-preserve behaviors for parity

- loops must remain durable cross-session state
- startup must consume ranked loops, not all loops
- ranking must reflect salience + importance + urgency, not only recency
- startup loop selection must suppress low-value loops

---

## D. User Model / Entity Profile

### Routes and files inspected

- Route: `GET /user/model`
- Handler: `get_user_model`
- File: [src/main.py](/opt/synapse/src/main.py:14106)
- Route: `POST /entities/profile`
- Handler: `entities_profile`
- File: [src/main.py](/opt/synapse/src/main.py:16090)
- Startup entity hint builder:
  - `_build_startbrief_entity_hints_from_profiles`
- Tests:
  - [tests/test_entities_profile.py](/opt/synapse/tests/test_entities_profile.py:1)

### What `/user/model` returned

Model: `UserModelResponse`

Fields:

- `tenantId`
- `userId`
- `model`
- `completenessScore`
- `metadata`
- `version`
- `exists`
- `createdAt`
- `updatedAt`
- `lastSource`

Construction:

- `_resolve_tenant_scope`
- `_fetch_user_model_rows_for_scope`
- `_hydrate_user_model_narratives`
- `_build_user_model_staleness_metadata`
- `_compute_domain_completeness`

So `/user/model` returned:

- one large structured blob
- plus freshness / completeness metadata

### What `/entities/profile` returned

Model: `EntityProfileResponse`

Fields:

- `entity`
- `keyFacts`
- `openLoops`
- `provenance`

`entity` included:

- `entityId`
- `canonicalName`
- `type`
- `aliases`
- `summary`
- `role`
- `relationship`
- `importance`
- `salience`
- `confidence`
- `recency.lastSeenAt`
- `recency.daysSinceSeen`
- `recency.firstSeenAt`

`keyFacts` included:

- `text`
- `confidence`
- `validAt`
- `invalidAt`

`openLoops` included:

- `id`
- `type`
- `text`
- `status`
- `salience`

### How entities were linked to facts and loops

Entity profile flow:

1. resolved canonical candidate with `_resolve_canonical_entity_candidate`
2. pulled role grounding with `_pg_get_entity_role_grounding`
3. fetched exact factual rows with `_pg_get_entity_facts_exact`
4. expanded with semantic-ish `_pg_search_facts`
5. filtered and deduped facts
6. scanned top loops and kept those whose text overlapped with entity terms

Important detail:

- entity-to-loop linking was textual overlap, not a fully normalized relationship graph in the serving path

### Useful versus bloated

Useful:

- entity card shape
- recency fields
- key facts
- open loops for a specific entity
- role / relationship labels

Bloated or weak:

- `/user/model` was too monolithic
- user-model hints were useful but the full `model` blob was broad and mixed
- entity role fallback could come from user model, not only evidence-backed factual state
- provenance sources were useful, but not detailed evidence refs

### Must-preserve behaviors for parity

- entity card must combine:
  - key facts
  - role/relationship
  - recency
  - related loops
- startup should keep lightweight entity hints
- profile freshness/completeness metadata mattered more than narrative prose blobs

---

## E. Day Brief / Daily Agenda

### Routes and files inspected

- Route: `GET /day/brief`
- Handler: `get_day_brief`
- Service: `buildDayBrief`
- File: [src/day_brief.py](/opt/synapse/src/day_brief.py:1)
- Route: `GET /actions/daily-agenda`
- Handler: `get_daily_agenda`
- Service: `listDailyAgenda`
- File: [src/main.py](/opt/synapse/src/main.py:14965)
- Tests:
  - [tests/test_day_brief.py](/opt/synapse/tests/test_day_brief.py:1)
  - [tests/test_action_state_mvp.py](/opt/synapse/tests/test_action_state_mvp.py:1)

### What `GET /day/brief` returned

Fields:

- `date`
- `timezone`
- `generatedAt`
- `calendarEvents`
- `remindersToday`
- `dueToday`
- `overdue`
- `counts`
- `suggestedFocus`
- `pressureLevel`
- `sourceFreshness`

Its job:

- query confirmed `calendar_items` overlapping the local day
- call `listDailyAgenda`
- combine the results into one deterministic daily packet

### What `GET /actions/daily-agenda` returned

Model: `DailyAgendaResponse`

Fields:

- `date`
- `timezone`
- `dueToday`
- `remindersToday`
- `overdue`
- `pendingCandidates`
- `counts`
- `suggestedActions`

### What deterministic logic was used

#### Day brief

`buildDayBrief` derived:

- `pressureLevel`
  - `high` if `overdue >= 3` or total event/task/reminder load `>= 8`
  - `medium` if any overdue or total load `>= 4`
  - else `low`

- `suggestedFocus`
  - `clear_overdue` if overdue exists
  - `protect_calendar_blocks` if calendar events exist
  - `finish_due_items` if due items exist
  - `handle_reminders` if reminders exist
  - fallback `light_planning`

#### Daily agenda

`listDailyAgenda` grouped:

- due action items today
- reminder action items today
- overdue pending items
- pending actionable candidates

Both endpoints were deterministic aggregations over canonical action/calendar state plus candidates.

### Must-preserve behaviors for parity

- one daily view must combine schedule and task state
- overdue items must affect pressure/focus
- due/reminder grouping must remain deterministic
- pending candidates must still be visible somewhere in day planning

---

## F. Session Ingest

### Routes and files inspected

- Route: `POST /session/ingest`
- Handler: `ingest_session`
- File: [src/main.py](/opt/synapse/src/main.py:16530)
- Route: `POST /ingest`
- Handler: `ingest`
- File: [src/main.py](/opt/synapse/src/main.py:13117)
- Session services:
  - `session.enqueue_session_ingest`
  - outbox drain helpers in `src/session.py`
- Tests:
  - [tests/test_session_ingest.py](/opt/synapse/tests/test_session_ingest.py:1)
  - [tests/test_v2_dual_write_ingest.py](/opt/synapse/tests/test_v2_dual_write_ingest.py:1)

### Where the full transcript was stored

Full-session ingest:

- `session_transcript`

Also dual-written or normalized into:

- `sessions_v2`
- `turns_v2`

Turn-level ingest:

- session buffer path
- dual-write support into `turns_v2`

### What was queued for background processing

`POST /session/ingest`:

- enqueued full transcript work through `session.enqueue_session_ingest`
- created outbox rows in `graphiti_outbox`
- tests confirm `job_type = 'session_raw_episode'`

The payload included:

- `tenant_id`
- `user_id`
- `session_id`
- transcript messages
- reference time

### How idempotency was handled

#### Session ingest

Tests confirm outbox dedupe key:

- `session_ingest_raw:{tenant}:{user}:{session_id}`

Repeated `POST /session/ingest` with the same session:

- did not create duplicate pending outbox rows

#### Turn ingest

Tests confirm:

- `turn_ingest_idempotency`
- duplicate `POST /ingest` requests deduped into one `turns_v2` row
- out-of-order inserts were normalized deterministically

### What `/session/ingest` returned

- `status`
- `sessionId`
- `graphitiAdded`

Behavior:

- `status="ingested"` if any valid message text/role pairs exist
- `status="skipped_empty_transcript"` for empty transcripts
- `graphitiAdded` remained `false`

### What `/ingest` returned

Stable observed behavior from tests:

- `status="ingested"`

The model still allowed:

- `sessionId`
- `identityUpdates`
- `loopsDetected`
- `loopsCompleted`
- `graphitiAdded`

But those were not the core observed behavior in current tests.

### Must-preserve behaviors for parity

- transcript persistence before downstream derivation
- idempotent retry behavior
- durable outbox enqueue
- session-level ingest should remain the canonical full-transcript path

---

# 3. V3 Parity Checklist

This section is a parity checklist only: behaviors that must exist before a replacement can credibly claim to match V2.

## Recall parity

- [ ] exact recall returns only evidence-backed factual claims
- [ ] episodic recall uses embedding-backed retrieval, not just latest-session fallback
- [ ] episodic recall also uses lexical overlap and recency
- [ ] hybrid recall preserves lane distinctions
- [ ] continuity recall remains clearly marked derived
- [ ] returned recall items include evidence/source references
- [ ] `focusQuery` is either intentionally supported or intentionally removed, not silently ignored
- [ ] `includeContext` is either truly supported or explicitly deprecated

## Startup / handover parity

- [ ] startup computes last activity and gap correctly
- [ ] startup distinguishes continuation / today / yesterday / multi-day
- [ ] startup uses recent summaries plus top loops
- [ ] startup handover text is compact and anti-drift
- [ ] steering note does not leak into prose
- [ ] startup includes entity hints
- [ ] startup exposes evidence/freshness metadata

## Open loop parity

- [ ] loops remain durable across sessions
- [ ] top loops are ranked by more than recency
- [ ] low-value loops are filtered before startup surfacing
- [ ] loop domain / importance / urgency survive retrieval

## Entity / profile parity

- [ ] durable profile endpoint exposes freshness/completeness
- [ ] entity card returns key facts, relationship/role, recency, and related loops
- [ ] startup uses lightweight entity hints instead of heavy entity blobs

## Day brief parity

- [ ] daily view combines calendar + actions
- [ ] due/reminders/overdue slices are deterministic
- [ ] pressure level reacts to workload and overdue state
- [ ] suggested focus reacts to actual day state
- [ ] pending candidates are visible somewhere in day planning

## Session ingest parity

- [ ] full transcript is durably stored
- [ ] session ingest is idempotent
- [ ] background/outbox processing is queued exactly once per session
- [ ] turn-level retries do not duplicate rows
- [ ] out-of-order turn arrival is normalized deterministically

---

# 4. V3 Test Recommendations

These are concrete parity tests implied by V2 behavior.

## Recall tests

- `exact` recall must drop claims with no evidence rows.
- `hybrid` recall must return factual + episodic + continuity items with clear lane labels.
- episodic recall for a continuation-style query must prefer a semantically similar older session over a merely recent unrelated one.
- continuity recall must not leak canonical factual rows into the continuity lane.
- `includeContext=true` must either produce real extra behavior or an explicit compatibility notice.
- `focusQuery` must not be silently ignored.

## Startup tests

- a gap under 30 minutes should produce `continuation`.
- a gap under 6 hours should produce `today`.
- a gap between 6 and 24 hours should produce `yesterday`.
- startup prose must not contain advice terms like `should`, `try`, `maybe`.
- steering note must appear in `ops_context` but not in `handover_text`.
- placeholder summary node fields must not leak into prose.
- startup must include entity hints when active entity profiles exist.

## Open-loop tests

- a high-salience, high-importance loop must outrank a merely recent low-value loop.
- loops with `needs_review` should be penalized versus active loops.
- domain-filtered `/memory/loops` responses must only contain matching-domain loops.

## Entity/profile tests

- entity profile must return canonical name, aliases, key facts, and open loops.
- unrelated loops must not be attached to an entity profile.
- stale or assistant/system entities must not appear in startup entity hints.

## Day brief tests

- confirmed calendar items on the target day must appear in day brief.
- overdue tasks must raise `pressureLevel`.
- no workload should produce `suggestedFocus=["light_planning"]`.
- due tasks and reminders must remain distinct slices.

## Ingest tests

- repeated `POST /session/ingest` for the same session must produce one pending outbox job.
- repeated `POST /ingest` for the same turn must produce one `turns_v2` row.
- out-of-order turn ingest must normalize turn ordering deterministically.
- empty transcript ingest must return `skipped_empty_transcript` and avoid queuing raw-episode work.

---

# 5. Bottom Line

Synapse V2’s real memory and startup behavior was stronger than its endpoint sprawl suggested.

The core V2 behaviors were:

- exact recall as evidence-backed fact retrieval
- episodic recall as embedding-assisted transcript recall
- continuity recall as explicitly derived memory
- startup as a compact synthesis of recent summaries, top loops, entity hints, and freshness state
- daily planning as deterministic aggregation
- session ingest as durable, idempotent transcript capture plus queued background work

The main liabilities were not that these behaviors were weak. The liabilities were:

- compatibility wrappers
- duplicated endpoint surfaces
- stale tests/scripts in places
- broad monolithic profile shapes
- unsurfaced internal audit signals like episodic weak recall

Those liabilities should not obscure what V2 genuinely already did well.

