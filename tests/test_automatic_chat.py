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
import asyncio



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


def test_voice_and_text_arrive_in_one_final_event(monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(mode="rehearsal", gemini_api_key="test"))

    async def voice(text, *_):
        assert "Nshuti" in text
        return "data:audio/wav;base64,UklGRg=="

    monkeypatch.setattr(main, "currator_voice", voice)
    with TestClient(main.app) as client:
        result = client.post(
            "/api/chat", json={"text": "Witwa nde?", "include_audio": True},
            headers={"Accept": "application/x-ndjson"},
        )
    events = [json.loads(line) for line in result.text.splitlines()]
    assert events[1] == {"phase": "preparing"}
    assert "Nshuti" in events[2]["reply"]["reply"]
    assert events[2]["reply"]["audio_url"].startswith("data:audio/wav")


def test_greeting_skips_gemini_and_late_voice_does_not_hold_the_answer(monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(mode="live", gemini_api_key="test"))

    async def unexpected_plan(*_):
        raise AssertionError("An exact greeting should not call Gemini chat")

    async def delayed_voice(*_):
        await asyncio.sleep(2)

    monkeypatch.setattr(main.GeminiBrain, "plan", unexpected_plan)
    monkeypatch.setattr(main, "currator_voice", delayed_voice)
    with TestClient(main.app) as client:
        response = client.post("/api/chat", json={
            "text": "Muraho neza! Witwa nde?", "language": "auto",
            "include_audio": True, "latency_budget_ms": 500,
        })
    result = response.json()
    assert response.status_code == 200
    assert result["language"] == "rw"
    assert "Nshuti" in result["reply"]
    assert result["audio_url"] is None
    assert result["audio_error"]
