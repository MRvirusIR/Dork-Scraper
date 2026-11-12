"""Search engine backends.

Each engine knows how to build a results-page URL for a dork + page number
and how to extract result URLs from the returned HTML.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.parse
from abc import ABC, abstractmethod
from typing import Dict, List, Type

from bs4 import BeautifulSoup
from defusedxml import ElementTree as SafeXML


class Engine(ABC):
    """Base class for all search engines."""

    name: str = "base"
    per_page: int = 10

    @abstractmethod
    def build_url(self, dork: str, page: int) -> str:
        """Return the URL for a given dork and zero-based page index."""

    @abstractmethod
    def parse(self, html: str) -> List[str]:
        """Extract result URLs from a results page."""

    @staticmethod
    def is_blocked(html: str) -> bool:
        lowered = html.lower()
        markers = (
            "unusual traffic",
            "g-recaptcha",
            "please complete the following challenge",
            "captcha-delivery",
            "/sorry/index",
            "detected unusual",
            "anomaly-modal",
        )
        return any(m in lowered for m in markers)


class GoogleEngine(Engine):
    name = "google"
    per_page = 100

    def build_url(self, dork: str, page: int) -> str:
        params = {
            "q": dork,
            "num": self.per_page,
            "start": page * self.per_page,
            "hl": "en",
            "filter": "0",
        }
        return "https://www.google.com/search?" + urllib.parse.urlencode(params)

    def parse(self, html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        urls: List[str] = []
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            # Legacy / no-JS redirect format: /url?q=<target>&sa=...
            if href.startswith("/url?"):
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                target = (qs.get("q") or qs.get("url") or [""])[0]
                if target.startswith("http"):
                    urls.append(target)
            # Modern format: direct links wrapping an <h3> title
            elif href.startswith("http") and a.find("h3"):
                urls.append(href)
        return [u for u in urls if not _is_engine_internal(u, ("google.", "gstatic.", "youtube.com/results"))]


class BingEngine(Engine):
    name = "bing"
    per_page = 50

    def build_url(self, dork: str, page: int) -> str:
        params = {"q": dork, "count": self.per_page, "first": page * self.per_page + 1}
        return "https://www.bing.com/search?" + urllib.parse.urlencode(params)

    def parse(self, html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        urls: List[str] = []
        for a in soup.select("li.b_algo h2 a[href]"):
            urls.append(_decode_bing(a["href"]))
        return [u for u in urls if u.startswith("http")]


class BingRSSEngine(Engine):
    """Bing's keyless RSS search interface, subject to upstream limits."""
    name = "bing_rss"
    per_page = 10

    def build_url(self, dork: str, page: int) -> str:
        return "https://www.bing.com/search?" + urllib.parse.urlencode(
            {"q": dork, "format": "rss", "count": self.per_page,
             "first": page * self.per_page + 1})

    def parse(self, text: str) -> List[str]:
        try:
            root = SafeXML.fromstring(text)
        except Exception as exc:
            raise ValueError("Bing returned invalid RSS") from exc
        if root.tag != "rss" or root.find("channel") is None:
            raise ValueError("Bing returned invalid RSS")
        urls = []
        for item in root.findall("./channel/item"):
            url = (item.findtext("link") or "").strip()
            if url.startswith(("http://", "https://")):
                urls.append(url)
        return urls


class DuckDuckGoEngine(Engine):
    name = "duckduckgo"
    per_page = 30

    def build_url(self, dork: str, page: int) -> str:
        params = {"q": dork, "s": page * self.per_page, "dc": page * self.per_page + 1}
        return "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode(params)

    def parse(self, html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        urls: List[str] = []
        for a in soup.select("a.result__a[href]"):
            href = a["href"]
            if "duckduckgo.com/l/" in href:
                qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                href = (qs.get("uddg") or [""])[0]
            if href.startswith("//"):
                href = "https:" + href
            if href.startswith("http") and "duckduckgo.com/y.js" not in href:
                urls.append(href)
        return urls


class YahooEngine(Engine):
    name = "yahoo"
    per_page = 10

    def build_url(self, dork: str, page: int) -> str:
        params = {"p": dork, "b": page * self.per_page + 1}
        return "https://search.yahoo.com/search?" + urllib.parse.urlencode(params)

    def parse(self, html: str) -> List[str]:
        soup = BeautifulSoup(html, "html.parser")
        urls: List[str] = []
        for a in soup.select("div.algo h3 a[href], div.compTitle a[href]"):
            href = a["href"]
            if "/RU=" in href:
                part = href.split("/RU=", 1)[1].split("/R", 1)[0]
                href = urllib.parse.unquote(part)
            if href.startswith("http") and "yahoo.com" not in urllib.parse.urlparse(href).netloc:
                urls.append(href)
        return urls



class BraveEngine(Engine):
    """Official Brave Search API (requires BRAVE_API_KEY in the environment)."""
    name = "brave"
    per_page = 20

    def build_url(self, dork: str, page: int) -> str:
        if page > 9:
            raise ValueError("Brave supports at most 10 result pages")
        return "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
            {"q": dork, "count": self.per_page, "offset": page, "result_filter": "web"})

    def parse(self, html: str) -> List[str]:
        data = json.loads(html)
        return [item["url"] for item in (data.get("web") or {}).get("results", [])
                if isinstance(item, dict) and isinstance(item.get("url"), str)]

    @staticmethod
    def is_blocked(html: str) -> bool:
        return False


