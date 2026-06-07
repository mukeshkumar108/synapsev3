## Companion Memory Primitives

### 1. Purpose

Cortex is not only a productivity memory engine. It is the intelligence layer that helps Sophie feel attentive, emotionally aware, personal, and continuous without pretending to be human.

Productivity memory asks:
- What does the user need to do?
- What is scheduled?
- What is due?

Companion memory asks:
- What does the user care about?
- What are they proud of?
- What hurts?
- What are they hoping for?
- What do they fear?
- Who matters?
- How do they like to be supported?
- What should Sophie ask about later?
- What should Sophie avoid?

The goal is not sentimentality. The goal is usable continuity. Sophie should feel like a respectful life-aware companion, not a task bot.

Companion memory must fit inside the existing V3 six-table architecture:
- `candidates` holds extracted candidate memories
- `confirmed_facts` holds promoted durable truth
- `timeline_events` reflects meaningful side effects later

No new tables are required. Typed envelopes inside `candidates.content` and `confirmed_facts.content` carry the companion-specific structure.

### 2. Companion Memory Categories

#### `win`
- Definition: A positive moment the user is pleased about right now.
- Examples: “I finally finished the investor deck.” “That conversation went better than I expected.”
- Candidate type mapping: `state` or `thread`
- Confirmed promotion: `fact_type=state` or `thread`, `domain=state` or `opportunities`
- Typical salience: medium to high
- Typical sensitivity: low to medium
- Typical lifespan/staleness: hours to 1 week unless reinforced
- Usually needs confirmation: no
- Sophie may proactively raise it: yes, lightly

#### `accomplishment`
- Definition: A concrete achievement worth remembering beyond the current moment.
- Examples: “I got the promotion.” “I shipped the Apollo migration.”
- Candidate type mapping: `fact`
- Confirmed promotion: `fact_type=identity` or `event`, `domain=profile` or `workstreams`
- Typical salience: high
- Typical sensitivity: low to medium
- Typical lifespan/staleness: long-lived
- Usually needs confirmation: sometimes if implied, otherwise no
- Sophie may proactively raise it: yes

#### `low`
- Definition: A painful or discouraging moment the user is currently in.
- Examples: “I feel awful about how that meeting went.” “Today has been rough.”
- Candidate type mapping: `state`
- Confirmed promotion: usually stays provisional; if promoted, `fact_type=state`, `domain=state`
- Typical salience: medium to high
- Typical sensitivity: high
- Typical lifespan/staleness: hours to 72 hours unless reinforced
- Usually needs confirmation: no
- Sophie may proactively raise it: yes, gently

#### `struggle`
- Definition: An ongoing difficulty, recurring challenge, or sustained friction.
- Examples: “I keep procrastinating on admin work.” “I am struggling with sleep again.”
- Candidate type mapping: `thread` or `fact`
- Confirmed promotion: `fact_type=state` or `thread`, `domain=habits`, `workstreams`, or `state`
- Typical salience: medium to high
- Typical sensitivity: high
- Typical lifespan/staleness: days to weeks
- Usually needs confirmation: often
- Sophie may proactively raise it: yes, carefully

#### `hope`
- Definition: A desired near- or mid-term positive outcome.
- Examples: “I hope this role opens more creative work.” “I hope Nina and I can reset.”
- Candidate type mapping: `fact` or `thread`
- Confirmed promotion: `fact_type=identity` or `thread`, `domain=goals` or `relationship`
- Typical salience: medium
- Typical sensitivity: medium to high
- Typical lifespan/staleness: weeks to months
- Usually needs confirmation: often
- Sophie may proactively raise it: yes, sparingly

#### `aspiration`
- Definition: A durable ambition, direction, or longer-range desire.
- Examples: “I want to write a book.” “I want to build a calmer life.”
- Candidate type mapping: `fact`
- Confirmed promotion: `fact_type=identity`, `domain=goals`
- Typical salience: high
- Typical sensitivity: medium
- Typical lifespan/staleness: months to years
- Usually needs confirmation: sometimes
- Sophie may proactively raise it: yes

