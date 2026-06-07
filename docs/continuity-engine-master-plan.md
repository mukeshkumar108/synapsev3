  
**The Continuity Engine**

Sophie · Synapse V3 · vNext Runtime

Master Build Plan — Three Lanes, One Triangle

Three parallel workstreams. One convergence point. One product goal: Sophie inhabits an ongoing relationship — she does not reconstruct it from transcript on every turn.

Date: 2026-05-27   Status: APPROVED FOR BUILD

**The Triangle**

These are not three separate projects. They are three sides of the same thing. Each lane is independently buildable and independently shippable. They converge at one integration milestone.

| Lane | Name | What it gives Sophie |
| :---- | :---- | :---- |
| **A** | Synapse Provenance | Knows what is true and who said it. Multi-speaker. Multi-source. Assistant claims separated from user truth. |
| **B** | vNext Runtime Fix | Fast enough to be real. Parallel tool execution. Clean state machine. Mastra as Tool SDK only. |
| **C** | Continuity Engine | Knows where we are right now. Hot scene state. Working memory. Sophie was already here. |

| The convergence point Lane A gives Synapse the provenance to know who said what. Lane B gives the runtime the speed to serve it. Lane C gives Sophie the structured working state to inhabit it. All three must be done before the Integration Sprint. |
| :---- |

**Where We Are**

| Synapse V3 Tasks 1–8.6 | Done. Pipeline works in isolation. Provenance-unaware. User-only bias in every agent prompt. |
| :---- | :---- |
| **Task 9** | In progress. Actions, events, user controls. Complete this before starting Lane A. |
| **vNext runtime** | Built. Functional. Sequential tool execution. Custom loop reinventing Mastra. Hot layer entirely absent. |
| **Mastra** | Used as Tool SDK only (memory, web search tools). Not the orchestrator. Keep it that way. |
| **Recent turns / compaction** | Warm layer exists (rollingSummary \+ recentTurns). Passed as plain text block. No structured scene state. |
| **Hot layer** | Does not exist. TurnLoopState is ephemeral — discarded after every turn. No writeback, no schema, no injection. |

**Non-Negotiables Across All Lanes**

| THESE RULES APPLY TO EVERY TASK IN EVERY LANE 6-pass synthesis pipeline is not replaced. It is augmented. Canonical V3 is the only layer authorised to answer what is true. No new orchestration frameworks. Mastra stays as Tool SDK only. No opaque combined scoring. Backward compatibility: single-user Sophie/health companion must not regress. Assistant output is never automatically truth in real\_life mode. Session boundaries are an implementation detail, not the mental model. |
| :---- |

| LANE A | Synapse Provenance Upgrade |
| :---: | :---- |

Move Synapse from 'User Memory Extraction' to 'Evidence-Backed Situational Continuity.' Every fact must carry who said it, who it is about, and what kind of claim it is. This unlocks multi-speaker sources (WhatsApp, Slack, group chats) and prevents the assistant from eating its own tail.

| START CONDITION Task 9 complete. Lane A does not block Lane B or C. END CONDITION / INTEGRATION-READY SIGNAL All 6 test scenarios pass. Single-user Sophie regression tests pass. Synapse emits claimed\_by\_entity\_id and subject\_entity\_id on every candidate. |
| :---- |

| Phase A1  Schema & Contract |
| :---- |
| **GOAL** Add provenance fields to the database and upgrade the agent input contract. No prompt changes yet. **TASKS** Run migration: add claimed\_by\_entity\_id, subject\_entity\_id, claim\_type, claim\_status, interaction\_mode to candidates and confirmed\_facts. Add indexes on subject\_entity\_id and claimed\_by\_entity\_id. Update agent\_contract.py: Participant model, TranscriptTurn model, AgentInput v2. Update pipeline\_runner.py: populate participants list and turns with \[Turn X\] markers before agent dispatch. Pass interaction\_mode (default: real\_life) through the full pipeline. Verify existing ingestion path still works with default field values. **DEFINITION OF DONE** Migration runs clean with no data loss. AgentInput v2 accepted by all existing agents (backward compatible via defaults). pytest tests/test\_api.py passes. **DO NOT** Do not update any agent prompts yet. Do not introduce new agents. |

