# SYNAPSE V2 Intelligence Export

This file is a portable intelligence export from the old Synapse repository. It is intentionally documentation-only. It does not propose copying the old runtime architecture as-is.

---

# 1. Executive summary

The old Synapse repo contains a real, battle-tested intelligence layer in three places:

1. The 6-pass derived memory pipeline in `src/derived_pipeline.py` plus `src/derived_passes/*`.
2. The older session-summary / startbrief / daily-analysis prompting in `src/session.py` and `src/main.py`.
3. The structured candidate, thread, entity, identity, living-context, and proactive surfacing schemas in Postgres migrations and normalization code.

What is worth reusing:

- Pass 1 triage prompt discipline: routing-only, anti-overreach, user-turn-only truth policy.
- Pass 2 extraction prompts: stand-alone items, explicit temporal-grounding rules, confirmation rules.
- Pass 3 thread prompt: concrete unresolved-situation framing, anti-psychologizing language.
- Pass 4 and Pass 5 synthesis prompts: strong guardrails against literary/therapy-style overreach.
- Candidate lifecycles, confidence labels, provenance/evidence patterns, and “needs review / stale / superseded” thinking.
- Startbrief/session-summary constraints that force compactness and anti-drift.

What should be reused carefully:

- Entity profile prose prompt in `src/derived_passes/pass15_entities.py`: useful, but warmer and looser than the later identity/living-context prompts.
- Daily analysis and user-model enrichment prompts in `src/main.py`: useful for ideas and labels, but they belong to the older, more monolithic user-model layer.
- Reconciliation prompts: useful as agent behavior specs, but the old storage layout was fragmented.

What should not be copied:

- `src/derived_pipeline.py` as a monolith.
- Direct coupling between extraction, persistence, dedupe, scoring, surfacing, and background jobs.
- Split-brain serving assumptions between derived tables, legacy tables, and Graphiti/FalkorDB.
- Duplicate candidate/object surfaces and brittle SQL-heavy lifecycle mutation logic.

---

# 2. Pipeline map

## 2.1 High-level flow

Raw input path in the old repo:

1. Raw transcript stored in `session_transcript`.
2. Pass 1 triage classifies memory-worthiness and routing flags.
3. Routed extraction passes run:
   - Pass 2a actionable
   - Pass 2b session changes
   - Pass 2c entity candidates
   - Pass 1.5 entities
   - Pass 3 threads
4. Threshold-triggered synthesis passes run:
   - Pass 4 identity
   - Pass 5 living context
5. Additional serving artifacts are built:
   - session summaries
   - session handover packets
   - always-on memory packets
   - daily overview / attention preview / unified ops read models

## 2.2 Pass-by-pass map

| Stage | File path | Main function(s) | Reads | Returns | Writes | Mode | Recommendation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Pass 1 triage | `src/derived_pipeline.py`, `src/derived_passes/pass1_triage.py` | `run_pass1_triage`, `run_rich_pass1_llm`, `_heuristic_pass1` | raw `messages`; prior checkpoints for Pass 4/5 trigger logic | `DerivedPassResult` with routing flags | `session_classifications`, `pipeline_runs`, `pipeline_checkpoints` | Mixed: LLM-first with no-op fallback | Reuse prompt and schema; discard orchestration style |
| Pass 2a actionable | `src/derived_pipeline.py`, `src/derived_passes/pass2_actionable.py` | `run_pass2_actionable`, `run_pass2_actionable_llm`, `_normalize_actionable_payload` | raw `messages`, temporal context | `DerivedPassResult` | `actionable_candidates`, plus run/checkpoint tables | LLM-led with deterministic normalization/persistence | Reuse prompt, subtype schema, timing rules; adapt storage |
| Pass 2b session changes | `src/derived_pipeline.py`, `src/derived_passes/pass2b_session_changes.py` | `run_pass2b_session_changes`, `run_pass2b_session_changes_llm`, `_normalize_session_changes_payload` | raw `messages`, temporal context, recent open session changes for supersession | `DerivedPassResult` | `session_changes`, run/checkpoint tables | LLM-led with deterministic supersession logic | Reuse prompt and shape; simplify supersession logic |
| Pass 2c entity candidates | `src/derived_pipeline.py`, `src/derived_passes/pass2c_entity_candidates.py` | `run_pass2c_entity_candidates`, `run_pass2c_entity_candidates_llm`, `_normalize_entity_candidates_payload` | raw `messages` | `DerivedPassResult` | `entity_candidates`, run/checkpoint tables | LLM-led with deterministic normalization | Reuse prompt and candidate taxonomy |
| Pass 1.5 entities | `src/derived_pipeline.py`, `src/derived_passes/pass15_entities.py` | `run_pass1_5_entities`, `discover_entity_mentions`, `resolve_entity_mentions`, `build_entity_profile` | `entity_candidates`, `session_classifications`, `entity_profiles`, raw `messages` | `DerivedPassResult` | `entity_profiles`, `memory_relationship_links`, `derived_assertions`, `low_confidence_items`, updates `entity_candidates.status='resolved'` | Mixed | Reuse resolution/profile prompts and coarse labels; discard SQL-heavy registry mutation style |
| Pass 3 threads | `src/derived_pipeline.py`, `src/derived_passes/pass3_threads.py` | `run_pass3_threads`, `extract_thread_actions`, `audit_thread_registry` | `session_classifications`, `open_threads`, raw `messages`, discovered entity mentions | `DerivedPassResult` | `open_threads`, `memory_relationship_links`, `derived_assertions`, quarantine/checkpoint tables | Mixed | Reuse prompt and lifecycle concepts; adapt into cleaner agent + object model |
| Pass 4 identity | `src/derived_pipeline.py`, `src/derived_passes/pass4_identity.py` | `build_pass4_identity_packet`, `run_pass4_identity`, `synthesize_identity_profile`, `normalize_identity_output` | recent identity-relevant sessions, `open_threads`, `entity_profiles`, `declared_profile_truth`, `durable_profile_facts`, existing `identity_profile` | `DerivedPassResult` | `identity_profile`, updates `pipeline_checkpoints` | LLM-led with deterministic packet assembly | Reuse prompt guardrails, declared-truth precedence, output fields |
| Pass 5 living context | `src/derived_pipeline.py`, `src/derived_passes/pass5_living_context.py` | `build_pass5_living_packet`, `run_pass5_living_context`, `synthesize_living_context`, `normalize_living_context_output` | recent context-relevant sessions, `open_threads`, `entity_profiles`, `memory_contradictions`, `low_confidence_items`, existing `living_context`, existing `identity_profile` | `DerivedPassResult` | `living_context`, `memory_contradictions`, `low_confidence_items`, checkpoints | LLM-led with deterministic packet assembly | Reuse prompt/output fields; keep contradiction and uncertainty concepts |

