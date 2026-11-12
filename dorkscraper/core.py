"""Core scraping engine: HTTP + optional Selenium fetchers, retries, rate limiting."""

from __future__ import annotations

import random
import json
import os
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

import requests

from .engines import Engine, get_engine
from .utils import clean_urls
from .scope import apply_site_scope, apply_literal_query_filter, engine_query

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
    out_of_scope_count: int = 0
    scope_warning: Optional[str] = None
    effective_query: Optional[str] = None
    literal_filter: Optional[str] = None
    literal_filtered_count: int = 0
    warning: Optional[str] = None

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
    manual_captcha: bool = False
    challenge_timeout: int = 120
    cancel_event: object = None
    challenge_notice: Optional[Callable[[str], None]] = None

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
        if self.engine.lower() == "brave":
            key = os.environ.get("BRAVE_API_KEY")
            if not key:
                raise ValueError("Brave requires the BRAVE_API_KEY environment variable")
            headers["X-Subscription-Token"] = key
            headers["Accept"] = "application/json"
        proxies = {"http": self.proxy, "https": self.proxy} if self.proxy else None
        if self.engine.lower() in ("serpapi_google", "serpapi_duckduckgo"):
            key = os.environ.get("SERPAPI_API_KEY")
            if not key:
                raise ValueError("SerpApi requires the SERPAPI_API_KEY environment variable")
            # SerpApi documents API key as a query parameter. Never propagate
            # request exceptions, which may contain the full credential-bearing URL.
            try:
                resp = requests.get(url, params={"api_key": key}, headers=headers,
                                    proxies=proxies, timeout=self.timeout, allow_redirects=False)
                if 300 <= resp.status_code < 400:
                    raise ValueError("SerpApi returned a redirect; request stopped")
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as exc:
                status = exc.response.status_code if exc.response is not None else None
                details = {400: "invalid request", 401: "invalid API key", 403: "account not permitted",
                           429: "rate or account limit reached", 500: "provider unavailable", 503: "provider unavailable"}
                message = "SerpApi request failed" + (" (HTTP %s)" % status if status else " (network error)")
                if status in details:
                    message += ": " + details[status]
                raise ValueError(message) from None
        resp = requests.get(url, headers=headers, proxies=proxies, timeout=self.timeout, allow_redirects=self.engine.lower() not in ("brave", "searxng"))
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
        try:
            self._driver = webdriver.Chrome(options=opts)
        except Exception:  # Browser/driver setup errors must not leak long local stack traces.
            raise RuntimeError("Could not start Chrome/Chromium. Install a compatible browser and Selenium driver; a graphical display is required for manual challenges.") from None
        return self._driver

    def _fetch_selenium(self, url: str) -> str:
        driver = self._get_driver()
        try:
            driver.get(url)
        except Exception:
            raise RuntimeError("Browser navigation failed or the window was closed; retry the search.") from None
        def browser_source():
            try:
                return driver.page_source
            except Exception:
                raise RuntimeError("Browser window was closed or became unavailable; retry the search.") from None
        time.sleep(2 + random.random() * 2)
        html = browser_source()
        if not self.manual_captcha or not get_engine(self.engine).is_blocked(html):
            return html
        notice = "Solve the challenge in the opened browser window. Waiting up to %s seconds." % self.challenge_timeout
        self._emit("warn", notice)
        if self.challenge_notice:
            self.challenge_notice(notice)
        try:
            deadline = time.monotonic() + self.challenge_timeout
            while time.monotonic() < deadline:
                if self.cancel_event is not None and self.cancel_event.wait(1):
                    break
                if self.cancel_event is None:
                    time.sleep(1)
                html = browser_source()
                if not get_engine(self.engine).is_blocked(html):
                    # Navigation can briefly produce a blank page after the challenge.
                    # Wait for recognizable results or a no-results message.
                    lower = html.lower()
                    no_results = ("no results found" in lower or "did not match any documents" in lower)
                    if get_engine(self.engine).parse(html) or no_results:
                        return html
            return html
        finally:
            if self.challenge_notice:
                self.challenge_notice("")

    def _fetch(self, url: str) -> str:
        last_exc: Optional[Exception] = None
        if self.engine.lower() == "brave" and not os.environ.get("BRAVE_API_KEY"):
            raise ValueError("Brave requires the BRAVE_API_KEY environment variable")
        if self.engine.lower() in ("serpapi_google", "serpapi_duckduckgo") and not os.environ.get("SERPAPI_API_KEY"):
            raise ValueError("SerpApi requires the SERPAPI_API_KEY environment variable")
        if self.engine.lower() in ("brave", "searxng", "serpapi_google", "serpapi_duckduckgo", "bing_rss") and self.use_selenium:
            raise ValueError("This provider cannot be used with Selenium")
        if self.manual_captcha and (not self.use_selenium or self.headless):
            raise ValueError("Manual CAPTCHA requires a visible Selenium browser")
        # Never retry potentially billable SerpApi searches automatically.
        attempts = 1 if self.engine.lower() in ("serpapi_google", "serpapi_duckduckgo") else self.retries + 1
        for attempt in range(1, attempts + 1):
            try:
                if self.use_selenium:
                    return self._fetch_selenium(url)
                return self._fetch_http(url)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if isinstance(exc, (ValueError, RuntimeError)):
                    break
                if (isinstance(exc, requests.HTTPError) and exc.response is not None
                        and exc.response.status_code in (403, 429)):
                    break  # Don't repeatedly request a provider that denied or rate-limited us.
                if attempt < attempts:
                    wait = self.delay * attempt + random.random()
                    self._emit("warn", f"fetch failed (attempt {attempt}): {exc}; retrying in {wait:.1f}s")
                    time.sleep(wait)
        raise last_exc  # type: ignore[misc]

    def _sleep_between(self) -> None:
        time.sleep(max(0.0, self.delay + random.uniform(0, self.jitter)))

    # ---------------------------------------------------------------- scrape
    def scrape(self, dork: str) -> SearchResult:
        engine: Engine = get_engine(self.engine)
        result = SearchResult(dork=dork, engine=engine.name, effective_query=engine_query(dork))
        collected: List[str] = []
        offset = 0
        seen_pages = set()
        for page in range(self.pages):
            self._emit("info", f"[{engine.name}] page {page + 1}/{self.pages}: {dork}")
            try:
                if engine.name == "serpapi_duckduckgo":
                    page_url = engine.build_offset_url(result.effective_query, offset)
                else:
                    page_url = engine.build_url(result.effective_query, page)
                html = self._fetch(page_url)
            except Exception as exc:  # noqa: BLE001
                if isinstance(exc, requests.HTTPError) and exc.response is not None:
                    code = exc.response.status_code
                    if code == 403 and engine.name == "searxng":
                        result.error = "SearXNG denied the request (HTTP 403); enable JSON format and check instance access."
                    elif code in (403, 429):
                        result.blocked = True
                        result.error = f"{engine.name} denied or rate-limited this request (HTTP {code}); try later."
                    elif code >= 500:
                        result.error = f"{engine.name} provider unavailable (HTTP {code}); try later or select another provider."
                    else:
                        result.error = f"{engine.name} request failed (HTTP {code})."
                else:
                    result.error = str(exc)
                self._emit("error", f"giving up on page {page + 1}: {result.error}")
                break
            if engine.is_blocked(html):
                result.blocked = True
                self._emit("error", f"{engine.name} returned a block/CAPTCHA page; stopping.")
                break
            try:
                found = engine.parse(html)
            except (ValueError, TypeError, KeyError) as exc:
                result.error = "Failed to parse search response: " + str(exc)
                self._emit("error", result.error)
                break
            if engine.name == "searxng":
                meta = json.loads(html)
                if meta.get('unresponsive_engines'):
                    result.warning = "Some SearXNG upstream engines were unavailable; results may be incomplete."
            result.pages_fetched += 1
            page_signature = tuple(found)
            if found and page_signature in seen_pages:
                result.warning = "Provider repeated a results page; pagination stopped."
                break
            if found:
                seen_pages.add(page_signature)
            collected.extend(found)
            self._emit("info", f"  -> {len(found)} raw URLs on this page")
            if not found:
                if engine.name == "google" and ("/httpservice/retry/enablejs" in html or "enable JavaScript" in html):
                    result.error = "Google returned a JavaScript-only page; try another provider or Selenium."
                    self._emit("warn", result.error)
                elif engine.name in ("google", "bing", "duckduckgo", "yahoo"):
                    result.warning = "No URLs parsed; the provider may have returned no results or changed its page."
                break
            if page + 1 < self.pages:
                if engine.name == "serpapi_duckduckgo":
                    try:
                        next_offset = engine.next_offset(html)
                        if next_offset is None:
                            break
                        if next_offset <= offset:
                            raise ValueError("Invalid SerpApi pagination offset")
                        offset = next_offset
                    except (ValueError, TypeError, AttributeError) as exc:
                        result.error = str(exc)
                        self._emit("error", result.error)
                        break
                self._sleep_between()
        # Validate URLs and enforce site: before deduplication so an unrelated
        # result can never replace an in-scope result in pattern/domain mode.
        pre_opts = dict(self.clean_opts)
        pre_opts['unique_mode'] = 'none'
        valid = clean_urls(collected, **pre_opts)
        scoped, result.out_of_scope_count, result.scope_warning = apply_site_scope(dork, valid)
        if result.scope_warning:
            self._emit('warn', result.scope_warning)
        elif result.out_of_scope_count:
            self._emit('info', f'Scope guard removed {result.out_of_scope_count} out-of-scope URLs')
        if valid and not scoped and result.out_of_scope_count == len(valid):
            warning = 'All provider results were outside the requested site scope; the provider may have ignored site:.'
            result.warning = (result.warning + ' ' if result.warning else '') + warning
        scoped, result.literal_filtered_count, result.literal_filter = apply_literal_query_filter(dork, scoped)
        if result.literal_filtered_count and not scoped:
            warning = 'No results contained the exact requested URL substring.'
            result.warning = (result.warning + ' ' if result.warning else '') + warning
        post_opts = dict(self.clean_opts)
        post_opts['strip_tracking'] = False
        result.urls = clean_urls(scoped, **post_opts)
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
