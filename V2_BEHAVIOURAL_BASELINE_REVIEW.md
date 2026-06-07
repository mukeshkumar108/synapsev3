# V2 Behavioural Baseline Review

This document reviews the existing V2 audit output using the correct framing:

- V2 is the behavioural baseline.
- V2 is not the architectural target.
- The goal is to preserve or exceed useful user-facing behavior without cloning V2 endpoints, tables, or orchestration.

Classification used throughout:

1. Preserve and improve in V3
2. Preserve behaviour but redesign implementation
3. Discard as V2 cruft
4. Defer because not needed for current Sophie ship

Sources reviewed:

- [docs/SYNAPSE_V2_ENDPOINT_OUTPUT_AUDIT.md](/opt/synapse/docs/SYNAPSE_V2_ENDPOINT_OUTPUT_AUDIT.md:1)
- [docs/V2_MEMORY_AND_STARTUP_BEHAVIOUR_AUDIT.md](/opt/synapse/docs/V2_MEMORY_AND_STARTUP_BEHAVIOUR_AUDIT.md:1)
- [docs/SYNAPSE_V2_INTELLIGENCE_EXPORT.md](/opt/synapse/SYNAPSE_V2_INTELLIGENCE_EXPORT.md:1)

---

# 1. Executive Summary

The right baseline is not “copy V2.” The right baseline is:

- what V2 actually helped Sophie do well
- what users likely experienced as continuity, usefulness, and safety
- what should survive even if the serving and storage model changes completely

The strongest V2 behaviours were:

- evidence-gated factual recall
- decent episodic recall quality
- explicit open-loop continuity
- startup handover with time-gap awareness
- lightweight entity hinting
- deterministic day-planning summaries
- durable ingest with idempotency

The weakest V2 behaviours were:

- legacy compatibility shells
- endpoint sprawl
- candidate-table-shaped API surfaces
- monolithic user-model exposure
- stale compatibility fields and tests that no longer matched live behavior

The main rule for V3 parity is simple:

- preserve user-visible behaviour
- redesign implementation freely
- drop V2 compatibility baggage

---

# 2. Behaviour Classification

## 2.1 Recall Quality

### Evidence-backed factual recall

- V2 behavior:
  - exact/factual recall returned only active canonical claims with evidence links
  - claims without evidence were dropped
- Classification: `1. Preserve and improve in V3`
- Reason:
  - this is one of the clearest quality and safety wins in V2
  - it directly reduced hallucinated “facts”
- Improvement direction:
  - keep evidence gating
  - improve factual coverage and ranking quality

### Episodic recall using embedding + lexical + recency scoring

- V2 behavior:
  - episodic recall used embedding candidates from `episodic_memory_embeddings`
  - combined embedding similarity, lexical overlap, recency, anchor overlap, and user-density
  - diversity pass reduced same-session overconcentration
- Classification: `1. Preserve and improve in V3`
- Reason:
  - this was real retrieval behavior, not fake “recent sessions” recall
  - users likely depended on “we were discussing this before” continuity

### Hybrid recall with separate factual / episodic / continuity lanes

- V2 behavior:
  - hybrid merged lane outputs while preserving lane labels in V2
  - legacy adapter flattened some continuity into derived facts
- Classification: `2. Preserve behaviour but redesign implementation`
- Reason:
  - the useful behavior is mixed recall, not the V2 endpoint shell or flattening
  - lane semantics matter; endpoint shape does not

### Continuity recall explicitly marked derived

- V2 behavior:
  - continuity lane was derived-only
  - canonical factual rows were excluded from continuity output
- Classification: `1. Preserve and improve in V3`
- Reason:
  - keeping derived continuity distinct from truth claims is a real safety property

### Query-profile-sensitive episodic scoring

- V2 behavior:
  - episodic scoring changed weights for `relationship`, `reflective`, `continuation`, `default` query profiles
- Classification: `2. Preserve behaviour but redesign implementation`
- Reason:
  - behaviorally useful
  - implementation can change; hard-coded profile heuristics do not need to survive literally

### Weak recall detection

- V2 behavior:
  - episodic recall computed `weakRecall` and `weakRecallReason`
  - current endpoint path did not actually surface them to Sophie
- Classification: `2. Preserve behaviour but redesign implementation`
- Reason:
  - the useful part is detecting weak recall quality
  - V2’s mistake was computing it but not consistently surfacing it

### `focusQuery`

- V2 behavior:
  - request field existed but was effectively ignored in the active recall path
- Classification: `3. Discard as V2 cruft`
- Reason:
  - unused API field
  - not a real behaviour baseline

### `includeContext`

- V2 behavior:
  - accepted by legacy `/memory/query`
  - only affected metadata and compatibility notice in T11 adapter mode