## 2.3 Supporting non-pass surfaces

| Surface | File path | Function(s) | Reads | Writes | Mode | Recommendation |
| --- | --- | --- | --- | --- | --- | --- |
| Session summaries | `src/session.py`, `src/session_summaries.py` | `_summarize_session_close`, `_summarize_session_bridge`, `_rewrite_structured_recap`, `upsert_session_summary` | transcript, reference date | `session_summaries` | LLM-led with strong parser/validator | Reuse structured recap rules and parser expectations |
| Fast handover | `src/fast_handover.py` | `build_fast_handover_packet`, `persist_fast_handover_packet` | raw messages only | `session_handover_packets` | Deterministic | Reuse TTL/caution ideas; not a primary intelligence asset |
| Startbrief | `src/main.py` | `_generate_startbrief_bridge_llm`, `_realize_startbrief_from_selected_evidence` | user narratives, open loops, selected evidence rows, daily themes | read-model only | LLM-led | Reuse prompt constraints and evidence-citation idea |
| Daily analysis | `src/main.py` | `_generate_daily_analysis_with_stats` | transcript or session summaries | `daily_analysis` | LLM-led | Reuse labels cautiously; avoid reviving monolithic user-model flow |
| Always-on packet | `src/main.py` | `_rewrite_always_on_packet_text`, `build_always_on_memory_packet` | declared truth, identity/living sections | `always_on_memory_packets` | Mixed | Reuse rewrite constraints, not artifact format |
| Attention preview / daily overview | `src/attention_preview.py`, `src/daily_overview.py` | `build_attention_preview`, `build_daily_overview` | action/task/event/thread/change/candidate tables | none | Deterministic | Reuse ranking fields and lifecycle labels, not implementation |
| Reconciliation | `src/derived_passes/candidate_audits.py`, `src/ops/reconcile_ops.py` | `audit_*`, `reconcile_actionable_candidate`, `reconcile_ops` | candidate tables / unified ops items | read-only recommendations or status mutations elsewhere | Mixed | Reuse prompt logic, discard coupled storage layout |

---

# 3. Exact prompts

This section quotes the exact prompt templates found in code. If a requested category has no dedicated prompt, it is marked clearly.

## 3.1 Triage / router / pass 1

- File: `src/derived_passes/pass1_triage.py`
- Function: `run_rich_pass1_llm`
- Prompt constant: `PASS1_PROMPT`
- Model: caller passes `model`; live default comes from `Settings.derived_pipeline_model_version`, default `google/gemma-4-26b-a4b-it` in `src/config.py`
- Dynamic variables: `{{transcript}}`
- Output schema: exact JSON object with `is_memory_worthy`, `session_kind`, `run_actionable_pass`, `run_session_changes_pass`, `run_entity_pass`, `run_threads_pass`, `identity_relevant`, `context_relevant`, `emotional_weight`, `emotional_note`, `tension_signal`, `ignore_reasons`
- Validation/parsing: `call_json_llm` -> `normalize_pass1_payload`
- Known weaknesses: falls back to `_heuristic_pass1` no-op style if LLM parse fails; old `session_classifications.entity_mentions` is legacy baggage

Exact prompt:

```text
You are the first-pass memory triage layer for a personal AI assistant.

Your job is NOT to write a nice summary and NOT to explain what the session means.
Your job is triage and routing:
- decide whether this session contains durable memory value
- identify what kind of follow-on processing it may need
- output only routing flags and lightweight triage metadata

Pass 1 is not the place for personality reading, emotional interpretation,
or deeper synthesis. Later passes will go back to the raw transcript.

Return JSON only in this exact shape:

{
  "is_memory_worthy": true,
  "session_kind": "technical|personal|mixed|transient",
  "run_actionable_pass": true,
  "run_session_changes_pass": true,
  "run_entity_pass": true,
  "run_threads_pass": true,
  "identity_relevant": true,
  "context_relevant": true,
  "emotional_weight": "none|low|medium|high",
  "emotional_note": "one short sentence if medium or high, otherwise null",
  "tension_signal": "one sentence or null. If this session contains a hint of something unspoken, avoided, or underneath the surface, name it briefly. Examples: 'User deflected from Riley topic back to work' | 'User expressed doubt then immediately pivoted to optimism' | 'User mentioned Jordan briefly then moved on quickly'. Only populate if clearly present in USER turns. Null if nothing notable.",
  "ignore_reasons": [
    "optional short reason for what should be ignored"
  ]
}
...
Transcript:
{{transcript}}
```

## 3.2 Task / action / todo extraction

