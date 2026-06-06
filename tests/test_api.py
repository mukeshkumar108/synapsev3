from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from core.api import app, get_database


class FakeDatabase:
    def __init__(self) -> None:
        self.outbox_rows: list[dict] = []
        self.confirmed_facts: list[dict] = []
        self.timeline_events: list[dict] = []

    async def execute(self, query: str, *args):
        if "INSERT INTO outbox" in query:
            self.outbox_rows.append(
                {
                    "id": args[0],
                    "user_id": args[1],
                    "source_type": args[2],
                    "raw_content": args[3],
                    "received_at": args[4],
                    "status": args[5],
                    "retry_count": args[6],
                    "metadata": args[7],
                }
            )
        return "OK"

    async def fetch(self, query: str, *args):
        if "FROM confirmed_facts" in query:
            return [fact for fact in self.confirmed_facts if fact["user_id"] == args[0] and fact["status"] == "active"]
        if "FROM timeline_events" in query:
            return [event for event in self.timeline_events if event["user_id"] == args[0]][: args[1]]
        return []

    async def close(self):
        return None


def _fact(*, fact_type: str, domain: str, content: dict, status: str = "active", last_seen_at: datetime | None = None, expires_at=None):
    return {
        "id": uuid4(),
        "user_id": "user-1",
        "fact_type": fact_type,
        "domain": domain,
        "content": content,
        "confidence": 0.9,
        "first_seen_at": datetime(2026, 5, 20, 12, 0),
        "last_seen_at": last_seen_at or datetime(2026, 5, 22, 12, 0),
        "last_confirmed_at": datetime(2026, 5, 22, 12, 0),
        "source_ids": [uuid4()],
        "status": status,
        "user_corrected": False,
        "correction_note": None,
        "expires_at": expires_at,
    }


def _override_database(db: FakeDatabase):
    async def _dependency():
        yield db

    return _dependency


def test_health_endpoint() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "synapse-v3"}