#### `fear`
- Definition: A durable or recurring fear with identity or life-pattern significance.
- Examples: “I am scared of burning out again.” “I worry I will disappoint everyone.”
- Candidate type mapping: `fact` or `thread`
- Confirmed promotion: `fact_type=state` or `identity`, `domain=state`
- Typical salience: high
- Typical sensitivity: high
- Typical lifespan/staleness: weeks to months
- Usually needs confirmation: yes
- Sophie may proactively raise it: only carefully

#### `worry`
- Definition: A current or near-term concern that may fade.
- Examples: “I am worried the team can tell I am behind.” “I am worried about Friday.”
- Candidate type mapping: `state` or `thread`
- Confirmed promotion: usually `state` or `thread`, `domain=state` or `obligations`
- Typical salience: medium to high
- Typical sensitivity: high
- Typical lifespan/staleness: hours to days
- Usually needs confirmation: no
- Sophie may proactively raise it: yes, gently

#### `inside_joke`
- Definition: A repeated playful reference meaningful to the user relationship.
- Examples: “Spreadsheet goblin mode.” “Tuesday is my fake Monday.”
- Candidate type mapping: `fact`
- Confirmed promotion: `fact_type=preference` or `relationship`, `domain=profile`
- Typical salience: low to medium
- Typical sensitivity: low
- Typical lifespan/staleness: long-lived if reinforced
- Usually needs confirmation: often
- Sophie may proactively raise it: yes, sparingly

#### `comfort_preference`
- Definition: A preference for how the user likes to be soothed, supported, or helped.
- Examples: “Do not overdo reassurance.” “Tea and one practical step helps.”
- Candidate type mapping: `fact`
- Confirmed promotion: `fact_type=preference`, `domain=profile`
- Typical salience: high
- Typical sensitivity: medium
- Typical lifespan/staleness: long-lived
- Usually needs confirmation: yes if inferred
- Sophie may proactively raise it: only by using it, not announcing it

#### `communication_preference`
- Definition: A preference about style, structure, or communication format.
- Examples: “Be direct.” “Give me bullet points when I am stressed.”
- Candidate type mapping: `fact`
- Confirmed promotion: `fact_type=preference`, `domain=profile`
- Typical salience: high
- Typical sensitivity: low to medium
- Typical lifespan/staleness: long-lived
- Usually needs confirmation: yes if inferred
- Sophie may proactively raise it: yes through behavior

#### `tone_preference`
- Definition: A preference for emotional tone or conversational energy.
- Examples: “Keep it calm.” “I like a bit of humor when I am spiraling.”
- Candidate type mapping: `fact`
- Confirmed promotion: `fact_type=preference`, `domain=profile`
- Typical salience: medium to high
- Typical sensitivity: medium
- Typical lifespan/staleness: long-lived
- Usually needs confirmation: yes if inferred
- Sophie may proactively raise it: yes through behavior

#### `encouragement_style`
- Definition: The kind of encouragement the user responds well to.
- Examples: “Push me gently.” “Do not cheerlead, just anchor me.”
- Candidate type mapping: `fact`
- Confirmed promotion: `fact_type=preference`, `domain=profile`
- Typical salience: high
- Typical sensitivity: medium
- Typical lifespan/staleness: long-lived
- Usually needs confirmation: yes if inferred
- Sophie may proactively raise it: yes through behavior

#### `personal_value`
- Definition: A principle the user explicitly or repeatedly cares about.
- Examples: “I care about honesty more than smoothness.” “Family comes first.”
- Candidate type mapping: `fact`
- Confirmed promotion: `fact_type=identity`, `domain=profile`
- Typical salience: high
- Typical sensitivity: medium
- Typical lifespan/staleness: long-lived
- Usually needs confirmation: sometimes
- Sophie may proactively raise it: yes, respectfully

#### `sensitivity_boundary`
- Definition: A boundary around topics, timing, or style Sophie should respect.
- Examples: “Do not bring up my ex unless I do.” “Do not push when I shut down.”
- Candidate type mapping: `fact`
- Confirmed promotion: `fact_type=constraint`, `domain=profile`
- Typical salience: high
- Typical sensitivity: high
- Typical lifespan/staleness: long-lived
- Usually needs confirmation: yes unless explicit
- Sophie may proactively raise it: no, but must respect it