- File: `src/derived_passes/pass2_actionable.py`
- Function: `run_pass2_actionable_llm`
- Prompt constant: `PASS2_ACTIONABLE_PROMPT`
- Model: `derived_pipeline_model_version`
- Dynamic variables: `{{temporal_context}}`, `{{transcript}}`
- Output schema: exact `{"actionable_candidates":[...]}` with `record_type`, `candidate_subtype`, `title`, `summary`, `provenance_summary`, `confidence`, `risk_tags`, `has_direct_user_expression`, `requires_confirmation`, `suggested_action`, timing fields, `waiting_on`, `needs_response`, `cadence_text`, external-link fields, `source`, nested `provenance`, `status`
- Validation/parsing: `_normalize_actionable_payload`
- Few-shot/examples: embedded as schema and rule examples only, not full chat few-shots
- Known weaknesses: one prompt handles tasks, reminders, habits, follow-ups, waiting-on, and calendar extraction together; can be broad

Exact prompt:

```text
You are Pass 2a for action/tool candidate extraction.

Act like an excellent chief of staff or executive assistant reading messy human conversation.

Your job is to identify real-world things Sophie may need to track, confirm, schedule, revisit, or surface later:
- tasks the user needs to do
- events/meetings/appointments that are scheduled or proposed
- reminder asks
- commitments/promises/intentions
- recurring habits/routines
- follow-ups, waiting-on states, or nudges Sophie may later surface
...
27. Calendar events must not auto-create: candidate_subtype=calendar_event and requires_confirmation=true.

{{temporal_context}}

Transcript:
{{transcript}}
```

## 3.3 Reminder extraction

No separate reminder-only prompt found.

- Reused lane: `src/derived_passes/pass2_actionable.py`
- Relevant schema values:
  - `record_type="reminder_candidate"`
  - `candidate_subtype="reminder"`
  - `suggested_action`
  - `proposed_remind_at`
  - `requires_confirmation`

## 3.4 Calendar / event extraction

No separate event-only prompt found.

- Reused lane: `src/derived_passes/pass2_actionable.py`
- Relevant schema values:
  - `record_type="event_candidate"`
  - `candidate_subtype="calendar_event"`
  - `due_iso`, `proposed_due_at`, `relevant_from_iso`, `relevant_until_iso`
  - hard rule: “Calendar events must not auto-create”

## 3.5 Durable facts

No dedicated “durable facts extraction prompt” was found.

Closest assets:

1. `src/derived_pipeline.py` / `build_pass4_identity_packet` and `_refresh_durable_profile_facts`
2. `src/declared_profile_truth.py`
3. Identity synthesis prompt consumes `durable_profile_facts` and `declared_profile_truth`

Conclusion:

- durable facts existed as a storage and precedence concept
- the durable-fact extraction path is partly deterministic / internal
- there is no standalone “durable facts” prompt in this repo

## 3.6 Entity / person / project / company extraction

There are three distinct prompt assets.

### 3.6.a Entity candidate extraction

- File: `src/derived_passes/pass2c_entity_candidates.py`
- Function: `run_pass2c_entity_candidates_llm`
- Prompt constant: `PASS2C_ENTITY_CANDIDATES_PROMPT`
- Output schema: `{"entity_candidates":[{"name","candidate_type","summary","source","provenance","confidence","status"}]}`

```text
You are Pass 2c for entity candidate extraction.

Your job is to identify named entities from a user transcript that are worth downstream resolution.
...
Transcript:
{{transcript}}
```

### 3.6.b Entity discovery

- File: `src/derived_passes/pass15_entities.py`
- Function: `discover_entity_mentions`
- Prompt constant: `ENTITY_DISCOVERY_PROMPT`
- Output schema: `{"entity_mentions":["Riley","Bluum"]}`

```text
You are identifying durable entity mentions from a user transcript for a personal AI assistant.

Your job is only to identify named entities worth sending to a downstream entity-resolution pass.
...
Transcript:
{transcript_text}
```

### 3.6.c Entity resolution / dedupe / match-vs-new

- File: `src/derived_passes/pass15_entities.py`
- Function: `resolve_entity_mentions`
- Prompt constant: `RESOLVE_PROMPT_TEMPLATE`
- Output schema: `{"resolutions":[...]}`
- Useful labels:
  - `decision`: `MATCH|NEW|TENTATIVE|SKIP`
  - `type`: `person|project|place|other`
  - `status`: `tentative|active`
  - `relationship_to_user`: coarse role labels
  - `evidence_strength`, `memory_relevance`, `relationship_confidence`

```text
You are maintaining an entity registry for a personal
AI assistant. Your job is to decide what to do with
each new entity mention.
...
Return JSON only — no preamble, no markdown fences:
{
  "resolutions": [
    ...
  ]
}
```

### 3.6.d Entity profile synthesis

- File: `src/derived_passes/pass15_entities.py`
- Function: `build_entity_profile`
- Prompt constant: `PROFILE_PROMPT_TEMPLATE`
- Output schema: `profile_text`, `key_facts`, `open_questions`, `last_known_status`

Known weakness:

- It explicitly asks for “warm and natural” friend-like internal prose, which is looser than the stricter later pass prompts.

## 3.7 Identity / profile extraction

- File: `src/derived_passes/pass4_identity.py`
- Function: `synthesize_identity_profile`
- Prompt constant: `IDENTITY_SYNTHESIS_PROMPT`
- Model: `derived_pipeline_model_version`
- Dynamic variables:
  - `{existing_profile}`
  - `{declared_profile_truth}`
  - `{durable_profile_facts}`
  - `{session_evidence}`
  - `{persistent_goals}`
