# Task 8.6: Memory Parity Foundation

## Purpose
Synapse V3 must not regress from the useful memory behaviors established in V2. While V2's architecture and endpoint sprawl were flawed, its behavioral baseline—evidence-backed factual recall, episodic recall, durable open loops, time-aware startup handover, and idempotent ingestion—must be preserved. 

This task implements the memory substrate and recall hierarchy necessary for Sophie to maintain a continuous, reliable relationship with the user.

---

## Core Decision
- **Add a Postgres `source_archive` table** as the permanent, immutable raw evidence substrate.
- The `outbox` becomes strictly a processing ledger (pending -> done/failed). It is no longer the permanent archive for raw transcripts.
- Mongo/R2/S3 are deferred; Postgres handles raw storage in this phase.

---

## Subtask 8.6A — Postgres Source Archive

### Goal
Establish permanent, immutable raw source storage for Sophie sessions and future external payloads (email, calendar, messages), decoupling archival storage from the processing ledger.

### Files Likely to Change
- `schema.sql` (New table: `source_archive`, modify `outbox`)
- `core/api.py` (Update `POST /v3/session/ingest` and outbox logic)
- `core/db.py`
- `runtime/` and `workers/` (Update reads to pull from `source_archive` instead of `outbox.raw_content`)

### Exact Behaviour
1. `POST /v3/session/ingest` stores the full transcript in `source_archive`.
2. An `outbox` row is created, storing a `source_archive_id` (or `source_ref`), not the permanent raw transcript.
3. The pipeline reads the source payload via the `source_archive` reference.
4. The `source_archive` supports various `source_type`s (`sophie_session`, `email`, `calendar`, `message_batch`).
5. `source_archive` schema includes: `id`, `user_id`, `source_type`, `source_external_id` (nullable), `session_id` (nullable), `conversation_id` (nullable), `occurred_at` (nullable), `captured_at`, `payload` (JSONB), `metadata` (JSONB), `created_at`.
6. The `outbox` schema retains processing status, retry/failure state, and the source reference.

### What Not To Do
- Do not use MongoDB or S3 in this task.
- Do not leave raw transcripts permanently in the `outbox` table.

### Tests Required
- Session ingest successfully creates a `source_archive` row.
- The corresponding `outbox` row correctly references the `source_archive` row.
- The processing pipeline successfully reads the payload from `source_archive`.
- Marking an `outbox` item as `done` does not delete or alter the `source_archive` transcript.
- A failed pipeline run preserves the `source_archive`.
- User ID isolation is enforced on `source_archive` reads.
- `source_archive` can gracefully store different payload shapes (simulated email/calendar shapes).

### Definition of Done
- Raw transcripts are permanently stored outside `outbox.raw_content`.
- The `outbox` functions solely as a processing queue.
- The provenance chain is intact: `confirmed_fact.source_ids` -> `outbox.id` -> `source_archive.id`.

### Blockers
- None.

---

## Subtask 8.6B — Pipeline Idempotency

### Goal
Ensure that rerunning the same source payload or outbox item does not duplicate data or dirty the memory state.

### Files Likely to Change
- `core/serving.py` or pipeline runner logic.
- `core/reconciliation.py` (ensure deduplication logic respects idempotency keys).

### Exact Behaviour
1. Rerunning a pipeline for the same `session_id` or `source_archive_id` does not create duplicate `session_summaries`.
2. Does not duplicate extracted candidates.
3. Does not duplicate `confirmed_facts`.
4. Does not duplicate `timeline_events`.
5. Outbox status transitions (pending -> processing -> done|failed) are safe and locking.
6. Pipeline failures preserve the `source_archive` and accurately record the error in the `outbox` or logging system.

### What Not To Do
- Do not rely on weak text-matching for idempotency if ID/hash-based deduplication is possible.

### Tests Required
- Run the pipeline on the same outbox item twice.
- Assert that counts for summaries, candidates, facts, and timeline events are identical before and after the second run.
- Simulate a failure, retry the outbox item, and assert safe recovery without duplication.

### Definition of Done
- The pipeline is fully idempotent based on source IDs.

### Blockers
- Subtask 8.6A must be complete.

---

## Subtask 8.6C — Startup/Handover Packet Parity

### Goal
The `startup_packet` must preserve the useful, time-aware, context-rich handover behavior from V2 without cloning V2's endpoint sprawl or monolithic logic.

### Files Likely to Change
- `core/serving.py` (Packet assembly logic)
- `agents/surfacing_agent.py` (Prompt and output schema updates)
- `core/api.py` (Endpoint response models)

