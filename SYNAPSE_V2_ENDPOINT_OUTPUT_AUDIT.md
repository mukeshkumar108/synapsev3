# Synapse V2 Endpoint Output Audit

This document audits what the old Synapse HTTP endpoints actually returned, how those responses were assembled, and which parts are worth preserving in a Cortex V3 rebuild.

Scope:

- Documentation only.
- No claim that V2 was architecturally correct.
- Emphasis on actual route behavior in code, response models, tests, and service functions.

Conventions:

- Paths and function names are quoted exactly where possible.
- If the requested endpoint name does not exactly exist in V2, that mismatch is called out explicitly.
- “Preserve” means preserve behavior or semantics, not route shape or storage design.

---

# 1. Executive summary

Synapse V2 exposed too many overlapping serving endpoints. The useful behavior was real, but the serving contract sprawled across:

- retrieval endpoints
- startup/handover endpoints
- day-planning endpoints
- candidate review endpoints
- action/calendar CRUD
- legacy and compatibility surfaces

The best parts of V2 were:

- evidence-backed factual recall
- explicit open-loop retrieval
- compact startup packets with strict anti-drift prose
- deterministic day-planning aggregation
- canonical action and calendar item state machines
- useful provenance, confidence, and lifecycle metadata

The worst parts were:

- legacy compatibility fields kept in live responses long after serving authority had moved
- multiple endpoints returning overlapping slices of the same operational state
- monolithic user-model and startbrief assembly
- candidate review surfaces that leaked staging-table structure into the API
- Graphiti/postgres continuity mixed into endpoint semantics and comments even after cutovers

Recommended V3 direction:

- collapse V2 endpoint sprawl into a small number of packets:
  - startup packet
  - recall packet
  - profile packet
  - day-planning packet
  - canonical action/event CRUD
  - ingest

---

# 2. Requested Endpoint Map Vs Actual V2 Routes

Two requested endpoint names do not exist exactly as written in V2:

| Requested | Actual V2 route |
| --- | --- |
| `GET /candidates/review-queue` | `GET /review-queue` |
| `GET /candidates/daily` | `GET /daily-candidates` |

Everything else in the request maps directly to an actual route.

---

# 3. Endpoint Audits

## 3.1 `POST /memory/query`

- Route file path: `src/main.py`
- Handler: `memory_query`
- Response model: `MemoryQueryResponse`

### Request

- Body model: `MemoryQueryRequest`
- Fields:
  - `tenantId`
  - `userId`
  - `query`
  - `limit`
  - `memoryIntent`: `exact|episodic|hybrid`
  - `referenceTime`
  - `includeContext`
  - `focusQuery`

### How it was built

- This route is explicitly a legacy compatibility adapter.
- Code path:
  - `memory_query`
  - `_memory_query_legacy_adapter`
  - `_memory_query_v2_service`
- It no longer used the old mixed-authority retrieval helpers.
- Tests in [tests/test_t11_legacy_adapter.py](/opt/synapse/tests/test_t11_legacy_adapter.py:1) confirm the adapter blocks the old retrieval path and maps only from V2 lanes.

### Internal tables/services used

- V2 service lanes, not direct legacy mixed retrieval
- factual lane: canonical claims/evidence-backed rows
- episodic lane: episodic recall items
- continuity lane: derived continuity items
- rollout/shadow helpers: `RolloutController`, shadow-diff metadata

### Actual response shape

Primary fields actually used:

- `facts`
- `factItems`
- `entities`
- `episodes`
- `metadata`

Legacy optional fields still on the model but not the main serving payload:

- `openLoops`
- `commitments`
- `contextAnchors`
- `userStatedState`
- `currentFocus`
- `recallSheet`
- `supplementalContext`

Representative response from adapter tests:

```json
{
  "facts": [
    "Ashley relationship status: dating"
  ],
  "factItems": [
    {
      "text": "Ashley relationship status: dating",
      "source": "canonical_claims",
      "sourceTenant": "default"
    }
  ],
  "entities": [],
  "episodes": [],
  "metadata": {
    "adapter": {
      "mode": "t11_legacy_to_v2_only",
      "legacyMixedAuthorityFallback": false
    }
  }
}
```

### Returned content type

- raw facts: yes
- synthesized narrative: no
- open loops: not in the active path
- entity hints: effectively no
- user model/profile: no
- day planning data: no
- debug/evidence: some evidence inside `factItems` and `episodes`; rollout metadata in `metadata`

### Useful vs cruft

Useful:

- evidence-backed factual recall
- explicit episodic items
- lane-aware metadata

Cruft:

- legacy optional fields on `MemoryQueryResponse`
- compatibility-oriented metadata
- dual vocabulary: `memoryIntent` on legacy route vs `lane` in V2 service

### Preserve in V3

- one recall endpoint that returns typed recall items
- evidence-backed factual lane
- separate episodic lane
- explicit classification of derived continuity vs canonical fact

### Discard or simplify

