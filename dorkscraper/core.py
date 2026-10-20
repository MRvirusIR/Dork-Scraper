"""Core scraping engine: HTTP + optional Selenium fetchers, retries, rate limiting."""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import requests

from .engines import Engine, get_engine
from .utils import clean_urls

_FALLBACK_UA = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

try:
    from fake_useragent import UserAgent
    _UA = UserAgent()

    def _random_ua() -> str:
        try:
            return _UA.random
        except Exception:  # noqa: BLE001
            return random.choice(_FALLBACK_UA)
except Exception:  # noqa: BLE001
    def _random_ua() -> str:
        return random.choice(_FALLBACK_UA)

LogFn = Callable[[str, str], None]


@dataclass
class SearchResult:
    """Outcome of scraping a single dork."""

    dork: str
    engine: str
    urls: List[str] = field(default_factory=list)
    pages_fetched: int = 0
    blocked: bool = False
    error: Optional[str] = None

    @property
    def count(self) -> int:
        return len(self.urls)


@dataclass
class DorkScraper:
    """Multi-engine dork scraper with retry, rate limiting and UA rotation."""

    engine: str = "google"
    pages: int = 1
    delay: float = 2.0
    jitter: float = 1.5
    timeout: int = 20
    retries: int = 2
    proxy: Optional[str] = None
    use_selenium: bool = False
    headless: bool = True
    log: Optional[LogFn] = None
    clean_opts: dict = field(default_factory=dict)

    _driver: object = field(default=None, init=False, repr=False)

    def _emit(self, level: str, message: str) -> None:
        if self.log:
            self.log(level, message)

    # ---------------------------------------------------------------- fetch
    def _fetch_http(self, url: str) -> str:
        headers = {
            "User-Agent": _random_ua(),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "DNT": "1",
            "Connection": "keep-alive",
        }
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        resp = requests.get(url, headers=headers, proxies=proxies, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    def _get_driver(self):
        if self._driver is not None:
            return self._driver
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

        opts = Options()
        if self.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument(f"--user-agent={_random_ua()}")
        if self.proxy:
            opts.add_argument(f"--proxy-server={self.proxy}")
        self._driver = webdriver.Chrome(options=opts)
        return self._driver

    def _fetch_selenium(self, url: str) -> str:
        driver = self._get_driver()
        driver.get(url)
        time.sleep(2 + random.random() * 2)
        return driver.page_source

    def _fetch(self, url: str) -> str:
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.retries + 2):
            try:
                if self.use_selenium:
                    return self._fetch_selenium(url)
                return self._fetch_http(url)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                wait = self.delay * attempt + random.random()
                self._emit("warn", f"fetch failed (attempt {attempt}): {exc}; retrying in {wait:.1f}s")
                time.sleep(wait)
        raise last_exc  # type: ignore[misc]

    def _sleep_between(self) -> None:
        time.sleep(max(0.0, self.delay + random.uniform(0, self.jitter)))

    # ---------------------------------------------------------------- scrape
    def scrape(self, dork: str) -> SearchResult:
        engine: Engine = get_engine(self.engine)
        result = SearchResult(dork=dork, engine=engine.name)
        collected: List[str] = []
        for page in range(self.pages):
            page_url = engine.build_url(dork, page)
            self._emit("info", f"[{engine.name}] page {page + 1}/{self.pages}: {dork}")
            try:
                html = self._fetch(page_url)
            except Exception as exc:  # noqa: BLE001
                result.error = str(exc)
                self._emit("error", f"giving up on page {page + 1}: {exc}")
                break
            if engine.is_blocked(html):
                result.blocked = True
                self._emit("error", f"{engine.name} returned a block/CAPTCHA page; stopping.")
                break
            found = engine.parse(html)
            collected.extend(found)
            result.pages_fetched += 1
            self._emit("info", f"  -> {len(found)} raw URLs on this page")
            if not found:
                break
            if page + 1 < self.pages:
                self._sleep_between()
        result.urls = clean_urls(collected, **self.clean_opts)
        return result

    def scrape_many(self, dorks: List[str]) -> List[SearchResult]:
        results: List[SearchResult] = []
        for i, dork in enumerate(dorks, 1):
            self._emit("info", f"=== dork {i}/{len(dorks)} ===")
            results.append(self.scrape(dork))
            if i < len(dorks):
                self._sleep_between()
        return results

    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.quit()
            except Exception:  # noqa: BLE001
                pass
            self._driver = None

    def __enter__(self) -> "DorkScraper":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
