"""Public Wikimedia lookups with bounded inputs and citations."""
from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from .models import Source


async def look_up(query: str, language: str, client: httpx.AsyncClient, user_agent: str):
    """Returns (extract, sources). No arbitrary URL fetching."""
    snippet_parts: list[str] = []
    sources: list[Source] = []
    q = query.strip()[:180]
    if not q:
        return "", sources
    headers = {"User-Agent": user_agent}
    lang = "rw" if language == "rw" else "en"
    # Kinyarwanda Wikipedia is smaller; retry English for broader coverage.
    for wiki_lang in dict.fromkeys([lang, "en"]):
        try:
            resp = await client.get(
                f"https://{wiki_lang}.wikipedia.org/w/api.php",
                params={"action": "query", "list": "search", "srsearch": q,
                        "srlimit": 1, "format": "json"},
                headers=headers, timeout=8,
            )
            resp.raise_for_status()
            entries = resp.json().get("query", {}).get("search", [])
            if entries:
                title = entries[0]["title"]
                page = await client.get(
                    f"https://{wiki_lang}.wikipedia.org/w/api.php",
                    params={"action": "query", "prop": "extracts", "explaintext": 1,
                            "exintro": 1, "titles": title, "format": "json"},
                    headers=headers, timeout=8,
                )
                page.raise_for_status()
                pages = page.json().get("query", {}).get("pages", {})
                extract = next(iter(pages.values()), {}).get("extract", "")
                if extract:
                    snippet_parts.append(f"Wikipedia ({wiki_lang}): {extract[:1100]}")
                    sources.append(Source(
                        label=f"Wikipedia: {title}",
                        url=f"https://{wiki_lang}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                    ))
                    break
        except (httpx.HTTPError, KeyError, ValueError):
            continue

    # Wikidata supplements Wikipedia. Entity labels are helpful, not authoritative for current events.
    try:
        resp = await client.get(
            "https://www.wikidata.org/w/api.php",
            params={"action": "wbsearchentities", "search": q, "language": "en",
                    "format": "json", "limit": 1},
            headers=headers, timeout=8,
        )
        resp.raise_for_status()
        items = resp.json().get("search", [])
        if items:
            item = items[0]
            item_id = item.get("id", "")
            description = item.get("description", "")
            if item_id.startswith("Q") and item_id[1:].isdigit() and description:
                snippet_parts.append(f"Wikidata: {item.get('label', '')}: {description[:350]}")
                sources.append(Source(label=f"Wikidata: {item_id}",
                                      url=f"https://www.wikidata.org/wiki/{item_id}"))
    except (httpx.HTTPError, KeyError, ValueError):
        pass
    return "\n".join(snippet_parts), sources


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