def test_instruction_packet_includes_open_loop(monkeypatch) -> None:
    db = FakeDatabase()
    db.confirmed_facts.append(
        _fact(
            fact_type="thread",
            domain="workstreams",
            content={
                "schema_version": "v1",
                "item_type": "thread",
                "title": "Waiting on Jordan contract",
                "summary": "Still waiting on Jordan.",
                "salience": "high",
                "priority": "high",
                "urgency": None,
                "importance": "high",
                "sensitivity": "low",
                "time": {"stale_after_hours": 72, "follow_up_after_hours": 24},
                "links": {"people": ["Jordan"], "projects": ["contract"], "related_facts": [], "related_threads": []},
                "lifecycle": {"stale_after_hours": 72, "follow_up_after_hours": 24, "expires_at": None},
                "evidence": {"raw_evidence": "Waiting on Jordan", "source_turn_refs": []},
                "metadata": {"companion_category": None, "agent_item": {}},
            },
        )
    )

    def fake_run(**kwargs):
        assert kwargs["threads"]
        return {
            "session_instructions": "Lead with the Jordan contract update.",
            "relevant_topics": ["Jordan contract"],
            "worth_attention": [
                {
                    "title": "Waiting on Jordan contract",
                    "why_it_matters": "It is blocking progress.",
                    "suggested_way_to_raise": "Ask whether Jordan has replied.",
                    "sensitivity": "low",
                    "source_fact_ids": [str(db.confirmed_facts[0]["id"])],
                }
            ],
            "suggested_focus": "Jordan contract",
            "tone_note": "Be practical.",
            "avoid": [],
            "stale_warnings": [],
        }

    monkeypatch.setattr("core.serving.surfacing_agent.run", fake_run)
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)
    response = client.get("/v3/sessions/instruction-packet", params={"user_id": "user-1"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["worth_attention"][0]["title"] == "Waiting on Jordan contract"


def test_avoid_topic_is_not_surface_topic(monkeypatch) -> None:
    db = FakeDatabase()
    db.confirmed_facts.append(
        _fact(
            fact_type="identity",
            domain="profile",
            content={
                "schema_version": "v1",
                "item_type": "fact",
                "title": "user",
                "summary": "Avoid fertility topic unless user raises it.",
                "salience": "high",
                "priority": None,
                "urgency": None,
                "importance": "high",
                "sensitivity": "high",
                "time": {},
                "links": {"people": [], "projects": ["fertility"], "related_facts": [], "related_threads": []},
                "lifecycle": {"expires_at": None, "stale_after_hours": None, "follow_up_after_hours": None},
                "evidence": {"raw_evidence": "Please don't bring up fertility", "source_turn_refs": []},
                "metadata": {"companion_category": "avoid_topic", "agent_item": {"fact_type": "constraint"}},
            },
        )
    )

    def fake_run(**kwargs):
        return {
            "session_instructions": "Stay respectful and avoid user-declared sensitive topics.",
            "relevant_topics": [],
            "worth_attention": [],
            "suggested_focus": "General support",
            "tone_note": "Be calm and respectful.",
            "avoid": ["fertility topic unless user raises it"],
            "stale_warnings": [],
        }

    monkeypatch.setattr("core.serving.surfacing_agent.run", fake_run)
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)
    response = client.get("/v3/sessions/instruction-packet", params={"user_id": "user-1"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["avoid"]
    assert body["worth_attention"] == []


def test_communication_preference_calibrates_tone_not_topic(monkeypatch) -> None:
    db = FakeDatabase()
    db.confirmed_facts.append(
        _fact(
            fact_type="preference",
            domain="profile",
            content={
                "schema_version": "v1",
                "item_type": "fact",
                "title": "user",
                "summary": "User prefers direct practical support.",
                "salience": "high",
                "priority": None,
                "urgency": None,
                "importance": "high",
                "sensitivity": "low",
                "time": {},
                "links": {"people": [], "projects": [], "related_facts": [], "related_threads": []},
                "lifecycle": {"expires_at": None, "stale_after_hours": None, "follow_up_after_hours": None},
                "evidence": {"raw_evidence": "Be direct", "source_turn_refs": []},
                "metadata": {"companion_category": "communication_preference", "agent_item": {"fact_type": "preference"}},
            },
        )
    )

    def fake_run(**kwargs):
        return {
            "session_instructions": "Be direct and practical.",
            "relevant_topics": [],
            "worth_attention": [],
            "suggested_focus": "Current conversation needs",
            "tone_note": "Direct, practical, low-fluff.",
            "avoid": [],
            "stale_warnings": [],
        }

    monkeypatch.setattr("core.serving.surfacing_agent.run", fake_run)
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)
    response = client.get("/v3/sessions/instruction-packet", params={"user_id": "user-1"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["tone_note"].startswith("Direct")
    assert body["relevant_topics"] == []


def test_stale_state_is_suppressed(monkeypatch) -> None:
    db = FakeDatabase()
    db.confirmed_facts.append(
        _fact(
            fact_type="state",
            domain="state",
            last_seen_at=datetime(2026, 5, 20, 8, 0),
            content={
                "schema_version": "v1",
                "item_type": "state",
                "title": None,
                "summary": "User felt stressed.",
                "salience": "high",
                "priority": None,
                "urgency": None,
                "importance": "high",
                "sensitivity": "medium",
                "time": {"stale_after_hours": 4},
                "links": {"people": [], "projects": [], "related_facts": [], "related_threads": []},
                "lifecycle": {"expires_at": None, "stale_after_hours": 4, "follow_up_after_hours": None},
                "evidence": {"raw_evidence": "I am stressed", "source_turn_refs": []},
                "metadata": {"companion_category": "worry", "agent_item": {}},
            },
        )
    )

    def fake_run(**kwargs):
        assert kwargs["state"] == []
        return {
            "session_instructions": "Do not assume the old state is still current.",
            "relevant_topics": [],
            "worth_attention": [],
            "suggested_focus": "Current conversation",
            "tone_note": "Neutral.",
            "avoid": [],
            "stale_warnings": ["Old state fact suppressed as stale."],
        }

    monkeypatch.setattr("core.serving.surfacing_agent.run", fake_run)
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)
    response = client.get(
        "/v3/sessions/instruction-packet",
        params={"user_id": "user-1", "current_datetime": "2026-05-22T12:00:00+00:00"},
    )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["stale_warnings"]


def test_worth_attention_max_three(monkeypatch) -> None:
    db = FakeDatabase()

    def fake_run(**kwargs):
        return {
            "session_instructions": "Focus tightly.",
            "relevant_topics": ["a", "b", "c"],
            "worth_attention": [
                {"title": "1", "why_it_matters": "a", "suggested_way_to_raise": "a", "sensitivity": "low", "source_fact_ids": []},
                {"title": "2", "why_it_matters": "b", "suggested_way_to_raise": "b", "sensitivity": "low", "source_fact_ids": []},
                {"title": "3", "why_it_matters": "c", "suggested_way_to_raise": "c", "sensitivity": "low", "source_fact_ids": []},
            ],
            "suggested_focus": "1",
            "tone_note": "calm",
            "avoid": [],
            "stale_warnings": [],
        }

    monkeypatch.setattr("core.serving.surfacing_agent.run", fake_run)
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)
    response = client.get("/v3/sessions/instruction-packet", params={"user_id": "user-1"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    assert len(response.json()["worth_attention"]) <= 3


def test_memory_query_returns_active_matching_facts() -> None:
    db = FakeDatabase()
    db.confirmed_facts.extend(
        [
            _fact(
                fact_type="preference",
                domain="profile",
                content={
                    "schema_version": "v1",
                    "item_type": "fact",
                    "title": "user",
                    "summary": "User is vegetarian.",
                    "salience": "high",
                    "priority": None,
                    "urgency": None,
                    "importance": "high",
                    "sensitivity": "low",
                    "time": {},
                    "links": {"people": [], "projects": [], "related_facts": [], "related_threads": []},
                    "lifecycle": {"expires_at": None, "stale_after_hours": None, "follow_up_after_hours": None},
                    "evidence": {"raw_evidence": "I am vegetarian", "source_turn_refs": []},
                    "metadata": {"companion_category": None, "agent_item": {}},
                },
            ),
            _fact(
                fact_type="preference",
                domain="profile",
                status="dismissed",
                content={
                    "schema_version": "v1",
                    "item_type": "fact",
                    "title": "user",
                    "summary": "Dismissed item",
                    "salience": "low",
                    "priority": None,
                    "urgency": None,
                    "importance": "low",
                    "sensitivity": "low",
                    "time": {},
                    "links": {"people": [], "projects": [], "related_facts": [], "related_threads": []},
                    "lifecycle": {"expires_at": None, "stale_after_hours": None, "follow_up_after_hours": None},
                    "evidence": {"raw_evidence": "dismissed", "source_turn_refs": []},
                    "metadata": {"companion_category": None, "agent_item": {}},
                },
            ),
        ]
    )

    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)
    response = client.post("/v3/memory/query", json={"user_id": "user-1", "query_text": "vegetarian"})
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "active"


def test_outbox_ingest_creates_pending_row() -> None:
    db = FakeDatabase()
    app.dependency_overrides[get_database] = _override_database(db)
    client = TestClient(app)
    response = client.post(
        "/v3/outbox/ingest",
        json={
            "user_id": "user-1",
            "source_type": "chat",
            "raw_content": "hello",
            "metadata": {"thread_id": "t-1"},
        },
    )
    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "pending"
    assert db.outbox_rows[0]["metadata"] == {"thread_id": "t-1"}
