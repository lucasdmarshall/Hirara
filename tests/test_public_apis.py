import asyncio
import json
import pytest
from hiraraweb import public_apis
from hiraraweb.tools import Toolset

pytest.importorskip("hirara_native")

@pytest.mark.asyncio
async def test_books_and_stackexchange(monkeypatch):
    urls=[]
    bodies=[{"totalItems":1,"items":[{"id":"book1","volumeInfo":{"title":"Rust &amp; Safety","authors":["Alice"],"industryIdentifiers":[{"type":"ISBN_13","identifier":"123"}]}}]},
            {"items":[{"question_id":1,"title":"Q &amp; A","body":"<p>Question</p>","accepted_answer_id":2,"score":5,"link":"https://stackoverflow.com/questions/1"}],"quota_remaining":99},
            {"items":[{"answer_id":2,"question_id":1,"body":"<p>Answer <code>42</code></p><pre>if x:\n    y()</pre>","score":10,"is_accepted":True}],"quota_remaining":98}]
    async def download(provider,url):
        urls.append(url);return json.dumps(bodies.pop(0))
    monkeypatch.setattr(public_apis,"_download",download)
    result=await public_apis.search("books",query="Rust")
    assert result["results"][0]["title"] == "Rust & Safety"
    result=await public_apis.search("stackexchange",query="Rust")
    assert result["error"] is None and result["answers_complete"]
    assert result["results"][0]["accepted_answer"]["body"].startswith("Answer 42")
    assert result["results"][0]["accepted_answer"]["code_blocks"] == ["if x:\n    y()"]
    assert result["quota_remaining"] == 98
    assert urls[2].startswith("https://api.stackexchange.com/2.3/answers/2?")

@pytest.mark.asyncio
async def test_weather_geocoding_and_validation(monkeypatch):
    urls=[]
    bodies=[{"results":[{"name":"Yangon","country":"Myanmar","latitude":16.8,"longitude":96.1},{"name":"Other","latitude":1,"longitude":2}]},
            {"latitude":16.8,"longitude":96.1,"timezone":"Asia/Yangon","current":{"temperature_2m":30},"current_units":{"temperature_2m":"C"},"daily":{"time":["2026-10-30"]},"daily_units":{"time":"iso8601"}}]
    async def download(provider,url):
        urls.append(url);return json.dumps(bodies.pop(0))
    monkeypatch.setattr(public_apis,"_download",download)
    result=await public_apis.search("weather",location="Yangon",forecast_days=3,units="metric")
    assert result["error"] is None and result["location"]["name"] == "Yangon"
    assert len(result["alternatives"]) == 1
    assert result["timezone"] == "Asia/Yangon"
    assert urls[0].startswith("https://geocoding-api.open-meteo.com/")
    assert urls[1].startswith("https://api.open-meteo.com/v1/forecast?")
    assert (await public_apis.search("weather",latitude=100,longitude=2))["error"]
    assert (await public_apis.search("weather",location="Yangon",forecast_days=8))["error"]
    assert len(urls) == 2

@pytest.mark.asyncio
async def test_provider_backoff_and_errors(monkeypatch):
    calls=[]
    async def download(provider,url):
        calls.append(url)
        return json.dumps({"items":[{"accepted_answer_id":2}],"backoff":10})
    monkeypatch.setattr(public_apis,"_download",download)
    result=await public_apis.search("stackexchange",query="Rust")
    assert result["backoff"] == 10 and not result["answers_complete"]
    assert len(calls) == 1
    async def failed(provider,url):
        return '{"error":{"message":"quota exceeded"}}'
    monkeypatch.setattr(public_apis,"_download",failed)
    assert "quota exceeded" in (await public_apis.search("books",query="Rust"))["error"]

@pytest.mark.asyncio
async def test_budget_cache_and_permissions(tmp_path,monkeypatch):
    monkeypatch.setenv("WT_CACHE_PATH",str(tmp_path/"cache.db"))
    ts=Toolset.from_env()
    calls=[]
    async def search(provider,**kwargs):
        calls.append(provider);await asyncio.sleep(0)
        return {"results":[{"url":"https://books.google.com/books?id=1"}],"error":None}
    monkeypatch.setattr(public_apis,"search",search)
    result=await ts.books_search(query="Rust",session_id="a")
    assert not result["cached"]
    assert (await ts.books_search(query="Rust",session_id="b"))["cached"]
    assert ts.urls.is_known("b","https://books.google.com/books?id=1")
    monkeypatch.setenv("HIRARA_ALLOWED_TOOLS","web_search")
    assert (await ts.books_search(query="Rust",session_id="b"))["error"]
    assert len(calls)==1
