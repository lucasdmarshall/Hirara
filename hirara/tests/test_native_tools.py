import pytest

pytest.importorskip("hirara_native")


def test_local_sdk_native_and_discovery(tmp_path, monkeypatch):
    from hirara.client import Client
    from hirarafs import tools as fs
    from hirarafs.config import FsConfig
    monkeypatch.setattr(fs,"_local_toolset",fs.Toolset(FsConfig(roots=(str(tmp_path),))))
    client=Client(local=True)
    assert client.symbolic_math("evaluate", "sin(pi/2)")["value"] == 1.0
    assert client.json_query({"a":[1,2]},"a[0]")["result"] == 1
    source=tmp_path/"source";source.write_text("hello")
    assert client.file_copy(str(source),str(tmp_path/"copy"))["bytes_copied"] == 5
    assert client.file_rename(str(tmp_path/"copy"),"renamed")["moved"]
    assert client.file_delete(str(tmp_path/"renamed"))["deleted"]
    names={tool["name"] for tool in client.tools()}
    assert {"file_copy","file_move","file_rename","file_delete","json_query","arxiv_search","pubmed_search", "document_index", "document_search", "document_remove", "stackexchange_search", "books_search", "weather", "symbolic_math"} <= names


def test_new_remote_helpers_match_advertised_schemas():
    import json
    import httpx
    import jsonschema
    from hirara.client import Client
    from hirarafs.tools import DOCUMENT_INDEX_SCHEMA, DOCUMENT_SEARCH_SCHEMA
    from hirarautil.tools import SYMBOLIC_MATH_SCHEMA
    from hiraraweb.tools import WEATHER_SCHEMA
    schemas={s["name"]:s["input_schema"] for s in [DOCUMENT_INDEX_SCHEMA,DOCUMENT_SEARCH_SCHEMA,SYMBOLIC_MATH_SCHEMA,WEATHER_SCHEMA]}
    captured=[]
    def handler(request):
        body=json.loads(request.content)
        jsonschema.validate(body["arguments"],schemas[body["name"]])
        captured.append(body)
        return httpx.Response(200,json={"error":None})
    client=Client("http://hub.local",local=False)
    with httpx.Client(transport=httpx.MockTransport(handler),base_url="http://hub.local") as http:
        client._client=http
        client.document_index(text="automobile",doc_id="a")
        client.document_index("/data/file.md")
        client.document_search("car")
        client.symbolic_math("evaluate","1+1")
        client.weather(latitude=16.8,longitude=96.1)
        client.weather("Yangon")
    assert len(captured)==6
    assert all(value is not None for call in captured for value in call["arguments"].values())
