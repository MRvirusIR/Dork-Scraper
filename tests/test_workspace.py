import time
import pytest
from fastapi.testclient import TestClient
from dorkscraper import webapp
from dorkscraper.core import DorkScraper, SearchResult
from dorkscraper.engines import get_engine
from dorkscraper.utils import clean_urls


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp, 'DB_PATH', tmp_path / 'test.db')
    webapp.CANCEL.clear()
    webapp.init_db()
    with TestClient(webapp.app, base_url='http://127.0.0.1:8765') as c:
        yield c


def headers():
    return {'X-Workspace-Token': webapp.TOKEN}


def test_url_validation_and_tracking():
    assert clean_urls(['httpx://bad.test/a', 'https://', 'http://[broken', 'https://user:pass@site.test/',
                       'https://ok.test:bad', 'https://OK.test/?id=1&utm_custom=x&fbclid=a#top']) == ['https://ok.test/?id=1']


def test_brave_parser_and_offset():
    engine = get_engine('brave')
    assert 'offset=2' in engine.build_url('site:example.com', 2)
    assert engine.parse('{"web":{"results":[{"url":"https://example.com/"},{}]}}') == ['https://example.com/']
    with pytest.raises(ValueError): engine.build_url('x', 10)


def test_brave_key_failure_no_network(monkeypatch):
    monkeypatch.delenv('BRAVE_API_KEY', raising=False)
    monkeypatch.setattr('dorkscraper.core.requests.get', lambda *a, **k: pytest.fail('must not request without API key'))
    with DorkScraper(engine='brave', retries=0) as scraper:
        r = scraper.scrape('test')
    assert 'BRAVE_API_KEY' in r.error


def test_brave_auth_and_parsing(monkeypatch):
    monkeypatch.setenv('BRAVE_API_KEY', 'secret-test-key')
    class Fake:
        text = '{"web":{"results":[{"url":"https://example.com/?id=1"}]}}'
        def raise_for_status(self): pass
    def get(url, **kw):
        assert url.startswith('https://api.search.brave.com/res/v1/web/search?')
        assert kw['headers']['X-Subscription-Token'] == 'secret-test-key'
        assert kw['allow_redirects'] is False
        return Fake()
    monkeypatch.setattr('dorkscraper.core.requests.get', get)
    with DorkScraper(engine='brave', retries=0) as scraper:
        r = scraper.scrape('site:example.com')
    assert r.urls == ['https://example.com/?id=1']


def test_local_security(client):
    assert client.get('/', headers={'host':'evil.example'}).status_code == 403
    assert client.get('/api/jobs', headers={'origin':'https://evil.example'}).status_code == 403
    assert client.post('/api/clean', json={'urls': []}).status_code == 403
    assert client.post('/api/clean', headers={**headers(), 'origin':'https://evil.example'}, json={'urls': []}).status_code == 403
    assert client.get('/').status_code == 200


def test_clean_preview_and_validation(client):
    data={'urls':['https://Example.com/p?utm_source=x&id=1','https://example.com/p?id=1','ftp://bad'], 'options':{}}
    r=client.post('/api/clean',headers=headers(),json=data)
    assert r.status_code == 200
    assert r.json()['input_count'] == 3 and r.json()['removed_count'] == 2
    assert r.json()['items'] == [{'url':'https://example.com/p?id=1','original':data['urls'][0]}]
    data['options']={'unique_mode':'bogus'}
    assert client.post('/api/clean',headers=headers(),json=data).status_code==422


def test_job_history_and_provenance(client, monkeypatch):
    def fake(self, query): return SearchResult(dork=query, engine=self.engine, urls=['https://example.com/?id=1'], pages_fetched=1)
    monkeypatch.setattr(DorkScraper, 'scrape', fake)
    r=client.post('/api/jobs',headers=headers(),json={'queries':['site:example.com'], 'engines':['google','bing'], 'delay':1})
    assert r.status_code==202
    jobid=r.json()['id']
    for _ in range(100):
        job=client.get('/api/jobs/'+jobid).json()
        if job['status']=='completed': break
        time.sleep(.03)
    assert job['status']=='completed' and job['completed']==2
    assert [x['engine'] for x in job['results']]==['google','bing']
    assert len(client.get('/api/jobs').json())==1
    assert client.delete('/api/jobs/'+jobid,headers=headers()).status_code==200
    assert client.get('/api/jobs/'+jobid).status_code==404


