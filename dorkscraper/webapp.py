"""Local-only web workspace. Run with ``dork-scraper-web``."""
from __future__ import annotations

import argparse
import json
import importlib.util
import os
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit, urlparse

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from .core import DorkScraper
from .engines import ENGINES
from .utils import clean_urls, normalize_url, get_domain, param_names
from .scope import apply_site_scope, apply_literal_query_filter, normalize_query_input

STATIC = Path(__file__).parent / "web"
TOKEN = secrets.token_urlsafe(32)
DB_PATH = Path(os.environ.get("DORK_SCRAPER_DB", Path.home() / ".dork-scraper" / "workspace.sqlite3"))
DB_LOCK = threading.RLock()
CANCEL = {}
KEYLESS_FALLBACK = ('bing_rss', 'bing', 'duckduckgo', 'google', 'yahoo')
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH), timeout=15)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with DB_LOCK, db() as con:
        con.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created REAL NOT NULL, data TEXT NOT NULL)")
        for row in con.execute("SELECT id, data FROM jobs").fetchall():
            data = json.loads(row['data'])
            if data.get('status') in ('queued', 'running'):
                data['status'] = 'interrupted'
                con.execute('UPDATE jobs SET data=? WHERE id=?', (json.dumps(data), row['id']))


def save(job):
    with DB_LOCK, db() as con:
        con.execute('INSERT OR REPLACE INTO jobs (id, created, data) VALUES (?, ?, ?)',
                    (job['id'], job['created'], json.dumps(job, ensure_ascii=False)))