| Phase A2  Fact Agent V2 |
| :---- |
| **GOAL** Deploy a provenance-aware extraction prompt that knows the difference between direct claims, reported speech, assistant interpretations, and RP canon. **TASKS** Update agents/fact\_agent.py prompt: extract claimed\_by\_entity\_id, subject\_entity\_id, claim\_type, evidence\_turn\_index. Implement real\_life vs fictional\_rp mode rules in the prompt: assistant claims are 'interpretation' in real\_life, 'direct' canon in fictional\_rp. Handle reported speech: 'Ashley told me she's tired' → claimed\_by: user, subject: ashley, claim\_type: reported. Update output schema validation to require the new provenance fields. Add test fixture: single-user chat (peanut allergy). Verify claimed\_by: user, subject: user, type: direct. Add test fixture: assistant interpretation confirmed by user. Verify upgrade path from interpretation → direct. **DEFINITION OF DONE** All 4 fact agent test fixtures pass. Single-user Sophie: no regression on health/preference extraction. Reported speech does not get flattened into direct user truth. **DO NOT** Do not update triage\_agent or reconciliation\_agent yet. Do not add RP-specific ontology. |

| Phase A3  Reconciliation Policy V2 |
| :---- |
| **GOAL** Update the reconciliation agent to preserve contested claims rather than overwriting them, and to handle superseding and confirmation correctly. **TASKS** Update agents/reconciliation\_agent.py: contested claims (Speaker A vs Speaker B on same subject) → CREATE both, mark status: contested. Superseding: speaker corrects their own prior claim → UPDATE old to status: superseded. Confirmation: user confirms assistant interpretation → upgrade claim\_type to direct, boost confidence. Add test fixture: group chat disagreement (Ashley: meeting at 2pm, John: meeting at 3pm). Verify both preserved as contested. Add test fixture: RP canon (Sophie picks up silver key in fictional\_rp mode). Verify stored as direct. Add test fixture: non-linear reference ('Remember Japan 2022?'). Verify vector search links to existing timeline event. **DEFINITION OF DONE** All 6 test scenarios pass. No existing confirmed\_facts deleted or overwritten incorrectly. Lane A integration-ready signal confirmed. **DO NOT** Do not rewrite all agents. Do not introduce new database tables. |

| LANE B | vNext Runtime Fix |
| :---: | :---- |

Stop reinventing Mastra inside the runtime. Fix the latency bottleneck. Clean up the 'donut architecture.' Keep confirmation-gated writes and answer eligibility — those are real requirements. Everything else gets simplified.

| START CONDITION Can begin immediately. Does not depend on Lane A or C. END CONDITION / INTEGRATION-READY SIGNAL Independent tool calls run in parallel. Turn latency reduced. State machine is readable. SessionContext can carry a currentScene field (even if empty). Lane C can write hot state into it. |
| :---- |

| Phase B1  Parallelize Tool Execution |
| :---- |
| **GOAL** Replace the serial for loop in capabilityExecutor.ts with Promise.all for independent read tools. This is the single highest-ROI change in the entire codebase. **TASKS** Identify all read-only capabilities in capabilityExecutor.ts (Memory, WebSearch, Synapse reads). Replace sequential for loop with Promise.all for independent reads. Keep serial execution only for dependent operations (e.g. web search result feeds into memory lookup). Add timing instrumentation: log per-capability latency before and after. Run existing test suite to confirm no regressions. **DEFINITION OF DONE** Parallel reads confirmed in logs. Turn latency reduced by measurable amount (target: \>30% on multi-tool turns). All existing tests pass. **DO NOT** Do not touch the loop logic or state machine yet. Do not change the confirmation-gated write path. |

