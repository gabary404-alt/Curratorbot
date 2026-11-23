import httpx
import pytest

from currator.config import Settings
from currator.speech import transcribe_automatic


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
    assert result == expected
    assert ("api.pindo.io" in hits) == (detected == "rw")