- Classification: `3. Discard as V2 cruft`
- Reason:
  - not real context-mode behavior in the active path

---

## 2.2 Deduplication

### Factual dedupe by claim identity and evidence-backed canonical rows

- V2 behavior:
  - factual lane grouped claim rows and returned only evidence-backed active claims
- Classification: `1. Preserve and improve in V3`
- Reason:
  - dedupe at the fact layer is fundamental to usable recall

### Continuity dedupe by normalized text

- V2 behavior:
  - continuity facts were deduped by normalized text
- Classification: `2. Preserve behaviour but redesign implementation`
- Reason:
  - the behavior is useful
  - text-only dedupe is brittle and should not be copied literally

### Episodic session diversity pass

- V2 behavior:
  - recall tried to avoid overfilling with one session
- Classification: `1. Preserve and improve in V3`
- Reason:
  - this improves recall usefulness materially

### Retry/idempotency dedupe for ingest

- V2 behavior:
  - session ingest deduped via outbox key
  - turn ingest deduped via `turn_ingest_idempotency`
- Classification: `1. Preserve and improve in V3`
- Reason:
  - this is core durability behavior

---

## 2.3 Confidence Scoring

### Factual truth/extraction confidence carried into recall metadata

- V2 behavior:
  - factual items carried truth and extraction confidence in metadata
- Classification: `1. Preserve and improve in V3`
- Reason:
  - confidence matters for downstream surfacing and operator trust

### Episodic composite scoring

- V2 behavior:
  - top episodic candidates had explicit composite scores
- Classification: `1. Preserve and improve in V3`
- Reason:
  - ranking quality is part of the baseline

### Summary/loop scoring inside startup

- V2 behavior:
  - startup selected summaries and loops by explicit score with thresholds
- Classification: `1. Preserve and improve in V3`
- Reason:
  - startup quality depended on scoring, not just latest rows

### Coarse label fields everywhere

- V2 behavior:
  - many endpoints mixed numeric confidence with `low|medium|high` compatibility labels
- Classification: `2. Preserve behaviour but redesign implementation`
- Reason:
  - confidence should survive
  - label clutter does not need to

---

## 2.4 Evidence / Source References

### Fact evidence refs

- V2 behavior:
  - factual items returned concrete evidence links and evidence text
- Classification: `1. Preserve and improve in V3`
- Reason:
  - this is one of the strongest baseline behaviors

### Episodic evidence lines

- V2 behavior:
  - episodic items returned evidence lines from transcript windows or transcript fallback
- Classification: `1. Preserve and improve in V3`
- Reason:
  - important for trust and grounding

### Startup evidence/freshness trace

- V2 behavior:
  - startbrief included selected summary IDs, loop ranking, freshness, selection trace, realizer info
- Classification: `2. Preserve behaviour but redesign implementation`
- Reason:
  - not all of that needs to be exposed all the time
  - but provenance and freshness matter

### Provenance source arrays without concrete evidence

- V2 behavior:
  - some entity/profile outputs gave provenance source names only
- Classification: `2. Preserve behaviour but redesign implementation`
- Reason:
  - source awareness matters
  - plain source lists are weaker than real evidence refs

---

## 2.5 Open-Loop Retrieval

### Durable cross-session open loops

- V2 behavior:
  - loops were durable memory and surfaced across startup and recall
- Classification: `1. Preserve and improve in V3`
- Reason:
  - this is a central continuity behavior

### Loop ranking by salience + importance + urgency + status penalty

- V2 behavior:
  - startup loops were not purely recent; they used weighted priority
- Classification: `1. Preserve and improve in V3`
- Reason:
  - this materially improved usefulness

### Domain-filtered loop retrieval

- V2 behavior:
  - `/memory/loops` could filter loops by domain
- Classification: `4. Defer because not needed for current Sophie ship`
- Reason:
  - useful, but not core to initial parity if startup loop ranking works

### Persona-compatible loop retrieval parameter

- V2 behavior:
  - `personaId` was accepted but ignored
- Classification: `3. Discard as V2 cruft`
- Reason:
  - compatibility-only behavior

---

## 2.6 Startup Handover

### Time-gap awareness

- V2 behavior:
  - startup computed minutes/hours since last spoke
  - depth labels changed by time gap
- Classification: `1. Preserve and improve in V3`
- Reason:
  - users experience this directly as continuity quality

### Startup depth classification

- V2 behavior:
  - `continuation`
  - `today`
  - `yesterday`
  - `multi_day`
- Classification: `1. Preserve and improve in V3`
- Reason:
  - compact but meaningful behavior cue

### Compact anti-drift handover text

- V2 behavior:
  - startup prose had strong anti-advice and anti-hallucination constraints
- Classification: `1. Preserve and improve in V3`
- Reason:
  - this was one of the best end-user-facing behaviors in V2

