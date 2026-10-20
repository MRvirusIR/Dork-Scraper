from dorkscraper.engines import ENGINES, get_engine


def test_all_engines_registered():
    assert set(ENGINES) == {"google", "bing", "duckduckgo", "yahoo"}


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