- Output schema:
  - `who_they_are`
  - `core_values`
  - `recurring_patterns`
  - `family_history`
  - `faith_and_beliefs`
  - `what_they_want`
  - `recurring_fears`
  - `what_they_avoid`
  - `how_they_relate`
  - `persistent_goals`
  - `current_chapter`
- Validation/parsing: `normalize_identity_output`
- Strongest reusable asset in repo: yes

Exact prompt excerpt:

```text
You are synthesizing an identity profile for the user
of a personal AI assistant named Sophie.

Your job is to identify this person, not interpret them.
...
Authority order:
1. declared profile truth
2. repeated explicit session facts
3. durable derived facts
4. prose synthesis
...
CRITICAL DISTINCTION:
- enduring identity = who this person is across time
- current chapter = what is active right now
...
Return JSON only — no preamble, no markdown:
{
  "who_they_are": "compact prose ...",
  ...
}
```

## 3.8 State / emotional context

Two distinct prompt assets exist.

### 3.8.a Pass 1 lightweight emotional routing

- File: `src/derived_passes/pass1_triage.py`
- Fields: `emotional_weight`, `emotional_note`, `tension_signal`
- Purpose: route only, not deep interpretation

### 3.8.b Living context synthesis

- File: `src/derived_passes/pass5_living_context.py`
- Function: `synthesize_living_context`
- Prompt constant: `LIVING_CONTEXT_PROMPT`
- Output schema:
  - `current_focus`
  - `recent_narrative`
  - `relationship_pulse`
  - `emotional_texture`
  - `primary_tension`
  - `what_theyre_avoiding`
  - `unspoken_goal`
  - `why_it_matters`
  - `active_contradictions`
  - `sophie_directives`
- Validation/parsing: `normalize_living_context_output`

Exact prompt excerpt:

```text
You are synthesizing the current living context for
the user of a personal AI assistant named Sophie.
...
TENSION MAP — unresolved current friction:
- What is the main unresolved friction right now?
...
12. Field-specific constraints:
    - primary_tension must be observable and concrete.
    - relationship_pulse must describe current relationship state
      or interaction stance, not how the relationship "feels."
    - emotional_texture should usually be null.
...
Return JSON only — no preamble, no markdown:
{
  "current_focus": "prose",
  ...
}
```

## 3.9 Session changes

- File: `src/derived_passes/pass2b_session_changes.py`
- Function: `run_pass2b_session_changes_llm`
- Prompt constant: `PASS2B_SESSION_CHANGES_PROMPT`
- Output schema: `{"session_changes":[{"kind","title","summary","effective_iso","time_text","source","provenance","confidence","status"}]}`

Exact prompt excerpt:

```text
You are Pass 2b for session change extraction.

Your job is to identify factual or contextual changes from a user transcript that update understanding of the user's world.
...
Return JSON only in this exact shape:
{
  "session_changes": [
    {
      "kind": "factual_update|state_change|decision_change|schedule_change|focus_change",
      ...
    }
  ]
}
```

## 3.10 Open threads / unresolved loops

- File: `src/derived_passes/pass3_threads.py`
- Function: `extract_thread_actions`
- Prompt constant: `THREAD_EXTRACTION_PROMPT`
- Input variables:
  - `{session_date}`
  - `{emotional_weight}`
  - `{emotional_note}`
  - `{thread_signals}`
  - `{transcript_text}`
  - `{existing_threads}`
- Output schema: `{"actions":[...]}`
- Actions:
  - `CREATE`
  - `UPDATE`
  - `RESOLVE`
  - `SNOOZE`
  - `NO_ACTION`
- Extra labels:
  - `category`
  - `priority`
  - `unresolvedness`
  - `follow_up_value`
  - `evidence_strength`
  - `why_this_matters_later`

Exact prompt excerpt:

```text
You are maintaining an open thread registry for a
personal AI assistant named Sophie.
...
Open threads are unresolved situations a caring attentive
friend would remember and follow up on later.
...
Relationship threads should usually be about the relationship situation
with a specific person, not about the user's grief, shame, anger, or fear
about that relationship.
...
Return JSON only — no preamble, no markdown:
{
  "actions": [
    ...
  ]
}
```

## 3.11 Reconciliation / dedupe / merge

Several prompt-based assets exist.

### 3.11.a Thread audit / merge

- File: `src/derived_passes/pass3_threads.py`
- Function: `audit_thread_registry`
- Prompt constant: `THREAD_AUDIT_PROMPT`
- Output schema: `audit_actions`
- Action labels:
  - `MERGE`
  - `RESOLVE`
  - `SNOOZE`
  - `CATEGORY_FIX`
  - `FLAG_REVIEW`

### 3.11.b Actionable candidate audit

- File: `src/derived_passes/candidate_audits.py`
- Function: `audit_actionable_candidates`
- Prompt constant: `_ACTIONABLE_AUDIT_PROMPT`
- Action labels:
  - `KEEP`
  - `REWRITE`
  - `MERGE`
  - `SUPERSEDE`
  - `NEEDS_REVIEW`
  - `NEEDS_CONTEXT`
  - `DISMISS`
  - `STALE`

### 3.11.c Session-change audit

- File: `src/derived_passes/candidate_audits.py`
- Function: `audit_session_changes`
- Prompt constant: `_SESSION_CHANGE_AUDIT_PROMPT`

### 3.11.d Entity-candidate audit

- File: `src/derived_passes/candidate_audits.py`
- Function: `audit_entity_candidates`
- Prompt constant: `_ENTITY_CANDIDATE_AUDIT_PROMPT`

### 3.11.e Actionable reconciliation

