import httpx
import os
from pathlib import Path
import pytest
from hirarafs.config import FsConfig
from hirarafs.documents import DocumentConfig
from hirarafs.tools import Toolset

pytest.importorskip("hirara_native")

@pytest.fixture
def ts(tmp_path,tiny_model):
    return Toolset(FsConfig(roots=(str(tmp_path),),allow_any_path=False),DocumentConfig(collections={"notes":str(tmp_path/"index")},models_dir=str(tiny_model)))

@pytest.mark.asyncio
async def test_semantic_lifecycle_and_filter(ts):
    try:
        assert (await ts.document_index(collection="notes",text="automobile",doc_id="a",metadata={"topic":"cars"}))["error"] is None
        if os.name == "posix":
            assert Path(ts.document_config.collections["notes"]).stat().st_mode & 0o077 == 0
        assert (await ts.document_index(collection="notes",text="banana",doc_id="b",metadata={"topic":"food"}))["chunks"] == 1
        result=await ts.document_search(collection="notes",query="car")
        assert result["error"] is None and result["results"][0]["doc_id"] == "a"
        assert result["results"][0]["text"] == "automobile"  # dense match without lexical overlap
        assert (await ts.document_search(collection="notes",query="car",filter={"topic":"food"}))["results"][0]["doc_id"] == "b"
        assert (await ts.document_search(collection="notes",query="car",filter={"topic":[]}))["results"] == []
        await ts.close()
        assert (await ts.document_search(collection="notes",query="car"))["results"][0]["doc_id"] == "a"
        await ts.document_index(collection="notes",text="banana",doc_id="a",metadata={"topic":"food"})
        assert (await ts.document_search(collection="notes",query="car",filter={"topic":"cars"}))["results"] == []
        assert (await ts.document_remove(collection="notes",doc_id="a"))["removed_chunks"] == 1
        assert (await ts.document_remove(collection="notes",doc_id="missing"))["removed_chunks"] == 0
    finally:
        await ts.close()

@pytest.mark.asyncio
async def test_root_policy_metadata_and_limits(ts,tmp_path,monkeypatch):
    path=tmp_path/"note.md";path.write_text("automobile")
    try:
        assert (await ts.document_index(collection="notes",path=str(path)))["doc_id"] == str(path)
        hit=(await ts.document_search(collection="notes",query="car"))["results"][0]
        assert hit["source"] == str(path) and hit["start"] == 0 and hit["end"] == len("automobile")
        assert not any(k.startswith("__hirara_") for k in hit["metadata"])
        assert (await ts.document_index(collection="notes",text="a"))["error"]
        assert (await ts.document_index(collection="notes",path=str(path),text="a",doc_id="bad"))["error"]
        assert (await ts.document_index(collection="notes",text="a",doc_id="bad",metadata={"__hirara_source":"fake"}))["error"]
        assert (await ts.document_search(collection="../../other",query="car"))["error"]
        assert (await ts.document_index(collection="notes",path="/etc/passwd"))["error"]
        monkeypatch.setenv("HIRARA_ALLOWED_TOOLS","file_read")
        assert (await ts.document_search(collection="notes",query="car"))["error"]
    finally:
        await ts.close()

@pytest.mark.asyncio
async def test_mutations_disabled_and_http(ts,monkeypatch):
    from hirarafs import service
    try:
        readonly=Toolset(ts.config,DocumentConfig(collections=ts.document_config.collections,models_dir=ts.document_config.models_dir,allow_write=False))
        assert (await readonly.document_index(collection="notes",text="car",doc_id="a"))["error"]
        monkeypatch.setattr(service,"_toolset",ts)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=service.app),base_url="http://test") as client:
            result=await client.post("/document_index",json={"collection":"notes","text":"automobile","doc_id":"a"})
            assert result.json()["error"] is None
            result=await client.post("/document_search",json={"collection":"notes","query":"car"})
            assert result.json()["results"][0]["doc_id"] == "a"
    finally:
        await ts.close()


def test_invalid_admin_config(monkeypatch):
    monkeypatch.setenv("CRAG_COLLECTIONS",'{"../bad":"/tmp/a"}')
    with pytest.raises(ValueError): DocumentConfig.from_env()

@pytest.mark.asyncio
async def test_pdf_source_citation(ts,tmp_path):
    pytest.importorskip("pypdfium2_raw")
    def stream(text):
        data=f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        return b"<< /Length "+str(len(data)).encode()+b" >>\nstream\n"+data+b"\nendstream"
    objects=[b"<< /Type /Catalog /Pages 2 0 R >>",b"<< /Type /Pages /Kids [3 0 R 5 0 R] /Count 2 >>",b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R >> >> /Contents 4 0 R >>",stream("banana tropical fruit"),b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 7 0 R >> >> /Contents 6 0 R >>",stream("automobile road vehicle"),b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    data=b"%PDF-1.4\n";offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data));data+=f"{i} 0 obj\n".encode()+obj+b"\nendobj\n"
    start=len(data)
    data+=f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode()
    data+=b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets[1:])
    data+=f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()
    path=tmp_path/"paper.pdf";path.write_bytes(data)
    try:
        result=await ts.document_index(collection="notes",path=str(path))
        assert result["error"] is None,result
        result=await ts.document_search(collection="notes",query="car")
        assert result["results"][0]["page"] == 1
        assert result["results"][0]["page_end"] == 2
        assert result["results"][0]["source"] == str(path)
        assert "automobile" in result["results"][0]["text"]
    finally:
        await ts.close()