def load(job_id):
    with DB_LOCK, db() as con:
        row = con.execute('SELECT data FROM jobs WHERE id=?', (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, 'Job not found')
    return json.loads(row['data'])


@app.middleware('http')
async def local_security(request: Request, call_next):
    # Reject remote DNS-rebinding hosts and cross-origin requests, including reads.
    host = request.headers.get('host', '').lower()
    try:
        parsed_host = urlsplit('http://' + host)
        hostname = parsed_host.hostname
        _ = parsed_host.port
    except ValueError:
        return JSONResponse({'detail': 'Invalid host'}, 403)
    if hostname not in ('127.0.0.1', 'localhost', '::1') or parsed_host.netloc != host:
        return JSONResponse({'detail': 'Local host required'}, 403)
    origin = request.headers.get('origin')
    if origin and origin.lower() != 'http://' + host:
        return JSONResponse({'detail': 'Cross-origin requests are not allowed'}, 403)
    if request.method not in ('GET', 'HEAD') and not secrets.compare_digest(request.headers.get('x-workspace-token', ''), TOKEN):
        return JSONResponse({'detail': 'Invalid workspace token'}, 403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    response.headers['Cache-Control'] = 'no-store'
    return response


class Options(BaseModel):
    strip_tracking: bool = True
    drop_static: bool = False
    params_only: bool = False
    unique_mode: str = 'exact'
    include_domains: List[str] = Field(default_factory=list)
    exclude_domains: List[str] = Field(default_factory=list)


def options_dict(options):
    data = options.model_dump() if hasattr(options, 'model_dump') else options.dict()
    if data['unique_mode'] not in ('exact', 'domain', 'pattern', 'none'):
        raise HTTPException(422, 'Invalid deduplication mode')
    if any(len(x) > 255 for x in data['include_domains'] + data['exclude_domains']):
        raise HTTPException(422, 'Domain filter too long')
    return data


class CleanRequest(BaseModel):
    urls: List[str]
    options: Options = Field(default_factory=Options)


class SearchRequest(BaseModel):
    queries: List[str]
    engines: List[str]
    pages: int = Field(default=1, ge=1, le=10)
    delay: float = Field(default=2, ge=1, le=60)
    manual_browser: bool = False
    keyless_fallback: bool = False
    options: Options = Field(default_factory=Options)


def clean_report(urls, opts):
    if len(urls) > 10000 or any(len(x) > 8192 for x in urls):
        raise HTTPException(422, 'Maximum 10,000 URLs; each URL must be under 8,192 characters')
    result = clean_urls(urls, **opts)
    # Preserve the first original for each normalized result (without network access).
    first = {}
    for raw in urls:
        try:
            normalized = normalize_url(raw, strip_tracking=opts['strip_tracking'])
            first.setdefault(normalized, raw)
        except ValueError:
            continue
    return {'input_count': len(urls), 'output_count': len(result), 'removed_count': len(urls)-len(result),
            'items': [{'url': u, 'original': first.get(u, u)} for u in result]}


def present_job(job):
    """Combine cross-engine results using the selected uniqueness policy."""
    mode = job.get('unique_mode', 'exact')
    seen, items = {}, []
    safe_results = []
    for original in job.get('results', []):
        result = dict(original)
        result['urls'], removed, warning = apply_site_scope(result['query'], result['urls'])
        result['out_of_scope_count'] = result.get('out_of_scope_count', 0) + removed
        result['scope_warning'] = warning
        result['urls'], literal_removed, literal = apply_literal_query_filter(result['query'], result['urls'])
        result['literal_filter'] = literal
        result['literal_filtered_count'] = result.get('literal_filtered_count', 0) + literal_removed
        safe_results.append(result)
        source = '%s / %s' % (result['engine'], result['query'])
        for url in result['urls']:
            parsed = urlparse(url)
            if mode == 'domain':
                key = get_domain(url)
            elif mode == 'pattern':
                key = (parsed.netloc.lower(), parsed.path, tuple(sorted(param_names(url))))
            elif mode == 'none':
                key = len(items)
            else:
                key = url
            if key not in seen:
                seen[key] = len(items)
                items.append({'url': url, 'sources': []})
            if source not in items[seen[key]]['sources']:
                items[seen[key]]['sources'].append(source)
    return {**job, 'results': safe_results, 'items': items}


def run_job(job, opts, cancel):
    job['status'] = 'running'; save(job)
    scrapers = {}
    def challenge_notice(message):
        job['notice'] = message
        save(job)
    try:
        results = []
        unavailable = {}
        total = len(job['queries']) * len(job['engines'])
        for query in job['queries']:
            matched = False
            for engine in job['engines']:
                if cancel.is_set():
                    job['status'] = 'cancelled'; return
                if job.get('keyless_fallback') and matched:
                    results.append({'query': query, 'engine': engine, 'urls': [], 'pages_fetched': 0,
                                    'blocked': False, 'error': None, 'skip_kind': 'not_needed',
                                    'skipped_reason': 'Skipped: an earlier keyless provider found matching URLs.'})
                elif engine in unavailable:
                    results.append({'query': query, 'engine': engine, 'urls': [], 'pages_fetched': 0,
                                    'blocked': False, 'error': None, 'skipped_reason': unavailable[engine]})
                else:
                    interactive = job.get('manual_browser', False) and engine in ('google', 'duckduckgo')
                    if engine not in scrapers:
                        scrapers[engine] = DorkScraper(engine=engine, pages=job['pages'], delay=job['delay'],
                                                      jitter=1, timeout=15, retries=1, clean_opts=opts,
                                                      use_selenium=interactive, headless=not interactive,
                                                      manual_captcha=interactive, cancel_event=cancel,
                                                      challenge_notice=challenge_notice)
                    if interactive:
                        challenge_notice('Interactive browser running for %s; use the opened window if a challenge appears.' % engine)
                    result = scrapers[engine].scrape(query)
                    if interactive:
                        challenge_notice('')
                    if cancel.is_set():
                        job['status'] = 'cancelled'; return
                    results.append({'query': query, 'engine': engine, 'urls': result.urls,
                                    'pages_fetched': result.pages_fetched, 'blocked': result.blocked,
                                    'error': result.error, 'out_of_scope_count': result.out_of_scope_count,
                                    'scope_warning': result.scope_warning, 'effective_query': result.effective_query or query,
                                    'literal_filter': result.literal_filter, 'literal_filtered_count': result.literal_filtered_count,
                                    'warning': result.warning})
                    if job.get('keyless_fallback') and result.urls:
                        matched = True
                    if result.blocked:
                        unavailable[engine] = 'Skipped after provider block or rate limit; try later.'
                    elif engine == 'google' and result.error and 'JavaScript-only' in result.error:
                        unavailable[engine] = 'Skipped after JavaScript-only response; choose an API provider.'
                job['results'] = results
                job['completed'] = len(results)
                save(job)
                if len(results) < total and not results[-1].get('skipped_reason') and cancel.wait(job['delay']):
                    job['status'] = 'cancelled'; return
        job['status'] = 'completed'
    except Exception as exc:
        job['status'] = 'failed'
        job['error'] = str(exc)
    finally:
        for scraper in scrapers.values():
            scraper.close()
        job['notice'] = ''
        save(job)
        with DB_LOCK:
            CANCEL.pop(job['id'], None)


@app.get('/', response_class=HTMLResponse)
def index():
    return (STATIC / 'index.html').read_text(encoding='utf-8').replace('__WORKSPACE_TOKEN__', TOKEN)


@app.get('/app.js')
def js():
    return Response((STATIC / 'app.js').read_text(encoding='utf-8'), media_type='text/javascript')


@app.get('/style.css')
def css():
    return Response((STATIC / 'style.css').read_text(encoding='utf-8'), media_type='text/css')


@app.get('/api/config')
def config():
    return {'engines': sorted(ENGINES), 'brave_configured': bool(os.environ.get('BRAVE_API_KEY')),
            'serpapi_google_configured': bool(os.environ.get('SERPAPI_API_KEY')),
            'searxng_configured': bool(os.environ.get('SEARXNG_URL'))}


@app.post('/api/clean')
def clean(body: CleanRequest):
    return clean_report(body.urls, options_dict(body.options))


@app.get('/api/jobs')
def jobs():
    with DB_LOCK, db() as con:
        rows = con.execute('SELECT data FROM jobs ORDER BY created DESC LIMIT 100').fetchall()
    return [present_job(json.loads(row['data'])) for row in rows]


@app.get('/api/jobs/{job_id}')
def get_job(job_id: str):
    return present_job(load(job_id))


@app.post('/api/jobs', status_code=202)
def create_job(body: SearchRequest):
    queries = normalize_query_input(body.queries)
    engines = list(KEYLESS_FALLBACK) if body.keyless_fallback else list(dict.fromkeys(body.engines))
    if not queries or len(queries) > 20 or any(len(q) > 600 for q in queries):
        raise HTTPException(422, 'Provide 1–20 queries, each up to 600 characters')
    if not engines or any(e not in ENGINES for e in engines):
        raise HTTPException(422, 'Select valid search engines')
    if body.manual_browser and not any(e in engines for e in ('google', 'duckduckgo')):
        raise HTTPException(422, 'Interactive browser requires direct Google or DuckDuckGo.')
    if body.manual_browser and importlib.util.find_spec('selenium') is None:
        raise HTTPException(422, 'Interactive browser requires Selenium; install dork-scraper[selenium].')
    if 'searxng' in engines and not os.environ.get('SEARXNG_URL'):
        raise HTTPException(422, 'SearXNG requires SEARXNG_URL for an instance with JSON enabled.')
    if 'brave' in engines and not os.environ.get('BRAVE_API_KEY'):
        raise HTTPException(422, 'Brave requires BRAVE_API_KEY; configure it or deselect Brave.')
    if any(e in engines for e in ('serpapi_google', 'serpapi_duckduckgo')) and not os.environ.get('SERPAPI_API_KEY'):
        raise HTTPException(422, 'SerpApi requires SERPAPI_API_KEY; configure it or deselect its engines.')
    opts = options_dict(body.options)
    with DB_LOCK:
        if len(CANCEL) >= 1:
            raise HTTPException(409, 'A search is already running')
        job = {'id': uuid.uuid4().hex, 'created': time.time(), 'status': 'queued',
               'queries': queries, 'engines': engines, 'pages': body.pages, 'delay': body.delay,
               'completed': 0, 'total': len(queries)*len(engines), 'results': [], 'error': None,
               'manual_browser': body.manual_browser, 'keyless_fallback': body.keyless_fallback, 'notice': '',
               'unique_mode': opts['unique_mode']}
        cancel = threading.Event(); CANCEL[job['id']] = cancel
        save(job)
        threading.Thread(target=run_job, args=(job, opts, cancel), daemon=True).start()
    return present_job(job)


@app.post('/api/jobs/{job_id}/cancel')
def cancel_job(job_id: str):
    load(job_id)
    with DB_LOCK:
        event = CANCEL.get(job_id)
        if not event:
            raise HTTPException(409, 'Job is not running')
        event.set()
    return {'ok': True, 'message': 'Cancellation requested; current search finishes first'}


@app.delete('/api/jobs/{job_id}')
def delete_job(job_id: str):
    with DB_LOCK:
        if job_id in CANCEL:
            raise HTTPException(409, 'Cancel the running job first')
        with db() as con:
            deleted = con.execute('DELETE FROM jobs WHERE id=?', (job_id,)).rowcount
    if not deleted:
        raise HTTPException(404, 'Job not found')
    return {'ok': True}


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description='Start the local Dork-Scraper workspace')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    init_db()
    print('Dork-Scraper workspace: http://127.0.0.1:%s' % args.port, flush=True)
    uvicorn.run(app, host='127.0.0.1', port=args.port, log_level='warning')


if __name__ == '__main__':
    main()
