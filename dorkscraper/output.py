"""Output writers: txt, json, csv."""

from __future__ import annotations

import csv
import json
from typing import List

from .core import SearchResult


def _all_urls(results: List[SearchResult]) -> List[str]:
    urls: List[str] = []
    for r in results:
        urls.extend(r.urls)
    return urls


def write_txt(results: List[SearchResult], path: str) -> int:
    urls = _all_urls(results)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(urls))
        if urls:
            fh.write("\n")
    return len(urls)


def write_json(results: List[SearchResult], path: str) -> int:
    payload = [
        {
            "dork": r.dork,
            "engine": r.engine,
            "count": r.count,
            "pages_fetched": r.pages_fetched,
            "blocked": r.blocked,
            "error": r.error,
            "urls": r.urls,
        }
        for r in results
    ]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    return sum(r.count for r in results)


def write_csv(results: List[SearchResult], path: str) -> int:
    rows = 0
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["dork", "engine", "url"])
        for r in results:
            for url in r.urls:
                writer.writerow([r.dork, r.engine, url])
                rows += 1
    return rows


WRITERS = {"txt": write_txt, "json": write_json, "csv": write_csv}


def write_output(results: List[SearchResult], path: str, fmt: str) -> int:
    try:
        writer = WRITERS[fmt.lower()]
    except KeyError as exc:
        raise ValueError(f"Unknown format '{fmt}'. Use: {', '.join(WRITERS)}") from exc
    return writer(results, path)