#### `avoid_topic`
- Definition: A topic the user does not want surfaced casually.
- Examples: fertility treatment, a grief topic, a family dispute
- Candidate type mapping: `fact`
- Confirmed promotion: `fact_type=constraint`, `domain=profile`
- Typical salience: high
- Typical sensitivity: high
- Typical lifespan/staleness: long-lived unless corrected
- Usually needs confirmation: yes if inferred
- Sophie may proactively raise it: no

#### `ask_about_later`
- Definition: Something worth checking back on later for companion continuity.
- Examples: “How did the conversation with Nina go?” “Did the interview happen?”
- Candidate type mapping: `thread`
- Confirmed promotion: `fact_type=thread`, `domain=workstreams`, `relationship`, or `opportunities`
- Typical salience: medium
- Typical sensitivity: medium
- Typical lifespan/staleness: days to weeks
- Usually needs confirmation: no
- Sophie may proactively raise it: yes

#### `celebration_moment`
- Definition: A moment that merits acknowledgment or celebration.
- Examples: birthday, launch, good news, a result the user cared about
- Candidate type mapping: `event` or `fact`
- Confirmed promotion: `fact_type=event`, `domain=events` or `opportunities`
- Typical salience: medium to high
- Typical sensitivity: low
- Typical lifespan/staleness: time-bound
- Usually needs confirmation: sometimes
- Sophie may proactively raise it: yes

#### `meaningful_routine`
- Definition: A recurring pattern that matters emotionally or identity-wise, not just operationally.
- Examples: Sunday meal prep as grounding, Friday call with dad, morning run for sanity
- Candidate type mapping: `fact` or `task`
- Confirmed promotion: `fact_type=preference` or `identity`, `domain=habits`
- Typical salience: medium to high
- Typical sensitivity: low to medium
- Typical lifespan/staleness: long-lived if reinforced
- Usually needs confirmation: sometimes
- Sophie may proactively raise it: yes

#### `important_person`
- Definition: A person who matters to the user beyond a passing mention.
- Examples: close friend, sister, partner, mentor, manager who strongly shapes current life
- Candidate type mapping: `fact`
- Confirmed promotion: `fact_type=relationship`, `domain=people`
- Typical salience: high
- Typical sensitivity: medium
- Typical lifespan/staleness: long-lived
- Usually needs confirmation: sometimes
- Sophie may proactively raise it: yes

#### `relationship_context`
- Definition: Ongoing context about a meaningful relationship.
- Examples: “Nina and I are rebuilding trust.” “My manager is supportive but inconsistent.”
- Candidate type mapping: `fact` or `thread`
- Confirmed promotion: `fact_type=relationship` or `thread`, `domain=people` or `relationship`
- Typical salience: high
- Typical sensitivity: high
- Typical lifespan/staleness: weeks to months
- Usually needs confirmation: often
- Sophie may proactively raise it: yes, carefully

### 3. Agent Mapping

#### `fact_agent`
Should detect:
- durable preferences
- values
- inside jokes
- communication preferences
- comfort preferences
- people who matter
- relationship context
- hopes/fears if they look durable rather than momentary
- meaningful routines when identity-relevant

#### `state_agent`
Should detect:
- current lows
- current wins
- temporary fears and worries
- current emotional pressure
- current excitement
- current vulnerability

These should stay provisional unless later reinforced.

#### `thread_agent`
Should detect:
- things to ask about later
- unresolved worries
- emotional open loops
- upcoming meaningful moments with unresolved follow-up value
- celebration follow-ups
- relationship situations

#### `task_agent`
Should detect only:
- real actions
- reminders
- operational habits
- explicit follow-ups
- waiting-on items when the user needs to act or track

#### `event_agent`
Should detect only:
- time-anchored plans
- invitations
- appointments
- deadlines
- celebration moments when they are calendar-like

### 4. Personalisation Layer

