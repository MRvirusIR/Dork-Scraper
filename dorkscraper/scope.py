"""Conservative site: scope detection and result filtering.

The search provider is not a security boundary: operators can be ignored. Only
one unambiguous positive site: hostname is enforced automatically. Complex
queries remain unchanged and are explicitly reported as not guarded.
"""
from __future__ import annotations

import re
import shlex
from urllib.parse import urlsplit

_HOST = re.compile(r'^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*$')


def _hostname(value):
    try:
        text = value.rstrip('.').encode('idna').decode('ascii').lower()
    except (UnicodeError, AttributeError):
        return None
    return text if _HOST.fullmatch(text) else None


def site_scope(query):
    """Return (host, subdomains_only, warning), without interpreting boolean expressions."""
    try:
        tokens = shlex.split(query)
    except ValueError:
        return None, False, 'Scope guard inactive: unmatched quotes in query.'
    # Parentheses and boolean operators can change the meaning of site:.
    if any(t.upper() in ('OR', 'NOT') or t.startswith('!') or '(' in t or ')' in t for t in tokens):
        return None, False, 'Scope guard inactive for complex queries; only an explicit Include domains filter applies.'
    positive = [t[5:] for t in tokens if t.lower().startswith('site:')]
    if not positive:
        return None, False, 'No unambiguous site: scope; only an explicit Include domains filter applies.'
    if len(positive) != 1:
        return None, False, 'Scope guard inactive for multiple site: operators; use one query per line or set Include domains.'
    raw = positive[0]
    wildcard = raw.startswith('*.')
    domain = _hostname(raw[2:] if wildcard else raw)
    if not domain:
        return None, False, 'Scope guard inactive for unsupported site: syntax; only an explicit Include domains filter applies.'
    return domain, wildcard, None


def apply_site_scope(query, urls):
    """Enforce domain label boundaries and return (kept, removed_count, warning)."""
    host, wildcard, warning = site_scope(query)
    if not host:
        return list(urls), 0, warning
    kept = []
    for url in urls:
        try:
            parsed = urlsplit(url)
            domain = _hostname(parsed.hostname or '')
        except ValueError:
            domain = None
        if domain and (domain.endswith('.' + host) or (not wildcard and domain == host)):
            kept.append(url)
    return kept, len(urls) - len(kept), None


def apply_literal_query_filter(query, urls):
    """Enforce the narrow inurl:?key= case as a case-sensitive URL substring.

    Other inurl expressions are left to the provider; this is deliberately not
    an attempt to emulate its complete query language.
    """
    try:
        tokens = shlex.split(query)
    except ValueError:
        return list(urls), 0, None
    if any(t.upper() in ('OR', 'NOT') or t.startswith('!') or '(' in t or ')' in t for t in tokens):
        return list(urls), 0, None
    values = [t[6:] for t in tokens if t.lower().startswith('inurl:')]
    if len(values) != 1 or not re.fullmatch(r'\?[A-Za-z_][A-Za-z0-9_-]*=', values[0]):
        return list(urls), 0, None
    literal = values[0]
    kept = [url for url in urls if literal in url]
    return kept, len(urls) - len(kept), literal


def engine_query(query):
    """Expand a simple wildcard site: for provider compatibility; filter locally."""
    host, wildcard, warning = site_scope(query)
    if not host or not wildcard or warning:
        return query
    pattern = r'(?<!\S)site:\*\.' + re.escape(host) + r'(?=\s|$)'
    return re.sub(pattern, 'site:' + host, query, count=1, flags=re.I)


def normalize_query_input(lines):
    """Unwrap plain copied Markdown code spans; split only an unambiguous span list."""
    output = []
    span_list = re.compile(r'^\s*`[^`\n]+`(?:\s*(?:and|,)\s*`[^`\n]+`)+\s*$', re.I)
    for line in lines:
        line = line.strip().replace('\\`', '`')
        if not line:
            continue
        if span_list.fullmatch(line):
            output.extend(x.strip() for x in re.findall(r'`([^`\n]+)`', line))
        elif re.fullmatch(r'`[^`\n]+`', line):
            output.append(line[1:-1].strip())
        else:
            output.append(line)
    output = [re.sub(r'(?i)(?<!\S)(site:)\\\*\.', r'\1*.', q) for q in output]
    return list(dict.fromkeys(q for q in output if q))