- legacy `MemoryQueryResponse` shell
- unused optional context fields
- adapter/shadow metadata in production serving responses

### V3 replacement

- `POST /v3/recall`
- Return a unified typed list:
  - `fact`
  - `episode`
  - `continuity_note`

---

## 3.2 `GET /user/model`

- Route file path: `src/main.py`
- Handler: `get_user_model`
- Response model: `UserModelResponse`

### Request

- Query params:
  - `tenantId`
  - `userId`
- Header:
  - `x-internal-token`

### How it was built

- `get_user_model`
- `_resolve_tenant_scope`
- `_fetch_user_model_rows_for_scope`
- `_hydrate_user_model_narratives`
- `_build_user_model_staleness_metadata`
- `_compute_domain_completeness`

### Internal tables/services used

- `user_model`
- tenant-scope resolution helpers

### Actual response shape

```json
{
  "tenantId": "default",
  "userId": "u1",
  "model": {},
  "completenessScore": {},
  "metadata": {
    "tenantCanonical": "default",
    "tenantScope": ["default"],
    "sourceTenant": "default"
  },
  "version": 3,
  "exists": true,
  "createdAt": "2026-05-01T10:00:00+00:00",
  "updatedAt": "2026-05-22T09:00:00+00:00",
  "lastSource": "daily_analysis"
}
```

### Returned content type

- raw facts: indirectly inside `model`
- synthesized narrative: yes, hydrated narratives
- user model/profile: yes
- debug/evidence: freshness and completeness metadata, but not evidence-grounded claims

### Useful vs cruft

Useful:

- durable profile packet
- freshness metadata
- completeness scoring by domain

Cruft:

- monolithic `model` blob
- tenant-scope fanout behavior in the serving contract
- narrative hydration mixed into the endpoint
- weak evidence semantics inside profile sections

### Preserve in V3

- a durable profile packet
- explicit freshness/completeness metadata

### Discard or simplify

- direct exposure of the old `user_model` blob
- tenant-scope serving semantics
- “hydrate narratives from stored model” behavior

### V3 replacement

- `GET /v3/profile`
- split durable identity from current state instead of one monolith

---

## 3.3 `GET /memory/loops`

- Route file path: `src/main.py`
- Handler: `memory_loops`
- Response model: `MemoryLoopsResponse`

### Request

- Query params:
  - `tenantId`
  - `userId`
  - `limit`
  - `personaId`
  - `domain`

### How it was built

- `loops.get_top_loops_for_startbrief`
- filtered in-handler by optional `domain`

Important behavior:

- `personaId` was accepted for backward compatibility but ignored for retrieval.

### Internal tables/services used

- loop retrieval service from `src/loops.py`
- loop metadata fields such as `domain`, `importance`, `urgency`

### Actual response shape

```json
{
  "items": [
    {
      "id": "loop-id",
      "type": "thread",
      "text": "Finish migration rollout",
      "status": "active",
      "salience": 6,
      "timeHorizon": "today",
      "dueDate": null,
      "lastSeenAt": "2026-05-22T09:00:00Z",
      "domain": "work",
      "importance": 8,
      "urgency": 7,
      "tags": []
    }
  ],
  "metadata": {
    "count": 1,
    "limit": 10,
    "sort": "priority_desc",
    "domainFilter": "work",
    "personaId": null,
    "scope": "user"
  }
}
```

### Returned content type

- open loops: yes
- debug/evidence: minimal metadata only

### Useful vs cruft

Useful:

- explicit loop packet
- salience/time horizon/status fields

Cruft:

- persona compatibility parameter that does nothing
- separate endpoint for a slice that could live inside startup/day packets

### Preserve in V3

- loop object semantics
- domain/time-horizon/status fields

### Discard or simplify

- standalone endpoint if loops are already included in startup/day packets
- `personaId` compatibility behavior

### V3 replacement

- embed loops into:
  - `GET /v3/startup-packet`
  - `GET /v3/day`

---

## 3.4 `GET /session/startbrief`

- Route file path: `src/main.py`
- Handler: `session_startbrief`
- Response model: `SessionStartBriefResponse`

### Request

- Query params:
  - `tenantId`
  - `userId`
  - `now`
  - `sessionId`
  - `personaId`
  - `timezone`
- Header:
  - `x-internal-token`

### How it was built

Large composite route. Key helpers:

- `_get_latest_session_id`
- `_load_recent_session_summaries`
- `loops.get_top_loops_for_startbrief`
- `_generate_startbrief_bridge_llm`
- `_realize_startbrief_from_selected_evidence`
- daily analysis lookup
- ingest freshness lookup
- entity-hint assembly

Tests in [tests/test_session_startbrief.py](/opt/synapse/tests/test_session_startbrief.py:1) show the intended contract:

- strict word caps
- anti-advice language
- anti-hallucinated continuity
- steering note excluded from prose

### Internal tables/services used

- `session_summaries`
- `daily_analysis`
- loop service
- session transcript lookup
- pending ingest freshness helpers
- entity-hint/profile assembly

### Actual response shape

