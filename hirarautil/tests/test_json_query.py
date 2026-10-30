import pytest
from hirarautil.config import UtilConfig
from hirarautil.tools import Toolset

pytest.importorskip("hirara_native")

@pytest.mark.asyncio
async def test_query_languages():
    ts = Toolset(UtilConfig())
    doc = {"items": [{"name": "a", "price": 2}, {"name": "b", "price": 9}], "a/b": None}
    assert (await ts.json_query(input=doc, expression="items[?price > `3`].name"))["result"] == ["b"]
    assert (await ts.json_query(input='{"a/b": 5}', expression="/a~1b", syntax="pointer"))["result"] == 5
    assert (await ts.json_query(input=doc, expression="/a~1b", syntax="pointer"))["error"] is None
    assert (await ts.json_query(input=doc, expression="/missing", syntax="pointer"))["error"]
    assert (await ts.json_query(input=doc, expression="items["))["error"]
    assert (await ts.json_query(input="bad json", expression="@"))["error"]
    assert (await ts.json_query(input=float("nan"), expression="@"))["error"]

@pytest.mark.asyncio
async def test_limits_and_policy(monkeypatch):
    assert (await Toolset(UtilConfig(max_input_chars=5)).json_query(input={"too": "long"}, expression="@"))["error"]
    assert (await Toolset(UtilConfig(max_output_bytes=2)).json_query(input={"big": 123}, expression="@"))["error"]
    monkeypatch.setenv("HIRARA_ALLOWED_TOOLS", "")
    assert (await Toolset(UtilConfig()).json_query(input={}, expression="@"))["error"]