- File: `src/derived_passes/candidate_audits.py`
- Function: `reconcile_actionable_candidate`
- Prompt constant: `_ACTIONABLE_RECONCILIATION_PROMPT`
- Decision labels:
  - `SEPARATE`
  - `MERGE`
  - `SUPERSEDE`
  - `DISMISS`
  - `STALE_EXISTING`

### 3.11.f Unified ops reconciliation agent

- File: `src/ops/reconcile_ops.py`
- Function: `_llm_recommendations`
- Prompt version: `PROMPT_VERSION = "reconciliation-agent-v1"`
- Output schema: `recommendations`
- Purpose: read-only reconciliation recommendations over normalized operational items

Exact prompt excerpt:

```text
You are Sophie, an executive assistant performing dry-run reconciliation over operational items.
Return JSON only. Do not include markdown.
Never mutate anything. Recommend only safe read-side actions.
Do not merge items merely because they mention the same person.
...
PROMPT_VERSION: reconciliation-agent-v1
INPUT_JSON:
...
```

## 3.12 Living context

Covered above in 3.8.b. This is the exact living-context prompt asset.

## 3.13 Start brief / session brief / daily overview / surfacing

### 3.13.a Session close structured summary + bridge

- File: `src/session.py`
- Function: `_summarize_session_close`
- Model route: `task="session_episode"` -> `openrouter_model_session_episode`, default `xiaomi/mimo-v2-flash`
- Output is parsed from labeled plaintext sections, not JSON
- Key output sections:
  - `SUMMARY`
  - `TONE`
  - `DECISIONS`
  - `UNRESOLVED`
  - `MOMENT`
  - `BRIDGE`

Exact prompt excerpt:

```text
You are a memory processor. Your job is to extract two distinct texts from the transcript below.

TASK 1: HISTORICAL SUMMARY
Rules:
- Write in PAST TENSE.
...
TASK 2: BRIDGING TEXT
Rules:
- 1-2 sentences max.
- Write in PRESENT or FUTURE tense.
...
Response format:
SUMMARY: ...
TONE: ...
DECISIONS:
- ...
UNRESOLVED:
- ...
MOMENT: ...
BRIDGE: ...
```

### 3.13.b Session bridge rewrite

- File: `src/session.py`
- Functions:
  - `_summarize_session_bridge`
  - `_summarize_session_bridge_strict`
  - `_rewrite_structured_recap`
- Usefulness: very high for strict rewrite/validation patterns

### 3.13.c Startbrief paragraph

- File: `src/main.py`
- Function: `_generate_startbrief_bridge_llm`
- Task route: `task="startbrief_bridge"` -> `openrouter_model_summary`, default `amazon/nova-micro-v1`
- Dynamic inputs:
  - `DEPTH`
  - `NOW_LOCAL`
  - `GAP_HUMAN`
  - `LAST_THREAD`
  - `USER_TONE`
  - `OPEN_THREADS`
  - `OPEN_THREAD_REASONS`
  - `OPEN_LOOPS`
  - `YESTERDAY_THEMES`
  - `STEERING_NOTE`
  - `CONTINUATION_HINT`
  - `USER_NARRATIVE_STABLE`
  - `USER_NARRATIVE_CURRENT`

Exact prompt excerpt:

```text
Write a STARTBRIEF paragraph addressed to the assistant ("you") about the user ("the user").
This text will be prepended as context for a stateless LLM call. It is not shown to the user.
...
- Write like a sharp friend making quick notes before a call.
...
Return ONLY the paragraph.
```

### 3.13.d Startbrief evidence realizer

- File: `src/main.py`
- Function: `_realize_startbrief_from_selected_evidence`
- Task route: `task="startbrief_realizer"`
- Output schema:
  - `handover_lines`
  - `ops_context_lines`
- Strong reusable idea: every line cites `evidence_ids`

### 3.13.e Daily overview

No prompt found in `src/daily_overview.py`.

- Status: deterministic read model
- Reusable intelligence is in ranking fields and lifecycle filtering, not prompt text

### 3.13.f Attention preview / surfacing

No general surfacing prompt found in `src/attention_preview.py`.

- Status: deterministic ranking/filtering read model
- Reusable intelligence is field selection, lifecycle logic, sensitivity/priority heuristics

## 3.14 Proactive / magic-moment / follow-up logic

There is no single “magic moment” prompt. Relevant assets are:

1. Promptless deterministic follow-up suggestion generation in `src/derived_pipeline.py`
   - example patterns:
     - `Quick check-in on {title.lower()}: any update?`
     - `Quick health check-in: how is "{loop_text}" going?`
     - `Last time we discussed {title.lower()}. Any update since then?`
2. `follow_up_candidates`, `clarification_candidates`, and `recent_change_candidates` schemas in `schema.sql`
3. Deterministic attention ranking in `src/attention_preview.py`

Closest prompt-based surfacing asset:

- `src/main.py` `_realize_startbrief_from_selected_evidence`

---

# 4. Output schemas and labels

This section extracts reusable fields, meanings, and whether they are worth carrying into a clean rebuild.

