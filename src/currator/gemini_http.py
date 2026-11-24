"""Bounded retries and safe diagnostics for Gemini requests."""

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)
RETRYABLE = {500, 502, 503, 504}
FLASH_LITE_MODELS = ("gemini-3.5-flash-lite", "gemini-3.1-flash-lite")


async def interaction_retry(client, body, key, timeout):
    steps = []
    for turn in body["contents"]:
        content = []
        for part in turn["parts"]:
            if "text" in part:
                content.append({"type": "text", "text": part["text"]})
            else:
                content.append({"type": "audio", **part["inline_data"]})
        steps.append({"type": "user_input" if turn.get("role", "user") == "user" else "model_output",
                      "content": content})
    config = body["generationConfig"]
    request = {"model": "gemini-3.8-flash", "input": steps, "store": False,
               "generation_config": {"max_output_tokens": config["maxOutputTokens"]}}
    if "system_instruction" in body:
        request["system_instruction"] = body["system_instruction"]["parts"][0]["text"]
    if "responseJsonSchema" in config:
        request["response_format"] = {"type": "text", "mime_type": "application/json",
                                      "schema": config["responseJsonSchema"]}
    response = await client.post("https://generativelanguage.googleapis.com/v1beta/interactions",
                                 json=request, headers={"x-goog-api-key": key}, timeout=timeout)
    response.raise_for_status()
    parts = [{"text": part["text"]} for step in response.json().get("steps", [])
             if step.get("type") == "model_output" for part in step.get("content", [])
             if part.get("type") == "text"]
    return httpx.Response(200, json={"candidates": [{"content": {"parts": parts}}]})


async def generate(client: httpx.AsyncClient, url: str, *, body: dict, key: str,
                   operation: str, timeout: float) -> httpx.Response:
    for attempt in range(2):
        try:
            response = await client.post(
                url, json=body, headers={"x-goog-api-key": key}, timeout=timeout,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            retryable = status in RETRYABLE or isinstance(exc, httpx.TransportError)
            logger.warning("Gemini %s attempt=%d status=%s error=%s",
                           operation, attempt + 1, status, type(exc).__name__)
            if attempt or not retryable:
                raise
            # Both supported Flash-Lite models accept our text, audio and JSON schemas.
            # Keep custom endpoints and models on their explicitly selected provider.
            for model, alternate in zip(FLASH_LITE_MODELS, reversed(FLASH_LITE_MODELS)):
                if url.endswith(f"/{model}:generateContent"):
                    if "tools" not in body:
                        return await interaction_retry(client, body, key, timeout)
                    url = url.removesuffix(f"{model}:generateContent") + f"{alternate}:generateContent"
                    logger.info("Gemini %s retry model=%s", operation, alternate)
                    break
            await asyncio.sleep(0.5)
    raise AssertionError("Gemini request exhausted without a result")


def failure_message(exc: httpx.HTTPError, operation: str) -> str:
    if isinstance(exc, httpx.TimeoutException):
        return f"Gemini timed out during {operation}. Please try again."
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 429:
            return "Gemini reached its usage limit. Try again after the quota resets."
        if code in (401, 403):
            return f"Gemini denied access for {operation}. Check the project's key and model access."
        if code in RETRYABLE:
            return f"Gemini is temporarily unavailable for {operation}. Please try again."
        return f"Gemini rejected the request for {operation} (HTTP {code})."
    return f"Could not reach Gemini for {operation}. Please try again."
