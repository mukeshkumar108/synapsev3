# Synapse V3 Runtime Integration Contract

## 1. Overview

Synapse V3 is the foundational memory and continuity engine for the Sophie runtime. It is strictly the **memory substrate**. It is responsible for storing, extracting, normalizing, and serving intelligence.

Synapse V3 **does not** own the final voice, personality, or verbatim text delivered to the user. 

The external Sophie runtime (or any consumer application) must use this API contract to read continuity states, recall specific memories, and ingest conversation transcripts.

**Synapse V3 Responsibilities Summary:**
- Semantic and structured memory recall.
- Startup and handover instruction packets.
- Session transcript ingestion and asynchronous extraction pipeline orchestration.
- Canonical tracking of actions, events, and user memory controls.

---

## 2. Required Endpoints for Sophie Runtime

### A. `GET /v3/sessions/instruction-packet`
**Purpose:** Called at the start of every session (or upon app foregrounding). It provides the Sophie runtime with context, open loops, and constraints *before* she speaks.

**Query Parameters:**
- `user_id` (string, required)
- `current_datetime` (string, optional, ISO format)
- `timezone` (string, optional, defaults to 'UTC')

**Expected Response Shape:**
```json
{
  "session_instructions": "String: Directives on how to approach the session.",
  "relevant_topics": ["String array: Topics worth raising naturally"],
  "worth_attention": [
    {
      "title": "Topic Title",
      "reason": "Why it matters",
      "suggested_focus": "Suggested way to approach it"
    }
  ],
  "suggested_focus": "String: The single most important current focal point.",
  "tone_note": "String: Calibration for energy and empathy.",
  "avoid": ["String array: Explicit boundaries or sensitive topics to avoid"],
  "stale_warnings": ["String array: Context that shouldn't be treated as current"],
  "handover_summaries": ["String array: Recent session summaries"],
  "active_open_loops": ["String array: Unresolved threads (from Thread Agent)"],
  "entity_hints": ["String array: Active people or projects"]
}
```
*(Note: Actions/Events are explicitly excluded from the standard instruction packet to avoid overloading the context window. They must be fetched via the `/v3/actions` or `/v3/events` endpoints or triggered contextually.)*

### B. `POST /v3/recall`
**Purpose:** Called when the runtime needs to explicitly search memory (e.g., user asks "What did I say about X?") or when internal routing determines context is required.

**Request Shape:**
```json
{
  "user_id": "string",
  "query": "string",
  "limit": 5,
  "recall_type": "semantic|entity|timeline" // optional
}
```

**Expected Response Shape:**
```json
{
  "items": [],
  "facts": [],
  "episodes": [],
  "continuity": {},
  "timeline": [],
  "certainty": "high|medium|low",
  "weak_recall": true|false,
  "weak_recall_reason": "String: explanation if weak",
  "source_refs": ["UUIDs"],
  "evidence_preview": ["String array: raw evidence quotes"],
  "linked_people": ["Names"],
  "linked_projects": ["Projects"],
  "linked_topics": ["Topics"]
}
```

### C. `POST /v3/session/ingest`
**Purpose:** Called at session close, extended inactivity, or explicit checkpointing. It securely writes the `source_archive`, adds the transcript to the `outbox`, and schedules the asynchronous extraction pipeline.

**Request Shape:**
```json
{
  "user_id": "string",
  "session_id": "string",
  "source_type": "chat",
  "messages": [
    {
      "role": "user|assistant",
      "content": "Message body",
      "timestamp": "ISO-8601 string"
    }
  ],
  "metadata": {
    "conversation_id": "optional",
    "timezone": "UTC"
  }
}
```
**Rules for `session/ingest`:**
- **What to send:** The exact, unmodified transcript of the session.
- **What not to send:** Internal reasoning loops, prompt templates, or system instructions.
- **When to call:** On session end, explicit user boundaries, or 30-minute quiet periods (buffer seal).

### D. `GET /v3/actions`, E. `POST /v3/actions`, F. `PATCH /v3/actions/{id}`
**Purpose:** Canonical management of user tasks, reminders, and system follow-ups.

**Key Concepts:**
- Support listing, creating, updating, completing, and dismissing actions.
- **Status Values:** `pending`, `confirmed`, `completed`, `dismissed`, `superseded`.
- **Confirmation Expectations:** Items extracted automatically may be `needs_confirmation=true`. The runtime is responsible for presenting these to the user.
- **Ambiguity Handling:** If Synapse returns an action missing critical context (e.g., "Call mom" but no date), the Runtime must handle the clarification UX.

### G. `GET /v3/events`, H. `POST /v3/events`, I. `PATCH /v3/events/{id}`
**Purpose:** Canonical management of time-anchored plans, appointments, and deadlines.