### Combining recent summaries + loops + entity hints + recent changes

- V2 behavior:
  - startup packet was a synthesis of multiple signals, not just summary text
- Classification: `1. Preserve and improve in V3`
- Reason:
  - this is the actual useful startup behavior

### `resume.bridge_text`

- V2 behavior:
  - concept existed and older tests/scripts referenced it
  - current implementation effectively leaves `resume.use_bridge=false` and `bridge_text=null`
- Classification: `3. Discard as V2 cruft`
- Reason:
  - current live behavior does not rely on it
  - stale compatibility artifact

### `session/brief` as separate surface

- V2 behavior:
  - compatibility summary surface overlapping startbrief
- Classification: `3. Discard as V2 cruft`
- Reason:
  - endpoint duplication, not user-visible capability gain

---

## 2.7 Entity Hints / Profile Behaviour

### Lightweight startup entity hints

- V2 behavior:
  - startup included lightweight entity hints ranked from active entity profiles
- Classification: `1. Preserve and improve in V3`
- Reason:
  - useful continuity boost at low token cost

### Entity profile card with facts + relationship + recency + loops

- V2 behavior:
  - entity profile combined key facts, role/relationship, recency, and open loops
- Classification: `1. Preserve and improve in V3`
- Reason:
  - this is a genuinely good serving behavior

### Role fallback from user model

- V2 behavior:
  - entity role/relationship could fall back to user model hints
- Classification: `2. Preserve behaviour but redesign implementation`
- Reason:
  - relational continuity matters
  - weakly grounded fallback should be handled more carefully

### `entity_profiles` array inside startup response

- V2 behavior:
  - legacy compatibility field, currently empty
- Classification: `3. Discard as V2 cruft`
- Reason:
  - not active useful behavior

---

## 2.8 Action / Calendar Lifecycle

### Canonical action item lifecycle

- V2 behavior:
  - action items had durable statuses and timestamps
  - audit log tracked transitions
- Classification: `1. Preserve and improve in V3`
- Reason:
  - this is real product behavior, not compatibility baggage

### Canonical calendar item lifecycle

- V2 behavior:
  - calendar items had confirm/cancel/archive lifecycle plus provenance
- Classification: `1. Preserve and improve in V3`
- Reason:
  - clear durable object behavior

### Day-level grouping of due / reminders / overdue / pending candidates

- V2 behavior:
  - daily agenda and day brief surfaced action state in useful buckets
- Classification: `1. Preserve and improve in V3`
- Reason:
  - users likely relied on this organization

### Alias routes for `/done`, `/dismiss`, `/cancel`

- V2 behavior:
  - multiple route aliases for simple status transitions
- Classification: `3. Discard as V2 cruft`
- Reason:
  - route clutter, not behavioral value

### Candidate promotion logic tightly coupled to CRUD

- V2 behavior:
  - candidates and CRUD were intertwined
- Classification: `2. Preserve behaviour but redesign implementation`
- Reason:
  - promotion and confirmation behavior matters
  - coupling does not

---

## 2.9 Freshness / Safety Behaviour

### Startup freshness reporting

- V2 behavior:
  - startup reported pending ingest freshness and provenance/debug state
- Classification: `1. Preserve and improve in V3`
- Reason:
  - startup should know when memory may still be catching up

### Evidence-gated fact safety

- V2 behavior:
  - factual lane dropped unsupported claims
- Classification: `1. Preserve and improve in V3`
- Reason:
  - direct safety property

### Explicit separation of canonical vs derived recall

- V2 behavior:
  - canonical factual and derived continuity were separated
- Classification: `1. Preserve and improve in V3`
- Reason:
  - major safety and interpretability gain

### Unsurfaced weak-recall audit

- V2 behavior:
  - internal quality signal existed but was not exposed consistently
- Classification: `2. Preserve behaviour but redesign implementation`
- Reason:
  - V3 should preserve the quality check, not the omission

---

# 3. Summary Table

