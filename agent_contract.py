from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Participant(BaseModel):
    id: str        # 'user', 'sophie', or UUID for external contacts
    name: str      # 'Alex', 'Sophie', 'Ashley'
    role: str      # 'user', 'assistant', 'contact'


class TranscriptTurn(BaseModel):
    index: int
    speaker_id: str
    content: str
    source_message_id: str | None = None


class AgentInput(BaseModel):
    user_id: str
    source_type: str
    raw_content: str
    interaction_mode: str = "real_life"
    participants: list[Participant] = Field(default_factory=list)
    turns: list[TranscriptTurn] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)


class AgentOutput(BaseModel):
    agent: str
    status: str
    items: list[Any] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    confidence_notes: str = ""