Top-level fields:

- `handover_text`
- `narrative`
- `handover_depth`
- `time_context`
- `resume`
- `ops_context`
- `evidence`
- `entity_hints`
- `entity_profiles`

Representative shape:

```json
{
  "handover_text": "You last spoke with the user earlier today. The conversation today stayed focused on finishing the portfolio update.",
  "handover_depth": "today",
  "time_context": {
    "time_of_day": "morning",
    "time_gap_human": "2 hours since last spoke"
  },
  "resume": {
    "use_bridge": true,
    "bridge_text": "Earlier today they tightened the thread and kept momentum on finishing the portfolio update."
  },
  "ops_context": {
    "top_loops_today": [],
    "steering_note": "Keep scope narrow for this sprint."
  },
  "evidence": {},
  "entity_hints": [],
  "entity_profiles": []
}
```

### Returned content type

- synthesized narrative: yes, but tightly constrained
- open loops: yes, in `ops_context`
- entity hints: yes
- day planning data: partially
- debug/evidence: yes, especially freshness/evidence substructures

### Useful vs cruft

Useful:

- startup packet concept
- strict anti-drift handover prose
- `handover_depth`
- `resume`
- `ops_context`
- evidence/freshness awareness
- entity hints as lightweight, not heavy profiles

Cruft:

- `entity_profiles` is marked as legacy compatibility
- too much responsibility in one route
- old daily-analysis/user-model influence baked into one packet

### Preserve in V3

- this should remain a first-class packet
- preserve compact handover prose constraints
- preserve loops + evidence freshness + entity hints

### Discard or simplify

- legacy `entity_profiles`
- monolithic assembly in one route module
- overly broad embedded ops/narrative baggage

### V3 replacement

- `GET /v3/startup-packet`

---

## 3.5 `GET /session/brief`

- Route file path: `src/main.py`
- Handler: `session_brief`
- Response model: `SessionBriefResponse`

### Request

- Query params:
  - `tenantId`
  - `userId`
  - `now`

### How it was built

- `_load_recent_session_summaries`
- `_build_handover_packet`
- `_select_facts`
- `_build_structured_sheet`
- `_get_latest_session_id`

The docstring explicitly says this is a compatibility session brief.

### Internal tables/services used

- derived postgres summaries and handover packet
- living-context and open-thread data via handover packet

### Actual response shape

- `timeGapDescription`
- `timeOfDayLabel`
- `facts`
- `openLoops`
- `commitments`
- `contextAnchors`
- `currentFocus`
- `briefContext`
- `narrativeSummary`
- `activeLoops`
- `currentVibe`

Representative shape:

```json
{
  "timeGapDescription": "3 hours since last spoke",
  "timeOfDayLabel": "morning",
  "facts": ["They reviewed the same thread and narrowed the next focus."],
  "openLoops": ["Confirm progress next session"],
  "commitments": [],
  "contextAnchors": {
    "timeOfDayLabel": "morning",
    "sessionId": "session-123",
    "source": "derived_postgres"
  },
  "currentFocus": "Finish portfolio update",
  "briefContext": "Facts: ...",
  "narrativeSummary": [],
  "activeLoops": [
    {
      "description": "Confirm progress next session",
      "status": "unresolved"
    }
  ],
  "currentVibe": {
    "timeOfDayLabel": "morning",
    "source": "derived_postgres"
  }
}
```

### Returned content type

- synthesized narrative: yes
- open loops: yes
- context anchors: yes

### Useful vs cruft

Useful:

- compact structured recap
- facts/open loops/current focus slice

Cruft:

- large legacy shape overlaps heavily with `startbrief`
- weak field semantics: `temporalVibe`, `currentVibe`, `energyHint`
- compatibility surface with too many narrative-era labels

### Preserve in V3

- nothing as a separate endpoint
- some summary fields can feed the startup packet

### Discard or simplify

- route itself
- nearly all legacy cosmetic fields

### V3 replacement

- subsumed by `GET /v3/startup-packet`

---

## 3.6 `GET /analysis/daily`

- Route file path: `src/main.py`
- Handler: `get_daily_analysis`
- Response model: `DailyAnalysisResponse`

### Request

- Query params:
  - `tenantId`
  - `userId`
  - `date`

### How it was built

- direct read from `daily_analysis`
- latest row if `date` absent
- requested date if provided

### Internal tables/services used

- `daily_analysis`

### Actual response shape

- `analysisDate`
- `themes`
- `scores`
- `steeringNote`
- `confidence`
- `exists`
- timestamps
- `metadata`

When missing, it returns an empty successful packet rather than 404.

### Returned content type

- synthesized narrative: yes, via `steeringNote`
- user model/profile: indirectly
- debug/evidence: no direct evidence

### Useful vs cruft

Useful:

- explicit daily themes
- confidence
- steering note as a private control signal

Cruft:

- separate endpoint for one nightly synthesis artifact
- weak grounding
- unclear authority versus startup/day packet

### Preserve in V3

