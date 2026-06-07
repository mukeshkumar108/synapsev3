# External Lanes V1: Calendar & Gmail

## 1. Overview
External Lanes V1 establishes the first "passive" intelligence paths for Synapse V3. The goal is to move beyond user-to-Sophie chat into observing and assisting with the user's primary professional and scheduling surfaces.

---

## 2. Scope V1

### In Scope
- **Calendar (Google/Outlook):** Read-only sync and prepared-write (pending confirmation).
- **Gmail:** Read, summarize, prioritize, and action detection.
- **Drafting:** Preparing reply drafts for user review.
- **Memory Ingestion:** Treating email/calendar as raw sources for the standard Cortex pipeline.

### Out of Scope
- WhatsApp/Instagram/SMS relationship intelligence.
- Full human-message intelligence lane (multi-participant threading).
- Autonomous sending or deletion of emails.
- Autonomous calendar cancellation or rescheduling.
- Advanced research agents or weekly pattern synthesis.
- Specialized raw archive storage (Mongo/R2).

---

## 3. Implementation: Calendar V1

### Capabilities
- **Sync:** Periodically ingest upcoming and recent events.
- **Action Extraction:** Detect deadlines or meeting requests from other sources and propose calendar events.
- **Conflict Detection:** Identify overlaps when proposing new events or during morning briefings.
- **Lifecycle:** 
  - **Create:** Only after user confirmation.
  - **Update:** Only after user confirmation.
  - **Delete/Archive:** Only after explicit user request.
- **Timeline:** Every import or write MUST generate a `timeline_events` entry (type: `event_confirmed` or `system`).

### Serving Impact
- Feeds `morning_briefing_packet` with the day's schedule.
- Populates the `daily_overview` endpoint.
- Provides temporal grounding for `startup_packet` (e.g., "You have a meeting in 15 minutes").

---

## 4. Implementation: Gmail V1

### Capabilities
- **Prioritization:** Classify incoming mail into high-salience vs. noise.
- **Classification:**
  - `needs_reply` / `needs_action`
  - `deadline` / `invitation` / `meeting_change`
  - `waiting_on_user` / `waiting_on_someone_else`
  - `FYI_only`
  - `noise` (newsletters, receipts, automated notifications)
- **Extraction:** Feed relevant email content into `task_agent`, `event_agent`, and `thread_agent` as raw source material.
- **Drafting:** Propose `suggested_reply` content for emails marked `needs_reply`.

### Authority Model
- **Cortex prepares:** Summaries, classifications, candidates, and drafts.
- **User executes:** Sending, archiving, or deleting requires explicit confirmation via the Sophie Runtime or Product Frontend.

---

## 5. Required Components

### Agents
- **`email_triage_agent` (New):** Specialized version of Triage for high-volume email. Filters noise and routes to extraction.
- **`email_action_agent` (New):** Summarizes threads and identifies the specific classifications (needs_reply, etc.).
- **`calendar_agent` (Update/Reuse):** Handles conflict detection and ISO date resolution for calendar-specific payloads.

### Services/Workers
- **`ExternalSourceWorker`:** Orchestrates the polling/webhook ingestion from Gmail/Calendar and writes to the `outbox`.
- **`DraftingService`:** Manages the lifecycle of proposed email drafts.

---

## 6. Packet Impact

### `morning_briefing_packet`
- Enhanced with: `calendar_schedule`, `urgent_emails`, `overnight_summary`.

### `outreach_packet`
- New triggers: `urgent_email_received`, `calendar_conflict_detected`, `meeting_invitation_pending`.

### `external_message_batch_packet`
- Now populated with Gmail thread summaries and participants.

---

## 7. Authority & Security

1. **Permission Boundary:** preparation is allowed; execution requires permission.
2. **Traceability:** Every fact or task extracted from Gmail/Calendar must link back to the specific `source_id` (Email UUID or Calendar Event ID).
3. **Draft Privacy:** Drafts remain in `candidates` or a specialized `drafts` table until "Promoted" to the provider (Gmail).
4. **No Auto-Delete:** V1 will never delete or archive a source item autonomously.

---

## 8. Recommended Implementation Order

1. **Phase 1: Calendar Read-Only.** Ingest events into `confirmed_facts` (domain: `events`). Update `morning_briefing_packet`.
2. **Phase 2: Email Triage.** Ingest Gmail into `outbox`. Build `email_triage_agent` to filter noise.
3. **Phase 3: Email Extraction.** Run `task_agent` and `event_agent` over high-salience emails.
4. **Phase 4: Calendar Write-Ready.** Implement candidate-to-calendar write flow (pending user confirmation).
5. **Phase 5: Email Drafting.** Implement `suggested_reply` logic for `needs_reply` emails.

---

## 9. Testing Strategy

- **Conflict Logic:** Test behavior when a new email invitation overlaps with an existing calendar event.
- **Noise Filtering:** Verify that newsletters and receipts do not trigger `task_agent` or `outreach_packet`.
- **Temporal Accuracy:** Ensure relative dates in emails ("Let's meet next Tuesday") resolve correctly against the ingestion timestamp.
- **Traceability:** Confirm that every fact extracted from an email can be traced back to the original raw email in the outbox.

---

## 10. Open Questions

- **Polling vs. Webhooks:** Should V1 rely on periodic polling or push notifications (Pub/Sub) for real-time responsiveness?
- **Auth Storage:** Where do OAuth tokens live? (Requirement: Product/Backend layer, Cortex receives temporary access or localized client).
- **Draft Location:** Should drafts be pushed to Gmail "Drafts" folder immediately or held in Cortex until the user says "Send"? (V1 Recommendation: Hold in Cortex for review).
- **Deep Threading:** How to handle 20+ message email threads without blowing the context window for extraction agents.
