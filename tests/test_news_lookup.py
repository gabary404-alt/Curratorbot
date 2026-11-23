import httpx
import pytest

from currator.knowledge import news_lookup


@pytest.mark.asyncio
async def test_news_lookup_falls_back_to_recent_google_news_for_rwanda():
    def respond(request):
        if request.url.host == "api.gdeltproject.org":
            return httpx.Response(429)
        if request.url.host == "www.ktpress.rw":
            return httpx.Response(503)
        assert request.url.params["q"] == "rwanda when:7d"
        assert request.url.params["gl"] == "RW"
        published = format_datetime(datetime.now(timezone.utc) - timedelta(days=1))
        return httpx.Response(200, text=f"""
            <rss><channel><item>
              <title>Rwanda opens an exhibition</title>
              <link>https://news.google.com/rss/articles/example</link>
              <pubDate>{published}</pubDate>
            </item></channel></rss>
        """)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        evidence, sources = await news_lookup("Latest news in Rwanda", client)
    assert "Rwanda opens an exhibition" in evidence
    assert sources[0].url == "https://news.google.com/rss/articles/example"


@pytest.mark.asyncio
async def test_rwanda_headlines_use_publisher_feed_if_search_providers_fail():
    published = format_datetime(datetime.now(timezone.utc) - timedelta(hours=3))

    def handler(request):
        if request.url.host != "www.ktpress.rw":
            return httpx.Response(429)
        return httpx.Response(200, text=f"""
            <rss><channel><item>
              <title>Rwanda opens a new exhibit</title>
              <link>https://www.ktpress.rw/example/</link>
              <pubDate>{published}</pubDate>
            </item></channel></rss>
        """)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        evidence, sources = await news_lookup("Latest Rwanda headlines", client)
    assert "opens a new exhibit" in evidence
    assert sources[0].url == "https://www.ktpress.rw/example/"
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