- steering-note concept
- lightweight daily theme labels if proven useful

### Discard or simplify

- standalone endpoint unless operational consumers truly need it

### V3 replacement

- fold into `GET /v3/startup-packet` and `GET /v3/day`

---

## 3.7 `GET /signals/pack`

- Route file path: `src/main.py`
- Handler: `signals_pack`
- Builder: `_build_signals_pack`

### Request

- Query params:
  - `tenantId`
  - `userId`
  - `sessionId`
  - `now`
  - `capacity`
  - `tacticAppetite`
- Header:
  - `x-internal-token`

### How it was built

- `_build_signals_pack`
- loop retrieval
- recent summary nodes
- `user_model`
- `daily_analysis`
- habit daily log state

Tests in [tests/test_signals_pack.py](/opt/synapse/tests/test_signals_pack.py:1) define the real contract better than the model layer.

### Internal tables/services used

- `user_model`
- `daily_analysis`
- loop retrieval
- recent session summary retrieval
- habits daily-log tables

### Actual response shape

Top-level shape from tests:

```json
{
  "generated_at": "2026-05-22T09:00:00Z",
  "session_id": "session-123",
  "classes": {
    "identity": [],
    "trajectory": [],
    "today": [],
    "open_loops": [],
    "state": [],
    "relationships": [],
    "habits": []
  },
  "debug": {
    "counts": {},
    "rejection_reasons": {}
  }
}
```

Per-signal fields validated in tests:

- `id`
- `class`
- `text`
- `confidence`
- `salience`
- `sensitivity`
- `recency_ts`
- `source`
- optionally `surface_policy`

Special behavior:

- non-habit classes capped at 3 items
- high sensitivity can set `surface_policy="steer_only"`

### Returned content type

- synthesized narrative: no
- open loops: yes
- user model/profile: indirectly
- debug/evidence: yes, in `debug`

### Useful vs cruft

Useful:

- compact steering/surfacing signal pack
- sensitivity-aware signals
- per-class caps

Cruft:

- too many class buckets for a stable external contract
- heavy debug data mixed into default response
- weak distinction between end-user serving and internal steering

### Preserve in V3

- signal pack concept
- sensitivity labels
- `surface_policy`

### Discard or simplify

- public taxonomy sprawl
- mandatory debug in primary surface

### V3 replacement

- `GET /v3/surfacing-signals`
- optional `include_debug=true`

---

## 3.8 `GET /day/brief`

- Route file path: `src/main.py`
- Handler: `get_day_brief`
- Service: `buildDayBrief`

### Request

- Query params:
  - `tenantId`
  - `userId`
  - `date`
  - `timezone`
- Header:
  - `x-internal-token`

### How it was built

- deterministic composition
- confirmed calendar events for the day
- `listDailyAgenda` for action slices
- pressure/focus derived in code

### Internal tables/services used

- `calendar_items`
- `action_items`
- `actionable_candidates` via `listDailyAgenda`

### Actual response shape

From `src/day_brief.py`:

```json
{
  "date": "2026-05-01",
  "timezone": "UTC",
  "generatedAt": "2026-05-01T07:00:00+00:00",
  "calendarEvents": [],
  "remindersToday": [],
  "dueToday": [],
  "overdue": [],
  "counts": {
    "calendarEvents": 0,
    "dueToday": 0,
    "remindersToday": 0,
    "overdue": 0
  },
  "suggestedFocus": ["light_planning"],
  "pressureLevel": "low",
  "sourceFreshness": {
    "mode": "on_demand",
    "calendarItemsLatestUpdatedAt": null,
    "actionItemsLatestUpdatedAt": null,
    "generatedAt": "2026-05-01T07:00:00+00:00",
    "cached": false
  }
}
```

### Returned content type

- day planning data: yes
- action/calendar records: yes
- debug/evidence: freshness only

### Useful vs cruft

Useful:

- deterministic day packet
- `pressureLevel`
- `suggestedFocus`
- freshness metadata

Cruft:

- overlapping with `/actions/daily-agenda`
- no need for separate day packet and daily agenda packet long-term

### Preserve in V3

- this behavior, not this separate route

### Discard or simplify

- duplicate day-planning surfaces

### V3 replacement

- `GET /v3/day`

---

## 3.9 `GET /actions/daily-agenda`

- Route file path: `src/main.py`
- Handler: `get_daily_agenda`
- Response model: `DailyAgendaResponse`
- Service: `listDailyAgenda`

### Request

- Query params:
  - `tenantId`
  - `userId`
  - `date`
  - `timezone`

### How it was built

- deterministic action-state service
- groups action items into:
  - due today
  - reminders today
  - overdue
- also includes pending actionable candidates

### Internal tables/services used

- `action_items`
- `actionable_candidates`

### Actual response shape

- `date`
- `timezone`
- `dueToday`
- `remindersToday`
- `overdue`
- `pendingCandidates`
- `counts`
- `suggestedActions`

### Returned content type

- day planning data: yes
- action records: yes
- candidate review data: yes

