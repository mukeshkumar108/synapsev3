# Cortex Moments and Packets

## 1. Core Principle

**Cortex is an intelligence preparation engine, not an endpoint collection.**

The primary function of Cortex is to synthesize raw data into structured **intelligence packets** tailored for specific **product moments**. Cortex is responsible for "knowing"; Sophie is responsible for "relating."

- Cortex prepares the right intelligence packet for the right moment.
- Endpoints are merely thin delivery mechanisms for these packets.
- Success is measured by the utility and timing of the intelligence provided, not by the breadth of the API.

---

## 2. Actors

| Actor | Role |
| :--- | :--- |
| **Sophie Runtime** | The conversational interface. Consumes instruction packets to drive voice, tone, and recall. Owns the final user experience. |
| **Cortex Internal Workers** | Background processes (extraction, reconciliation, decay, summarization). They consume raw data and prepare the memory hierarchy. |
| **Product Frontend** | The UI where the user interacts with their timeline, tasks, and settings. Consumes packets for visualization and dashboarding. |
| **External Source Connectors** | Ingest raw data from WhatsApp, Email, Calendar, etc. They feed the outbox, triggering the Cortex pipeline. |

---

## 3. Product Moments

### Session Start
- **Trigger:** User opens the chat or sends an initial message.
- **Consumer:** Sophie Runtime.
- **Intelligence Needed:** Current state, recent focus, relevant topics, tone calibration.
- **Cortex Provides:** `startup_packet` (instruction packet).
- **Sophie/Runtime Owns:** Opening greeting, persona expression, and transition into conversation.
- **Sensitivity/Freshness:** High sensitivity (avoid-topics). Must reflect the last 30 minutes of external ingestion.

### User Asks for Recall
- **Trigger:** User asks "What happened with X?" or "Tell me about Y."
- **Consumer:** Sophie Runtime.
- **Intelligence Needed:** Semantic match of facts, evidence-based context, related people/projects.
- **Cortex Provides:** `recall_packet`.
- **Sophie/Runtime Owns:** Narrating the memory back to the user naturally.
- **Sensitivity/Freshness:** High sensitivity. Grounded in confirmed facts only.

### Explicit Command/Action/Calendar Write
- **Trigger:** User says "Remind me to..." or "Add a meeting..."
- **Consumer:** Cortex Workers (Task/Event Agents).
- **Intelligence Needed:** Temporal grounding, intent extraction, conflict detection.
- **Cortex Provides:** `command_context_packet` (for confirmation) or direct write to candidates.
- **Sophie/Runtime Owns:** Confirming the action with the user.
- **Sensitivity/Freshness:** High accuracy required. Real-time.

### Ambient Session Ingestion
- **Trigger:** Session closure or 30-minute quiet buffer.
- **Consumer:** Cortex Workers.
- **Intelligence Needed:** Extraction of facts, tasks, state, and threads from raw transcript.
- **Cortex Provides:** Candidate items for reconciliation.
- **Sophie/Runtime Owns:** N/A (Background process).
- **Sensitivity/Freshness:** Processing should complete within minutes of session end.

### Morning Briefing
- **Trigger:** First interaction of the day or scheduled background job.
- **Consumer:** Product Frontend / Sophie Runtime.
- **Intelligence Needed:** Daily schedule, overdue tasks, primary focus, "what's new since yesterday."
- **Cortex Provides:** `morning_briefing_packet`.
- **Sophie/Runtime Owns:** Presenting the briefing in the user's preferred morning tone.
- **Sensitivity/Freshness:** Consolidated view of the last 24 hours.

### End-of-Day Summary
- **Trigger:** End of user's active day (timezone-aware).
- **Consumer:** Product Frontend / Sophie Runtime.
- **Intelligence Needed:** Achievements, open loops for tomorrow, emotional pulse of the day.
- **Cortex Provides:** `eod_summary_packet`.
- **Sophie/Runtime Owns:** Affirmation and transition to rest/planning.
- **Sensitivity/Freshness:** Summary of the current day's events.

### Rolling 3–5 Day Context
- **Trigger:** Periodic background synthesis.
- **Consumer:** Cortex Workers (Living Context synthesis).
- **Intelligence Needed:** Identifying shifts in focus, emerging tensions, or repeated patterns.
- **Cortex Provides:** `recent_context_packet`.
- **Sophie/Runtime Owns:** N/A (Feeds into subsequent Startup Packets).
- **Sensitivity/Freshness:** Low-frequency synthesis.