### Exact Behaviour
1. The packet must include: `last_interaction_at`, `time_since_last_interaction`, `sessions_today_count`, `is_first_contact_today`.
2. Compute `handover_depth`: `continuation` | `same_day` | `yesterday` | `multi_day` | `cold_start`.
3. Include recent context: `last_session_summary`, `today_context`, and `yesterday_context` (if available/relevant).
4. Include `active_open_loops` (scored/ranked), `entity_hints` (known related entities), `avoid` topics, and a `tone_note`.
5. Include `freshness` or `catch_up` state (e.g., pending outbox items).
6. **Anti-drift:** Ensure handover prose does not invent continuity or offer advice.

### What Not To Do
- Do not clone `GET /session/startbrief` or `GET /session/brief` exactly.
- Do not include monolithic user models in the startup packet.

### Tests Required
- Test second session on the same day (should be `continuation` or `same_day`).
- Test first session of the next day (should be `yesterday` depth and include yesterday's context).
- Test multi-day gap (should not hallucinate recent context).
- Test cold start (no prior sessions).
- Assert that `avoid_topic` boundaries are respected and not surfaced.
- Assert that stale state is not surfaced as current.

### Definition of Done
- The startup packet accurately reflects the time gap and provides grounded, non-hallucinated context utilizing summaries, loops, and entity hints.

### Blockers
- None.

---

## Subtask 8.6D — Retrieval V1

### Goal
Replace the basic lexical retrieval scaffold with a multi-lane retrieval system that mirrors V2's behavioral parity (factual, episodic, continuity).

### Files Likely to Change
- `core/serving.py` (Retrieval logic)
- `core/api.py` (Recall endpoints)

### Exact Behaviour
1. Support `recall_type` or `intent`: `exact`, `episodic`, `hybrid`.
2. **Factual Lane:** Retrieves `confirmed_facts`, strictly evidence/source aware.
3. **Episodic Lane:** Retrieves `session_summaries` and windows from the `source_archive`.
4. **Continuity Lane:** Retrieves `timeline_events`, open loops, and derived continuity.
5. Return typed items: `fact`, `episode`, `continuity_note`, `timeline_event`.
6. Included metadata: `confidence`, `score`, `source_refs`, `evidence_preview`, and `weak_recall` flag/reason.
7. Implement improved retrieval (lexical + fuzzy baseline, top-k ranking, recency/confidence weighting).
8. If semantic (pgvector) embeddings are not yet available, build the ranked lexical baseline now, but mark vector search as a P0 requirement before beta.
9. Refuse to hallucinate answers if retrieval confidence is below threshold.

### What Not To Do
- Do not build full vector infrastructure if it distracts from the core V1 pipeline parity, but design the interface to accept it.
- Do not mix derived continuity rows with canonical factual rows without clear labels.

### Tests Required
- Broad query ("remember that conversation about God...") successfully finds the relevant session/source via episodic/summary search.
- Exact factual query returns the correct `confirmed_fact`.
- A weak/unmatched query returns a `weak_recall` flag, not fake certainty.
- Ensure strict user isolation in all retrieval queries.
- Ensure `evidence` and `source_refs` are present in returned items.

### Definition of Done
- Multi-lane retrieval (Factual, Episodic, Continuity) is functional, returns typed items, and includes source grounding.

### Blockers
- Subtask 8.6A (Source Archive) must be complete to support Episodic retrieval.

---

## Subtask 8.6E — Entity/Open Loop Continuity

### Goal
Establish minimum viable entity and open-loop behavior to ensure memory stays connected across sessions and packets.

### Files Likely to Change
- `core/reconciliation.py`
- `agents/fact_agent.py` or `agents/thread_agent.py` (Schema updates for links)
- `core/serving.py` (Startup packet assembly)

### Exact Behaviour
1. Preserve `links.people` and `links.projects` from candidates into `confirmed_facts` during reconciliation.
2. Ensure the startup packet includes active open loops, ranked by a combination of salience, importance, urgency, and recency.
3. Surface known entity names from `confirmed_facts` as `entity_hints` in the startup packet.
4. **Safety:** Do not blindly merge entities with the same name.
5. Ambiguous entity matches require explicit confirmation or must remain unlinked.

### What Not To Do
- Do not build a monolithic user profile endpoint.
- Do not implement aggressive auto-merging of person entities based solely on first names.

### Tests Required
- Extracting a task involving a person ("Call Ashley") preserves the person link through to the confirmed fact.
- Two distinct facts mentioning people with the same name do not auto-merge without strong contextual evidence.
- An active, high-salience open loop appears in the startup packet.
- A stale or dismissed open loop does not appear in the startup packet.
- When an entity is known and relevant, an `entity_hint` is successfully surfaced in the startup packet.

### Definition of Done
- Entities and open loops are preserved through the pipeline, ranked correctly, and surfaced appropriately without aggressive over-merging.

### Blockers
- Subtask 8.6C (Startup Packet) must be in progress or complete to surface the hints/loops.

---
*Task 8.6 defines the memory parity baseline. Do not proceed to Task 9 (External Integrations or Proactivity) until these foundations are tested and verified.*