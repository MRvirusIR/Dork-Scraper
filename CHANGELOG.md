# Changelog

All notable changes to this project are documented here.
This project adheres to [Semantic Versioning](https://semver.org/).

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