| Phase B2  State Machine Clarity |
| :---- |
| **GOAL** Replace the 'donut' architecture (linear spine calling an imperative while loop) with a readable state machine. Make the turn flow declarative and traceable. **TASKS** Define explicit turn states: ROUTING → GATHERING\_CONTEXT → MODEL\_GEN → ELIGIBILITY\_CHECK → FINALIZE. If ELIGIBILITY\_CHECK fails, state transitions back to GATHERING\_CONTEXT (max 2 passes, same as current bounded loop). Replace the while loop in executeTurn.ts with the state machine. Preserve all existing safety logic. Keep TurnLoopState but rename fields to match state machine semantics for readability. Remove manual producedToolLedgerEntryIds / consumedToolLedgerEntryIds tracking — replace with per-state input/output contracts. Ensure every state transition is logged with a reason. **DEFINITION OF DONE** Turn flow readable end-to-end without tracing through nested loop logic. Confirmation-gated writes still work correctly. Answer eligibility still works correctly. All existing tests pass. **DO NOT** Do not migrate to Mastra Workflows yet — this is a cleanup, not a framework adoption. Do not touch capability execution (done in B1). |

| Phase B3  SessionContext Hot State Slot |
| :---- |
| **GOAL** Add a currentScene field to SessionContext so Lane C has a place to write hot state. This phase does not implement the hot layer — it only creates the slot. **TASKS** Add currentScene: SceneState | null to SessionContext type. Define SceneState schema (empty object initially — Lane C will populate it). Update ensureSession to load currentScene from fast store (Redis or DB row keyed by session\_id). Default to null. Pass currentScene through every stage of the spine (it already travels through — just needs to be typed). Add empty hot\_state section to TurnPacket.context.sections (Lane C will populate). Update writebackAndQueue to persist currentScene back to fast store after each turn. **DEFINITION OF DONE** SessionContext carries currentScene field. currentScene persists across turns (loaded at turn start, saved at turn end). Lane C integration-ready signal: hot state slot exists and round-trips correctly. All existing tests pass. **DO NOT** Do not define the scene schema in detail — that is Lane C. Do not inject anything into the prompt yet. |

| LANE C | Continuity Engine — Hot Layer |
| :---: | :---- |

Give Sophie a structured working state that persists across turns. She should not reconstruct 'where are we?' from transcript text every turn. She should already be inside the situation when she responds.

| THE CORE INSIGHT Transcript replay ≠ situational awareness. Knowing the last 10 messages is different from knowing: we are in a tense moment with Ashley, three threads are open, the emotional tone is fragile, and the user hasn't answered her question yet. That second thing requires structured state, not text. |
| :---- |

| START CONDITION Lane B Phase B3 complete (hot state slot exists in SessionContext). Can otherwise run in parallel with Lane A and B. END CONDITION / INTEGRATION-READY SIGNAL Sophie reasons from SceneState, not just transcript. Drift and looping are measurably reduced. Hot writeback runs after every turn. |
| :---- |

| Phase C1  Scene Schema Definition |
| :---- |
| **GOAL** Define what constitutes 'The Scene.' This is a design decision, not a code decision. Get it wrong here and everything downstream is wrong. **TASKS** Define SceneState schema with these fields: active\_entities (participants currently salient), emotional\_tone, open\_threads (unresolved questions/beats), current\_salience (what matters most right now, distinct from long-term importance), recent\_developments (what changed in the last few turns), continuity\_constraints (things that must remain coherent), timeline\_position (optional: for RP or long narrative sessions). Distinguish stable\_importance (long-term: Ashley is always important) from current\_salience (this session: Elena suddenly became important). Write the schema as a TypeScript type and a Pydantic model (for Synapse consumption). Write 3 example SceneState objects: casual daily check-in, emotionally tense conversation, RP companion session. Review: does this schema cover the drift/looping/re-asking failures identified in stress testing? Adjust before proceeding. **DEFINITION OF DONE** SceneState schema defined, typed, and reviewed. 3 example instances written and validated. Schema covers all failure modes identified in RP/companion stress testing. **DO NOT** Do not write extraction or injection code yet. Do not over-engineer the schema — start minimal, expand later. |

