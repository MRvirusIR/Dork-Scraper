#!/usr/bin/env python3
"""Backward-compatible entry point. Prefer: `dork-scraper` or `python -m dorkscraper`."""
from dorkscraper.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