### Useful vs cruft

Useful:

- task/reminder grouping
- inclusion of pending candidates

Cruft:

- separate from `/day/brief`
- one more day-slice endpoint

### Preserve in V3

- due/reminder/overdue grouping logic

### Discard or simplify

- standalone endpoint if a unified day packet exists

### V3 replacement

- subsumed by `GET /v3/day`

---

## 3.10 `GET/POST/PATCH/DELETE /actions/items`

- Route file path: `src/main.py`
- Handlers:
  - `create_action_item`
  - `list_action_items`
  - `patch_action_item`
  - `delete_action_item`
- Extra mutation aliases also existed:
  - `PATCH /actions/items/{id}/status`
  - `POST /actions/items/{id}/done`
  - `POST /actions/items/{id}/dismiss`
  - `POST /actions/items/{id}/cancel`

### Request

POST body: `ActionItemCreateRequest`

- `tenantId`
- `userId`
- `kind`
- `title`
- `notes`
- `dueAt`
- `remindAt`
- `recurrenceRule`
- `sourceType`
- `sourceRef`
- `confidence`
- `provenanceSummary`

PATCH body: `ActionItemPatchRequest`

- editable fields plus `actor` and `reason`

DELETE params:

- `tenantId`
- `userId`
- `reason`
- `actor`

GET query params:

- `tenantId`
- `userId`
- filters: `status`, `kind`, `title`, `include_done`, `date_from`, `date_to`, `limit`, `offset`

### How it was built

Service module: `src/action_state.py`

Key functions:

- `createActionItem`
- `listActionItems`
- `updateActionItemStatus`
- `updateActionItem`
- `archiveActionItem`
- `markActionItemDone`
- `dismissActionItem`
- `cancelActionItem`

### Internal tables/services used

- `action_items`
- `action_audit_log`
- `actionable_candidates` for promotion/reconciliation

### Actual response shape

Canonical item shape from `_row_to_action_item`:

```json
{
  "id": "uuid",
  "tenantId": "default",
  "userId": "u1",
  "kind": "todo",
  "title": "Send report",
  "notes": null,
  "status": "pending",
  "dueAt": "2026-05-01T15:00:00+00:00",
  "remindAt": null,
  "recurrenceRule": null,
  "sourceType": "direct_user",
  "sourceRef": null,
  "confidence": null,
  "provenanceSummary": null,
  "createdAt": "2026-05-01T09:00:00+00:00",
  "updatedAt": "2026-05-01T09:00:00+00:00",
  "completedAt": null,
  "dismissedAt": null,
  "cancelledAt": null
}
```

### Returned content type

- action records: yes
- debug/evidence: provenance summary only, no rich evidence packet

### Useful vs cruft

Useful:

- canonical action item object
- explicit lifecycle state machine
- audit log
- provenance and confidence

Cruft:

- too many overlapping mutation endpoints
- `sourceType` taxonomy mixed operational and ingestion concerns
- candidate promotion logic attached closely to CRUD layer

### Preserve in V3

- canonical action object
- status transitions
- audit trail

### Discard or simplify

- alias endpoints `/done`, `/dismiss`, `/cancel`
- candidate-promotion logic in the public CRUD contract

### V3 replacement

- `GET /v3/actions`
- `POST /v3/actions`
- `PATCH /v3/actions/{id}`
- status update as one patch operation, not several alias routes

---

## 3.11 `GET/POST/PATCH/DELETE /calendar/items`

- Route file path: `src/main.py`
- Handlers:
  - `create_calendar_item`
  - `list_calendar_items`
  - `patch_calendar_item`
  - `delete_calendar_item`
- Extra mutation alias:
  - `POST /calendar/items/{id}/cancel`

### Request

POST body: `CalendarItemCreateRequest`

- core fields:
  - `tenantId`
  - `userId`
  - `title`
  - `startsAt`
  - `endsAt`
  - `timezone`
  - `allDay`
  - `location`
  - `participants`
  - `organizer`
  - `rsvpStatus`
  - `status`
  - `sourceKind`
  - `sourceRef`
  - `evidenceRefs`
  - `provenanceSummary`
  - `confidence`
- plus external sync fields

PATCH body: `CalendarItemPatchRequest`

- editable event fields plus `actor` and `reason`

GET filters:

- `tenantId`
- `userId`
- `status`
- `source_kind`
- `external_provider`
- `participant`
- `include_cancelled`
- `include_archived`
- `date_from`
- `date_to`
- `limit`
- `offset`

### How it was built

Service module: `src/calendar_state.py`

Key functions:

- `createCalendarItem`
- `listCalendarItems`
- `updateCalendarItem`
- `archiveCalendarItem`
- `cancelCalendarItem`

### Internal tables/services used

- `calendar_items`
- `calendar_audit_log`

### Actual response shape

Canonical calendar item shape from `_row_to_calendar_item`:

