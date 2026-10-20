"""URL cleaning, normalisation and filtering helpers."""

from __future__ import annotations

import fnmatch
import urllib.parse
from typing import Iterable, List, Optional, Sequence

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "gclid", "fbclid", "msclkid", "yclid", "_ga", "ref_src",
}

STATIC_EXTENSIONS = (
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico", ".css",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3",
)


def normalize_url(url: str, strip_tracking: bool = True, trailing_slash: bool = False) -> str:
    """Normalise a URL: trim, lowercase host, drop fragments and tracking params."""
    url = url.strip().replace("\xa0", " ").split(" ")[0]
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    query = parsed.query
    if strip_tracking and query:
        pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
        pairs = [(k, v) for k, v in pairs if k.lower() not in TRACKING_PARAMS]
        query = urllib.parse.urlencode(pairs, doseq=True, safe="/:,")
    path = parsed.path or "/"
    if trailing_slash and not query and not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path += "/"
    return urllib.parse.urlunparse(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.params, query, "")
    )


def get_domain(url: str) -> str:
    netloc = urllib.parse.urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def has_params(url: str) -> bool:
    return bool(urllib.parse.urlparse(url).query)


def param_names(url: str) -> List[str]:
    query = urllib.parse.urlparse(url).query
    return [k for k, _ in urllib.parse.parse_qsl(query, keep_blank_values=True)]


def dedupe(urls: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def dedupe_by_domain(urls: Iterable[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for u in urls:
        d = get_domain(u)
        if d not in seen:
            seen.add(d)
            out.append(u)
    return out


def dedupe_by_pattern(urls: Iterable[str]) -> List[str]:
    """Keep one URL per (host, path, sorted param names).

    Perfect for building parameterised target lists (SQLi/XSS testing) where
    ``?id=1`` and ``?id=999`` are the same injectable endpoint.
    """
    seen = set()
    out: List[str] = []
    for u in urls:
        parsed = urllib.parse.urlparse(u)
        key = (parsed.netloc.lower(), parsed.path, tuple(sorted(param_names(u))))
        if key not in seen:
            seen.add(key)
            out.append(u)
    return out


def is_static_asset(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    return path.endswith(STATIC_EXTENSIONS)


def matches_domain_filter(url: str, patterns: Sequence[str]) -> bool:
    domain = get_domain(url)
    return any(fnmatch.fnmatch(domain, p.lower()) for p in patterns)


def clean_urls(
    urls: Iterable[str],
    *,
    strip_tracking: bool = True,
    trailing_slash: bool = False,
    drop_static: bool = False,
    params_only: bool = False,
    unique_mode: str = "exact",
    include_domains: Optional[Sequence[str]] = None,
    exclude_domains: Optional[Sequence[str]] = None,
) -> List[str]:
    """Apply the full cleaning pipeline and return a filtered, de-duplicated list.

    ``unique_mode``: ``exact`` | ``domain`` | ``pattern`` | ``none``.
    """
    cleaned: List[str] = []
    for raw in urls:
        if not raw or not raw.strip():
            continue
        url = normalize_url(raw, strip_tracking=strip_tracking, trailing_slash=trailing_slash)
        if not url.startswith("http"):
            continue
        if drop_static and is_static_asset(url):
            continue
        if params_only and not has_params(url):
            continue
        if include_domains and not matches_domain_filter(url, include_domains):
            continue
        if exclude_domains and matches_domain_filter(url, exclude_domains):
            continue
        cleaned.append(url)

    if unique_mode == "exact":
        return dedupe(cleaned)
    if unique_mode == "domain":
        return dedupe_by_domain(cleaned)
    if unique_mode == "pattern":
        return dedupe_by_pattern(cleaned)
    return cleaned