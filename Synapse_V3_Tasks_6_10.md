

**Synapse V3**

Tasks 6–10: Ship Sophie

Session ingest · Recall · Runtime integration · Actions · Calendar \+ Gmail

*Tasks 1–5 built the pipeline. Tasks 6–10 connect Sophie to it. After Task 10, real users can use Sophie with real memory, real calendar, and real email. Build in order. One task at a time.*

Date: 2026-05-22   Status: APPROVED FOR BUILD

| Where we are |
| :---- |

Tasks 1–5 complete. The V3 pipeline exists and works in isolation. Sophie is still talking to Synapse V2. Nothing is wired together yet. These five tasks fix that.

| Done | Task 1 scaffold/schema · Task 2 triage/session summary · Task 3 extraction/candidates · Task 4 reconciliation/confirmed\_facts/timeline · Task 5 surfacing/serving endpoints · State decay · Calendar read-only import |
| :---- | :---- |
| **Not done** | Sophie → Cortex V3 wiring · Session ingest · Recall · Actions API · Gmail |
| **Users waiting** | Mukesh · Ashley · Morgan · Krishna · Vinesh |
| **The gap** | Sophie cannot remember anything across sessions yet because she is not calling V3. That is what Tasks 6–10 fix. |

| Task 6 — V3 Session Ingest |
| :---- |

| Why this comes now Tasks 1–5 built the pipeline but nothing feeds it. Sophie sessions are not being stored or processed in V3 yet. Without this task, the entire pipeline is idle. This is the entry point. |
| :---- |

**Goal**

User talks to Sophie. The session transcript enters Cortex V3. The extraction pipeline runs. Confirmed facts get written. This is the pipe that makes everything else work.

**Files to add / change**

| workers/session\_ingest.py | New. Accepts a sealed session transcript. Writes to outbox. Triggers pipeline. |
| :---- | :---- |
| **core/endpoints/ingest.py** | New. POST /v3/session/ingest endpoint. |
| **core/pipeline\_runner.py** | New. Orchestrates: session summary → triage → extraction → reconciliation → confirmation. Called after ingest. |
| **tests/test\_task6.py** | New. Tests for this task. |

**Exact behaviour**

| POST /v3/session/ingest {   user\_id: string,   session\_id: string,   messages: \[ { role: user|assistant, content: string, timestamp: ISO } \],   source\_type: 'chat',   metadata: { timezone, platform } } → Write raw transcript to outbox (status: pending) → Store full transcript as raw\_content in outbox row → Trigger pipeline\_runner asynchronously (do not block response) → Return { success: true, outbox\_id: uuid, status: 'processing' } pipeline\_runner runs:   1\. session\_summary\_agent → writes session\_summaries row   2\. triage\_agent → returns flags   3\. extraction agents (parallel, only flagged ones)   4\. reconciliation\_agent   5\. confirmation → writes confirmed\_facts \+ timeline\_events |
| :---- |

**Do not**

| Block the HTTP response while the pipeline runs. Return immediately, process async. Store the transcript anywhere other than the outbox raw\_content column for now. No Mongo yet. Run the pipeline synchronously inside the request handler. Change the existing agent files. pipeline\_runner calls them, it does not modify them. |
| :---- |

**Tests required**

* POST /v3/session/ingest with a real 10-message transcript returns 200 with outbox\_id.

* Outbox row exists with correct user\_id and status: pending.

* Pipeline runs and completes — session\_summaries row exists after processing.

* At least one confirmed\_facts row exists if the transcript contained a clear task.

* At least one timeline\_events row exists after pipeline completes.

**Verification commands**

