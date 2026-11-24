"""Public Wikimedia lookups with bounded inputs and citations."""
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree

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
    articles = [asyncio.create_task(_bounded_lookup(_wikipedia(query, lang, client, headers)))
                for lang in languages]
    entity = asyncio.create_task(_bounded_lookup(_wikidata(query, client, headers)))
    try:
        article = None
        for task in articles:
            article = await task
            if article:
                break
        supplement = await entity if not article or entity.done() else None
        evidence = [result for result in (article, supplement) if result]
    finally:
        for task in [*articles, entity]:
            task.cancel()
        await asyncio.gather(*articles, entity, return_exceptions=True)
    return "\n".join(extract for extract, _ in evidence), [source for _, source in evidence]


async def definition_during_outage(text, language, client, user_agent):
    """Use a same-language encyclopedia introduction for standalone definition requests."""
    if needs_current_info(text):
        return None
    for lang, pattern in (("en", r"what (?:is|are) (.+)"), ("rw", r"(.+) ni iki")):
        match = re.fullmatch(pattern, text.strip().strip("?!. ").casefold())
        if not match or language not in ("auto", lang):
            continue
        topic = match[1].strip()
        if len(topic.split()) > 6 or not topic:
            return None
        article = await _bounded_lookup(_wikipedia(topic, lang, client, {"User-Agent": user_agent}))
        if article:
            evidence, source = article
            if source.label.removeprefix("Wikipedia: ").casefold() != topic:
                return None
            intro = evidence.partition(": ")[2].splitlines()[0]
            sentences = re.split(r"(?<=[.!?])\s+", intro)
            return sentences[0], lang, source
    return None


def needs_current_info(text: str) -> bool:
    triggers = (
        "today", "tomorrow", "now", "latest", "current", "weather", "news",
        "president", "prime minister", "price", "2026", "2027", "this week",
        "uyu munsi", "ubu", "amakuru mashya", "ikirere", "perezida",
        "minisitiri w'intebe", "minisitiri w’intebe", "ikiguzi",
    )
    return matches_phrase(text, triggers)


async def news_lookup(query: str, client: httpx.AsyncClient):
    """Search recent global news coverage. Evidence is limited to headlines."""
    terms = re.findall(r"[^\W_]+", query.casefold())[:30]
    ignored = set(
        "what who is are was were the a an in on of about for me tell please "
        "current latest today now news this week updates give you can happening "
        "amakuru mashya agezweho uyu munsi ubu ni iki nde mu i kuri kuriya "
        "mbwira amakuru ibibera ibishya".split()
    )
    keywords = list(dict.fromkeys(word for word in terms if len(word) > 1 and word not in ignored))
    search = " ".join(f'"{word}"' for word in keywords[:5]) or "Rwanda"

    async def fetch():
        response = await client.get(
            "https://api.gdeltproject.org/api/v2/doc/doc",
            params={"query": search, "mode": "artlist", "format": "json",
                    "timespan": "7d", "maxrecords": 4, "sort": "hybridrel"},
        )
        response.raise_for_status()
        evidence, sources = [], []
        for article in response.json().get("articles", [])[:4]:
            title, url = article.get("title"), article.get("url")
            if not isinstance(title, str) or not isinstance(url, str):
                continue
            parsed = urlsplit(url)
            if not title.strip() or parsed.scheme != "https" or not parsed.hostname or url in {
                source.url for source in sources
            }:
                continue
            seen = article.get("seendate", "")
            date = seen[:8] if isinstance(seen, str) else ""
            evidence.append(f"Headline indexed {date}: {title[:220]}")
            sources.append(Source(label=f"{parsed.hostname}: {title[:140]}", url=url))
        return "\n".join(evidence), sources

    async def rss_news(endpoint, allowed_hosts, *, params=None, required_terms=()):
        async with client.stream(
            "GET", endpoint, params=params,
            follow_redirects=True,
        ) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 256_000:
                    return "", []
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError:
            return "", []
        evidence, sources = [], []
        now = datetime.now(timezone.utc)
        for item in root.findall("./channel/item")[:70]:
            url = item.findtext("link", "")
            title = item.findtext("title", "").strip()
            link = urlsplit(url)
            title_words = set(re.findall(r"[^\W_]+", title.casefold()))
            if (not title or link.scheme != "https" or link.hostname not in allowed_hosts
                    or any(term not in title_words for term in required_terms)):
                continue
            date = item.findtext("pubDate", "")[:40]
            try:
                published = parsedate_to_datetime(date)
            except (ValueError, OverflowError):
                continue
            if published.tzinfo is None or not now - timedelta(days=7) <= published <= now:
                continue
            evidence.append(f"Headline published {date}: {title[:220]}")
            sources.append(Source(label=title[:160], url=url))
            if len(sources) == 4:
                break
        return "\n".join(evidence), sources

    providers = [
        fetch(),
        rss_news(
            "https://news.google.com/rss/search", {"news.google.com"},
            params={"q": f"{' '.join(keywords[:5]) or 'Rwanda'} when:7d",
                    "hl": "en", "gl": "RW", "ceid": "RW:en"},
        ),
    ]
    local = {"rwanda", "rwandan", "kigali"}
    broad = {"headlines", "breaking", "recent", "amakuru", "rw", "national", "top"}
    if not keywords or local.intersection(keywords):
        required = [word for word in keywords if word not in local | broad]
        if "kigali" in keywords and not {"rwanda", "rwandan"}.intersection(keywords):
            required.append("kigali")
        providers.append(rss_news(
            "https://www.ktpress.rw/feed/", {"www.ktpress.rw", "ktpress.rw"},
            required_terms=required,
        ))

    tasks = [asyncio.create_task(_bounded_lookup(provider)) for provider in providers]
    try:
        for task in asyncio.as_completed(tasks):
            result = await task
            if result and result[1]:
                return result
        return "", []
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def needs_wikipedia(text: str) -> bool:
    triggers = ("who", "what is", "tell me about", "define", "history", "capital",
                "ni nde", "ni iki", "amateka", "umurwa mukuru", "wikipedia", "wikidata")
    return matches_phrase(text, triggers)


def matches_phrase(text: str, phrases: tuple[str, ...]) -> bool:
    normalized = text.casefold()
    return any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized) for phrase in phrases)