| Field / label | Meaning | Where used | Bring forward? |
| --- | --- | --- | --- |
| `candidate_type` | Coarse entity kind | `entity_candidates`, entity prompts | Yes |
| `record_type` | Coarse actionable kind | `actionable_candidates` | Yes, but likely rename to `item_type` |
| `candidate_subtype` | Sharper actionable category | Pass 2a prompt/schema | Yes |
| `fact_type` | Durable profile fact category | `durable_profile_facts` | Yes |
| `domain` / `source_domain` / `target_domain` | Cross-object domain typing | `memory_relationship_links`, docs/specs | Yes, conceptually |
| `confidence` | Numeric or coarse trust score | prompts, `entity_profiles`, packet rewrites | Yes |
| `confidence_score` | normalized numeric confidence | candidate tables | Yes |
| `confidence_label` | `low|medium|high` | actionable/session-change/entity-candidate tables | Yes |
| `priority` | coarse urgency/salience label | `open_threads`, thread prompt | Yes, if simplified |
| `priority_score` | numeric surfacing weight | follow-up / clarification / recent-change candidates | Yes |
| `importance` / `importance_score` | durable relevance | read models, entity/thread scoring | Yes |
| `urgency` | time-based pressure | unified ops / attention models | Yes |
| `status` | lifecycle state | nearly all tables | Yes |
| `discovered_at` | not explicit as a universal field | concept only | Unclear; prefer `created_at` / `first_seen_at` |
| `first_seen_at` | first evidence time | `entity_profiles`, `low_confidence_items`, contradictions | Yes |
| `last_seen_at` | last evidence time | entities, contradictions, low-confidence, silence flags | Yes |
| `last_confirmed_at` | entity key-fact field | `PROFILE_PROMPT_TEMPLATE` output | Yes |
| `last_updated_at` / `updated_at` | mutation time | many tables | Yes |
| `expires_at` | handover TTL / candidate window expiry | `session_handover_packets`, some read models | Yes |
| `source` / `source_type` / `source_kind` | origin surface | candidates, facts, action/calendar objects | Yes |
| `source_ref` / `provenance` | structured origin metadata | candidate/object tables | Yes |
| `raw evidence` / `source_turn_refs` / `evidence_refs` | direct grounding | candidates, threads, contradictions, session summaries | Yes, strongly |
| `needs_confirmation` | candidate should not auto-promote | Pass 2a provenance/metadata | Yes |
| `merge/update instructions` | audit/reconcile actions | candidate audits, thread audit, unify/reconcile | Yes |
| `entity links` / `related_entities` | object-to-entity connection | threads, actionable provenance | Yes |
| `person links` / `relationship_to_user` | coarse relational role | entity resolution/profile | Yes |
| `project links` | inferred by `type=project` or relationship roles like `active_project` | entity pipeline | Yes |
| `thread/open-loop status` | unresolvedness and lifecycle | thread prompt and `open_threads` | Yes |
| `follow_up_after` / follow-up timing | earliest surfacing time | `open_threads`, proactive candidates | Yes |
| `emotional_weight` | light routing severity | Pass 1 triage | Yes |
| `temporal grounding fields` | `due_iso`, `effective_iso`, `time_text`, `date_resolution_basis` | Pass 2a/2b prompts and provenance | Yes |
| `stale` | should not surface as active | candidate tables, audit prompts, unified ops | Yes |
| `dismissed` | intentionally rejected/suppressed | candidates and objects | Yes |
| `superseded` | replaced by newer item | session changes, candidates, contradictions | Yes |
| `corrected` | not a universal table field; appears more as timeline/correction effect | timeline / trust-layer logic | Concept yes; field name unclear |

## 4.1 Important enum sets

### Actionable

- `record_type`: `event_candidate`, `task_candidate`, `reminder_candidate`, `commitment`
- `candidate_subtype`: `todo`, `reminder`, `calendar_event`, `habit`, `follow_up`, `waiting_on`, `nudge`
- `status`: `detected`, `needs_review`, `confirmed`, `dismissed`, `acted_on`, `superseded`, `stale`, later schema also `expired`
- `suggested_action`: `create_action_item`, `ask_user`, `ignore`

### Session changes

- `kind`: `factual_update`, `state_change`, `decision_change`, `schedule_change`, `focus_change`
- `status`: `detected`, `needs_review`, `confirmed`, `dismissed`, `superseded`, `stale`

### Entities

- `candidate_type` / `type`: `person`, `project`, `place`, `other`
- `entity resolution decision`: `MATCH`, `NEW`, `TENTATIVE`, `SKIP`
- `entity profile status`: `tentative`, `active`, `dormant`, `archived`
- `relationship_to_user`: prompt examples include `girlfriend`, `daughter`, `son`, `friend`, `colleague`, `active_project`, `mother`, `father`, `other`

### Threads

- `action`: `CREATE`, `UPDATE`, `RESOLVE`, `SNOOZE`, `NO_ACTION`
- `category`: `health`, `relationship`, `goal`, `commitment`, `worry`, `project`, `other`, later audit also `assistant_feedback`
- `priority`: `high`, `medium`, `low`
- `unresolvedness`: `open`, `resolved`, `unclear`
- `follow_up_value`: `low`, `medium`, `high`
- `evidence_strength`: `weak`, `medium`, `strong`
- table status/lifecycle: `open`, `resolved`, `snoozed`, `archived`; later `lifecycle_state` includes `active`, `resolved`, `snoozed`, `superseded`

### Identity / living context

- not rigid enum-driven outside nested lists, but strong field semantics matter more than labels

## 4.2 Specific field notes

### Fields worth preserving almost exactly

- `message_hint`
- `source_turn_refs`
- `date_resolution_basis`
- `requires_confirmation`
- `has_direct_user_expression`
- `waiting_on`
- `needs_response`
- `cadence_text`
- `follow_up_after`
- `relationship_to_user`
- `active_contradictions`
- `sophie_directives`

### Fields worth preserving conceptually but probably renaming

- `record_type` -> likely `item_type`
- `confidence_label` -> could become derived from numeric confidence
- `one_line_summary` in `session_classifications` -> routing note only
- `who_they_are` / `current_chapter` pair should remain conceptually intact

### Fields that are useful but too architecture-bound to keep literally

- `run_id`
- `candidate_key`, `change_key` hash patterns
- `pipeline_name`, `input_watermark`, `output_hash`
- `memory_layer`, `retention_floor`, `semantic_category`