| curl \-X POST http://localhost:8000/v3/session/ingest \\   \-H 'Content-Type: application/json' \\   \-d '{"user\_id":"test\_user","session\_id":"s1",        "messages":\[{"role":"user","content":"remind me to call Ashley tomorrow",        "timestamp":"2026-05-22T10:00:00Z"}\],        "source\_type":"chat","metadata":{}}' \# Check DB SELECT \* FROM outbox WHERE user\_id='test\_user' ORDER BY created\_at DESC LIMIT 1; SELECT \* FROM session\_summaries WHERE user\_id='test\_user' ORDER BY created\_at DESC LIMIT 1; SELECT \* FROM confirmed\_facts WHERE user\_id='test\_user' ORDER BY created\_at DESC LIMIT 3; SELECT \* FROM timeline\_events WHERE user\_id='test\_user' ORDER BY created\_at DESC LIMIT 3; |
| :---- |

**Definition of done**

| POST /v3/session/ingest returns 200 immediately. Pipeline runs async and completes without error. session\_summaries row created for every ingested chat session. confirmed\_facts and timeline\_events rows created for clear tasks and events in transcript. All tests in tests/test\_task6.py pass. |
| :---- |

| Task 7 — Recall V1 |
| :---- |

| Why this comes now Users will ask Sophie 'remember when I told you about X?' Sophie needs to be able to retrieve something useful. Without recall, memory is write-only — it gets stored but never retrieved on demand. This is the read side of the pipeline. |
| :---- |

**Goal**

User asks Sophie to recall something. Sophie queries Cortex and gets back relevant confirmed facts, session summaries, and timeline events. Not perfect. Useful. V1.

**Files to add / change**

| core/recall.py | New. Recall logic: vector search over confirmed\_facts \+ keyword search over session\_summaries. |
| :---- | :---- |
| **core/endpoints/recall.py** | New. POST /v3/recall endpoint. |
| **tests/test\_task7.py** | New. |

**Exact behaviour**

