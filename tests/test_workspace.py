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
