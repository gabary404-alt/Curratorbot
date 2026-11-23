import httpx
import pytest

from currator.config import Settings
from currator.kinyarwanda import prepare_for_speech
from currator.speech import currator_voice, transcribe_automatic


@pytest.mark.asyncio
async def test_single_voice_model_reads_both_languages():
    import json

    def handler(request):
        body = json.loads(request.content)
        assert request.url.path == "/v1beta/interactions"
        assert body["model"] == "gemini-3.8-flash-lite-tts"
        assert body["generation_config"]["speech_config"] == [{"voice": "Zubenelgenubi"}]
        assert body["input"][0]["content"][0]["text"] in {"Muraho neza!", "Hi there!"}
        return httpx.Response(200, json={"steps": [{
            "type": "model_output", "content": [{"type": "audio", "data": "UklGRg=="}],
        }]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        for text in ("Muraho neza!", "Hi there!"):
            assert (await currator_voice(text, Settings(gemini_api_key="test"), client)).startswith(
                "data:audio/wav;base64,"
            )


def test_speech_punctuation_preserves_elision_and_question_intonation():
    assert prepare_for_speech("Yego , ndabyumva; ni iby’u Rwanda. Urumva ??") == (
        "Yego, ndabyumva. ni iby'u Rwanda. Urumva?"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("detected", "pindo", "expected"),
    [
        ("rw", "Nagiye i Kigali.", ("Nagiye i Kigali.", False)),
        ("rw", "Sinagiye i Kigali.", ("Sinagiye i Kigali.", True)),
        ("rw", None, ("Nagiye i Kigali.", False)),
        ("mixed", None, ("Nagiye i Kigali.", False)),
    ],
)
async def test_auto_speech_uses_specialist_and_flags_disagreement(detected, pindo, expected):
    hits = []

    def handler(request):
        hits.append(request.url.host)
        if request.url.host == "api.pindo.io":
            return httpx.Response(200, json={"text": pindo}) if pindo else httpx.Response(503)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{
            "text": f'{{"text":"Nagiye i Kigali.","language":"{detected}","unclear":false}}',
        }]}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await transcribe_automatic(
            b"sample", "audio/webm", "audio/webm", Settings(gemini_api_key="test"), client,
        )
    assert result == (*expected, detected)
    assert ("api.pindo.io" in hits) == (detected == "rw")
