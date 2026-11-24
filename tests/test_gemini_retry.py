import httpx
import pytest

from currator.brain import GeminiBrain
from currator.config import Settings
from currator.speech import UpstreamFailure, transcribe_english_gemini


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["chat", "transcription"])
async def test_recovers_from_a_temporary_503(operation):
    statuses = iter([503, 200])

    models = []
    def handler(request):
        models.append(request.url.path.split("/")[-1])
        if models[-1] == "interactions":
            return httpx.Response(200, json={"steps": [{"type": "model_output", "content": [
                {"type": "text", "text": "Nshuti"},
            ]}]})
        return httpx.Response(next(statuses), json={
            "candidates": [{"content": {"parts": [{"text": "Nshuti"}]}}],
        })

    settings = Settings(gemini_api_key="test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        if operation == "chat":
            assert await GeminiBrain(settings, client).answer("Witwa nde?", "rw", []) == (
                "Nshuti", [],
            )
        else:
            assert await transcribe_english_gemini(b"audio", "audio/wav", settings, client) == "Nshuti"
    assert models == ["gemini-3.5-flash-lite:generateContent", "interactions"]


@pytest.mark.asyncio
async def test_quota_error_reports_limit_without_retrying():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UpstreamFailure, match="usage limit"):
            await GeminiBrain(Settings(gemini_api_key="test"), client).answer("Hello", "en", [])
    assert len(calls) == 1
