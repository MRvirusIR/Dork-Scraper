# Changelog

All notable changes to this project are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

## [3.0.0] - Unreleased

### Added
- Optional local web workspace with responsive light/dark UI, search, cleaning, exports, and SQLite history.
- Multi-query, multi-engine jobs with per-engine status, progress, cancellation between searches and source attribution.
- Official Brave Search API provider using `BRAVE_API_KEY` (requires a subscription; max 10 pages).
- Cross-engine deduplication with exact, domain, pattern, or none modes.
- URL cleaning preview retains the first original for each output, with local text import.
- Localhost-only server with Host/Origin checks and a per-process mutation token.
- Automated tests for the workspace API, safety checks, job lifecycle and Brave provider.

### Changed
- URL validation rejects non-HTTP(S) schemes, malformed hosts/ports and embedded credentials.
- Tracking cleanup handles arbitrary `utm_` parameters as well as known tracking keys.

### Limitations
- HTML-based providers depend on search-engine markup and may block requests or change results.
- Brave live access requires a valid API key; cancellation waits for the current search to finish.
- History is stored unencrypted locally and the UI is intended for a single trusted user.

## [2.0.0] - 2026-10-20

A complete rewrite. The old single-file script is now a proper package.

### Added
- **Multi-engine support**: Google, Bing, DuckDuckGo and Yahoo backends.
- **Full CLI** (`argparse`): engines, pages, delay/jitter, timeout, retries, proxy.
- **Batch mode**: run many dorks from a file with `-D/--dork-file` (ready-made lists in `dorks/`).
- **Output formats**: `txt`, `json`, `csv` via `-f/--format`.
- **Built-in cleaning**: tracking-param stripping, static-asset dropping, params-only
  filtering, domain include/exclude globs, and `exact | domain | pattern | none` de-duplication.
- **Clean-only mode**: `--clean-file` cleans an existing URL list without scraping
  (replaces the old `split.py` + `clean-urls.py`).
- **Stealth**: rotating User-Agents, randomised delays, retries with backoff,
  CAPTCHA/block-page detection, optional Selenium engine and proxy support.
- **Pretty output** with `rich` (graceful fallback when not installed).
- `pyproject.toml` with a `dork-scraper` console entry point, unit tests and GitHub Actions CI.

### Changed
- Default fetching uses lightweight HTTP requests instead of requiring a browser.
- Robust Google parser that handles both modern and no-JS result layouts.

### Removed
- Committed `chromedriver` and `chromedriver_linux64.zip` binaries (install your own driver).
- Standalone `split.py` / `clean-urls.py` (folded into the cleaning pipeline).

## [1.0.0]
- Initial single-file Selenium-based Google dork scraper.
