import json

import httpx
import pytest

from currator.brain import GeminiBrain
from currator.config import Settings
from currator.speech import PindoSpeech, UpstreamFailure, transcribe_english_gemini


@pytest.mark.asyncio
async def test_pindo_stt_contract():
    def handler(req):
        assert req.method == 'POST'
        assert str(req.url) == 'https://api.pindo.io/ai/stt/rw/public'
        assert b'name="audio"; filename="recording.wav"' in req.content
        return httpx.Response(200, json={'status':'success', 'data': {'text': 'Muraho neza'}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await PindoSpeech(Settings(), client).transcribe(b'WAV sample', 'audio/wav')
    assert result == 'Muraho neza'


@pytest.mark.asyncio
async def test_pindo_tts_contract():
    def handler(req):
        assert req.method == 'POST'
        assert str(req.url) == 'https://api.pindo.io/ai/tts/rw/public'
        assert b'Muraho neza' in req.content
        return httpx.Response(200, json={'status':'success', 'data': {'generated_audio_url': 'audio/test.wav'}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await PindoSpeech(Settings(pindo_media_base_url='https://api.pindo.io/'), client).speak('Muraho neza')
    assert result == 'https://api.pindo.io/audio/test.wav'


@pytest.mark.asyncio
async def test_gemini_answer_with_grounding():
    def handler(req):
        assert req.method == 'POST'
        assert req.headers['x-goog-api-key'] == 'test-key'
        assert b'google_search' in req.content
        return httpx.Response(200, json={'candidates': [{
            'content': {'parts': [{'text': 'Verified answer'}]},
            'groundingMetadata': {'groundingChunks':[{'web': {'title':'Source','uri':'https://example.com'}}]},
        }]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result, sources = await GeminiBrain(Settings(gemini_api_key='test-key'), client).answer(
            'What is the latest news?', 'en', [], use_google=True)
    assert result == 'Verified answer'
    assert sources[0].url == 'https://example.com'


@pytest.mark.asyncio
async def test_gemini_english_audio_contract():
    def handler(req):
        assert req.headers['x-goog-api-key'] == 'test-key'
        assert b'inline_data' in req.content
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': 'Hello there'}]}}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await transcribe_english_gemini(b'fake audio', 'audio/webm',
                                                  Settings(gemini_api_key='test-key'), client)
    assert result == 'Hello there'


@pytest.mark.asyncio
async def test_pindo_rate_limit_failure():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda req: httpx.Response(429, json={'error': 'limit reached'})
    )) as client:
        with pytest.raises(UpstreamFailure):
            await PindoSpeech(Settings(), client).speak('Muraho')


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["", "test-token"])
async def test_pindo_tts_payload_and_observed_media_host(token):
    audio_url = "https://pindo-ai-api-generated.s3.af-south-1.amazonaws.com/sample.wav"

    def handler(request):
        expected = {"text": "Muraho!", "speech_rate": 1.0}
        if token:
            expected["lang"] = "rw"
            assert request.headers["Authorization"] == "Bearer test-token"
        else:
            assert "Authorization" not in request.headers
        assert json.loads(request.content) == expected
        return httpx.Response(200, json={"data": {"generated_audio_url": audio_url}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        settings = Settings(pindo_token=token)
        assert await PindoSpeech(settings, client).speak("Muraho!") == audio_url


@pytest.mark.asyncio
async def test_pindo_null_transcript_is_empty():
    response = httpx.Response(200, json={"data": {"text": None}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)) as client:
        assert await PindoSpeech(Settings(), client).transcribe(b"wav", "audio/wav") == ""


@pytest.mark.asyncio
async def test_pindo_retries_explicit_transient_tts_failure():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"data": {
            "generated_audio_url": "https://api.pindo.io/test.wav",
        }})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await PindoSpeech(Settings(), client).speak("Muraho!")
    assert calls == 2
    assert result == "https://api.pindo.io/test.wav"


@pytest.mark.asyncio
async def test_pindo_does_not_retry_rate_limit():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(429)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(UpstreamFailure, match="rate limit"):
            await PindoSpeech(Settings(), client).speak("Muraho!")
    assert calls == 1
