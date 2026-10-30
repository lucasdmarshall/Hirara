import httpx
import pytest

pytest.importorskip("hirara_native")

@pytest.mark.asyncio
async def test_http_json_query_and_schema(monkeypatch):
    from hirarautil import service
    monkeypatch.delenv("HIRARA_BACKEND_TOKEN", raising=False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service.app),base_url="http://test") as client:
        response=await client.post("/json_query",json={"input":{"a":[1,2]},"expression":"a[1]"})
        assert response.status_code == 200 and response.json()["result"] == 2
        assert "json_query" in {s["name"] for s in (await client.get("/schemas")).json()["tools"]}