---

# 5. Agent mapping recommendation

This is conceptual only. It assumes a clean rebuild with separate agents, not the old repo layout.

## triage_agent

- Reuse:
  - `PASS1_PROMPT`
- Preserve fields:
  - `is_memory_worthy`
  - `session_kind`
  - routing booleans
  - `emotional_weight`
  - `emotional_note`
  - `tension_signal`
  - `ignore_reasons`
- Preserve examples/rules:
  - “Pass 1 is not the place for personality reading”
  - “Only extract facts stated or confirmed by the USER”
- Avoid:
  - writing `session_classifications`-shaped legacy rows directly
- Suggested output shape:
  - `{"memory_worthy":bool,"routes":[...],"emotional_weight":"...","tension_signal":null|string,"ignore":[...]}`

## session_summary_agent

- Reuse:
  - `_summarize_session_close`
  - `_rewrite_structured_recap`
  - `_summarize_session_bridge`
- Preserve fields:
  - `summary_facts`
  - `tone`
  - `decisions`
  - `unresolved`
  - `moment`
  - `bridge`
- Preserve examples:
  - strict labeled output and word caps
- Avoid:
  - parser dependence on freeform brittle plaintext if new repo can use strict JSON
- Suggested output shape:
  - `{"summary":"...","bridge":"...","decisions":[...],"unresolved":[...],"moment":null|string,"tone":null|string}`

## task_agent

- Reuse:
  - `PASS2_ACTIONABLE_PROMPT`
  - `_ACTIONABLE_AUDIT_PROMPT`
  - `_ACTIONABLE_RECONCILIATION_PROMPT`
- Preserve fields:
  - `candidate_subtype`
  - `requires_confirmation`
  - `has_direct_user_expression`
  - all temporal fields
  - `waiting_on`
  - `needs_response`
  - `cadence_text`
  - `risk_tags`
- Avoid:
  - fragmented candidate/object tables
- Suggested output shape:
  - `{"items":[{"type":"task|reminder|habit|follow_up|waiting_on","title":"...","summary":"...","time":{...},"confidence":0.0,"needs_confirmation":true,"evidence":[...]}]}`

## event_agent

- Reuse:
  - same Pass 2a prompt rules for `calendar_event`
- Preserve:
  - explicit anti-invention time rules
  - “Calendar events must not auto-create”
- Avoid:
  - mixed storage with general actionables if the new system has a clean event object
- Suggested output shape:
  - `{"events":[{"title":"...","starts_at":null|string,"time_text":null|string,"confidence":0.0,"needs_confirmation":true,"evidence":[...]}]}`

## fact_agent

- Reuse:
  - entity discovery / entity resolution prompts
  - durable-fact precedence ideas from Pass 4 packet assembly
- Preserve:
  - `declared_profile_truth` precedence
  - `type`, `relationship_to_user`, `key_facts`
  - `first_mentioned`, `last_confirmed`
- Avoid:
  - entity profile prose as primary truth store
- Suggested output shape:
  - `{"facts":[{"subject":"...","predicate":"...","object":"...","confidence":0.0,"evidence":[...],"kind":"profile|relationship|project|state"}],"entities":[...]}`

## state_agent

- Reuse:
  - `LIVING_CONTEXT_PROMPT`
  - Pass 1 emotional routing fields
- Preserve:
  - `current_focus`
  - `primary_tension`
  - `relationship_pulse`
  - `emotional_texture`
  - `active_contradictions`
  - `sophie_directives`
- Avoid:
  - over-wide “recent_narrative” blobs if a cleaner state object exists
- Suggested output shape:
  - `{"state":{"focus":"...","tension":"...","relationship_pulse":null|string,"contradictions":[...],"directives":[...]}}`

## thread_agent

- Reuse:
  - `THREAD_EXTRACTION_PROMPT`
  - `THREAD_AUDIT_PROMPT`
- Preserve:
  - unresolved-situation framing
  - thread categories
  - `follow_up_after`
  - `why_this_matters_later`
  - `evidence_strength`
- Avoid:
  - giant SQL transition logic in `run_pass3_threads`
- Suggested output shape:
  - `{"threads":[{"action":"create|update|resolve|snooze","title":"...","detail":"...","category":"...","priority":"...","follow_up_after":null|string,"related_entities":[...],"evidence":[...]}]}`

## reconciliation_agent

- Reuse:
  - actionable audit/reconciliation prompts
  - entity resolution prompt
  - unified ops reconciliation prompt
- Preserve:
  - conservative merge posture
  - explicit `SEPARATE|MERGE|SUPERSEDE|DISMISS|STALE_EXISTING`
  - explicit risk / rationale / confirmation requirements
- Avoid:
  - storage-coupled SQL mutation side effects
- Suggested output shape:
  - `{"decisions":[{"action":"merge|separate|supersede|dismiss|needs_review","targets":[...],"reason":"...","confidence":0.0}]}`

## surfacing_agent

- Reuse:
  - startbrief paragraph prompt
  - startbrief evidence realizer
  - always-on packet rewrite constraints
  - deterministic attention labels from `attention_preview.py`
- Preserve:
  - evidence-cited lines
  - anti-drift, anti-advice, anti-poetic constraints
  - separation between enduring identity and current chapter
- Avoid:
  - old `daily_analysis` and `user_model` monolith as primary source
- Suggested output shape:
  - `{"surface_now":[...],"brief_lines":[{"text":"...","evidence_ids":[...]}],"runtime_context":"..."}`

---

# 6. What not to copy

## Monolithic route orchestration

- `src/main.py`
- `src/derived_pipeline.py`

Problems:

- far too many concerns in single files
- prompts, SQL, orchestration, serving, and migration logic co-located
- hard to reason about causality and test boundaries