| POST /v3/recall {   user\_id: string,   query: string,   // 'remember when I mentioned Ashley' or 'what tasks do I have'   limit: int       // default 5 } Recall strategy (in order):   1\. Search confirmed\_facts by semantic similarity (pgvector on content JSONB)   2\. Search session\_summaries by keyword match on summary text   3\. Search timeline\_events by title \+ summary Return: {   facts: \[ { id, fact\_type, content, confidence, last\_seen\_at } \],   summaries: \[ { id, summary, tags, occurred\_at } \],   timeline: \[ { id, event\_type, title, occurred\_at } \],   certainty: 'high' | 'partial' | 'low' } certainty \= high if confirmed\_facts match found with confidence \> 0.8 certainty \= partial if only summaries or timeline matched certainty \= low if no strong match — return best guesses with low flag |
| :---- |

**Do not**

| Return raw transcripts. Return structured facts and summaries only. Hallucinate. If certainty is low, say so in the response. Build a complex vector index yet. pgvector on confirmed\_facts content::text is enough for V1. Return more than 5 results per category without a higher limit being set. |
| :---- |

**Tests required**

* Ingest a session containing 'Ashley is stressed about her job'. Then POST /v3/recall with query 'Ashley'. Verify Ashley appears in facts or summaries.

* POST /v3/recall with a query that matches nothing. Verify certainty: low and no hallucinated results.

* Verify response always returns the correct shape even when empty.

**Definition of done**

| POST /v3/recall returns relevant confirmed\_facts for queries matching ingested content. Certainty field correctly reflects match quality. No hallucinated results ever returned. All tests in tests/test\_task7.py pass. |
| :---- |

| Task 8 — Sophie Runtime Integration V1 |
| :---- |

| Why this comes now Tasks 1–7 built the full V3 pipeline and recall. Sophie still does not use any of it. This task wires Sophie to Cortex V3 for the three moments that matter most: session start, recall, and session end. After this task Sophie has real memory. |
| :---- |

**Goal**

Sophie calls Cortex V3 at three moments: on session start (gets instruction packet), during session when user asks to recall something (calls /v3/recall), and on session end (posts transcript to /v3/session/ingest). No more V2 calls for these three moments.

**Files to add / change**

| runtime/cortex\_client.py | New. Thin client Sophie uses to call Cortex V3. Three methods: get\_startup\_packet(), recall(query), ingest\_session(messages). |
| :---- | :---- |
| **runtime/sophie\_runtime.py** | Modify. Replace V2 startbrief call with cortex\_client.get\_startup\_packet(). Add cortex\_client.recall() when user asks to remember something. Add cortex\_client.ingest\_session() on session close. |
| **tests/test\_task8.py** | New. Integration tests for the wired flow. |

**Exact behaviour**

| // SESSION START cortex\_client.get\_startup\_packet(user\_id) → GET /v3/sessions/instruction-packet?user\_id=X → Returns: { session\_instructions, relevant\_topics,              worth\_attention, tone\_note, avoid } → Sophie uses this to open the session // DURING SESSION — recall trigger // Trigger words: 'remember', 'did I', 'what did I say about', // 'do you know', 'tell me about' cortex\_client.recall(user\_id, query\_text) → POST /v3/recall → Sophie narrates result naturally — does not dump raw JSON // SESSION END // Trigger: user closes app, 10min inactivity, explicit goodbye cortex\_client.ingest\_session(user\_id, session\_id, messages) → POST /v3/session/ingest → Fire and forget — do not wait for pipeline to complete |
| :---- |

**Startup packet — what Sophie does with it**

| session\_instructions | Sophie reads this before responding. It sets her posture for this session. |
| :---- | :---- |
| **relevant\_topics** | Sophie can raise these if they come up naturally. Not forced. |
| **worth\_attention** | Max 3 items. Sophie surfaces at most one of these per session unprompted. |
| **tone\_note** | Sophie adjusts her energy accordingly. If tone\_note says 'user had a hard day' she is warmer. |
| **avoid** | Sophie never raises these. If user brings them up, she responds but does not initiate. |

**Do not**

| Remove V2 entirely in this task. Keep V2 running as fallback. V3 is the primary path, V2 is the safety net for now. Show the raw packet JSON to the user. Sophie translates it into natural conversation. Call /v3/recall on every message. Only trigger on explicit recall language. Wait for session ingest to complete before ending the session. Fire and forget. Break Sophie's existing conversation flow. This task adds three API calls, nothing more. |
| :---- |

**Tests required**

* Session start: Sophie calls GET /v3/sessions/instruction-packet and the result is present in the session context.

* Recall: User message containing 'remember' triggers POST /v3/recall and Sophie uses the result.

* Session end: POST /v3/session/ingest is called with the full message array when session closes.

* Full flow test: ingest a session, start a new session, verify startup packet reflects content from the previous session.

**Definition of done**

| Sophie calls /v3/sessions/instruction-packet on every session start. Sophie calls /v3/recall when user asks to remember something. Sophie calls /v3/session/ingest when session ends. A real user (you) can have a conversation, say 'remind me to call Ashley tomorrow', end the session, start a new session, and Sophie knows about the reminder. All tests in tests/test\_task8.py pass. |
| :---- |

| Task 9 — Actions and Events API |
| :---- |

| Why this comes now Users say 'remind me to...' and 'add that to my calendar' in conversation. Sophie needs to handle these explicitly, confirm with the user, and write to Cortex. This is the user control layer — memory the user creates deliberately, not just what gets extracted. |
| :---- |

**Goal**

Explicit user commands write to Cortex with user confirmation. Remind me, add to calendar, create a task, mark something done. Clean confirmation flow. Sophie owns the UX, Cortex owns the storage.

**Files to add / change**

| core/endpoints/actions.py | New. POST /v3/actions/task, POST /v3/actions/event, PATCH /v3/actions/task/:id, DELETE /v3/actions/task/:id |
| :---- | :---- |
| **core/endpoints/memory\_control.py** | New. POST /v3/memory/correct, POST /v3/memory/dismiss, POST /v3/memory/forget |
| **runtime/action\_handler.py** | New. Sophie-side logic: detect command intent → extract parameters → confirm with user → call Cortex. |
| **tests/test\_task9.py** | New. |

**Exact behaviour**

| // TASK CREATION POST /v3/actions/task { user\_id, title, due\_date, reminder\_at, priority, source: 'explicit' } → Writes directly to confirmed\_facts (fact\_type: task, confidence: 1.0) → Writes timeline\_event (event\_type: task\_confirmed) → Returns { id, title, due\_date, reminder\_at } // EVENT CREATION POST /v3/actions/event { user\_id, title, date, time, location, attendees, source: 'explicit' } → Writes directly to confirmed\_facts (fact\_type: event, confidence: 1.0) → Writes timeline\_event (event\_type: event\_confirmed) → If calendar worker connected: also writes to Google Calendar → Returns { id, title, date, time } // MEMORY CORRECTION POST /v3/memory/correct { user\_id, fact\_id, correction: 'that is wrong, it was Tuesday' } → Sets confirmed\_facts.user\_corrected \= true → Sets confirmed\_facts.correction\_note \= correction → Sets confirmed\_facts.status \= 'corrected' → Writes timeline\_event (event\_type: user\_correction) // FORGET POST /v3/memory/forget { user\_id, fact\_id } → Sets confirmed\_facts.status \= 'dismissed' → Sophie never surfaces this again |
| :---- |

**Sophie confirmation flow**

| User: 'remind me to call Ashley tomorrow at 9am' Sophie: 'Got it — remind you to call Ashley tomorrow at 9am. Shall I set that?' User: 'yes' Sophie calls POST /v3/actions/task Sophie: 'Done. I'll remind you tomorrow at 9am.' User: 'forget what I said about the meeting being cancelled' Sophie: 'Done, I'll forget that.' Sophie calls POST /v3/memory/forget with the relevant fact\_id |
| :---- |

**Do not**

| Write to confirmed\_facts without user confirmation for explicit commands. Always confirm first. Bypass the confirmation step even for 'obvious' requests. Build a complex intent classifier. Simple keyword matching is fine for V1: 'remind me', 'add to calendar', 'forget', 'that's wrong', 'mark that done'. Connect to Google Calendar in this task. That is Task 10\. Just write to confirmed\_facts for now. |
| :---- |

**Definition of done**

| 'Remind me to call Ashley tomorrow at 9am' → Sophie confirms → confirmed\_facts row created with confidence 1.0. 'Forget that' → relevant confirmed\_facts row status set to dismissed. 'That's wrong' → user\_corrected set to true, correction\_note stored. All explicit writes have timeline\_events side effects. All tests in tests/test\_task9.py pass. |
| :---- |

| Task 10 — Calendar and Gmail Real Integrations |
| :---- |

| Why this comes now Users are expecting calendar and email. Sophie can now store and retrieve memory, handle explicit commands, and has real context at session start. Now we connect real external data so the daily overview has real calendar events and Sophie can see what is in the inbox. |
| :---- |

**Goal**

Google Calendar syncs into Cortex. Gmail is read in the background. Sophie's daily overview shows real events and real email priorities. Users feel immediately that Sophie knows their day.

**Files to add / change**

| workers/calendar\_worker.py | New. Google Calendar OAuth \+ sync. Reads events, writes to confirmed\_facts. Runs every 15 min. |
| :---- | :---- |
| **workers/gmail\_worker.py** | New. Gmail OAuth \+ read. Reads inbox, writes raw email content to outbox. Runs every 30 min. |
| **core/oauth.py** | New. Google OAuth 2.0 token storage and refresh logic. Shared by both workers. |
| **core/endpoints/connect.py** | New. GET /v3/connect/google — initiates OAuth flow. GET /v3/connect/google/callback — handles redirect. |
| **core/endpoints/overview.py** | Modify. GET /v3/overview/daily now reads calendar events from confirmed\_facts and email priorities from surfacing agent output. |
| **tests/test\_task10.py** | New. |

**Calendar worker — exact behaviour**

| calendar\_worker runs every 15 minutes per connected user 1\. Fetch events from Google Calendar API for next 7 days 2\. For each event:    → Check if confirmed\_facts row exists with same google\_event\_id    → If new: write to confirmed\_facts (fact\_type: event, confidence: 1.0)              write timeline\_event (event\_type: event\_confirmed)              source: 'google\_calendar'    → If exists and changed: UPDATE confirmed\_facts    → If deleted in Google: set confirmed\_facts.status \= 'dismissed' 3\. Calendar events write directly to confirmed\_facts — high confidence    BUT always write source\_id and timeline\_event    so reconciliation can reason over conflicts later |
| :---- |

**Gmail worker — exact behaviour**

| gmail\_worker runs every 30 minutes per connected user 1\. Fetch unread emails from last 24h (or since last sync) 2\. For each email thread:    → Write raw email content to outbox (source\_type: 'email')    → Pipeline processes it: triage → extraction → reconciliation    → Extraction agents find tasks, events, threads in email content 3\. Surfacing agent output includes email priorities:    → 'Email from Mark needs a reply'    → 'Invoice from Acme is overdue'    These appear in worth\_attention in the startup packet 4\. Daily overview includes top 3 email priorities Note: Gmail worker READS only in this task. Drafting is a Sophie tool call (Task 10b — comes later). |
| :---- |

**OAuth setup**

| core/oauth.py handles: \- Google OAuth 2.0 authorization URL generation \- Callback handling and token exchange \- Refresh token storage (encrypted in Postgres — new table: user\_connections) \- Access token refresh when expired user\_connections table:   id UUID PK   user\_id TEXT   provider TEXT  \-- 'google\_calendar' | 'gmail'   access\_token TEXT (encrypted)   refresh\_token TEXT (encrypted)   token\_expires\_at TIMESTAMP   scopes TEXT\[\]   connected\_at TIMESTAMP   status TEXT  \-- 'active' | 'revoked' | 'error' Scopes needed:   Google Calendar: https://www.googleapis.com/auth/calendar.readonly                    https://www.googleapis.com/auth/calendar.events   Gmail:           https://www.googleapis.com/auth/gmail.readonly   (Add gmail.compose later when drafting is built) |
| :---- |

**Do not**

| Build Gmail drafting or sending in this task. Read only. Store OAuth tokens unencrypted. Encrypt at rest. Crash or break Sophie if Google connection fails. Graceful degradation — daily overview works without calendar, just shows less. Run calendar or Gmail workers synchronously inside an HTTP request. They run on a schedule. Build WhatsApp, Instagram, or any other source in this task. |
| :---- |

**Tests required**

* OAuth flow completes and refresh token stored in user\_connections.

* calendar\_worker runs and writes at least one event to confirmed\_facts from a real calendar.

* GET /v3/overview/daily includes calendar events for connected user.

* gmail\_worker runs and writes at least one email thread to outbox.

* GET /v3/sessions/instruction-packet for a user with email includes email-derived items in worth\_attention.

* If Google token is revoked, workers fail gracefully with status: error in user\_connections. Sophie still works.

**Definition of done**

| User can connect Google account via /v3/connect/google. Calendar events appear in GET /v3/overview/daily. Email priorities appear in the startup packet worth\_attention. Sophie can say 'you have a call at 2pm' without being told about it. Sophie can say 'you have an email from Mark that looks important' without being told. All tests in tests/test\_task10.py pass. |
| :---- |

| After Task 10 — what you have |
| :---- |

| *Sophie has real memory. She remembers what users tell her. She knows their calendar. She sees their inbox. She surfaces what matters. She picks up where she left off. This is the product. Ship it to the five users. Then listen.* |
| :---- |

| What comes next | Proactive outreach (push/WhatsApp). Gmail drafting. User memory control UI. WhatsApp ingestion. End of day summary. Weekly patterns. These all build on what Tasks 6–10 deliver. |
| :---- | :---- |
| **What does not come next** | More architecture docs. More spec debates. More Mongo decisions. More endpoint sprawl. Real users using Sophie and telling you what is wrong. That is the only input that matters now. |

*Synapse V3 Tasks 6–10 · 2026-05-22 · Give Task 6 to Codex now.*