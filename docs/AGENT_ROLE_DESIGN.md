## Agent Role Design

Cortex agents should be designed as role-based specialists, not generic prompt calls.

Each agent should feel like a clearly bounded professional function inside the system:
- a specialist with one job
- a defined decision boundary
- a structured input
- a strict output contract
- explicit things it must never do

This keeps the system legible, composable, and safer to evolve.

### 1. Agent Classes

#### A. Extraction Specialists

Current extraction specialists:
- `task_agent`
- `event_agent`
- `fact_agent`
- `state_agent`
- `thread_agent`

Their job:
- extract structured candidates from raw source material
- stay in lane
- preserve evidence
- avoid overreach

They should:
- read raw source material only
- avoid cross-contamination across domains
- emit candidate-shaped structured items
- preserve exact evidence and traceability
- avoid inference when evidence is weak

They should not:
- reconcile against existing memory
- write to the database
- call other agents
- decide what becomes trusted memory
- produce broad summaries in place of extraction

#### B. Judgement Agents

Current and planned judgement agents:
- `reconciliation_agent`
- `surfacing_agent`
- future `outreach_agent`

Their job:
- make nuanced decisions using candidate, fact, and context packets
- apply human-like judgement within strict output contracts
- preserve memory integrity and user trust

They should:
- reason over prepared structured packets
- make decisions conservatively
- respect sensitivity, ambiguity, and user boundaries
- operate as editorial or planning roles rather than extractors

They should not:
- freewheel outside their allowed decision set
- improvise new schemas
- collapse multiple responsibilities into one broad prompt
- bypass validation or persistence safeguards

### 2. Prompt Style By Class

#### Extraction Prompts

Extraction prompts should emphasize:
- narrow domain
- raw evidence
- no cross-contamination
- structured JSON
- no database access

They should sound like:
- a precise specialist
- focused on one memory lane only
- disciplined about what belongs elsewhere

They should include:
- what counts
- what does not count
- examples of correct vs incorrect extraction
- exact required JSON shape

They should avoid:
- generic “analyze this conversation” phrasing
- open-ended synthesis
- role language that encourages drift into judgement or personality

#### Judgement Prompts

Judgement prompts should emphasize:
- role identity, such as memory editor or chief of staff
- decision responsibility
- conservative judgement
- what good and bad decisions mean
- sensitivity and boundary handling
- clear allowed decision set
- strict output schema

They should sound like:
- a careful editor
- a planner
- a trusted internal decision-maker

They should include:
- consequences of bad judgement
- explicit distinctions between similar decision options
- stronger handling for ambiguity and sensitivity
- clear instructions not to invent IDs, facts, or actions

### 3. Reconciliation Agent Role

`reconciliation_agent` should be defined as:

**“Sophie’s memory editor for Cortex.”**

Responsibilities:
- decide what becomes trusted memory
- prevent duplicate or dirty memory
- distinguish repeated evidence from new information
- decide `CREATE`, `MERGE`, `UPDATE`, or `DISMISS`
- preserve `companion_category` meaning
- handle sensitive boundaries carefully
- avoid merging merely by shared people or topics

This role is editorial, not extractive.

Its standard structure should be:
- Role: Sophie’s memory editor
- Job: keep memory clean, useful, non-duplicative, and safe
- Decision boundary: decide only between `CREATE`, `MERGE`, `UPDATE`, `DISMISS`
- Input: new candidate packets plus a small set of existing facts
- Output schema: reconciliation instruction array
- Must-never rules:
  - never invent `candidate_id`
  - never invent `target_id`
  - never over-merge by vague similarity
  - never casually flatten sensitive boundaries into generic memories

### 4. Surfacing Agent Role

`surfacing_agent` should be defined as:

**“Sophie’s chief of staff.”**

Responsibilities:
- decide what Sophie should be aware of now
- choose 2-3 things maximum
- suppress stale, dismissed, or overly sensitive items
- produce a briefing, not a personality response
- prepare Sophie, not replace Sophie

This role is briefing and prioritization, not extraction and not final conversation generation.

Its standard structure should be:
- Role: Sophie’s chief of staff
- Job: prepare the best possible brief for the current moment
- Decision boundary: rank and filter what deserves attention now
- Input: relevant confirmed facts, open tasks, current state, recent timeline, and context packet
- Output schema: session brief with instructions, focus, warnings, and relevant topics
- Must-never rules:
  - never produce a full chat reply as if it were Sophie
  - never surface dismissed or stale items as current
  - never overload the brief with too many topics
  - never ignore avoid-topic or sensitivity boundaries

### 5. Runtime Boundary

The runtime boundary should stay explicit:

- Cortex agents prepare structured intelligence.
- Sophie runtime owns final voice, tone, personality, and exact wording.
- Cortex may provide calibration signals, warnings, and suggested focus.
- Cortex should not pretend to speak as Sophie unless explicitly building a message draft for an outreach packet later.

This distinction matters because:
- Cortex is the intelligence and memory layer
- Sophie runtime is the conversational delivery layer

If Cortex starts speaking as Sophie too early, system responsibilities blur and errors become harder to contain.

### 6. Failure Modes

Common failure modes to guard against:

- extractor overreach creates noisy candidates
- reconciliation overmerge poisons memory
- surfacing overshares sensitive context
- runtime overuses memory and feels creepy

More concretely:

- `task_agent` overreach:
  - turns events or companion follow-ups into tasks
- `fact_agent` overreach:
  - stores operational or temporary context as durable truth
- `thread_agent` overreach:
  - creates open loops for trivial or resolved items
- `reconciliation_agent` overmerge:
  - combines distinct memories because the same person appears in both
- `reconciliation_agent` under-conservative behavior:
  - promotes inferred sensitive memory too easily
- `surfacing_agent` over-surfacing:
  - raises sensitive, stale, or avoid-topic material casually
- runtime misuse:
  - references memory too often or too explicitly and feels invasive

### 7. Design Rule

Every agent should be specified using the same structure:

- role
- job
- decision boundary
- input
- output schema
- must-never rules

This creates consistency across the system.

It also makes prompt review easier:
- if the role is vague, the prompt will drift
- if the job is broad, the agent will overreach
- if the decision boundary is weak, it will do adjacent work
- if the output schema is loose, persistence and testing become brittle
- if must-never rules are absent, safety and memory quality degrade

The design goal is not just “make the prompt better.”

The design goal is:
- one role
- one job
- one decision boundary
- one contract

That is how Cortex stays modular, trustworthy, and evolvable.
