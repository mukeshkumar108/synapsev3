## Task 5 Checkpoint

### 1. What Task 5 Built

Task 5 established the first serving layer for Synapse V3.

It now supports:
- a surfacing judgement agent
- a Python serving layer that gathers confirmed memory and timeline context
- runtime-facing endpoints for session briefing, daily overview, memory query, and outbox ingestion
- deterministic tests for surfacing behavior and serving endpoints

Task 5 is the first point where Sophie runtime can ask Cortex:

“What should I know before talking to this user right now?”

### 2. What Endpoints Now Exist

The following endpoints now exist:

- `GET /v3/sessions/instruction-packet`
- `GET /v3/overview/daily`
- `POST /v3/memory/query`
- `POST /v3/outbox/ingest`

These provide the first usable runtime-facing interface for Cortex.

### 3. How `surfacing_agent` Works

`agents/surfacing_agent.py` is a judgement agent.

Role:
- Sophie’s chief of staff

Input:
- relevant active confirmed facts
- tasks
- events
- current state
- active threads
- recent timeline
- time of day
- current datetime
- timezone

Output:
- `session_instructions`
- `relevant_topics`
- `worth_attention`
- `suggested_focus`
- `tone_note`
- `avoid`
- `stale_warnings`

Key rules:
- `worth_attention` is capped at 3 items
- stale, dismissed, corrected, expired, or suppressed items should not be surfaced as current
- avoid-topic memories should appear in `avoid`, not as topics to raise
- communication preferences should calibrate tone, not become conversation topics
- surfacing is a briefing layer, not a reply generator

### 4. What `core/serving.py` Does

`core/serving.py` is the deterministic assembly layer behind Task 5.

It handles:
- fetching active confirmed facts
- fetching recent timeline events
- filtering expired or stale state facts
- classifying confirmed facts into tasks, events, state, and threads
- building the session instruction packet
- building the daily overview
- placeholder memory query over confirmed-fact content
- outbox ingestion for new raw content

It is the adapter between storage and agent judgement.

### 5. What `core/api.py` Does

`core/api.py` exposes the initial FastAPI serving layer.

It defines:
- request models for memory query and outbox ingest
- a database dependency
- the four Task 5 routes

It does not implement workers, background orchestration, or external source connectors.

It is intentionally thin:
- HTTP boundary
- request validation
- handoff into `core/serving.py`

### 6. How Instruction Packet Differs From Daily Overview

#### Session Instruction Packet

Purpose:
- prepare Sophie for a live conversation right now

Focus:
- briefing quality
- calibration
- most relevant 2-3 things
- tone and caution

Output includes:
- `session_instructions`
- `relevant_topics`
- `worth_attention`
- `suggested_focus`
- `tone_note`
- `avoid`
- `stale_warnings`

#### Daily Overview

Purpose:
- provide a broader daily operational snapshot

Focus:
- schedule
- open tasks
- current worth-attention summary
- daily focus

Output includes:
- `date`
- `schedule`
- `open_tasks`
- `worth_attention`
- `suggested_focus`

Important note:
- `worth_attention` max 3 applies to the session instruction packet.
- daily overview and future morning briefing are allowed to include more total items grouped by category.

### 7. How Cortex Respects The Runtime Boundary

Task 5 keeps the runtime boundary explicit:

- Cortex prepares intelligence.
- Sophie runtime owns final voice, tone, personality, and exact wording.

Cortex provides:
- calibration
- warnings
- structured memory context
- prioritization
- suggested focus

Cortex does not:
- generate Sophie’s final user-facing message in the session packet
- pretend to speak as Sophie
- replace runtime personality decisions

This keeps the system modular and reduces creepiness or overreach.

### 8. Known Caveats

- placeholder retrieval, no vector or rerank yet
- simple temporal hardening
- live surfacing evals still needed
- daily overview and morning briefing may need separate treatment
- human-message intelligence lane not built yet

Additional practical caveats:
- surfacing quality is still only as good as the current confirmed-fact population
- current retrieval is content-text based, not semantic
- packet quality still needs real-world evaluation against mixed companion and productivity memory

### 9. Recommended Next Phase

Recommended next steps after Task 5:

- human-message intelligence lane design
- source connection and message-buffering design
- optional reranking layer later

More specifically:
- define the human-message intelligence lane before building proactive outreach behavior
- design source-specific ingestion and buffering for external channels
- upgrade retrieval later with vector search and/or reranking once serving flow is stable

Task 5 provides the first runtime-ready interface.
The next phase should improve what enters Cortex and how Cortex decides what deserves proactive handling.
