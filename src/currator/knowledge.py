"""Public Wikimedia lookups with bounded inputs and citations."""
from __future__ import annotations

import asyncio
import re
from urllib.parse import quote

import httpx

from .models import Source


LOOKUP_TIMEOUT = 5.0


async def _wikipedia(query, language, client, headers):
    response = await client.get(
        f"https://{language}.wikipedia.org/w/api.php",
        params={
            "action": "query", "generator": "search", "gsrsearch": query,
            "gsrlimit": 1, "prop": "extracts", "explaintext": 1,
            "exintro": 1, "format": "json",
        },
        headers=headers,
    )
    response.raise_for_status()
    pages = response.json().get("query", {}).get("pages", {})
    page = next(iter(pages.values()), {})
    title, extract = page.get("title"), page.get("extract")
    if isinstance(title, str) and isinstance(extract, str) and extract.strip():
        slug = quote(title.replace(" ", "_"), safe="")
        return f"Wikipedia ({language}): {extract[:1100]}", Source(
            label=f"Wikipedia: {title}", url=f"https://{language}.wikipedia.org/wiki/{slug}",
        )
    return None


async def _wikidata(query, client, headers):
    response = await client.get(
        "https://www.wikidata.org/w/api.php",
        params={
            "action": "wbsearchentities", "search": query, "language": "en",
            "format": "json", "limit": 1,
        },
        headers=headers,
    )
    response.raise_for_status()
    item = next(iter(response.json().get("search", [])), {})
    item_id, description = item.get("id"), item.get("description")
    if isinstance(item_id, str) and re.fullmatch(r"Q[0-9]+", item_id) and description:
        return f"Wikidata: {item.get('label', '')}: {description[:350]}", Source(
            label=f"Wikidata: {item_id}", url=f"https://www.wikidata.org/wiki/{item_id}",
        )
    return None


async def _bounded_lookup(request):
    try:
        return await asyncio.wait_for(request, timeout=LOOKUP_TIMEOUT)
    except (TimeoutError, httpx.HTTPError, ValueError, TypeError, AttributeError):
        return None


async def look_up(query: str, language: str, client: httpx.AsyncClient, user_agent: str):
    """Prefer a Kinyarwanda article when available, with a shared lookup window."""
    query = query.strip()[:180]
    if not query:
        return "", []
    headers = {"User-Agent": user_agent}
    languages = ("rw", "en") if language == "rw" else ("en",)
    *articles, entity = await asyncio.gather(
        *(_bounded_lookup(_wikipedia(query, lang, client, headers)) for lang in languages),
        _bounded_lookup(_wikidata(query, client, headers)),
    )
    article = next((result for result in articles if result), None)
    evidence = [result for result in (article, entity) if result]
    return "\n".join(extract for extract, _ in evidence), [source for _, source in evidence]


def needs_current_info(text: str) -> bool:
    triggers = (
        "today", "tomorrow", "now", "latest", "current", "weather", "news",
        "president", "prime minister", "price", "2026", "2027", "this week",
        "uyu munsi", "ubu", "amakuru mashya", "ikirere", "perezida",
        "minisitiri w'intebe", "minisitiri w’intebe", "ikiguzi",
    )
    return matches_phrase(text, triggers)


def needs_wikipedia(text: str) -> bool:
    triggers = ("who", "what is", "tell me about", "define", "history", "capital",
                "ni nde", "ni iki", "amateka", "umurwa mukuru", "wikipedia", "wikidata")
    return matches_phrase(text, triggers)


def matches_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    normalized = text.casefold()
    return any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized) for phrase in phrases)