def test_cancel_and_validation(client, monkeypatch):
    def fake(self, query): return SearchResult(dork=query, engine=self.engine)
    monkeypatch.setattr(DorkScraper, 'scrape', fake)
    assert client.post('/api/jobs',headers=headers(),json={'queries':[], 'engines':['google']}).status_code==422
    assert client.post('/api/jobs',headers=headers(),json={'queries':['x'], 'engines':['invalid']}).status_code==422
    r=client.post('/api/jobs',headers=headers(),json={'queries':['a','b'], 'engines':['google'],'delay':3})
    jobid=r.json()['id']
    assert client.post('/api/jobs/'+jobid+'/cancel',headers=headers()).status_code==200
    for _ in range(100):
        job=client.get('/api/jobs/'+jobid).json()
        if job['status']=='cancelled': break
        time.sleep(.01)
    assert job['status']=='cancelled'


def test_interrupted_on_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(webapp,'DB_PATH',tmp_path/'jobs.db')
    webapp.init_db()
    webapp.save({'id':'x','created':1,'status':'running'})
    webapp.init_db()
    assert webapp.load('x')['status']=='interrupted'


def test_cross_engine_unique_modes():
    base = {'results': [
        {'engine':'google', 'query':'q1', 'urls':['https://example.com/a?id=1']},
        {'engine':'bing', 'query':'q2', 'urls':['https://example.com/a?id=2']},
    ]}
    assert len(webapp.present_job({**base, 'unique_mode':'exact'})['items']) == 2
    grouped=webapp.present_job({**base, 'unique_mode':'pattern'})['items']
    assert len(grouped)==1 and grouped[0]['sources']==['google / q1','bing / q2']
    assert len(webapp.present_job({**base, 'unique_mode':'none'})['items'])==2
    assert len(webapp.present_job({**base, 'unique_mode':'domain'})['items'])==1


def test_old_history_scope_filter_and_attribution(client):
    job = {'id':'old','created':1,'status':'completed','queries':['site:*.bugcod3.com'],
           'engines':['bing'], 'results':[{'engine':'bing','query':'site:*.bugcod3.com',
           'urls':['https://a.bugcod3.com/', 'https://example.com/']}], 'total':1,'completed':1}
    webapp.save(job)
    data=client.get('/api/jobs/old').json()
    assert data['results'][0]['urls']==['https://a.bugcod3.com/']
    assert data['results'][0]['out_of_scope_count']==1
    assert [i['url'] for i in data['items']]==['https://a.bugcod3.com/']


def test_serpapi_key_handling_and_no_retry(monkeypatch):
    import requests
    monkeypatch.setenv('SERPAPI_API_KEY','sensitive-key-123')
    attempts=[]
    def fail(url, **kwargs):
        attempts.append((url,kwargs))
        assert 'sensitive-key-123' not in url
        assert kwargs['params']['api_key']=='sensitive-key-123'
        assert kwargs['allow_redirects'] is False
        raise requests.exceptions.ConnectionError('https://serpapi.com/?api_key=sensitive-key-123')
    monkeypatch.setattr('dorkscraper.core.requests.get', fail)
    result=DorkScraper(engine='serpapi_google', retries=3, delay=0).scrape('site:example.com')
    assert len(attempts)==1 and 'network error' in result.error
    assert 'sensitive-key-123' not in result.error


def test_serpapi_provider_success(monkeypatch):
    monkeypatch.setenv('SERPAPI_API_KEY','test-key')
    class Response:
        status_code=200
        text='{"organic_results":[{"link":"https://example.com/?name=test"},{"link":"https://notexample.com/"}]}'
        def raise_for_status(self): pass
    monkeypatch.setattr('dorkscraper.core.requests.get',lambda *a,**kw: Response())
    result=DorkScraper(engine='serpapi_google',retries=0).scrape('site:example.com inurl:"?name="')
    assert result.urls==['https://example.com/?name=test']
    assert result.out_of_scope_count==1