```json
{
  "id": "uuid",
  "tenantId": "default",
  "userId": "u1",
  "title": "Meeting with Sarah",
  "description": null,
  "notes": null,
  "startsAt": "2026-05-05T09:00:00+00:00",
  "endsAt": "2026-05-05T10:00:00+00:00",
  "timezone": "UTC",
  "allDay": false,
  "location": null,
  "participants": [{"name": "Sarah"}],
  "organizer": null,
  "rsvpStatus": "unknown",
  "status": "confirmed",
  "sourceKind": "chat",
  "sourceRef": {"sessionId": "s1"},
  "evidenceRefs": [],
  "provenanceSummary": null,
  "confidence": null,
  "externalProvider": null,
  "externalId": null,
  "externalCalendarId": null,
  "externalEtag": null,
  "externalUpdatedAt": null,
  "syncStatus": "not_synced",
  "recurrenceRule": null,
  "recurrenceParentId": null,
  "dedupeKey": null,
  "metadata": {},
  "createdAt": "2026-05-05T08:00:00+00:00",
  "updatedAt": "2026-05-05T08:00:00+00:00",
  "cancelledAt": null,
  "archivedAt": null
}
```

### Returned content type

- calendar records: yes
- debug/evidence: yes, provenance/evidence refs

### Useful vs cruft

Useful:

- canonical event object
- provenance and evidence refs
- cancellation/archive lifecycle

Cruft:

- external sync fields in the default response for every consumer
- large metadata surface
- alias cancel endpoint

### Preserve in V3

- canonical event object
- evidence refs
- clean lifecycle

### Discard or simplify

- provider sync internals in the default API contract
- separate cancel alias if patch can express it

### V3 replacement

- `GET /v3/events`
- `POST /v3/events`
- `PATCH /v3/events/{id}`

---

## 3.12 `POST /calendar/items/:id/cancel`

- Actual route in FastAPI: `POST /calendar/items/{calendar_item_id}/cancel`
- Route file path: `src/main.py`
- Handler: `cancel_calendar_item`

### Request

- Path param: `calendar_item_id`
- Query params:
  - `tenantId`
  - `userId`
  - `reason`
  - `actor`

### How it was built

- thin wrapper over `cancelCalendarItem`

### Useful vs cruft

Useful:

- explicit user/system cancellation transition

Cruft:

- separate route for a simple status change

### V3 replacement

- use `PATCH /v3/events/{id}` with `status="cancelled"`

---

## 3.13 `POST /session/ingest`

- Route file path: `src/main.py`
- Handler: `ingest_session`
- Response model: `SessionIngestResponse`

### Request

- Body model: `SessionIngestRequest`
- Fields:
  - `tenantId`
  - `userId`
  - `personaId`
  - `sessionId`
  - `startedAt`
  - `endedAt`
  - `messages`

### How it was built

- computes `started_at` and `ended_at` from messages if absent
- converts messages to payload
- calls `session.enqueue_session_ingest`
- writes full transcript and async outbox job

### Internal tables/services used

- `session_transcript`
- `graphiti_outbox`
- `sessions_v2`
- `turns_v2`
- enqueue/drain session services

Tests:

- [tests/test_session_ingest.py](/opt/synapse/tests/test_session_ingest.py:1)
- [tests/test_v2_dual_write_ingest.py](/opt/synapse/tests/test_v2_dual_write_ingest.py:1)

### Actual response shape

```json
{
  "status": "ingested",
  "sessionId": "session-123",
  "graphitiAdded": false
}
```

For empty transcripts:

```json
{
  "status": "skipped_empty_transcript",
  "sessionId": "session-123",
  "graphitiAdded": false
}
```

### Returned content type

- no recall/profile payload
- pure ingest acknowledgement

### Useful vs cruft

Useful:

- full-session durable ingest
- idempotent outbox enqueue
- transcript persistence before downstream processing

Cruft:

- `graphitiAdded` compatibility field is always false

### Preserve in V3

- this should remain the canonical transcript ingest route

### Discard or simplify

- Graphiti-named compatibility fields in response

### V3 replacement

- `POST /v3/session/ingest`

---

## 3.14 `POST /ingest`

- Route file path: `src/main.py`
- Handler: `ingest`
- Response model: `IngestResponse`

### Request

- Body model: `IngestRequest`
- Fields:
  - `tenantId`
  - `userId`
  - `personaId`
  - `role`
  - `text`
  - `timestamp`
  - `sessionId`
  - `metadata`
- Header:
  - `x-internal-token`

### How it was built

- `process_ingest(request, graphiti_client, background_tasks)`
- route docstring says:
  - adds messages to session buffer
  - triggers background janitor

Observed from tests:

- legacy turn-level ingest
- writes/normalizes `turns_v2` in dual-write mode
- idempotency tracked in `turn_ingest_idempotency`
- can bootstrap session-close/session-ingest behavior

### Internal tables/services used

- `session_buffer`
- janitor/outbox/session lifecycle machinery
- `turns_v2`
- `turn_ingest_idempotency`

### Actual response shape

From tests, the stable observed field is:

```json
{
  "status": "ingested"
}
```