| Phase C2  Hot Writeback |
| :---- |
| **GOAL** After each turn, extract scene changes from the assistant's response and update the hot state in the fast store. This is the missing mechanism Gemini identified. **TASKS** Build SceneExtractor: a lightweight LLM call after model generation that reads the turn and updates SceneState fields (entities, tone, open threads, recent developments). Run SceneExtractor asynchronously — it must not add to turn latency. Write updated SceneState back to SessionContext.currentScene via the B3 writeback mechanism. Handle checkpoint triggers: scene changes, emotional turning points, long-turn thresholds → trigger a Synapse warm layer update (not just hot). Define what does NOT trigger a hot update (trivial turns, confirmations) to avoid noise. Test: user says 'I'm in the car.' Verify next turn SceneState.active\_context includes this. Verify turn after that still has it. **DEFINITION OF DONE** SceneState updates persist across turns. SceneExtractor runs async (no latency impact on main turn). Checkpoint triggers fire correctly. Trivial turns do not pollute scene state. **DO NOT** Do not inject scene state into the prompt yet. Do not block turn response on SceneExtractor completion. |

| Phase C3  Hot Injection — Working Memory Block |
| :---- |
| **GOAL** Inject the current SceneState into a dedicated \[WORKING\_MEMORY\] block in the prompt. The model reasons from situation, not transcript. **TASKS** Add \[WORKING\_MEMORY\] section to the prompt, positioned before \[CONVERSATION\_HISTORY\]. Render SceneState as a structured, concise natural language block (not raw JSON). Update Sophie's kernel prompt to explicitly instruct: 'You are already inside this situation. Reason from it, not from the transcript.' Tune \[WORKING\_MEMORY\] rendering: dense enough to be useful, short enough not to dominate the context window (target: \<200 tokens). A/B test: turns with \[WORKING\_MEMORY\] vs without. Measure drift reduction. Handle graceful degradation: if SceneState is null (first turn, new session), \[WORKING\_MEMORY\] is omitted silently. **DEFINITION OF DONE** Sophie references scene state in responses without being prompted to. Drift and looping measurably reduced in multi-turn sessions. \[WORKING\_MEMORY\] block \<200 tokens on typical sessions. Graceful degradation confirmed on cold start. **DO NOT** Do not hardcode the working memory format — it will evolve. Do not merge \[WORKING\_MEMORY\] with \[CONVERSATION\_HISTORY\]. |

| INTEGRATION SPRINT Wire the Triangle |
| :---: |

| ENTRY CONDITIONS — ALL THREE REQUIRED Lane A: all 6 provenance test scenarios pass. Lane B: parallel execution live, state machine readable, SessionContext hot state slot round-trips. Lane C: SceneState persists across turns, writeback async, \[WORKING\_MEMORY\] injected. |
| :---- |

The integration sprint wires three things together that have been running in parallel. It should take one focused week, not a month. If it takes longer, the lanes were not independently complete.

| I1 | Wire Synapse provenance output into SceneExtractor. Confirmed facts with claimed\_by\_entity\_id should feed into session salience updates. |
| :---- | :---- |
| **I2** | Wire Synapse startbrief into \[WORKING\_MEMORY\] seed. Cold-start SceneState should be seeded from the Synapse handover packet, not blank. |
| **I3** | Validate end-to-end: user message → parallel tools → provenance-aware memory → SceneState update → \[WORKING\_MEMORY\] injection → Sophie responds from inhabited context. |
| **I4** | Voice migration: route /api/chat through vNext spine (the remaining legacy gap from the original vNext spec). |
| **I5** | Run full regression: single-user Sophie, health companion scenario, RP companion scenario, group chat scenario. |

| The integration-done signal Sophie says something in turn 8 that could only be coherent if she retained the emotional state from turn 2\. Not because it was in the last 3 messages. Because it was in her structured scene state. That is the moment the triangle closes. |
| :---- |

**What We Are Not Building**

Scope creep will come. This section is the anchor.

| No new orchestration frameworks (no full Mastra adoption, no LangGraph). No roleplay-specific ontology in Lane A — that comes after provenance is proven. No group-chat UI or multi-user product features. No Apple Health / wearable integrations. No new database architecture — augment what exists. No rewrite of triage\_agent, state\_agent, or thread\_agent in Lane A Phase 1\. No blocking the turn response on SceneExtractor in Lane C. No quality-based quarantine until Lane A is proven stable. |
| :---- |

