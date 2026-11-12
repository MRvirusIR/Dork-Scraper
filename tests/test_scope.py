from dorkscraper.scope import apply_site_scope, normalize_query_input, engine_query, site_scope
from dorkscraper.core import DorkScraper


def test_user_example_normalizes_two_queries():
    pasted = '`site:*.bugcod3.com inurl:"?name="`and `site:*.bugcod3.com inurl:"?type="`'
    assert normalize_query_input([pasted]) == [
        'site:*.bugcod3.com inurl:"?name="', 'site:*.bugcod3.com inurl:"?type="']
    assert engine_query('site:*.bugcod3.com inurl:"?name="') == 'site:bugcod3.com inurl:"?name="'


def test_scope_wildcard_subdomains_and_boundary():
    urls = ['https://a.bugcod3.com/?name=x', 'https://bugcod3.com/?name=x',
            'https://evilbugcod3.com/', 'https://bugcod3.com.attacker.test/',
            'https://dict.leo.org/englisch-deutsch/site', 'https://A.BUGCOD3.COM:443/']
    kept, removed, warning = apply_site_scope('site:*.bugcod3.com inurl:"?name="', urls)
    assert kept == [urls[0], urls[-1]] and removed == 4 and warning is None
    kept, removed, _ = apply_site_scope('site:bugcod3.com', urls)
    assert kept == [urls[0], urls[1], urls[-1]] and removed == 3


def test_scope_complex_expressions_warn_instead_of_rewriting():
    for query in ['site:a.example OR site:b.example', 'NOT site:a.example', 'site:a.example site:b.example', 'site:example.com/path', 'inurl:"site:example.com"', 'site:"unterminated']:
        _, _, warning = site_scope(query)
        assert warning, query
    s = 'site:one.example and site:two.example'
    assert normalize_query_input([s]) == [s]
    assert engine_query('site:*.example.com OR site:*.other.com') == 'site:*.example.com OR site:*.other.com'


def test_scraper_enforces_before_dedup_and_exposes_effective_query(monkeypatch):
    html = ('<li class="b_algo"><h2><a href="https://dict.leo.org/">bad</a></h2></li>'
            '<li class="b_algo"><h2><a href="https://a.bugcod3.com/?name=x">good</a></h2></li>'
            '<li class="b_algo"><h2><a href="https://bugcod3.com/?name=x">root</a></h2></li>')
    requests=[]
    def fetch(self, url): requests.append(url); return html
    monkeypatch.setattr(DorkScraper,'_fetch', fetch)
    result = DorkScraper(engine='bing').scrape('site:*.bugcod3.com inurl:"?name="')
    assert result.urls == ['https://a.bugcod3.com/?name=x']
    assert result.out_of_scope_count == 2
    assert result.effective_query == 'site:bugcod3.com inurl:"?name="'
    assert 'site%3Abugcod3.com' in requests[0]


def test_markdown_escaped_wildcard():
    assert normalize_query_input([r'`site:\*.bugcod3.com inurl:"?name="`']) == ['site:*.bugcod3.com inurl:"?name="']


def test_explicit_domain_globs_match_www_and_ignore_port():
    from dorkscraper.utils import clean_urls
    urls=['https://www.bugcod3.com:443/a','https://x.bugcod3.com/a','https://bugcod3.com/a','https://badbugcod3.com/a']
    assert clean_urls(urls,include_domains=['*.bugcod3.com']) == urls[:2]


def test_literal_inurl_first_param_filter():
    from dorkscraper.scope import apply_literal_query_filter
    urls=['https://x.example/?name=1','https://x.example/?type=1','https://x.example/?a=1&name=1']
    kept, count, literal = apply_literal_query_filter('site:*.example.com inurl:"?name="', urls)
    assert (kept,count,literal) == ([urls[0]],2,'?name=')
    assert apply_literal_query_filter('site:example.com inurl:admin',urls) == (urls,0,None)
    assert apply_literal_query_filter('inurl:"?name=" OR inurl:"?type="',urls) == (urls,0,None)