## Giant pipeline files

- `src/derived_pipeline.py`

Problems:

- pass execution, persistence, audit, proactive candidates, contradictions, silence detection, and helpers all mixed together
- difficult to extract clean agent boundaries

## Deterministic language judgement mixed with semantic logic

- `src/fast_handover.py`
- parts of `src/attention_preview.py`
- parts of `src/session.py`

Problems:

- regex heuristics are useful as fallbacks, but not as the main intelligence layer
- brittle when they try to approximate meaning

## Brittle merge logic

- `src/derived_pipeline.py` session-change supersession helpers
- `src/derived_pipeline.py` thread-topic matching / relationship resolution SQL paths
- `src/derived_passes/candidate_audits.py` if copied without cleaner object model

Problems:

- many edge-case branches
- hard-coded topic matching and hash keys
- lifecycle mutation logic is tightly bound to old tables

## Duplicated candidate tables

- `actionable_candidates`
- `entity_candidates`
- `follow_up_candidates`
- `clarification_candidates`
- `recent_change_candidates`

Problems:

- fragmented pre-object staging model
- surfacing and reconciliation need to normalize across too many partial tables

## Graphiti / FalkorDB coupling

- See docs: `docs/SYNAPSE_TECHNICAL_PIPELINE_MAP.md`, `README.md`
- Also legacy references in `src/graphiti_client.py`, `src/falkor_utils.py`

Problems:

- split-brain memory authority
- harder debugging and unclear serving authority

## Anything that makes debugging difficult

- implicit background-loop orchestration in worker runtime
- large amounts of hidden state in checkpoints and status mutations
- plaintext section parsing instead of strict JSON when avoidable
- mixed old/new tables with compatibility behavior

---

# 7. Suggested migration order

Safest import order for a clean rebuild:

1. Triage/session summary prompt improvements
   - port `PASS1_PROMPT`
   - port structured session recap and bridge rules
2. Extraction agents
   - task/event/reminder from Pass 2a
   - session changes from Pass 2b
   - entities from Pass 2c + pass 1.5 assets
   - threads from Pass 3
3. Reconciliation
   - action/entity/thread reconciliation prompts
   - conservative merge/supersede policies
4. Surfacing/start brief
   - startbrief paragraph prompt
   - evidence-citing realizer
   - always-on packet rewrite constraints
5. Proactive/outreach/magic moments
   - follow-up candidate timing ideas
   - clarification / recent-change candidate ideas
   - attention-ranking rules
6. Workers/integrations
   - calendar/action promotion
   - external syncs
   - background loops only after agent outputs are stable

---

# 8. Appendix: raw assets

## 8.1 Key prompt constant names

- `PASS1_PROMPT`
- `PASS2_ACTIONABLE_PROMPT`
- `PASS2B_SESSION_CHANGES_PROMPT`
- `PASS2C_ENTITY_CANDIDATES_PROMPT`
- `THREAD_EXTRACTION_PROMPT`
- `THREAD_AUDIT_PROMPT`
- `IDENTITY_SYNTHESIS_PROMPT`
- `LIVING_CONTEXT_PROMPT`
- `ENTITY_DISCOVERY_PROMPT`
- `RESOLVE_PROMPT_TEMPLATE`
- `PROFILE_PROMPT_TEMPLATE`
- `_ACTIONABLE_AUDIT_PROMPT`
- `_SESSION_CHANGE_AUDIT_PROMPT`
- `_ENTITY_CANDIDATE_AUDIT_PROMPT`
- `_ACTIONABLE_RECONCILIATION_PROMPT`

## 8.2 Useful raw schema snippets

### `actionable_candidates`

```text
record_type: event_candidate|task_candidate|reminder_candidate|commitment
candidate_subtype: todo|reminder|calendar_event|habit|follow_up|waiting_on|nudge
status: detected|confirmed|dismissed|expired|needs_review|acted_on|superseded|stale
```

### `session_changes`

```text
kind: factual_update|state_change|decision_change|schedule_change|focus_change
status: detected|needs_review|confirmed|dismissed|superseded|stale
```

### `entity_candidates`

```text
candidate_type: person|project|place|other
status: detected|needs_review|resolved|dismissed|superseded
```

### `entity_profiles`

```text
status: tentative|active|dormant|archived
relationship_to_user: coarse role labels only
```

### `open_threads`

```text
status: open|resolved|snoozed|archived
priority: high|medium|low
category: health|relationship|goal|commitment|worry|project|other
thread_type: situational plus later specialized values
```

### Meaning-memory primitives

```text
low_confidence_items.status: open|asked|answered|dismissed|expired
memory_contradictions.status: active|resolved|superseded
memory_events.event_type: past_event|upcoming_event|commitment|anniversary|deadline
memory_events.lifecycle_state: active|resolved|superseded
memory_silence_flags.status: active|acknowledged|dismissed|resolved
```

## 8.3 Representative non-prompt phrasing assets

From `src/derived_pipeline.py` proactive candidates:

```text
Quick check-in on {title.lower()}: any update?
Quick health check-in: how is "{loop_text}" going?
You mentioned "{statement}" earlier. Did I understand that correctly?
Last time we discussed {title.lower()}. Any update since then?
Any update on {canonical} since we last discussed them?
```

These are small but reusable surfacing patterns.

## 8.4 Clear absences

These were requested but no dedicated exact prompt was found:

- standalone durable-facts extraction prompt
- standalone reminder-only prompt
- standalone calendar-only prompt
- daily-overview prompt
- generic attention/surfacing prompt for `attention_preview.py`

Where no dedicated prompt exists, the behavior is deterministic or folded into a broader lane.

