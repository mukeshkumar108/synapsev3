

**Synapse V3**

Build Specification

LLM-first · Modular · Clean slate

*This is the document Codex opens on day one. Schema, agent contracts, prompt shapes, Codex tasks in order. No fluff.*

Date: 2026-05-21   Version: V3.0   Status: APPROVED FOR BUILD

| 1   What we are building |
| :---- |

| *An AI companion that feels like someone who genuinely knows you — remembers what you told it, reaches out when it matters, and gets more useful every day. The pipeline is invisible. The product is presence.* |
| :---- |

Sophie talks to users in real time. Synapse V3 runs in the background, extracting what matters from every conversation, email, and message, reconciling it with what it already knows, and preparing intelligence packets that make Sophie feel alive.

| Sophie runtime | Conversation, tone, tools, response generation, delivery. Consumes prepared context. Never stores anything. |
| :---- | :---- |
| **Synapse V3 core** | Stores and serves normalised intelligence. Does not contain agent logic. Boring and stable by design. |
| **Specialist agents** | Separate files. One job each. Replace Python logic with LLM judgment where language is involved. |
| **External sources** | Chat, WhatsApp, Email, Calendar. All feed the same pipeline via the outbox. |

| The one rule Agents read raw source material. Never a summary. Never another agent's output. Always the original. One file per agent. One job per agent. If an agent file exceeds 200 lines, treat it as a warning — the agent is probably doing too much. Schema, test helpers, and utility files may naturally be longer. No deterministic logic for language decisions. LLMs decide what is a task, what is the same thing, what is stale. Python only writes to the database. |
| :---- |

| 2   Clean slate — what to copy, what to leave |
| :---- |

The legacy codebase (18,000-line main.py, 8,600-line derived\_pipeline.py) is not being refactored. It is being left behind. Create a new repository: synapse-v3.

| Copy from V2 | Postgres connection utility (db.py). Environment variables (.env). Migration tooling. Auth middleware. The prompts and extraction logic from the 6-pass pipeline — the logic was right, the scaffolding was wrong. |
| :---- | :---- |
| **Leave behind** | Everything in derived\_pipeline.py. Everything in main.py beyond routing. All deterministic merge functions. All candidate table fragmentation. The Graphiti/FalkorDB integration. All legacy loops. |
| **New repo structure** | synapse-v3/agents/ — one file per agent. synapse-v3/workers/ — one file per worker. synapse-v3/core/ — database, serving endpoints. synapse-v3/runtime/ — Sophie fast path. synapse-v3/schema.sql — the six core tables. |

| 3   The six core tables |
| :---- |

These are the only tables that exist on day one. Nothing else. Get these right — everything else builds on them.

**1\. outbox**

*Everything that arrives lands here first. Raw. Unprocessed. The safety net.*

| Column | Type | Purpose |
| :---- | :---- | :---- |
| id | UUID PK | Unique identifier |
| user\_id | TEXT | Owner |
| source\_type | ENUM | chat / whatsapp / email / calendar / sms |
| raw\_content | TEXT | Unmodified original content. Never mutated. |
| received\_at | TIMESTAMP | When it arrived |
| status | ENUM | pending / processing / done / failed |
| retry\_count | INT | For resilience. Max 3\. |
| metadata | JSONB | Source-specific context (thread\_id, sender etc) |

**2\. message\_buffer**

*For message-based sources only. Accumulates individual messages into a processable unit. Seals after 30 minutes of quiet. Becomes an outbox entry when sealed.*

| Column | Type | Purpose |
| :---- | :---- | :---- |
| id | UUID PK | Unique identifier |
| user\_id | TEXT | Owner |
| source\_type | ENUM | whatsapp / sms / dm |
| messages | JSONB\[\] | Accumulating array of individual messages |
| last\_message\_at | TIMESTAMP | Updated on every new message |
| status | ENUM | accumulating / sealed / processed |
| sealed\_at | TIMESTAMP | Set when buffer closes after 30min quiet |

**3\. session\_summaries**

*One row per sealed chat session. Searchable history of the relationship. Chat only — not created for email or WhatsApp.*