Cortex should gradually learn how Sophie should speak to the user without becoming manipulative.

Useful personalization concepts:
- `preferred_tone`
- `responds_well_to`
- `dislikes_tone`
- `encouragement_style`
- `directness_level`
- `humour_style`
- `affection_level_non_romantic`
- `reminder_style`
- `challenge_style`
- `comfort_style`
- `check_in_frequency_preference`
- `topics_to_avoid`
- `sensitive_topics`
- `language_preferences`
- `examples_of_phrasing_that_worked`
- `examples_of_phrasing_that_backfired`

These should be stored as typed `fact` candidates and later promoted selectively into `confirmed_facts.content`.

Purpose:
- make Sophie more respectful
- make Sophie more useful
- make Sophie more emotionally calibrated

Not purpose:
- emotional dependency
- persuasion
- covert steering

### 5. Safety and Boundaries

Sophie must not:
- pretend to be human
- create romantic or sexual dependency
- isolate the user from real people
- use sensitive memories manipulatively
- use possessive language

Sophie should:
- encourage real-world support when appropriate
- respect “do not bring this up” preferences
- treat user correction as higher authority than inferred memory
- use sensitive context with restraint
- avoid overusing emotionally loaded memories for effect

If there is tension between inferred companion usefulness and explicit user preference, user preference wins.

### 6. Candidate Envelope Examples

#### 1. Win / accomplishment

```json
{
  "schema_version": "v1",
  "item_type": "state",
  "title": "Finished investor deck",
  "summary": "The user feels relieved and proud after finishing the investor deck.",
  "salience": "high",
  "sensitivity": "medium",
  "evidence": {
    "raw_evidence": "I finally finished the investor deck and I feel so much lighter.",
    "source_turn_refs": []
  },
  "links": {
    "people": [],
    "projects": ["investor deck"],
    "related_facts": [],
    "related_threads": []
  },
  "lifecycle": {
    "follow_up_after_hours": 24,
    "stale_after_hours": 72,
    "expires_at": null
  },
  "metadata": {
    "companion_category": "win",
    "agent_item": {}
  }
}
```

#### 2. Low / struggle

```json
{
  "schema_version": "v1",
  "item_type": "state",
  "title": "Rough day at work",
  "summary": "The user feels overwhelmed and discouraged after a hard day.",
  "salience": "high",
  "sensitivity": "high",
  "evidence": {
    "raw_evidence": "Today has been rough. I feel like I cannot catch up.",
    "source_turn_refs": []
  },
  "links": {
    "people": [],
    "projects": [],
    "related_facts": [],
    "related_threads": []
  },
  "lifecycle": {
    "follow_up_after_hours": 12,
    "stale_after_hours": 48,
    "expires_at": null
  },
  "metadata": {
    "companion_category": "low",
    "agent_item": {}
  }
}
```

#### 3. Hope / aspiration

```json
{
  "schema_version": "v1",
  "item_type": "fact",
  "title": "Creative career direction",
  "summary": "The user hopes their next role gives them more creative ownership.",
  "salience": "medium",
  "sensitivity": "medium",
  "evidence": {
    "raw_evidence": "I really hope my next role gives me more room to build things my way.",
    "source_turn_refs": []
  },
  "links": {
    "people": [],
    "projects": [],
    "related_facts": [],
    "related_threads": []
  },
  "lifecycle": {
    "follow_up_after_hours": null,
    "stale_after_hours": null,
    "expires_at": null
  },
  "metadata": {
    "companion_category": "hope",
    "agent_item": {}
  }
}
```

#### 4. Fear / worry

```json
{
  "schema_version": "v1",
  "item_type": "thread",
  "title": "Fear of burnout returning",
  "summary": "The user is worried they may be slipping back toward burnout.",
  "salience": "high",
  "sensitivity": "high",
  "evidence": {
    "raw_evidence": "I am scared I am heading back into burnout territory.",
    "source_turn_refs": []
  },
  "links": {
    "people": [],
    "projects": [],
    "related_facts": [],
    "related_threads": []
  },
  "lifecycle": {
    "follow_up_after_hours": 24,
    "stale_after_hours": 168,
    "expires_at": null
  },
  "metadata": {
    "companion_category": "fear",
    "agent_item": {}
  }
}
```

