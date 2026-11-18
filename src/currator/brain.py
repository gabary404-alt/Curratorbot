"""Gemini text response generation and optional Google Search grounding."""
from __future__ import annotations

import httpx

from .config import Settings
from .models import Source
from .speech import UpstreamFailure

PERSONA = """You are Currator, a friendly conversational robot presenting in Rwanda.
Primary language is Kinyarwanda; answer in Kinyarwanda when language=rw and English when en.
Use natural, polite, casual speech suitable for speaking aloud. Keep replies concise (1-4 sentences,
usually under 75 words). Never pretend to have sensed, moved, or seen something unless hardware
telemetry confirms it. Do not invent current facts, opening hours, directions or search results.
When sources are given, rely on them and say when data is insufficient. Clearly admit uncertainty.
You are an AI robot, not a human person. You may share your name and describe your abilities.
Never provide motor control commands: physical motion is handled by a separate safety service.
"""


class GeminiBrain:
    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings = settings
        self.client = client

    async def answer(
        self, text: str, language: str, history: list[dict],
        knowledge: str = "", use_google: bool = False,
    ) -> tuple[str, list[Source]]:
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.settings.gemini_model}:generateContent")
        facts = (f"\nVerified context, if relevant:\n{knowledge[:2400]}" if knowledge else "")
        prompt = (f"Language: {language}. User message: {text}{facts}\n"
                  "If this requests live information but you have no grounded evidence, say so.")
        contents = [{"role": item["role"], "parts": [{"text": item["text"]}]}
                    for item in history[-6:]]
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        body: dict = {
            "system_instruction": {"parts": [{"text": PERSONA}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.55, "maxOutputTokens": 280},
        }
        if use_google:
            body["tools"] = [{"google_search": {}}]
        try:
            resp = await self.client.post(
                url, json=body,
                headers={"x-goog-api-key": self.settings.gemini_api_key}, timeout=30,
            )
            resp.raise_for_status()
            candidates = resp.json().get("candidates", [])
            if not candidates:
                raise UpstreamFailure("No Gemini response received")
            candidate = candidates[0]
            reply = "".join(p.get("text", "") for p in
                            candidate.get("content", {}).get("parts", []) if not p.get("thought"))
            sources = []
            for item in candidate.get("groundingMetadata", {}).get("groundingChunks", []):
                web = item.get("web", {})
                uri = web.get("uri", "")
                if uri.startswith("https://"):
                    sources.append(Source(label=web.get("title", "Web source"), url=uri))
            if not reply.strip():
                raise UpstreamFailure("Gemini returned an empty answer")
            return reply.strip(), sources[:4]
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in (400, 403) and use_google:
                raise UpstreamFailure("Google Search grounding not enabled for this free-tier model") from exc
            if status == 429:
                raise UpstreamFailure("Gemini free-tier quota or rate limit reached") from exc
            raise UpstreamFailure(f"Gemini HTTP request failed ({status})") from exc
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise UpstreamFailure("Gemini temporarily unavailable") from exc


def mock_reply(text: str, language: str) -> str:
    t = text.lower()
    if "witwa" in t or "name" in t:
        return ("Nitwa Currator, ndi robot ifasha abantu gusubiza ibibazo!"
                if language == "rw" else
                "I'm Currator, a friendly robot assistant. Nice to meet you!")
    if "muraho" in t or "hello" in t or "hi" == t:
        return ("Muraho neza! Nishimiye kuganira nawe."
                if language == "rw" else "Hello! Great to meet you. What would you like to know?")
    return ("Ndi mu buryo bwo kugerageza. Iyo API izaba ihujwe, nzashobora kugusubiza "
            "mu Kinyarwanda kandi nkashaka amakuru."
            if language == "rw" else
            "I'm running in demo mode. Connect the APIs to answer questions and look up facts.")