The response model still allowed:

- `sessionId`
- `identityUpdates`
- `loopsDetected`
- `loopsCompleted`
- `graphitiAdded`

But those are legacy/optional and not the core modern behavior.

### Returned content type

- ingest acknowledgement only

### Useful vs cruft

Useful:

- low-latency single-turn ingestion if orchestrator truly needs it

Cruft:

- legacy wide `IngestResponse`
- unclear overlap with `/session/ingest`
- old loop/identity update ideas in the response model

### Preserve in V3

- only if there is a real turn-streaming need

### Discard or simplify

- response model extras
- dual role as both session buffer write and pseudo-memory mutation surface

### V3 replacement

- either remove entirely
- or replace with `POST /v3/turns/append` if streaming append is still needed

---

## 3.15 `GET /candidates/review-queue` requested, actual `GET /review-queue`

- Route file path: `src/main.py`
- Handler: `get_review_queue`
- Response model: `ReviewQueueResponse`

### Request

- Query params:
  - `tenantId`
  - `userId`
  - `now`
  - `limit`

### How it was built

- direct lens over `actionable_candidates`
- only status `needs_review`
- grouped by `record_type`

### Internal tables/services used

- `actionable_candidates`

### Actual response shape

- `tenantId`
- `userId`
- `asOf`
- `items`
- `byType`
- `metadata`

Per item shape is `ActionableCandidateItem`. Important fields:

- `id`
- `kind`
- `candidateSubtype`
- `title`
- `summary`
- `dueIso`
- `waitingOn`
- `needsResponse`
- `cadenceText`
- `provenance`
- `confidence`
- `confidenceLabel`
- `status`

Tests confirm `byType` grouping and support-field exposure in [tests/test_daily_candidates_endpoint.py](/opt/synapse/tests/test_daily_candidates_endpoint.py:1).

### Returned content type

- candidate review data: yes

### Useful vs cruft

Useful:

- operator review queue
- `waitingOn`, `needsResponse`, `cadenceText`

Cruft:

- exposes staging-table structure directly
- route name mismatch with conceptual “candidates” namespace
- not an end-user API

### Preserve in V3

- only if there is a human review tool

### Discard or simplify

- candidate-table-shaped public response

### V3 replacement

- internal reviewer surface only, not a primary product API

---

## 3.16 `GET /candidates/daily` requested, actual `GET /daily-candidates`

- Route file path: `src/main.py`
- Handler: `get_daily_candidates`
- Response model: `DailyCandidatesResponse`

### Request

- Query params:
  - `tenantId`
  - `userId`
  - `now`
  - `date`
  - `limit`

### How it was built

- date-scoped lens over `actionable_candidates`
- `_include_candidate_in_daily_lens` determines relevancy
- groups into:
  - `needsReview`
  - `upcomingCommitments`
  - `detected`

### Internal tables/services used

- `actionable_candidates`

### Actual response shape

```json
{
  "tenantId": "t",
  "userId": "u",
  "asOf": "2026-04-27T12:00:00+00:00",
  "needsReview": [],
  "upcomingCommitments": [],
  "detected": [],
  "metadata": {
    "sourceOfTruth": "actionable_candidates",
    "lens": "daily",
    "horizonDays": 14
  }
}
```

Tests show:

- future items excluded unless relevant on the requested day
- noisy undated detected items filtered

### Returned content type

- candidate review data: yes
- day planning data: partially

### Useful vs cruft

Useful:

- daily relevancy filtering
- 14-day horizon concept

Cruft:

- another candidate-table-shaped API
- overlaps with daily agenda and day brief

### Preserve in V3

- relevancy filtering logic

### Discard or simplify

- endpoint itself as a top-level product surface

### V3 replacement

- internal planning/reviewer logic
- not a primary public endpoint

---

## 3.17 `POST /entities/profile`

- Route file path: `src/main.py`
- Handler: `entities_profile`
- Response model: `EntityProfileResponse`

### Request

- Body model: `EntityProfileRequest`
- Fields:
  - `tenantId`
  - `userId`
  - `entityId`
  - `name`
  - `referenceTime`
  - `includeOpenLoops`
  - `factsLimit`
  - `loopsLimit`

### How it was built

- `_resolve_canonical_entity_candidate`
- `_pg_get_entity_role_grounding`
- `_pg_get_entity_facts_exact`
- `_pg_search_facts`
- loops retrieval
- user-model role fallback

Important code comments show this route was already in a Graphiti-replaced/degraded transition state.

### Internal tables/services used

- canonical entity lookup helpers
- postgres continuity facts
- loop service
- `user_model`

### Actual response shape

Representative response from tests:

```json
{
  "entity": {
    "entityId": "p1",
    "canonicalName": "Ashley",
    "type": "person",
    "aliases": ["Ash"],
    "summary": "Ashley is the user's girlfriend.",
    "role": "girlfriend",
    "relationship": "girlfriend",
    "importance": 0.91,
    "salience": 0.88,
    "confidence": 0.6,
    "recency": {
      "lastSeenAt": "2026-04-09T09:00:00Z",
      "daysSinceSeen": 0,
      "firstSeenAt": null
    }
  },
  "keyFacts": [
    {
      "text": "Ashley is the user's girlfriend.",
      "confidence": 0.91,
      "validAt": "2026-04-09T09:00:00Z",
      "invalidAt": null
    }
  ],
  "openLoops": [
    {
      "id": "l1",
      "type": "thread",
      "text": "Repair relationship with Ashley",
      "status": "active",
      "salience": 7
    }
  ],
  "provenance": {
    "sources": ["postgres_continuity_nodes", "postgres_continuity_facts", "loops"]
  }
}
```

### Returned content type

- raw facts: yes
- open loops: yes
- entity hints/profile: yes
- debug/evidence: provenance sources, but not full evidence refs

### Useful vs cruft

Useful:

- entity card concept
- key facts + open loops + role/relationship + recency

Cruft:

- route still shaped by Graphiti replacement history
- role grounding partially continuity-derived, not always evidence-backed
- user-model fallback for role semantics

### Preserve in V3

- entity card endpoint

### Discard or simplify

- Graphiti replacement comments/semantics
- weakly grounded role fallback paths

### V3 replacement

- `GET /v3/entities/{entity_id}`
- optionally search endpoint for name resolution

---

# 4. Cross-Cutting Findings

## 4.1 What V2 actually returned well

- evidence-backed factual recall
- typed episode recall
- compact startup handover prose with good guardrails
- deterministic day planning
- useful action/calendar lifecycle fields
- entity cards with recency and open-loop context

## 4.2 Common compatibility cruft

- legacy response fields kept “just in case”
- alias routes for simple status transitions
- candidate tables leaking directly into APIs
- Graphiti/postgres migration-era metadata embedded in serving surfaces
- multiple endpoints returning overlapping operational slices

## 4.3 Weak semantics

- `user_model` as a catch-all blob
- `session_brief` fields like `temporalVibe`, `currentVibe`, `energyHint`
- public candidate routes that reflect staging state more than durable product objects
- mixed “narrative summary” and “facts” vocabularies in the same packet

---

# 5. What Cortex V3 Should Preserve

- A single startup packet with:
  - brief handover text
  - recent continuity
  - top loops
  - entity hints
  - freshness/debug only when needed
- A single recall endpoint with typed items:
  - fact
  - episode
  - continuity note
- A clean durable profile packet:
  - identity
  - current state
  - freshness/completeness
- A unified day packet:
  - schedule
  - due/reminders/overdue
  - suggested focus
  - pressure level
- Canonical action and event CRUD objects
- Entity card endpoint
- Canonical session ingest

---

# 6. What Cortex V3 Should Not Recreate

- separate `/session/brief` and `/session/startbrief`
- separate `/day/brief` and `/actions/daily-agenda`
- candidate-table-shaped top-level product APIs
- legacy adapter envelopes like old `/memory/query`
- Graphiti migration baggage in response semantics
- alias mutation endpoints for each status transition
- monolithic `user_model` serving blob

---

# 7. Recommended Cortex V3 Serving Contract

Recommended V3 surface:

## 7.1 Startup

- `GET /v3/startup-packet`

Returns:

- `handover`
- `resume`
- `top_loops`
- `entity_hints`
- `current_state`
- `freshness`

## 7.2 Recall

- `POST /v3/recall`

Returns typed recall items:

- `fact`
- `episode`
- `continuity_note`

Each item should include:

- `text`
- `confidence`
- `evidence_refs`
- `source_kind`
- `derived`

## 7.3 Profile

- `GET /v3/profile`

Returns:

- `identity`
- `current_state`
- `durable_facts`
- `freshness`
- `completeness`

## 7.4 Day Planning

- `GET /v3/day`

Returns:

- `calendar_events`
- `due_today`
- `reminders_today`
- `overdue`
- `pending_review`
- `suggested_focus`
- `pressure_level`

## 7.5 Actions

- `GET /v3/actions`
- `POST /v3/actions`
- `PATCH /v3/actions/{id}`

## 7.6 Events

- `GET /v3/events`
- `POST /v3/events`
- `PATCH /v3/events/{id}`

## 7.7 Entities

- `GET /v3/entities/{id}`

Returns:

- `entity`
- `key_facts`
- `open_threads`
- `recency`

## 7.8 Ingest

- `POST /v3/session/ingest`
- optional `POST /v3/turns/append` only if streaming append is still required

---

# 8. Bottom Line

V2 had useful serving behavior, but too many endpoint shapes reflected transitional architecture rather than stable product contracts. Cortex V3 should keep the durable behaviors:

- evidence-backed recall
- startup handover
- day planning
- canonical action/event objects
- entity cards
- durable ingest

It should drop the V2 sprawl:

- overlapping brief/day endpoints
- candidate staging APIs as first-class product surfaces
- legacy compatibility fields
- migration-era retrieval and profile baggage