| Behaviour | Classification | Notes |
| --- | --- | --- |
| Evidence-gated factual recall | 1 | Core quality baseline |
| Embedding-assisted episodic recall | 1 | Core continuity baseline |
| Hybrid lane behavior | 2 | Preserve behavior, redesign serving |
| Derived-only continuity lane | 1 | Preserve safety distinction |
| Weak recall detection | 2 | Preserve signal, redesign exposure |
| `focusQuery` request field | 3 | Unused |
| `includeContext` compatibility mode | 3 | Not real current behavior |
| Fact dedupe | 1 | Preserve |
| Text-based continuity dedupe | 2 | Preserve behavior, redesign logic |
| Session diversity in episodic recall | 1 | Preserve |
| Ingest idempotency | 1 | Preserve |
| Confidence scoring in recall | 1 | Preserve |
| Startup selection scoring | 1 | Preserve |
| Coarse compatibility confidence labels | 2 | Preserve confidence, not clutter |
| Fact evidence/source refs | 1 | Preserve |
| Episodic evidence lines | 1 | Preserve |
| Startup provenance/freshness trace | 2 | Preserve behavior, redesign exposure |
| Durable open loops | 1 | Preserve |
| Loop ranking by weighted priority | 1 | Preserve |
| Domain-filtered loop API | 4 | Defer |
| Persona loop parameter | 3 | Discard |
| Time-gap-aware startup | 1 | Preserve |
| Startup depth labels | 1 | Preserve |
| Anti-drift handover prose | 1 | Preserve |
| `resume.bridge_text` behavior | 3 | Current live value is effectively dead |
| Separate `/session/brief` surface | 3 | Endpoint cruft |
| Startup entity hints | 1 | Preserve |
| Entity card behavior | 1 | Preserve |
| User-model role fallback | 2 | Preserve behavior, redesign grounding |
| Startup `entity_profiles` field | 3 | Discard |
| Canonical action lifecycle | 1 | Preserve |
| Canonical calendar lifecycle | 1 | Preserve |
| Day-level due/reminder/overdue grouping | 1 | Preserve |
| Alias action/calendar mutation routes | 3 | Discard |
| Candidate-promotion coupling | 2 | Preserve behavior, redesign implementation |
| Startup freshness / ingest catch-up awareness | 1 | Preserve |

---

# 4. V3 Behavioural Parity Checklist

This is a behavioural checklist only.

## P0 Before Replacing Sophie V2

These are the minimum behaviors that need parity before V2 can be replaced safely.

### Recall

- [ ] Exact recall returns only evidence-backed factual memory.
- [ ] Episodic recall can retrieve relevant older conversations, not just recent ones.
- [ ] Hybrid recall can combine fact + episode + derived continuity behaviorally.
- [ ] Canonical facts and derived continuity are clearly separated.
- [ ] Recall items include usable evidence/source grounding.

### Startup / handover

- [ ] Startup knows how long it has been since the last meaningful interaction.
- [ ] Startup distinguishes continuation vs same-day vs multi-day context.
- [ ] Startup handover text is compact, non-advising, and non-hallucinatory.
- [ ] Startup includes top current loops.
- [ ] Startup includes lightweight entity hints.
- [ ] Startup includes enough freshness state to avoid stale confidence.

### Open loops

- [ ] Durable open loops survive across sessions.
- [ ] Open loops are ranked by more than recency.
- [ ] Low-value loops do not dominate startup.

### Entity / profile

- [ ] Entity card behavior exists:
  - facts
  - role/relationship
  - recency
  - linked loop context

### Day planning

- [ ] Day planning combines schedule + actions.
- [ ] Due items, reminders, and overdue items are separately visible.
- [ ] Workload can produce a pressure signal.

### Ingest / durability

- [ ] Full transcripts are durably stored.
- [ ] Session ingest is idempotent.
- [ ] Retries do not duplicate turn/session writes.
- [ ] Background processing can be queued safely after durable write.

## P1 Before Beta

These improve operator trust and quality, but are not all required for the first hard replacement.

### Recall quality

- [ ] Weak recall is detected and handled explicitly.
- [ ] Episodic ranking preserves session diversity.
- [ ] Confidence scoring is exposed consistently enough for downstream safety logic.
- [ ] Source/evidence refs are normalized across recall item types.

### Startup quality

- [ ] Startup scoring over summaries and loops is explicit and inspectable.
- [ ] Recent change synthesis is reliable and non-trivial.
- [ ] Startup exposes operator/debug provenance when needed, without polluting the main response.

### Entity/profile

- [ ] Role/relationship grounding is better than V2’s weak fallback behavior.
- [ ] Profile freshness/completeness state is visible enough for trust decisions.

### Day planning

- [ ] Pending review candidates are incorporated coherently into day-planning behavior.
- [ ] Action/calendar provenance remains available for auditability.

## P2 Backlog

These are useful behaviors but not necessary for the current Sophie ship.

- [ ] Domain-filtered loop retrieval as a first-class served behavior.
- [ ] Fine-grained compatibility metadata for old client shapes.
- [ ] Expanded surfacing/debug traces equivalent to the noisiest V2 evidence payloads.
- [ ] Secondary or niche review surfaces shaped like V2 internal candidate lenses.

---

# 5. Practical Reading Of The Baseline

The baseline should be read like this:

- Preserve what improved recall quality.
- Preserve what improved continuity at startup.
- Preserve what improved trust through evidence and freshness.
- Preserve what made actions, events, and loops durable and usable.
- Do not preserve endpoint duplication, compatibility shells, or old storage-shaped response clutter.

That is the right interpretation of V2 as a behavioural baseline.

