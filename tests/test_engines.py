from dorkscraper.engines import ENGINES, get_engine


def test_all_engines_registered():
    assert set(ENGINES) == {"google", "bing", "duckduckgo", "yahoo", "brave", "serpapi_google", "serpapi_duckduckgo", "bing_rss", "searxng"}


def test_google_parse():
    html = (
        '<a href="/url?q=https://target.com/a.php%3Fid%3D1&sa=U">x</a>'
        '<a href="https://site.org/page"><h3>Title</h3></a>'
        '<a href="https://www.google.com/preferences"><h3>G</h3></a>'
    )
    assert get_engine("google").parse(html) == ["https://target.com/a.php?id=1", "https://site.org/page"]


def test_duckduckgo_parse():
    html = '<a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fx.com%2Fp%3Fid%3D3">r</a>'
    assert get_engine("duckduckgo").parse(html) == ["https://x.com/p?id=3"]


def test_bing_parse():
    html = '<li class="b_algo"><h2><a href="https://b.com/q.asp?id=9">t</a></h2></li>'
    assert get_engine("bing").parse(html) == ["https://b.com/q.asp?id=9"]


def test_block_detection():
    assert get_engine("google").is_blocked("Our systems have detected unusual traffic")


def test_bing_decodes_wrapped_result():
    html = '<li class="b_algo"><h2><a href="https://www.bing.com/ck/a?u=a1aHR0cHM6Ly9leGFtcGxlLmNvbS9hP2lkPTE">Result</a></h2></li>'
    assert get_engine('bing').parse(html) == ['https://example.com/a?id=1']


def test_google_js_only_page_is_reported(monkeypatch):
    from dorkscraper.core import DorkScraper
    monkeypatch.setattr(DorkScraper, '_fetch', lambda self, url: '<a href="/httpservice/retry/enablejs">Retry</a>')
    result = DorkScraper(engine='google').scrape('site:example.com')
    assert result.urls == [] and 'JavaScript-only' in result.error


def test_serpapi_google_parse_and_pagination():
    engine = get_engine('serpapi_google')
    assert 'start=20' in engine.build_url('site:example.com', 2)
    assert engine.parse('{"organic_results":[{"link":"https://example.com/"},{"title":"missing"}]}') == ['https://example.com/']
    import pytest
    with pytest.raises(ValueError, match='SerpApi returned an error'):
        engine.parse('{"error":"secret should not be echoed"}')


def test_serpapi_success_empty_is_not_an_error():
    engine = get_engine('serpapi_google')
    payload = '''{"search_metadata":{"status":"Success"},"search_information":{"organic_results_state":"Fully empty"},"error":"Google hasn't returned any results for this query."}'''
    assert engine.parse(payload) == []
    import pytest
    with pytest.raises(ValueError):
        engine.parse(payload.replace('Success', 'Error'))


def test_captcha_word_in_result_is_not_blocked():
    engine = get_engine('duckduckgo')
    html = '<a class="result__a" href="https://example.com/captcha">What is CAPTCHA?</a>'
    assert not engine.is_blocked(html)
    assert engine.is_blocked('<div class="anomaly-modal">challenge</div>')
    assert engine.parse(html) == ['https://example.com/captcha']


def test_serpapi_duckduckgo_url_and_parsing():
    from urllib.parse import urlsplit, parse_qs
    engine = get_engine('serpapi_duckduckgo')
    for page, offset in [(0, '0'), (1, '11'), (2, '61')]:
        params = parse_qs(urlsplit(engine.build_url('site:example.com', page)).query)
        assert params['engine'] == ['duckduckgo'] and params['start'] == [offset]
    assert engine.parse('{"organic_results":[{"link":"https://example.com/x"}]}') == ['https://example.com/x']


def test_keyless_bing_rss_parses_only_items():
    from urllib.parse import urlparse, parse_qs
    engine = get_engine('bing_rss')
    query = parse_qs(urlparse(engine.build_url('site:example.com', 1)).query)
    assert query['format'] == ['rss'] and query['first'] == ['11']
    rss = '''<?xml version="1.0"?><rss><channel><link>https://bing.com/</link><item><link>https://example.com/a?id=1&amp;x=2</link></item><item><link>javascript:bad</link></item></channel></rss>'''
    assert engine.parse(rss) == ['https://example.com/a?id=1&x=2']
    assert engine.parse('<rss><channel/></rss>') == []


def test_keyless_bing_rejects_invalid_xml_and_entities():
    import pytest
    engine = get_engine('bing_rss')
    for payload in ['<html>not rss</html>', '<rss><channel>', '<!DOCTYPE rss [<!ENTITY x "example">]><rss><channel><item><link>&x;</link></item></channel></rss>']:
        with pytest.raises(ValueError, match='invalid RSS'):
            engine.parse(payload)


def test_searxng_url_validation_and_parsing(monkeypatch):
    from urllib.parse import urlparse, parse_qs
    import pytest
    engine = get_engine('searxng')
    monkeypatch.setenv('SEARXNG_URL','http://127.0.0.1:8080/prefix')
    url = urlparse(engine.build_url('site:example.com', 1))
    assert url.path == '/prefix/search' and parse_qs(url.query)['pageno'] == ['2']
    assert engine.parse('{"results":[{"url":"https://example.com/a"},{"bad":1}]}') == ['https://example.com/a']
    for host in ['http://external.test', 'https://user:pass@host.test', 'https://host.test/?x=1', 'file:///tmp']:
        monkeypatch.setenv('SEARXNG_URL',host)
        with pytest.raises(ValueError): engine.build_url('test', 0)
    with pytest.raises(ValueError): engine.parse('{"error":"bad"}')
