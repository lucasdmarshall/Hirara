import httpx
import pytest
from hirarafs.config import FsConfig
from hirarafs.tools import Toolset

pytest.importorskip("hirara_native")

@pytest.mark.asyncio
async def test_http_permissions_and_native_result(tmp_path, monkeypatch):
    from hirarafs import service
    monkeypatch.setattr(service, "_toolset", Toolset(FsConfig(roots=(str(tmp_path),))))
    monkeypatch.setenv("HIRARA_BACKEND_TOKEN", "test-token")
    source=tmp_path/"a"; source.write_text("data")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service.app),base_url="http://test") as client:
        body={"path":str(source),"dest":str(tmp_path/"b")}
        assert (await client.post("/file_copy",json=body)).status_code == 401
        result=await client.post("/file_copy",json=body,headers={"Authorization":"Bearer test-token"})
        assert result.status_code == 200 and result.json()["bytes_copied"] == 4
        invalid=await client.post("/file_copy",json={},headers={"Authorization":"Bearer test-token"})
        assert invalid.status_code == 422 and invalid.json()["error"]
        monkeypatch.setenv("HIRARA_ALLOWED_TOOLS", "file_read")
        denied=await client.post("/file_delete",json={"path":str(source)},headers={"Authorization":"Bearer test-token"})
        assert denied.json()["error"] and source.exists()
