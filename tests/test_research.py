import json
import pytest
from hirara_core.download import DownloadResult
from hiraraweb import research
from hiraraweb.tools import Toolset

pytest.importorskip("hirara_native")

ATOM = """<feed xmlns="http://www.w3.org/2005/Atom" xmlns:os="http://a9.com/-/spec/opensearch/1.1/"><os:totalResults>1</os:totalResults><entry><id>http://arxiv.org/abs/1234.5678v1</id><title>A paper</title><summary>Abstract text</summary><author><name>Alice</name></author><published>2026-01-01</published></entry></feed>"""

@pytest.mark.asyncio
async def test_arxiv_guard_cache_and_provenance(tmp_path, monkeypatch):
    calls = []
    async def download(url, **kwargs):
        calls.append((url, kwargs))
        return DownloadResult(ATOM.encode(), url, 200, "application/atom+xml", False, [])
    monkeypatch.setattr(research, "safe_download", download)
    monkeypatch.setenv("WT_CACHE_PATH", str(tmp_path/"cache.db"))
    ts = Toolset.from_env()
    result = await ts.arxiv_search(query="ti:security & x", session_id="session")
    assert result["error"] is None
    assert result["results"][0]["authors"] == ["Alice"]
    assert result["total"] == 1
    assert ts.urls.is_known("session", "https://arxiv.org/abs/1234.5678v1")
    assert ts.urls.is_known("session", "https://arxiv.org/pdf/1234.5678v1")
    assert calls[0][0].startswith("https://export.arxiv.org/api/query?")
    assert calls[0][1]["allow_private_ips"] is False
    assert calls[0][1]["max_redirects"] == 0
    assert (await ts.arxiv_search(query="ti:security & x", session_id="second"))["cached"]
    assert len(calls) == 1
    assert (await ts.arxiv_search(query="q", max_results=0))["error"]
    monkeypatch.setenv("HIRARA_ALLOWED_TOOLS", "web_search")
    assert (await ts.arxiv_search(query="q"))["error"]
    assert len(calls) == 1

@pytest.mark.asyncio
async def test_pubmed_empty_failure_and_metadata(monkeypatch):
    bodies = [json.dumps({"esearchresult": {"count":"1", "idlist":["42"]}}), json.dumps({"result": {"uids":["42"], "42": {"title":"Study", "authors":[{"name":"Bob"}], "pubdate":"2026", "fulljournalname":"Journal", "articleids":[{"idtype":"doi", "value":"10.1/test"}]}}})]
    async def download(provider, url):
        return bodies.pop(0)
    monkeypatch.setattr(research, "_download", download)
    result = await research.search("pubmed", "test")
    assert result["error"] is None
    assert result["total"] == 1
    assert result["results"][0]["doi"] == "10.1/test"
    assert result["results"][0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/42/"
    assert "summary" not in result["results"][0]
    bodies.append('{"esearchresult":{"count":"0","idlist":[]}}')
    assert (await research.search("pubmed", "absent"))["results"] == []
    bodies.append("not json")
    assert (await research.search("pubmed", "bad"))["error"]

@pytest.mark.asyncio
async def test_truncation_and_network_failure(monkeypatch):
    async def truncated(url, **kwargs):
        return DownloadResult(b"x", url, 200, "text/plain", True, [])
    monkeypatch.setattr(research,"safe_download",truncated)
    assert "2 MB" in (await research.search("arxiv","q"))["error"]
