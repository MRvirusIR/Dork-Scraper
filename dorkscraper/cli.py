"""Command-line interface for Dork-Scraper."""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from . import __version__
from .core import DorkScraper, SearchResult
from .engines import ENGINES
from .output import write_output
from .utils import clean_urls

BANNER = r"""
    ____             __      _____                                
   / __ \____  _____/ /__   / ___/______________ _____  ___  _____
  / / / / __ \/ ___/ //_/   \__ \/ ___/ ___/ __ `/ __ \/ _ \/ ___/
 / /_/ / /_/ / /  / ,<     ___/ / /__/ /  / /_/ / /_/ /  __/ /    
/_____/\____/_/  /_/|_|   /____/\___/_/   \__,_/ .___/\___/_/     
                                              /_/   v{version}
        Multi-engine Google-Dork URL scraper  -  by MRvirusIR
"""


# ----------------------------------------------------------------- pretty log
try:
    from rich.console import Console
    from rich.table import Table
    _console = Console()
    _RICH = True
except Exception:  # noqa: BLE001
    _console = None
    _RICH = False

_COLORS = {"info": "cyan", "warn": "yellow", "error": "red", "ok": "green"}
_PREFIX = {"info": "[*]", "warn": "[!]", "error": "[-]", "ok": "[+]"}


def _make_logger(quiet: bool):
    def log(level: str, message: str) -> None:
        if quiet and level in ("info", "warn"):
            return
        prefix = _PREFIX.get(level, "[*]")
        if _RICH:
            color = _COLORS.get(level, "white")
            _console.print(f"[{color}]{prefix}[/{color}] {message}")
        else:
            print(f"{prefix} {message}", file=sys.stderr)
    return log


def _emit(level: str, message: str, quiet: bool = False) -> None:
    _make_logger(quiet)(level, message)