| Column | Type | Purpose |
| :---- | :---- | :---- |
| id | UUID PK | Unique identifier |
| user\_id | TEXT | Owner |
| source\_id | UUID | FK to outbox |
| summary | TEXT | \~100 word plain English summary |
| tags | TEXT\[\] | eg stress, planning, relationship, urgent |
| open\_items | JSONB | Things clearly unresolved at session end |
| key\_decisions | JSONB | Things clearly decided |
| emotional\_tone | TEXT | happy / stressed / neutral / anxious / energised |
| occurred\_at | TIMESTAMP | When the conversation happened |

**4\. candidates**

*Everything extracted is a candidate first. Nothing becomes fact without passing through reconciliation and confirmation. The safety buffer between extraction and truth.*

| Column | Type | Purpose |
| :---- | :---- | :---- |
| id | UUID PK | Unique identifier |
| user\_id | TEXT | Owner |
| source\_id | UUID | FK to outbox — always traceable to origin |
| candidate\_type | ENUM | task / event / fact / state / thread / invitation |
| content | JSONB | The extracted item in structured form |
| raw\_evidence | TEXT | Exact text that generated this candidate |
| confidence | FLOAT | 0.0 to 1.0 |
| needs\_confirmation | BOOL | True if ambiguous — Sophie will ask user |
| status | ENUM | pending / confirmed / dismissed / superseded / expired |
| reconciliation\_instruction | ENUM | CREATE / MERGE / UPDATE / DISMISS — set by reconciliation agent |
| merge\_target\_id | UUID | FK to confirmed\_facts if MERGE/UPDATE |
| created\_at | TIMESTAMP | When extracted |

**5\. confirmed\_facts**

*The source of truth. Everything Sophie uses comes from here. Immutable audit trail via source\_ids back to raw content.*

| Column | Type | Purpose |
| :---- | :---- | :---- |
| id | UUID PK | Unique identifier |
| user\_id | TEXT | Owner |
| fact\_type | ENUM | task / event / preference / relationship / state / thread / identity |
| domain | ENUM | profile / people / goals / workstreams / habits / obligations / events / state / opportunities |
| content | JSONB | The confirmed item |
| confidence | FLOAT | Starts at extraction confidence, bumps on reinforcement |
| first\_seen\_at | TIMESTAMP | When first extracted |
| last\_seen\_at | TIMESTAMP | When last reinforced or referenced |
| last\_confirmed\_at | TIMESTAMP | When user last confirmed or system last validated |
| source\_ids | UUID\[\] | All outbox entries that contributed to this fact |
| status | ENUM | active / stale / historical / corrected / dismissed |
| user\_corrected | BOOL | True if user explicitly corrected this |
| correction\_note | TEXT | What the user said when correcting |
| expires\_at | TIMESTAMP | For time-limited facts like state and events |

**6\. timeline\_events**

*Written automatically as a side effect of every confirmed\_facts write. One unified timeline with a type field. Do not write to this directly — it is always a side effect.*

| Column | Type | Purpose |
| :---- | :---- | :---- |
| id | UUID PK | Unique identifier |
| user\_id | TEXT | Owner |
| event\_type | ENUM | task\_confirmed / event\_confirmed / fact\_learned / state\_change / session / outreach\_sent / item\_dismissed / user\_correction / relationship\_update |
| timeline\_type | ENUM | interaction / user\_life / calendar / relationship / system |
| title | TEXT | Human readable summary |
| summary | TEXT | Brief description |
| occurred\_at | TIMESTAMP | When it happened in the world |
| observed\_at | TIMESTAMP | When Synapse learned about it — can differ from occurred\_at |
| source\_id | UUID | FK to outbox or confirmed\_facts |
| related\_fact\_ids | UUID\[\] | Confirmed facts this event relates to |
| status | ENUM | current / stale / historical / corrected |
| confidence | FLOAT | Inherited from source |

| 4   The agent roster |
| :---- |

Nine agents. One file each. Every agent follows the same contract: takes structured input, returns structured JSON, nothing else. No database calls inside agents. No calls to other agents.

