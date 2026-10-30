import pytest

pytest.importorskip("hirara_native")


def test_local_sdk_native_and_discovery(tmp_path, monkeypatch):
    from hirara.client import Client
    from hirarafs import tools as fs
    from hirarafs.config import FsConfig
    monkeypatch.setattr(fs,"_local_toolset",fs.Toolset(FsConfig(roots=(str(tmp_path),))))
    client=Client(local=True)
    assert client.json_query({"a":[1,2]},"a[0]")["result"] == 1
    source=tmp_path/"source";source.write_text("hello")
    assert client.file_copy(str(source),str(tmp_path/"copy"))["bytes_copied"] == 5
    assert client.file_rename(str(tmp_path/"copy"),"renamed")["moved"]
    assert client.file_delete(str(tmp_path/"renamed"))["deleted"]
    names={tool["name"] for tool in client.tools()}
    assert {"file_copy","file_move","file_rename","file_delete","json_query","arxiv_search","pubmed_search"} <= names