# ----------------------------------------------------------------- dork input
def collect_dorks(args: argparse.Namespace) -> List[str]:
    dorks: List[str] = []
    if args.dork:
        dorks.extend(args.dork)
    if args.dork_file:
        with open(args.dork_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    dorks.append(line)
    if not dorks and not args.clean_file:
        try:
            entered = input("Enter Dork: ").strip()
        except (EOFError, KeyboardInterrupt):
            entered = ""
        if entered:
            dorks.append(entered)
    # de-duplicate preserving order
    seen = set()
    unique = []
    for d in dorks:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


# ----------------------------------------------------------------- summary
def print_summary(results: List[SearchResult], total: int) -> None:
    if _RICH:
        table = Table(title="Dork-Scraper results", show_lines=False)
        table.add_column("#", justify="right", style="dim")
        table.add_column("Dork", style="cyan", overflow="fold")
        table.add_column("Engine", style="magenta")
        table.add_column("URLs", justify="right", style="green")
        table.add_column("Status", style="yellow")
        for i, r in enumerate(results, 1):
            status = "blocked" if r.blocked else (r.error or "ok")
            table.add_row(str(i), r.dork, r.engine, str(r.count), status)
        _console.print(table)
        _console.print(f"[bold green][+] Total unique URLs written: {total}[/bold green]")
    else:
        for i, r in enumerate(results, 1):
            status = "blocked" if r.blocked else (r.error or "ok")
            print(f"{i}. [{r.engine}] {r.count:>4}  {status}  {r.dork}", file=sys.stderr)
        print(f"[+] Total unique URLs written: {total}", file=sys.stderr)


# ----------------------------------------------------------------- clean mode
def run_clean_file(args: argparse.Namespace, log) -> int:
    with open(args.clean_file, "r", encoding="utf-8") as fh:
        raw = [line.strip() for line in fh if line.strip()]
    log("info", f"loaded {len(raw)} URLs from {args.clean_file}")
    cleaned = clean_urls(
        raw,
        strip_tracking=not args.keep_tracking,
        trailing_slash=args.trailing_slash,
        drop_static=args.drop_static,
        params_only=args.params_only,
        unique_mode=args.unique,
        include_domains=args.include_domain or None,
        exclude_domains=args.exclude_domain or None,
    )
    result = SearchResult(dork="(clean)", engine="file", urls=cleaned)
    written = write_output([result], args.output, args.format)
    log("ok", f"{written} URLs written to {args.output} ({len(raw) - len(cleaned)} removed)")
    return 0


# ----------------------------------------------------------------- argparse
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="dork-scraper",
        description="Scrape result URLs from search engines using Google-style dorks.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  dork-scraper -d 'inurl:index.php?id=' -e google -p 2 -o out.txt\n"
            "  dork-scraper -D dorks.txt -e duckduckgo --params-only -f json -o out.json\n"
            "  dork-scraper -d 'site:example.com' --unique domain\n"
            "  dork-scraper --clean-file raw.txt --drop-static -o clean.txt\n"
        ),
    )
    p.add_argument("-d", "--dork", action="append", metavar="DORK", help="a dork query (repeatable)")
    p.add_argument("-D", "--dork-file", metavar="FILE", help="file with one dork per line (# = comment)")
    p.add_argument("-e", "--engine", default="google", choices=sorted(ENGINES), help="search engine")
    p.add_argument("-p", "--pages", type=int, default=1, help="result pages per dork (default 1)")
    p.add_argument("-o", "--output", default="urls.txt", help="output file (default urls.txt)")
    p.add_argument("-f", "--format", default="txt", choices=["txt", "json", "csv"], help="output format")

    net = p.add_argument_group("network / stealth")
    net.add_argument("--delay", type=float, default=2.0, help="base delay between requests (s)")
    net.add_argument("--jitter", type=float, default=1.5, help="extra random delay up to N s")
    net.add_argument("--timeout", type=int, default=20, help="request timeout (s)")
    net.add_argument("--retries", type=int, default=2, help="retries per failed request")
    net.add_argument("--proxy", help="proxy URL, e.g. http://127.0.0.1:8080 or socks5://...")
    net.add_argument("--selenium", action="store_true", help="use a real Chrome browser (needs chromedriver)")
    net.add_argument("--no-headless", action="store_true", help="show the browser window (with --selenium)")

    filt = p.add_argument_group("filtering / cleaning")
    filt.add_argument("--unique", default="exact", choices=["exact", "domain", "pattern", "none"],
                      help="de-duplication mode (default exact)")
    filt.add_argument("--params-only", action="store_true", help="keep only URLs with query parameters")
    filt.add_argument("--drop-static", action="store_true", help="drop images/css/fonts/media URLs")
    filt.add_argument("--trailing-slash", action="store_true", help="append / to param-less paths")
    filt.add_argument("--keep-tracking", action="store_true", help="keep utm/gclid/... tracking params")
    filt.add_argument("--include-domain", action="append", metavar="GLOB", help="keep only these domains (repeatable)")
    filt.add_argument("--exclude-domain", action="append", metavar="GLOB", help="drop these domains (repeatable)")
    filt.add_argument("--clean-file", metavar="FILE", help="just clean an existing URL file (no scraping)")

    misc = p.add_argument_group("misc")
    misc.add_argument("-q", "--quiet", action="store_true", help="only print warnings/errors/summary")
    misc.add_argument("--no-banner", action="store_true", help="do not print the ASCII banner")
    misc.add_argument("-V", "--version", action="version", version=f"dork-scraper {__version__}")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    log = _make_logger(args.quiet)

    if not args.no_banner and not args.quiet:
        banner = BANNER.format(version=__version__)
        if _RICH:
            _console.print(f"[bold red]{banner}[/bold red]")
        else:
            print(banner, file=sys.stderr)

    if args.clean_file:
        try:
            return run_clean_file(args, log)
        except FileNotFoundError:
            log("error", f"file not found: {args.clean_file}")
            return 1

    dorks = collect_dorks(args)
    if not dorks:
        log("error", "no dorks provided. Use -d, -D or enter one interactively.")
        return 1

    clean_opts = dict(
        strip_tracking=not args.keep_tracking,
        trailing_slash=args.trailing_slash,
        drop_static=args.drop_static,
        params_only=args.params_only,
        unique_mode=args.unique,
        include_domains=args.include_domain or None,
        exclude_domains=args.exclude_domain or None,
    )

    scraper = DorkScraper(
        engine=args.engine,
        pages=max(1, args.pages),
        delay=args.delay,
        jitter=args.jitter,
        timeout=args.timeout,
        retries=args.retries,
        proxy=args.proxy,
        use_selenium=args.selenium,
        headless=not args.no_headless,
        log=log,
        clean_opts=clean_opts,
    )

    try:
        results = scraper.scrape_many(dorks)
    except KeyboardInterrupt:
        log("error", "interrupted by user")
        return 130
    finally:
        scraper.close()

    # global cross-dork de-duplication for txt output
    to_write = results
    if args.format == "txt" and len(results) > 1 and args.unique != "none":
        merged: List[str] = []
        for r in results:
            merged.extend(r.urls)
        merged = clean_urls(merged, unique_mode=args.unique, strip_tracking=False)
        to_write = [SearchResult(dork="(merged)", engine=args.engine, urls=merged)]

    total = write_output(to_write, args.output, args.format)
    log("ok", f"saved {total} URLs to {args.output} [{args.format}]")
    if not args.quiet:
        print_summary(results, total)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
