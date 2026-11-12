from dorkscraper.engines import ENGINES, get_engine


def test_all_engines_registered():
    assert set(ENGINES) == {"google", "bing", "duckduckgo", "yahoo", "brave", "serpapi_google"}


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