### Weekly Pattern Summary
- **Trigger:** Weekly scheduled job.
- **Consumer:** Product Frontend.
- **Intelligence Needed:** Habit tracking, long-term goals progress, relationship trends.
- **Cortex Provides:** `weekly_pattern_packet`.
- **Sophie/Runtime Owns:** Dashboard visualization and "Week in Review" message.
- **Sensitivity/Freshness:** High-level abstraction.

### Source Connection / Day-0 Backfill
- **Trigger:** User connects a new service (e.g., Gmail).
- **Consumer:** Cortex Workers.
- **Intelligence Needed:** Bulk extraction, historical anchoring, identification of key people/projects.
- **Cortex Provides:** `source_connection_packet`.
- **Sophie/Runtime Owns:** Progress updates ("I'm learning about your last 6 months...").
- **Sensitivity/Freshness:** Historical bulk processing.

### External Message Batch Ingestion
- **Trigger:** Periodic poll of WhatsApp, Instagram DMs, SMS, or Email threads.
- **Consumer:** Cortex Workers / Sophie Runtime (for proactivity).
- **Intelligence Needed:** Identifying urgent needs or high-salience info from non-chat sources.
- **Cortex Provides:** `external_message_batch_packet`.
- **Sophie/Runtime Owns:** Deciding if a push notification is warranted.
- **Sensitivity/Freshness:** Near-real-time.
- **Boundary Rule:** External human-message sources must not be treated like user-to-Sophie chat. They are observation-only lanes.

### Proactive Outreach
- **Trigger:** Synthesis of urgent tasks, time-sensitive events, or companion follow-ups.
- **Consumer:** Sophie Runtime.
- **Intelligence Needed:** Reason for outreach, suggested message, timing window.
- **Cortex Provides:** `outreach_packet`.
- **Sophie/Runtime Owns:** Delivery timing and delivery channel choice (Push vs WhatsApp).
- **Sensitivity/Freshness:** Critical timing rules.
- **Approval Rule:** Preparation is allowed; execution requires permission. Sending, removing, or rescheduling requires explicit confirmation unless a narrow automation rule is granted.

---

## 4. Packet Types

### `startup_packet`
- **Purpose:** Brief Sophie for a live session.
- **Inputs:** Active facts, recent timeline, current state, time/timezone.
- **Output Shape:** `session_instructions`, `relevant_topics`, `worth_attention` (max 3), `tone_note`, `avoid`.
- **Consumer:** Runtime-facing.

### `recall_packet`
- **Purpose:** Provide specific memory content for user queries.
- **Inputs:** Query text, confirmed facts, evidence markers.
- **Output Shape:** `matched_facts`, `evidence_quotes`, `related_entities`, `certainty_score`.
- **Consumer:** Runtime-facing.

### `command_context_packet`
- **Purpose:** Provide confirmation data for an inferred user command.
- **Inputs:** Extracted candidate (task/event), existing conflicts.
- **Output Shape:** `suggested_action`, `parameters`, `conflicts`, `needs_confirmation_reason`.
- **Consumer:** Runtime-facing.

### `morning_briefing_packet`
- **Purpose:** High-level operational overview for the start of the day.
- **Inputs:** Calendar, open tasks, yesterday's summary.
- **Output Shape:** `date`, `schedule[]`, `priority_tasks[]`, `daily_focus`, `weather/context`.
- **Consumer:** Frontend-facing / Runtime-facing.

### `eod_summary_packet`
- **Purpose:** Reflective summary of the day.
- **Inputs:** Today's timeline events, accomplishments, unresolved threads.
- **Output Shape:** `achievements[]`, `open_loops_for_tomorrow`, `emotional_summary`.
- **Consumer:** Frontend-facing.

### `recent_context_packet`
- **Purpose:** Update the "Living Context" for the user.
- **Inputs:** Last 3–5 days of session summaries and timeline events.
- **Output Shape:** `current_narrative`, `primary_tension`, `relationship_pulse`.
- **Consumer:** Worker-facing (internal memory update).