class SearXNGEngine(Engine):
    """A user-configured SearXNG instance with JSON enabled; no key."""
    name = "searxng"

    def build_url(self, dork: str, page: int) -> str:
        base = os.environ.get("SEARXNG_URL", "").strip()
        try:
            parsed = urllib.parse.urlsplit(base)
            host = parsed.hostname
            port = parsed.port  # validate invalid port syntax
        except ValueError:
            raise ValueError("Invalid SEARXNG_URL") from None
        if (not host or parsed.scheme not in ("http", "https") or parsed.username or parsed.password
                or parsed.query or parsed.fragment
                or (parsed.scheme == "http" and host not in ("localhost", "127.0.0.1", "::1"))):
            raise ValueError("SEARXNG_URL must be HTTPS or local HTTP, without credentials or query")
        path = parsed.path.rstrip('/') + '/search'
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, urllib.parse.urlencode(
            {"q": dork, "format": "json", "pageno": page + 1}), ''))

    def parse(self, text: str) -> List[str]:
        data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(data.get('results'), list):
            raise ValueError("Invalid SearXNG JSON response; enable JSON format on the instance")
        return [item['url'] for item in data['results'] if isinstance(item, dict)
                and isinstance(item.get('url'), str)]

    @staticmethod
    def is_blocked(text: str) -> bool:
        return False


class SerpApiGoogleEngine(Engine):
    """Google results via the optional third-party SerpApi service."""
    name = "serpapi_google"
    per_page = 10

    def build_url(self, dork: str, page: int) -> str:
        params = {"engine": "google", "q": dork, "start": page * self.per_page, "output": "json"}
        return "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)

    def parse(self, html: str) -> List[str]:
        data = json.loads(html)
        if not isinstance(data, dict):
            raise ValueError("Invalid SerpApi response")
        metadata = data.get("search_metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("Invalid SerpApi response")
        error = data.get("error")
        no_results = (metadata.get("status") == "Success" and
                      error == "Google hasn't returned any results for this query.")
        if error and not no_results:
            # Provider messages can contain secrets: never echo raw error text.
            raise ValueError("SerpApi returned an error; check account, quota and query")
        if metadata.get("status") in ("Error", "Processing", "Queued"):
            raise ValueError("SerpApi search did not complete successfully")
        results = data.get("organic_results") or []
        if not isinstance(results, list):
            raise ValueError("Invalid SerpApi response")
        return [item["link"] for item in results if isinstance(item, dict)
                and isinstance(item.get("link"), str)]

    @staticmethod
    def is_blocked(html: str) -> bool:
        return False


class SerpApiDuckDuckGoEngine(SerpApiGoogleEngine):
    """DuckDuckGo organic results via the optional third-party SerpApi service."""
    name = "serpapi_duckduckgo"
    per_page = 50

    def build_url(self, dork: str, page: int) -> str:
        # DuckDuckGo's initial response contains at most 11 organic results;
        # subsequent pages can contain up to 50.
        start = 0 if page == 0 else 11 + (page - 1) * self.per_page
        return self.build_offset_url(dork, start)

    def build_offset_url(self, dork: str, start: int) -> str:
        params = {"engine": "duckduckgo", "q": dork, "start": start, "output": "json"}
        return "https://serpapi.com/search.json?" + urllib.parse.urlencode(params)

    def next_offset(self, html: str):
        data = json.loads(html)
        pagination = data.get("serpapi_pagination") or {}
        if not isinstance(pagination, dict):
            raise ValueError("Invalid SerpApi pagination")
        link = pagination.get("next")
        if not link:
            return None
        if not isinstance(link, str):
            raise ValueError("Invalid SerpApi pagination")
        starts = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query).get("start", [])
        if len(starts) != 1 or not starts[0].isdigit() or len(starts[0]) > 8:
            raise ValueError("Invalid SerpApi pagination offset")
        return int(starts[0])

def _decode_bing(href: str) -> str:
    """Bing sometimes wraps results in bing.com/ck/a?...&u=a1<base64>."""
    if "bing.com/ck/a" not in href:
        return href
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
    u = (qs.get("u") or [""])[0]
    if u.startswith("a1"):
        b64 = u[2:]
        b64 += "=" * (-len(b64) % 4)
        try:
            return base64.urlsafe_b64decode(b64).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            return href
    return href


def _is_engine_internal(url: str, needles) -> bool:
    netloc = urllib.parse.urlparse(url).netloc.lower()
    return any(n in netloc or n in url for n in needles)


ENGINES: Dict[str, Type[Engine]] = {
    cls.name: cls for cls in (GoogleEngine, BingEngine, BingRSSEngine, DuckDuckGoEngine, YahooEngine, BraveEngine, SearXNGEngine, SerpApiGoogleEngine, SerpApiDuckDuckGoEngine)
}


def get_engine(name: str) -> Engine:
    try:
        return ENGINES[name.lower()]()
    except KeyError as exc:
        raise ValueError(f"Unknown engine '{name}'. Available: {', '.join(ENGINES)}") from exc
