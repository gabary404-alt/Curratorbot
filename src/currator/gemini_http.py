"""Bounded retries and safe diagnostics for Gemini requests."""

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)
RETRYABLE = {500, 502, 503, 504}


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