def test_serpapi_missing_key_and_http_error_dont_leak(monkeypatch):
    import requests
    monkeypatch.delenv('SERPAPI_API_KEY', raising=False)
    assert 'SERPAPI_API_KEY' in DorkScraper(engine='serpapi_google',delay=0).scrape('x').error
    monkeypatch.setenv('SERPAPI_API_KEY','SECRET_DO_NOT_LOG')
    class FakeResponse:
        status_code=401
        def raise_for_status(self):
            response=requests.Response()
            response.status_code=401
            raise requests.HTTPError('https://serpapi.com/?api_key=SECRET_DO_NOT_LOG',response=response)
    monkeypatch.setattr('dorkscraper.core.requests.get', lambda *a, **k: FakeResponse())
    r=DorkScraper(engine='serpapi_google',retries=3,delay=0).scrape('site:example.com')
    assert 'HTTP 401' in r.error and 'SECRET_DO_NOT_LOG' not in r.error


@pytest.mark.parametrize('code,detail', [(401, 'invalid API key'), (429, 'limit reached'), (503, 'provider unavailable')])
def test_serpapi_http_errors_are_safe_and_not_retried(monkeypatch, code, detail):
    import requests
    monkeypatch.setenv('SERPAPI_API_KEY', 'secret-test-key')
    attempts = []
    def fail(*args, **kwargs):
        attempts.append(1)
        response = requests.Response(); response.status_code = code
        raise requests.HTTPError('secret-test-key', response=response)
    monkeypatch.setattr('dorkscraper.core.requests.get', fail)
    result = DorkScraper(engine='serpapi_google', retries=3, delay=0).scrape('site:example.com')
    assert len(attempts) == 1 and ('HTTP %s' % code) in result.error and detail in result.error
    assert 'secret-test-key' not in result.error


def test_rate_limited_html_provider_is_not_retried(monkeypatch):
    import requests
    attempts = []
    def fail(*args, **kwargs):
        attempts.append(1)
        response = requests.Response(); response.status_code = 429
        raise requests.HTTPError('long URL', response=response)
    monkeypatch.setattr('dorkscraper.core.requests.get', fail)
    result = DorkScraper(engine='duckduckgo', retries=3, delay=0).scrape('test')
    assert len(attempts) == 1 and result.blocked and 'HTTP 429' in result.error


def test_batch_skips_blocked_and_js_only_providers(tmp_path, monkeypatch):
    import threading
    monkeypatch.setattr(webapp, 'DB_PATH', tmp_path / 'batch.db')
    webapp.init_db()
    calls = []
    def scrape(self, query):
        calls.append((self.engine, query))
        if self.engine == 'duckduckgo':
            return SearchResult(dork=query, engine=self.engine, blocked=True)
        if self.engine == 'google':
            return SearchResult(dork=query, engine=self.engine, error='Google returned a JavaScript-only page')
        return SearchResult(dork=query, engine=self.engine)
    monkeypatch.setattr(DorkScraper, 'scrape', scrape)
    class NoWait(threading.Event):
        def wait(self, timeout=None): return False
    job = {'id':'job', 'created':time.time(), 'queries':['one','two'],
           'engines':['duckduckgo','google','bing'], 'pages':1, 'delay':1}
    webapp.run_job(job, {}, NoWait())
    assert job['status'] == 'completed' and job['completed'] == 6
    assert calls == [('duckduckgo','one'), ('google','one'), ('bing','one'), ('bing','two')]
    assert job['results'][3]['skipped_reason'] and job['results'][4]['skipped_reason']
    assert 'skipped_reason' not in job['results'][5]
    assert len(webapp.present_job(job)['results']) == 6


def test_serpapi_empty_is_completed_as_zero_results(monkeypatch):
    monkeypatch.setenv('SERPAPI_API_KEY', 'test-key')
    class Response:
        status_code = 200
        text = '''{"search_metadata":{"status":"Success"},"search_information":{"organic_results_state":"Fully empty"},"error":"Google hasn't returned any results for this query."}'''
        def raise_for_status(self): pass
    monkeypatch.setattr('dorkscraper.core.requests.get', lambda *a, **k: Response())
    result = DorkScraper(engine='serpapi_google', retries=0).scrape('site:example.com')
    assert result.error is None and result.pages_fetched == 1 and result.urls == []


def test_yahoo_upstream_error_reported_without_query_url(monkeypatch):
    import requests
    def fail(*args, **kwargs):
        response = requests.Response(); response.status_code = 500
        raise requests.HTTPError('upstream error with private query', response=response)
    monkeypatch.setattr('dorkscraper.core.requests.get', fail)
    result = DorkScraper(engine='yahoo', retries=0).scrape('test')
    assert 'provider unavailable (HTTP 500)' in result.error
    assert 'private query' not in result.error