| *Agent contract — every agent receives: { user\_id, source\_type, raw\_content, context } and returns: { agent, status, items\[\], errors\[\], confidence\_notes }. Items are always arrays even if empty. Errors are always surfaced, never swallowed.* |
| :---- |

| Agent 1 — Session Summary  (session\_summary\_agent.py) |  |
| :---- | :---- |
| **Job** | Read a sealed chat transcript. Write a compressed, searchable summary. This is the only agent that creates a session\_summaries row. |
| **Input** | raw\_content: full transcript text. source\_id: outbox UUID. |
| **Output** | { summary: string \~100 words, tags: string\[\], open\_items: object\[\], key\_decisions: object\[\], emotional\_tone: string } |
| **Prompt shape** | You are reading a conversation transcript. Return a JSON object with: a plain-English summary of what happened (under 120 words), an array of tags from this list \[stress, planning, relationship, urgent, health, work, personal, celebration, conflict\], any items that are clearly unresolved, any decisions that were clearly made, and the overall emotional tone (happy/stressed/neutral/anxious/energised). Return only valid JSON. |
| **Model** | Any cheap fast model. gemma-4 or equivalent. |
| **Must never** | Summarise in a way that loses nuance. Do not interpret or judge. Do not extract tasks or events — that is not your job. |

| Agent 2 — Triage  (triage\_agent.py) |  |
| :---- | :---- |
| **Job** | Read raw content. Return boolean flags only. Determines which extraction agents run. Must be fast and cheap. |
| **Input** | raw\_content: transcript, email, or buffered messages. source\_type: chat / email / whatsapp. |
| **Output** | { has\_tasks: bool, has\_events: bool, has\_facts: bool, has\_state\_change: bool, has\_threads: bool, has\_invitations: bool, emotional\_weight: low/medium/high, memory\_worthy: bool } |
| **Prompt shape** | You are a classifier. Read this content and return a JSON object with boolean flags indicating what types of information are present. has\_tasks: are there any to-dos, reminders, or commitments? has\_events: are there any calendar items, meetings, or time-anchored plans? has\_facts: are there any durable facts or preferences about the user or people they know? has\_state\_change: has the user's emotional or situational state changed? has\_threads: are there any unresolved ongoing situations? has\_invitations: any explicit invitations or plans being made? emotional\_weight: low/medium/high. memory\_worthy: is this worth extracting at all? Return only valid JSON. |
| **Model** | Cheapest available model. Speed matters here. |
| **Must never** | Extract anything. Return anything other than the boolean flags. Hallucinate flags that are not clearly present. |

| Agent 3 — Task Extraction  (task\_agent.py) |  |
| :---- | :---- |
| **Job** | Extract tasks, todos, reminders, commitments, and habits from raw content. Runs only if triage has\_tasks is true. |
| **Input** | raw\_content: original unmodified transcript or message content. |
| **Output** | Array of task candidates: \[{ title, description, due\_date, reminder\_at, priority, is\_habit, recurrence, raw\_evidence, confidence }\] |
| **Prompt shape** | You are extracting tasks and commitments from a conversation. Return a JSON array of task objects. Each object must include: title (short, actionable), description (optional context), due\_date (ISO if mentioned, null if not), reminder\_at (ISO if mentioned, null if not), priority (high/medium/low), is\_habit (true if recurring), recurrence (daily/weekly/null), raw\_evidence (exact quote from source), confidence (0.0-1.0). Extract only things that are clearly actionable. Do not infer tasks that were not stated. Return only valid JSON array. |
| **Model** | Mid-tier model. Needs to handle ambiguous natural language. |
| **Must never** | Create tasks from vague statements. Set due\_date if none was mentioned. Return anything other than a JSON array. |

