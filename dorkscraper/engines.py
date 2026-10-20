"""Search engine backends.

Each engine knows how to build a results-page URL for a dork + page number
and how to extract result URLs from the returned HTML.
"""

from __future__ import annotations

import base64
import urllib.parse
from abc import ABC, abstractmethod
from typing import Dict, List, Type

from bs4 import BeautifulSoup


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
            "captcha",
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
    cls.name: cls for cls in (GoogleEngine, BingEngine, DuckDuckGoEngine, YahooEngine)
}


def get_engine(name: str) -> Engine:
    try:
        return ENGINES[name.lower()]()
    except KeyError as exc:
        raise ValueError(f"Unknown engine '{name}'. Available: {', '.join(ENGINES)}") from exc
