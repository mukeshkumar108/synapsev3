## Build Principles

Synapse V3 is governed by the V3 build spec first.

### Source of Truth

- `Synapse_V3_Build_Spec.md` is the source of truth for:
  - architecture
  - task order
  - table count
  - repo structure
  - agent boundaries

- `SYNAPSE_V2_INTELLIGENCE_EXPORT.md` is reference material only.

### How To Use V2

- Consult `SYNAPSE_V2_INTELLIGENCE_EXPORT.md` for:
  - prompts
  - labels
  - lifecycle metadata
  - edge cases
  - proven judgement patterns

- Reuse useful V2 ideas only by adapting them into the V3 contract.
- Do not treat the V2 export as a replacement for the V3 build spec.

### Explicit Constraints

- Never copy old architecture.
- Never import old modules.
- Never recreate `derived_pipeline.py`.
- Never add old tables or revive the old fragmented storage model.

### Responsibility Split

- Keep Python responsible for:
  - validation
  - lifecycle
  - persistence
  - ranking and eligibility
  - traceability

- Keep agents responsible for:
  - structured semantic judgement

### Default Rule For Future Tasks

For every task going forward:

1. Follow the V3 build spec.
2. Consult `SYNAPSE_V2_INTELLIGENCE_EXPORT.md` for relevant prompt intelligence.
3. Reuse useful V2 ideas only by adapting them into the V3 contract.
4. Never copy old architecture, old modules, old tables, or `derived_pipeline.py`.
5. Keep Python responsible for validation, lifecycle, persistence, ranking/eligibility, and traceability.
6. Keep agents responsible for structured semantic judgement.