#### 5. Inside joke

```json
{
  "schema_version": "v1",
  "item_type": "fact",
  "title": "Spreadsheet goblin mode",
  "summary": "The user jokingly calls deep admin-focus mode spreadsheet goblin mode.",
  "salience": "low",
  "sensitivity": "low",
  "evidence": {
    "raw_evidence": "I am back in spreadsheet goblin mode again.",
    "source_turn_refs": []
  },
  "links": {
    "people": [],
    "projects": [],
    "related_facts": [],
    "related_threads": []
  },
  "lifecycle": {
    "follow_up_after_hours": null,
    "stale_after_hours": null,
    "expires_at": null
  },
  "metadata": {
    "companion_category": "inside_joke",
    "agent_item": {}
  }
}
```

#### 6. Communication preference

```json
{
  "schema_version": "v1",
  "item_type": "fact",
  "title": "Direct support preference",
  "summary": "The user prefers direct, grounded support over soft reassurance.",
  "salience": "high",
  "sensitivity": "medium",
  "evidence": {
    "raw_evidence": "Please do not over-comfort me. Just tell me the next step.",
    "source_turn_refs": []
  },
  "links": {
    "people": [],
    "projects": [],
    "related_facts": [],
    "related_threads": []
  },
  "lifecycle": {
    "follow_up_after_hours": null,
    "stale_after_hours": null,
    "expires_at": null
  },
  "metadata": {
    "companion_category": "communication_preference",
    "agent_item": {}
  }
}
```

#### 7. Thing to ask about later

```json
{
  "schema_version": "v1",
  "item_type": "thread",
  "title": "How the Nina conversation went",
  "summary": "The user planned to talk with Nina again and it is worth following up later.",
  "salience": "medium",
  "sensitivity": "high",
  "evidence": {
    "raw_evidence": "We said we would talk again this weekend, but I do not know how to start.",
    "source_turn_refs": []
  },
  "links": {
    "people": ["Nina"],
    "projects": [],
    "related_facts": [],
    "related_threads": []
  },
  "lifecycle": {
    "follow_up_after_hours": 48,
    "stale_after_hours": 168,
    "expires_at": null
  },
  "metadata": {
    "companion_category": "ask_about_later",
    "agent_item": {}
  }
}
```

#### 8. Thing to avoid

```json
{
  "schema_version": "v1",
  "item_type": "fact",
  "title": "Do not casually raise fertility topic",
  "summary": "The user does not want fertility-related topics surfaced unless they bring them up first.",
  "salience": "high",
  "sensitivity": "high",
  "evidence": {
    "raw_evidence": "Please do not bring that up unless I do.",
    "source_turn_refs": []
  },
  "links": {
    "people": [],
    "projects": [],
    "related_facts": [],
    "related_threads": []
  },
  "lifecycle": {
    "follow_up_after_hours": null,
    "stale_after_hours": null,
    "expires_at": null
  },
  "metadata": {
    "companion_category": "avoid_topic",
    "agent_item": {}
  }
}
```

### 7. Future Surfacing Implications

Later, `surfacing_agent` should use companion memory to:
- celebrate wins
- gently follow up on lows
- ask about meaningful people
- reference inside jokes sparingly
- adapt tone to the user
- avoid sensitive topics
- choose between practical support and emotional support
- avoid overwhelming the user

Surfacing should treat companion memory as calibration, not as a list to dump. The question is not “what can Sophie mention?” It is “what helps Sophie respond well right now?”

### 8. Implementation Guidance For Later

Suggested order:
1. Update `fact_agent` prompt and categories
2. Update `state_agent` prompt and categories
3. Update `thread_agent` prompt and categories
4. Add tests for companion primitives
5. Later, use these fields in `reconciliation_agent`
6. Later, use these fields in `surfacing_agent` and the session instruction packet

This document should guide future Task 3 refinements, but it does not require any immediate code change.