**Key Concepts:**
- These are **internal event candidates only**.
- They are **not** currently synced to external providers (no Google Calendar writes yet).
- Similar to actions, they require runtime confirmation UX if `needs_confirmation=true` or confidence is low.

### J. `POST /v3/memory-controls`
**Purpose:** Direct user-invoked control over their memory substrate (overriding automated extraction).

**Supported Actions (Payload Types):**
- `avoid_topic`: Explicitly mark a subject off-limits.
- `forget`: Soft-delete or suppress an extracted fact.
- `dismiss`: Mark a candidate or open loop as invalid.
- `correct`: Replace an existing fact with a corrected version.
- `resolve_loop`: Explicitly close a thread/open loop.

**Rules:**
- This endpoint **never** deletes raw data from the `source_archive` (for compliance/audit reasons).
- It writes immutable `timeline_events` representing the user's control action.
- Directly influences future `/v3/sessions/instruction-packet` generation (e.g., updating the `avoid` list).

---

## 3. Runtime Responsibilities vs. Synapse Responsibilities

### Synapse Owns (The Backend):
- Persistent memory storage (`confirmed_facts`, `candidates`, `source_archive`).
- Asynchronous extraction and reconciliation pipelines.
- Vector embeddings, semantic recall, and scoring.
- Traceability and source evidence grounding.
- Entity tracking and open-loop continuity states.
- The canonical REST APIs for actions, events, and memory controls.

### Sophie Runtime Owns (The Client/Execution):
- Voice, tone, personality, and verbatim final wording.
- Execution speed and latency optimization.
- **Decision Logic:** Deciding *when* to trigger `recall`.
- **Decision Logic:** Deciding *when* to POST a new action/event vs. waiting for background extraction.
- **UX & Flow:** Prompting the user for clarification if a Synapse entity or action is ambiguous.
- **UX & Flow:** Requesting confirmation for pending background actions.
- Future adaptive runtime loops and SceneState generation (vNext).

---

## 4. Important Behavioural Rules for Sophie

1. **Do not call `/v3/recall` on every message.** Rely on the session instruction packet and active context unless explicitly searching memory.
2. **Always call `GET /v3/sessions/instruction-packet` at session start.** This prevents Sophie from flying blind.
3. **Always call `POST /v3/session/ingest` at session close or timeout.** Failure to do so drops memory.
4. **Do not treat `weak_recall` as certainty.** If Synapse returns `weak_recall: true`, Sophie must express uncertainty or ask for clarification.
5. **Do not attempt to sync events externally.** Let Synapse own the eventual Google Calendar sync integration.
6. **Do not attempt to delete raw memory via the API.** Use the `/v3/memory-controls` endpoint to manage memory state safely.
7. **Ask for clarification.** If an action/event target lacks detail, do not guess. Let the user clarify.
8. **Present candidates safely.** Before executing risky state changes, confirm pending items with the user.

---

## 5. Current Limitations

- **Embeddings:** The current vector search relies on a placeholder or initial embedding provider. Performance may shift during final prod deployment.
- **Entity System:** The entity system is lightweight (relies on text matching and simple UUID relationships); there is no full canonical Graph DB yet.
- **Open-Loop Lifecycle:** The open-loop status is derived from metadata and timeline status; it is not yet a distinct, strictly-typed table.
- **Calendar Sync:** Events are internal to Synapse only. External write sync (Google Calendar) is not implemented.
- **Adaptive Runtime:** The external runtime does not yet support adaptive pacing or multi-bubble natively.
- **SceneState / Hot Layer:** The working memory SceneState injection (Continuity Engine Lane C) is not yet active.
- **Provenance Awareness:** Multi-speaker awareness and assistant-created canon tracking (Continuity Engine Lane A) are planned but not fully integrated into standard extraction yet.

---

## 6. Migration Notes from Older Sophie/Synapse Integrations

Any external Sophie application must migrate off legacy routes. The external repo should audit all existing network calls and remap them to the V3 contract.

**Likely Deprecated Paths to Remap:**
- **Old Memory Query:** Replace old direct vector calls with `POST /v3/recall`.
- **Old Startbrief / Handover:** Replace old summary fetches with `GET /v3/sessions/instruction-packet`.
- **Old Session Close:** Replace old immediate-extraction pipelines with `POST /v3/session/ingest`.
- **Old Action/Reminder paths:** Route through `POST /v3/actions`.
- **Old Calendar routes:** Route through `POST /v3/events`.

*Warning: Implementing Sophie against Synapse V3 requires strictly adhering to these paths. Do not bypass the `/v3/` API namespace to query databases directly.*