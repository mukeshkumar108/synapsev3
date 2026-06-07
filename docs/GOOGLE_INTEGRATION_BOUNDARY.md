# Google Integration Boundary

## 1. Decision

**Use direct Google APIs with OAuth 2.0 offline access for production Calendar and Gmail integration.**

Do not use the Model Context Protocol (MCP) as the background synchronization architecture for Synapse V3.

---

## 2. Why Not MCP

MCP is an excellent pattern for interactive assistant/tooling contexts where a user is present and guiding the action in real-time. However, Cortex operates primarily as a passive background intelligence engine. MCP lacks the necessary primitives for our requirements:

- **Scheduled Sync:** Cortex needs to pull data continuously in the background without user interaction.
- **Silent Email Triage:** High-volume processing that should not clutter a chat context window or require runtime LLM orchestration just to fetch data.
- **Calendar State Freshness:** Ensuring the day's schedule is accurate requires deterministic polling or webhooks.
- **Token Management:** Handling token refresh and revokes securely in long-running processes.
- **Reliability:** Managing retries, backoffs, and rate limits natively against the provider.
- **Auditability:** Tracking exactly when and how a piece of external data entered the Cortex pipeline.
- **Provider-Specific Normalization:** Mapping complex Google payloads (like recurring events or nested email threads) into clean Cortex primitives before extraction agents touch them.

---

## 3. Ownership

To maintain a clean architecture, responsibilities are strictly divided across the stack:

### Product / Backend Owns:
- OAuth consent flows and user authorization UI.
- Connected account records in the primary database.
- Secure token storage (encrypted at rest) and token refresh lifecycles.
- Managing reconnect flows if a token is revoked.
- Enforcing provider scopes.

### Cortex Owns:
- Accepting normalized import payloads (from the backend/workers).
- Processing via `calendar_import` endpoints or the `outbox`.
- Email triage and intelligence extraction.
- Promoting extracted data to `confirmed_facts` and `candidates`.
- Automatically writing `timeline_events` for any imported data or state change.
- Providing synthesized intelligence via surfacing packets (e.g., `morning_briefing_packet`).

### Sophie Runtime Owns:
- Real-time, user-triggered tool calls during an active chat session.
- The Confirmation UX (e.g., "Would you like me to send this draft?").
- Final voice and tone of how external data is presented to the user.
- Showing drafts, schedule previews, and action results.

---

## 4. Two Access Paths

Data moves between Google and Synapse through two distinct paths:

### A. Slow Path (Background Worker)
- **Role:** Observation and passive intelligence.
- **Flow:** 
  1. A backend worker uses the offline refresh token to periodically sync calendar events or read recent Gmail.
  2. The worker formats the raw data into normalized payloads and pushes them into Cortex (via outbox or direct import endpoints).
  3. Extraction, reconciliation, and surfacing happen asynchronously.
- **Outcome:** The user's background intelligence (timeline, schedule, memory) stays up to date without interaction.

### B. Fast Path (Sophie Tool Call)
- **Role:** Interactive execution and real-time retrieval.
- **Flow:**
  1. User asks for a specific action during chat (e.g., "Add a meeting with John tomorrow at 2 PM" or "What did the last email from Sarah say?").
  2. Sophie uses direct Google API access (or a fast backend tool service proxying the request).
  3. **Crucial:** Write/send actions require explicit user confirmation via Sophie's UX before execution.
  4. After execution, the backend writes the result back into Cortex (e.g., creating a `timeline_events` entry for the sent email or booked meeting) to ensure Cortex's state remains accurate.

---

## 5. Scopes

OAuth scopes must be staged and follow the principle of least privilege. Use the narrowest scopes possible. Avoid broad/full-mail scopes (`https://mail.google.com/`) unless absolutely required by a future feature.

**Calendar V1 Read:**
- `https://www.googleapis.com/auth/calendar.events.readonly` (preferred) or `calendar.readonly`

**Calendar Write-Ready:**
- `https://www.googleapis.com/auth/calendar.events`

**Gmail V1 Read:**
- `https://www.googleapis.com/auth/gmail.readonly`

**Gmail Draft (V1 Extension):**
- `https://www.googleapis.com/auth/gmail.compose`

**Gmail Send (Future Phase):**
- `https://www.googleapis.com/auth/gmail.send` (Only to be introduced later, and **only** accompanied by explicit user confirmation UI).

---

## 6. Normalized Payloads

When the backend worker pushes data into Cortex, it must not send raw Google API JSON. It must send a normalized payload.

### Calendar Event Import Payload
```json
{
  "provider_id": "google_calendar_event_id",
  "source_account": "user@gmail.com",
  "title": "Project Sync",
  "description": "Weekly alignment",
  "start_time": "2026-05-22T10:00:00Z",
  "end_time": "2026-05-22T11:00:00Z",
  "status": "confirmed",
  "attendees": ["alice@example.com", "bob@example.com"],
  "is_recurring": true,
  "html_link": "https://calendar.google.com/..."
}
```

### Gmail Message/Thread Triage Payload
```json
{
  "provider_thread_id": "google_thread_id",
  "provider_message_id": "google_message_id",
  "source_account": "user@gmail.com",
  "from": "manager@company.com",
  "to": ["user@gmail.com"],
  "cc": [],
  "subject": "Q3 Roadmap Draft",
  "body_text": "Please review the attached roadmap by Friday...",
  "received_at": "2026-05-22T08:30:00Z",
  "labels": ["INBOX", "IMPORTANT"]
}
```

---

## 7. Token & Security Notes

- **Encryption:** Refresh tokens and access tokens must be encrypted at rest in the product backend database.
- **Isolation:** Never expose raw provider access tokens to Cortex agents. Agents only deal with the text/data inside the normalized payload.
- **Graceful Failure:** If a token is revoked or expires and cannot be refreshed, the worker must fail gracefully, halt the sync for that user, and flag the product layer to prompt the user to reconnect.
- **User Control:** The user must be able to disconnect the integration and revoke access at any time from the product frontend.
- **Auditability:** Every write operation made to a provider (Calendar/Gmail) through the Fast Path must leave an audit trail in Cortex (via `timeline_events` and/or `outbox` records).

---

## 8. Immediate Implementation Sequence

1. **Calendar Read-Only Connector Spike:** Cortex already conceptually supports read-only ingestion. Build a backend worker spike to fetch events using offline OAuth and push them via a `calendar_import` normalized payload.
2. **Gmail Triage Implementation:** Set up the Gmail read worker to push normalized email payloads into the Cortex `outbox`, triggering the new `email_triage_agent`.
3. **Calendar Write-Ready:** Implement the Fast Path tool call for Sophie to propose events, request confirmation, and write back to Google Calendar, followed by updating Cortex's timeline.
4. **Gmail Draft-for-Review:** Implement the slow path capability where Cortex generates a drafted reply (stored as a candidate/draft) and Sophie surfaces it for review and manual sending.
