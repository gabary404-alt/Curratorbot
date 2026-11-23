import httpx
import pytest
from fastapi.testclient import TestClient

from currator import main
from currator.config import Settings
from currator.speech import safe_audio_url


@pytest.fixture
def rehearsal(monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(mode="rehearsal"))
    with TestClient(main.app) as client:
        yield client


def test_rehearsal_bilingual_prepared_replies(rehearsal):
    config = rehearsal.get("/api/status").json()
    assert config["speech_input"] == ["rw"]
    assert config["speech_output"] == []
    assert config["motion_enabled"] is False
    for language, text in [("rw", "Muraho! Witwa nde?"), ("en", "Hi, what's your name?")]:
        reply = rehearsal.post("/api/chat", json={"text": text, "language": language}).json()
        assert reply["simulated"] is True
        assert reply["source_mode"] == "rehearsal"
        assert "Nshuti" in reply["reply"]


def test_rehearsal_transcribes_without_a_voice_key(rehearsal):

    def handler(request):
        if request.url.path == "/ai/stt/rw/public":
            return httpx.Response(200, json={"data": {"text": "Witwa nde?"}})
        raise AssertionError("Rehearsal without a key must not call a speech provider")

    provider_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    original_client = main.app.state.client
    main.app.state.client = provider_client
    try:
        upload = {"audio": ("question.webm", b"clip", "audio/webm;codecs=opus")}
        transcription = rehearsal.post("/api/speech/transcribe?language=rw", files=upload)
        assert transcription.status_code == 200
        reply = rehearsal.post("/api/chat", json={"text": transcription.json()["text"]}).json()
        voice = rehearsal.post("/api/speech/synthesize", json={"text": reply["reply"]}).json()
        assert voice == {"audio_url": None, "provider": "unavailable", "simulated": False}
    finally:
        main.app.state.client = original_client
        rehearsal.portal.call(provider_client.aclose)


def test_local_english_engine_is_exposed_and_used(rehearsal):
    class LocalTestEngine:
        async def transcribe(self, raw):
            assert raw == b"English audio"
            return "what is your name"

    main.app.state.english = LocalTestEngine()
    assert rehearsal.get("/api/status").json()["speech_input"] == ["rw", "en"]
    response = rehearsal.post(
        "/api/speech/transcribe?language=en",
        files={"audio": ("question.wav", b"English audio", "audio/wav")},
    )
    assert response.json()["text"] == "what is your name"


def test_empty_and_invalid_speech_requests(rehearsal):
    assert rehearsal.post(
        "/api/speech/transcribe", files={"audio": ("empty.wav", b"", "audio/wav")},
    ).status_code == 422
    assert rehearsal.post(
        "/api/speech/synthesize", json={"text": "  ", "language": "rw"},
    ).status_code == 422
    assert rehearsal.post(
        "/api/speech/synthesize", json={"text": "Hello", "language": "fr"},
    ).status_code == 422


@pytest.mark.parametrize("url", [
    "https://pindo-ai-api-generated.s3.af-south-1.amazonaws.com.evil.test/voice.wav",
    "https://api.pindo.io:444/voice.wav",
    "https://user@api.pindo.io/voice.wav",
    "https://api.pindo.io:bad/voice.wav",
    "///invalid/voice.wav",
    "https://[invalid/voice.wav",
])
def test_reject_unexpected_media_locations(url):
    assert safe_audio_url(url, "https://api.pindo.io/") is None


def test_current_answer_requires_sources(monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(
        mode="live", gemini_api_key="test", google_search_grounding=True,
    ))

    async def without_sources(self, *args, **kwargs):
        return "Unverified news", []

    monkeypatch.setattr(main.GeminiBrain, "answer", without_sources)
    with TestClient(main.app) as client:
        response = client.post("/api/chat", json={"text": "What is today's news?", "language": "en"})
    assert response.json()["source_mode"] == "live_unavailable"
    assert "Unverified news" not in response.json()["reply"]


def test_now_matches_word_boundaries():
    assert main.needs_current_info("What is happening now?")
    assert not main.needs_current_info("What do you know about robots?")


@pytest.mark.asyncio
async def test_wikimedia_prefers_requested_language_and_keeps_sources():
    from currator.knowledge import look_up

    def handler(request):
        if request.url.host == "www.wikidata.org":
            return httpx.Response(200, json={"search": [{
                "id": "Q3859", "label": "Kigali", "description": "Capital city",
            }]})
        assert request.url.params["generator"] == "search"
        return httpx.Response(200, json={"query": {"pages": {"1": {
            "title": "Kigali", "extract": request.url.host,
        }}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        context, sources = await look_up("Kigali", "rw", client, "CurratorBot test")
    assert "rw.wikipedia.org" in context
    assert "en.wikipedia.org" not in context
    assert [source.url for source in sources] == [
        "https://rw.wikipedia.org/wiki/Kigali", "https://www.wikidata.org/wiki/Q3859",
    ]


def test_both_languages_use_the_same_voice(monkeypatch):
    monkeypatch.setattr(main, "settings", Settings(mode="live", gemini_api_key="test"))
    calls = []

    async def speak(text, *_):
        calls.append(text)
        return "data:audio/wav;base64,UklGRg=="

    monkeypatch.setattr(main, "currator_voice", speak)
    with TestClient(main.app) as client:
        for text, language in (("Muraho", "rw"), ("Hello", "en")):
            response = client.post("/api/speech/synthesize", json={"text": text, "language": language})
            assert response.status_code == 200
            assert response.json()["provider"] == "currator"
    assert calls == ["Muraho", "Hello"]