### `weekly_pattern_packet`
- **Purpose:** Identify long-term trends and habit progress.
- **Inputs:** Last 7 days of intelligence.
- **Output Shape:** `habit_stats`, `goal_progress`, `notable_shifts`.
- **Consumer:** Frontend-facing.

### `external_message_batch_packet`
- **Purpose:** Summarize high-salience info from external human-message sources.
- **Inputs:** Raw messages from outbox (WhatsApp, Email, etc.).
- **Output Shape:**
  - `source_type`, `source_connection_id`, `conversation_id`, `participants`
  - `current_batch`, `context_tail`, `speaker_attribution_notes`
  - `operational_items`, `relationship_threads`, `sensitive_items`
  - `do_not_attribute_to_user`, `extraction_evidence_scope`
- **Consumer:** Worker-facing / Runtime-facing.

### `source_connection_packet`
- **Purpose:** Status and findings from a new source ingestion.
- **Inputs:** Bulk processing results.
- **Output Shape:** `ingestion_status`, `top_entities_found`, `top_projects_found`.
- **Consumer:** Frontend-facing.

### `outreach_packet`
- **Purpose:** Trigger and guide a proactive message.
- **Inputs:** Urgent task/thread/event.
- **Output Shape:**
  - `type`: `reminder_due` | `care_check_in` | `open_loop_nudge` | `thoughtful_followup` | `prepared_research` | `draft_created` | `time_sensitive_update` | `action_requires_confirmation`
  - `suggested_message`, `reason`, `ideal_at_window`, `sensitivity_rules`
- **Consumer:** Runtime-facing.

---

## 5. Memory Hierarchy

Cortex operates on a **query-dependent recall** strategy, moving data through levels of abstraction:

1.  **Raw Source / Transcript Archive:** Full fidelity. Used for **exact wording** or **disputed recall**.
2.  **Session Summaries:** Recaps of individual interactions. Used for **broad temporal recall**.
3.  **EOD Summaries:** Daily synthesis. Used for **broad temporal recall**.
4.  **Rolling Context (3–5 Days):** The "Living Context." Used for **broad temporal recall**.
5.  **Weekly Summaries:** Pattern recognition. Used for **broad temporal recall**.
6.  **Confirmed Facts / Timeline / Open Loops:** The durable "Truth." Used for **specific factual recall**.

**Recall Strategy:**
- **Specific Factual Recall:** Start with `confirmed_facts` and `timeline`.
- **Broad Temporal Recall:** Start with `weekly`, `recent`, `EOD`, and `session` summaries.
- **Exact Wording / Disputed Recall:** Fall back to `raw source / transcript archive`.

**Note on Storage:** The `outbox` is the processing ledger, not necessarily the long-term raw archive. Raw source storage may be inline Postgres, Mongo, R2/S3, or pluggable via `source_ref`.

---

## 6. Runtime Boundary

- **Cortex prepares intelligence.** It provides the "what," the "why," and the "warnings." It operates in JSON and structured logic.
- **Sophie owns the final voice.** She takes the structured packets and translates them into personality-driven conversation. She handles tone, wording, and confirmation UX.

---

## 7. Endpoint Implications

Endpoints in Synapse V3 are **packet-delivery vehicles**. They focus on authentication, validation, and assembly.

- **Avoid Legacy Sprawl:** Do not recreate monolithic endpoint collections or V2 compatibility layers.
- **Canonical Object APIs:** Maintain clean APIs for user-owned objects:
  - **Actions** (tasks, habits)
  - **Events** (calendar, reminders)
  - **Memory Controls** (corrections, dismissals)
  - **Source Connections** (if owned by Cortex)

Prefer moment-based routes (e.g., `GET /v3/overview/daily`) over granular property mutations.

---

## 8. Open Questions

- **Raw Source Archive:** Finalizing the long-term storage strategy (Postgres vs specialized object storage).
- **Queryable Timeline:** Efficiently supporting "What was I doing three Tuesdays ago?" without full-text searching the archive.
- **EOD/Weekly Storage:** Dedicated table vs typed rows in `session_summaries`.
- **Hybrid Search:** Implementing Cohere rerank over semantic search results.
- **Proactivity Calibration:** Preventing "outreach fatigue" through cross-worker coordination.
