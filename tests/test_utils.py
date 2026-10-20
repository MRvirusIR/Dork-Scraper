from dorkscraper.utils import clean_urls, normalize_url, dedupe_by_pattern, get_domain


def test_normalize_strips_tracking_and_fragment():
    u = normalize_url("HTTPS://Example.COM/page.php?id=1&utm_source=x#top")
    assert u == "https://example.com/page.php?id=1"


def test_get_domain_strips_www():
    assert get_domain("https://www.site.org/a") == "site.org"


def test_dedupe_by_pattern():
    urls = ["http://a.com/p.php?id=1", "http://a.com/p.php?id=2", "http://a.com/p.php?cat=2"]
    assert dedupe_by_pattern(urls) == ["http://a.com/p.php?id=1", "http://a.com/p.php?cat=2"]


def test_clean_pipeline():
    raw = ["http://a.com/x.php?id=1", "http://a.com/x.php?id=1", "http://b.com/logo.png",
           "http://c.com/about", "not a url", "http://evil.gov/y.php?q=1"]
    out = clean_urls(raw, drop_static=True, params_only=True, exclude_domains=["*.gov"])
    assert out == ["http://a.com/x.php?id=1"]


def test_unique_domain():
    raw = ["http://a.com/1", "http://www.a.com/2", "http://b.com/"]
    assert clean_urls(raw, unique_mode="domain") == ["http://a.com/1", "http://b.com/"]