**First Codex Prompts — One Per Lane**

**Lane A — Phase A1**

| Task: Implement schema migration and AgentInput v2 for provenance awareness in Synapse V3. 1\. Database: Update schema.sql with ALTER TABLE statements. Add claimed\_by\_entity\_id TEXT, subject\_entity\_id TEXT, claim\_type TEXT DEFAULT 'direct', claim\_status TEXT DEFAULT 'pending', interaction\_mode TEXT DEFAULT 'real\_life' to candidates and confirmed\_facts. Add indexes on subject\_entity\_id and claimed\_by\_entity\_id. Write and run migrate\_phase1.py. 2\. Contract: Update agents/agent\_contract.py. Add Participant(id, name, role) and TranscriptTurn(index, speaker\_id, content, source\_message\_id) Pydantic models. Update AgentInput to include participants: list\[Participant\], turns: list\[TranscriptTurn\], interaction\_mode: str \= 'real\_life'. All new fields must have defaults for backward compatibility. 3\. Pipeline: Update core/pipeline\_runner.py. Before dispatching agents, populate participants by mapping user\_id to 'user' and Sophie's persona to 'sophie'. Format raw\_content with \[Turn 0\], \[Turn 1\] markers. Pass interaction\_mode through to AgentInput. 4\. Verify: Run pytest tests/test\_api.py. All existing tests must pass. No existing ingestion path should break. Constraints: Backward compatible. No prompt changes. No new agents. No new tables. |
| :---- |

**Lane B — Phase B1**

| Task: Parallelize independent tool execution in the vNext capability executor. 1\. Audit: In src/lib/runtime/vnext/capabilityExecutor.ts, identify all capability types that are read-only and independent (Memory lookup, WebSearch, Synapse calendar read, Synapse actions read). 2\. Refactor: Replace the sequential for loop with Promise.all for all independent reads. Any capability that depends on the output of another must remain sequential — document the dependency explicitly. 3\. Instrumentation: Add console.time / performance.now logging per capability. Log: capability name, start time, duration, success/fail. This data is needed to measure improvement. 4\. Test: Run the existing test suite. Confirm no regressions. If possible, add a simple timing test that asserts parallel execution (two capabilities complete closer together than sequentially possible). Constraints: Do not touch the loop logic. Do not touch the confirmation-gated write path. Do not touch answer eligibility. |
| :---- |

**Lane C — Phase C1**

| Task: Define the SceneState schema. This is design work, not implementation. Produce the schema definition only — no extraction or injection code. 1\. Create src/lib/runtime/vnext/types/sceneState.ts with the SceneState TypeScript interface. Include: active\_entities (string\[\]), emotional\_tone (string), open\_threads ({id, description, since\_turn}\[\]), current\_salience ({entity\_id, reason}\[\]), recent\_developments (string\[\]), continuity\_constraints (string\[\]), timeline\_position (string | null). 2\. Create synapse-v3/core/scene\_state.py with the equivalent Pydantic model (for Synapse consumption in Lane A integration). 3\. Write 3 example SceneState JSON objects as test fixtures in tests/fixtures/scene\_state\_examples.json: (a) casual daily check-in, (b) emotionally tense conversation about a difficult relationship, (c) RP companion session mid-scene. 4\. Do not write any extraction logic. Do not write any prompt injection logic. Schema and fixtures only. Constraints: Schema must be minimal — resist adding fields not needed for the three example scenarios. It will grow later. |
| :---- |

**One Page Summary**

|  | LANE A  Provenance | LANE B  Runtime |
| :---- | :---- | :---- |
| **Goal** | Who said what | Fast & readable |
| **Phase 1** | Schema \+ AgentInput v2 | Parallelize tools |
| **Phase 2** | Fact Agent V2 | State machine cleanup |
| **Phase 3** | Reconciliation V2 | SessionContext hot slot |
| **Blocks on** | Task 9 complete | Nothing |
| **Integration signal** | 6 test scenarios pass | Hot state slot round-trips |

| Complete all three lanes. Run the integration sprint. Sophie inhabits the relationship. |
| :---: |

