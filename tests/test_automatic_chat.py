from fastapi.testclient import TestClient

from currator import main
from currator.brain import ReplyPlan
from currator.config import Settings
from currator.models import Source


def test_auto_chat_uses_detected_language_and_fetches_only_when_requested(monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(mode="live", gemini_api_key="test"))
    plans = iter([
        ReplyPlan(language="fr", route="answer", query="", reply="Trois chacun."),
        ReplyPlan(language="rw", route="reference", query="Kigali", reply=""),
    ])

    async def plan(self, text, history, retrieval):
        assert retrieval == "auto"
        return next(plans)

    searches = []

    async def lookup(query, language, *_):
        searches.append((query, language))
        return "Kigali is the capital of Rwanda.", [
            Source(label="Kigali", url="https://en.wikipedia.org/wiki/Kigali"),
        ]

    async def answer(self, text, language, history, knowledge, **kwargs):
        assert knowledge == "Kigali is the capital of Rwanda."
        assert language == "rw"
        return "Kigali ni umurwa mukuru w'u Rwanda.", []

    monkeypatch.setattr(main.GeminiBrain, "plan", plan)
    monkeypatch.setattr(main.GeminiBrain, "answer", answer)
    monkeypatch.setattr(main, "look_up", lookup)
    with TestClient(main.app) as client:
        direct = client.post("/api/chat", json={"text": "Douze divisé par quatre ?", "language": "auto"})
        assert direct.json()["language"] == "fr"
        assert direct.json()["reply"] == "Trois chacun."
        assert not searches
        research = client.post("/api/chat", json={"text": "Mbwira ibya Kigali", "language": "auto"})
    assert searches == [("Kigali", "rw")]
    assert research.json()["source_mode"] == "wikipedia"
    assert research.json()["sources"][0]["label"] == "Kigali"
import json



def test_research_progress_arrives_as_stream_events(monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(mode="rehearsal"))

    async def lookup(*_):
        return "Kigali", [Source(label="Kigali", url="https://en.wikipedia.org/wiki/Kigali")]

    monkeypatch.setattr(main, "look_up", lookup)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/chat", json={"text": "Kigali", "retrieval": "on"},
            headers={"Accept": "application/x-ndjson"},
        )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[:2] == [{"phase": "thinking"}, {"phase": "researching"}]
    assert events[2]["reply"]["sources"][0]["label"] == "Kigali"