| Agent 4 — Event Extraction  (event\_agent.py) |  |
| :---- | :---- |
| **Job** | Extract calendar events, appointments, invitations, deadlines, and past events worth anchoring to a date. Runs only if triage has\_events or has\_invitations is true. |
| **Input** | raw\_content: original content. current\_date: today's date for relative date resolution. |
| **Output** | Array of event candidates: \[{ title, date, time, duration, location, attendees, is\_invitation, needs\_confirmation, is\_past, raw\_evidence, confidence }\] |
| **Prompt shape** | You are extracting calendar events and time-anchored plans from a conversation. Return a JSON array. Each event must include: title, date (ISO if determinable), time (ISO if mentioned), location (null if not mentioned), attendees (array of names), is\_invitation (true if the user was invited by someone else), needs\_confirmation (true if the event is tentative or unclear), is\_past (true if this event already happened), raw\_evidence (exact quote), confidence (0.0-1.0). Resolve relative dates using the current\_date provided. Return only valid JSON array. |
| **Model** | Mid-tier model. |
| **Must never** | Guess at dates that were not stated. Return non-calendar items. |

| Agent 5 — Fact and Identity Extraction  (fact\_agent.py) |  |
| :---- | :---- |
| **Job** | Extract durable facts, preferences, and identity information about the user and people they mention. Runs only if triage has\_facts is true. |
| **Input** | raw\_content: original content. |
| **Output** | Array of fact candidates: \[{ subject, fact\_type, content, about\_user, person\_name, raw\_evidence, confidence }\] |
| **Prompt shape** | You are extracting durable facts and preferences from a conversation. Return a JSON array. Each fact must include: subject (user or a person's name), fact\_type (preference / trait / relationship / background / constraint), content (the fact in plain English), about\_user (true if this is about the user themselves), person\_name (name if about someone else), raw\_evidence (exact quote), confidence (0.0-1.0). Only extract facts that are clearly stated or strongly implied. Do not infer. Return only valid JSON array. |
| **Model** | Mid-tier model. |
| **Must never** | Extract fleeting opinions as durable facts. Return state or mood information — that belongs to the state agent. |

| Agent 6 — State Extraction  (state\_agent.py) |  |
| :---- | :---- |
| **Job** | Extract the user's current emotional state, focus, energy, and situational context. Runs only if triage has\_state\_change is true. State is always short-lived — never durable. |
| **Input** | raw\_content: original content. |
| **Output** | Single state object: { emotional\_state, current\_focus, energy\_level, stress\_level, notable\_tension, raw\_evidence, confidence, provisional: true } |
| **Prompt shape** | You are reading a conversation to understand how the user is doing right now. Return a single JSON object with: emotional\_state (one word: happy/stressed/anxious/excited/flat/neutral/frustrated), current\_focus (what they are primarily thinking about), energy\_level (high/medium/low), stress\_level (high/medium/low), notable\_tension (any specific worry or pressure, null if none), raw\_evidence (quotes that support this reading), confidence (0.0-1.0). Always include provisional: true. State is temporary — never mark it as durable. Return only valid JSON. |
| **Model** | Mid-tier model. Needs emotional nuance. |
| **Must never** | Mark state as durable or permanent. Diagnose. Use clinical language. State that the user is fine when evidence suggests otherwise. |

| Agent 7 — Thread Extraction  (thread\_agent.py) |  |
| :---- | :---- |
| **Job** | Extract unresolved ongoing situations that deserve follow-up. Runs only if triage has\_threads is true. |
| **Input** | raw\_content: original content. |
| **Output** | Array of thread candidates: \[{ title, summary, involves, last\_status, follow\_up\_question, follow\_up\_after\_hours, raw\_evidence, confidence }\] |
| **Prompt shape** | You are identifying unresolved ongoing situations from a conversation. Return a JSON array. Each thread must include: title (short name for this situation), summary (what is happening), involves (array of people or things involved), last\_status (what was the state of this situation at the end of the conversation), follow\_up\_question (the natural question Sophie could ask to follow up, in conversational language), follow\_up\_after\_hours (how many hours before following up makes sense — e.g. 4 for urgent, 24 for normal, 72 for low priority), raw\_evidence (exact quotes), confidence (0.0-1.0). Only extract genuinely unresolved situations. Return only valid JSON array. |
| **Model** | Mid-tier model. |
| **Must never** | Create threads for things that were clearly resolved. Return tasks or events — those belong to other agents. |

| Agent 8 — Reconciliation  (reconciliation\_agent.py) |  |
| :---- | :---- |
| **Job** | Compare new candidates against existing confirmed facts. Decide whether to CREATE, MERGE, UPDATE, or DISMISS each candidate. Replaces all deterministic deduplication logic. This is the magic bullet. |
| **Input** | new\_candidates: array from extraction agents. existing\_facts: top 10 relevant facts fetched by vector search before this agent runs. Never the full database. |
| **Output** | Array of instructions: \[{ candidate\_id, instruction: CREATE|MERGE|UPDATE|DISMISS, target\_id: null or confirmed\_facts UUID, confidence\_delta: float, reason: string }\] |
| **Prompt shape** | You are a reconciliation agent. You will be given new candidates extracted from a conversation and a set of existing facts from the database. For each candidate, decide: CREATE (this is genuinely new), MERGE (this is the same as an existing fact and should be combined), UPDATE (this updates an existing fact with new information), DISMISS (this is redundant, wrong, or too low confidence to store). Return a JSON array of instructions. Each instruction must include: candidate\_id, instruction (CREATE/MERGE/UPDATE/DISMISS), target\_id (the UUID of the existing fact if MERGE or UPDATE, otherwise null), confidence\_delta (how much to adjust confidence — positive to increase, negative to decrease), reason (one sentence explaining your decision). Return only valid JSON array. |
| **Model** | Best available model. This is the most important agent. Quality matters more than cost here. |
| **Must never** | Access the database directly. Make up target\_ids. Return instructions for candidates that were not in the input. |

| Agent 9 — Surfacing  (surfacing\_agent.py) |  |
| :---- | :---- |
| **Job** | Given everything Synapse knows, decide what deserves attention right now. Runs when the user opens the app and on a schedule. Outputs the ranked brief that becomes the session instruction packet and outreach candidates. |
| **Input** | confirmed\_facts: relevant active facts. tasks: open tasks with due dates. events: upcoming events. state: current living context. recent\_timeline: last 5 timeline events. time\_of\_day: morning/afternoon/evening/night. |
| **Output** | { session\_instructions: string, relevant\_topics: string\[\], worth\_attention: object\[\], suggested\_focus: string, tone\_note: string, avoid: string\[\], stale\_warnings: string\[\] } |
| **Prompt shape** | You are Sophie's chief of staff. Given what you know about the user right now, produce a session brief. session\_instructions: how Sophie should approach this conversation (1-2 sentences). relevant\_topics: things worth raising if they come up naturally (array of short phrases). worth\_attention: the 2-3 most important things right now, each with a title, why it matters, and a suggested way Sophie could raise it. suggested\_focus: the single most important thing. tone\_note: how Sophie should calibrate her energy and empathy. avoid: things that are stale or have been dismissed — do not raise these. stale\_warnings: explicit warnings about context that should not be treated as current. Return only valid JSON. |
| **Model** | Best available model. |
| **Must never** | Include dismissed items. Surface stale state as current. Produce more than 3 worth\_attention items. Overwhelm the brief. |

| 5   The full pipeline — step by step |
| :---- |

**Fast path — real time**

User sends a message. Sophie responds immediately using recent context plus current state from confirmed\_facts. Simultaneously, a lightweight urgency classifier checks if the message needs immediate action (reminder in 5 minutes, emergency). If yes, handle it now. The message also goes into the outbox.

**Slow path — background extraction**

| 1\. MESSAGE ARRIVES    Chat session → outbox (status: pending)    WhatsApp/SMS message → message\_buffer (status: accumulating)    Email → outbox (status: pending)    Calendar update → outbox (status: pending) 2\. BUFFER SEALS (WhatsApp/SMS only)    After 30 min quiet → message\_buffer.status \= sealed    Create outbox entry from sealed buffer 3\. SESSION SUMMARY (chat only)    session\_summary\_agent reads raw\_content    Writes to session\_summaries    Writes timeline\_event (type: session, timeline\_type: interaction) 4\. TRIAGE    triage\_agent reads raw\_content    Returns boolean flags    Determines which extraction agents run 5\. PARALLEL EXTRACTION (only flagged agents run)    task\_agent        → task candidates    event\_agent       → event candidates    fact\_agent        → fact candidates    state\_agent       → state candidates    thread\_agent      → thread candidates    All write to candidates table with status: pending 6\. VECTOR SEARCH    For each candidate, fetch top 10 relevant confirmed\_facts    by semantic similarity    Pass to reconciliation agent 7\. RECONCILIATION    reconciliation\_agent receives candidates \+ relevant existing facts    Returns instructions: CREATE / MERGE / UPDATE / DISMISS    Update candidates.reconciliation\_instruction 8\. CONFIRMATION    Auto-confirm if: explicitly stated \+ complete \+ low-risk (e.g. remind me at 9am tomorrow)    Ask user if: inferred \+ high confidence (e.g. I should probably call Ashley)    Sophie raises needs\_confirmation items naturally in next session    Ambiguous/missing fields → needs\_confirmation regardless of confidence    Weak/contextual only → candidate table only, never confirmed\_facts    Dismissed → candidates.status \= dismissed 9\. WRITE TO CONFIRMED\_FACTS    CREATE → new confirmed\_facts row    MERGE → update existing row, append source\_id    UPDATE → update existing row fields, bump last\_seen\_at, adjust confidence    Side effect → write timeline\_event for every confirmed write 10\. SURFACING (runs periodically \+ on session start)     surfacing\_agent reads active confirmed\_facts, tasks, events, state     Returns session instruction packet     Stored as prepared intelligence item     Consumed by Sophie runtime on next session open |
| :---- |

| 6   The serving layer — what Sophie gets |
| :---- |

Sophie runtime consumes two types of prepared packet. It never queries confirmed\_facts directly. It never runs agents. It only consumes what Synapse has already prepared.

| Session instruction packet | Served when user opens a session. Contains: session\_instructions, relevant\_topics, worth\_attention (max 3), suggested\_focus, tone\_note, avoid list, stale\_warnings. Sophie opens the session already oriented. Endpoint: GET /v3/sessions/instruction-packet |
| :---- | :---- |
| **Outreach packet** | Served when Synapse identifies a proactive reason to reach out. Contains: suggested\_message, reason, ideal\_at window, expires\_at, sensitivity, suppression rules. Sophie does not decide what to say — Synapse prepared it. Endpoint: GET /v3/outreach/active-packet |
| **Memory query** | Sophie can query specific facts during a session. Endpoint: POST /v3/memory/query with { user\_id, query\_text }. Returns top 5 relevant confirmed\_facts by vector search. |
| **Daily overview** | Served on demand or at session start. Endpoint: GET /v3/overview/daily. Returns: schedule (from events), open tasks, worth\_attention, suggested\_focus. |

| 7   Codex tasks — in exact order |
| :---- |

Build in this order. Do not jump ahead. Each task is a working, tested unit before the next begins.

| 1 | Schema and scaffolding *Create the repo, the six core tables, and the agent contract. Nothing else.* mkdir synapse-v3. Copy db.py, .env, migration tooling from V2. Create schema.sql with exactly the six tables defined in Section 3\. No other tables. Create agents/ directory. Create agent\_contract.py defining the standard input/output shape every agent must follow. Create a simple test\_pipeline.py CLI that reads a hardcoded transcript and will eventually run it through the pipeline. Verify: migrations run cleanly. Tables exist. Contract file exists. CLI runs without error. |
| :---: | :---- |

| 2 | Triage agent \+ session summary agent *Two agents working against a real transcript. Output verified.* Build agents/triage\_agent.py following the contract. Prompt from Section 4\. Build agents/session\_summary\_agent.py following the contract. Prompt from Section 4\. Wire both into test\_pipeline.py. Feed 3 different test transcripts. Verify: triage returns correct boolean flags for each transcript. Session summary produces a readable \~100 word summary with tags. Unit tests for both agents. Must pass before moving on. |
| :---: | :---- |

| 3 | Parallel extraction agents *All five extraction agents working. Candidates written to database.* Build agents/task\_agent.py, event\_agent.py, fact\_agent.py, state\_agent.py, thread\_agent.py. All follow the contract. Prompts from Section 4\. Wire into test\_pipeline.py — triage flags determine which agents run. All extraction agents write candidates to the candidates table. Test with 5 diverse transcripts including WhatsApp-style fragmented messages. Verify: each agent only extracts its domain. No cross-contamination. Candidates table populates correctly with raw\_evidence always present. |
| :---: | :---- |

| 4 | Reconciliation agent \+ confirmation *The magic bullet. LLM deduplication replacing all Python merge logic.* Implement vector search: before reconciliation runs, fetch top 10 relevant confirmed\_facts for each batch of candidates using pgvector. Build agents/reconciliation\_agent.py. Prompt from Section 4\. Takes candidates \+ relevant existing facts. Returns CREATE/MERGE/UPDATE/DISMISS instructions. Implement confirmation logic: confidence \>= 0.8 and not needs\_confirmation → write to confirmed\_facts. Below threshold → status: needs\_confirmation. Implement timeline\_event side effect: every confirmed\_facts write automatically creates a timeline\_events row. Test with a scenario where the same fact appears across multiple sessions. Verify MERGE works correctly. Verify confidence bumps on reinforcement. Verify: no duplicate confirmed\_facts. source\_ids array correctly traces back to original outbox entries. |
| :---: | :---- |

| 5 | Surfacing agent \+ serving endpoints *Sophie gets a brief. The pipeline is end to end.* Build agents/surfacing\_agent.py. Prompt from Section 4\. Build GET /v3/sessions/instruction-packet — runs surfacing agent, returns session brief. Build GET /v3/overview/daily — returns schedule, open tasks, worth\_attention. Build POST /v3/memory/query — vector search over confirmed\_facts. Build POST /v3/outbox/ingest — the entry point for all new content. Wire Sophie runtime to consume instruction-packet on session open. End to end test: ingest a transcript → pipeline runs → Sophie opens next session with correct brief. This is the milestone. When this works, the pipeline is live. |
| :---: | :---- |

| 8   What comes after the pipeline |
| :---- |

Do not build any of this until all five Codex tasks above are complete and tested.

| Outreach channel | Choose one: WhatsApp Business API or push notification. Build the delivery mechanism. Wire to GET /v3/outreach/active-packet. |
| :---- | :---- |
| **Message buffer worker** | 30-minute seal logic for WhatsApp and SMS. Watches message\_buffer, seals on quiet, creates outbox entry. |
| **Email worker** | Gmail read. Extracts items via the same extraction agents. Writes to outbox with source\_type: email. |
| **Calendar worker** | Google Calendar sync. Writes events to confirmed\_facts directly (high confidence). BUT: must still write timeline\_event and source\_id for every import. Reconciliation can reason over calendar events later if they conflict with chat or email context. |
| **State decay worker** | Periodically reviews state and provisional facts. Marks as stale after 48h unless reinforced. Updates confirmed\_facts.status. |
| **User memory control** | Text commands: forget that, that's wrong, that's done, remember this. Each creates a timeline\_event and updates/suppresses confirmed\_facts. |
| **Prepared intelligence agents** | Companion reach-out, action, daily planning agents. Run after the core pipeline is stable. Write outreach packets. |

**The one thing to remember**

| *The pipeline is invisible. Sophie talking to users is visible. Build the pipeline well enough that Sophie feels alive. Then ship. Then improve. The six months of learning what not to build was not wasted — it is why V3 will work.* |

# Synapse V3 Build Principles

## Source of truth

The V3 build spec controls:
- architecture
- task order
- six-table schema
- repo boundaries
- agent contract
- no legacy monolith imports

The V2 intelligence export controls:
- prompt inspiration
- labels and metadata worth preserving
- lifecycle concepts
- edge cases
- battle-tested judgement patterns

## Rule

Port the intelligence, not the architecture.

## Agent/Python split

Agents:
- classify meaning
- extract nuanced items
- judge semantic sameness
- identify unresolved threads
- produce structured metadata

Python:
- validates shape
- enforces enums
- stores candidates/facts
- manages status transitions
- applies deterministic eligibility/ranking rules
- handles timestamps/staleness/suppression
- writes timeline events
- preserves traceability

| :---- |

*Synapse V3 Build Specification · 2026-05-21 · Open this document first.*