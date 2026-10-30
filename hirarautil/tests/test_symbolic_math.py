import math
import pytest
from hirarautil.config import UtilConfig
from hirarautil.tools import Toolset

pytest.importorskip("hirara_native")

@pytest.mark.asyncio
async def test_math_operations():
    ts=Toolset(UtilConfig())
    assert (await ts.symbolic_math(operation="solve",expression="2*x + 4 = 0"))["solutions"] == [-2.0]
    assert (await ts.symbolic_math(operation="solve",expression="x^2 + 1 = 0"))["solutions"] == []
    result=await ts.symbolic_math(operation="differentiate",expression="x^3",order=2)
    assert result["error"] is None
    value=await ts.symbolic_math(operation="evaluate",expression=result["result"],variables={"x":2})
    assert value["value"] == 12.0
    result=await ts.symbolic_math(operation="evaluate",expression="sin(pi/2) + ln(e)")
    assert math.isclose(result["value"],2.0)
    assert (await ts.symbolic_math(operation="simplify",expression="2*x + 3*x"))["error"] is None

@pytest.mark.asyncio
async def test_math_rejects_unsupported_and_undefined(monkeypatch):
    ts=Toolset(UtilConfig())
    for expression in ["1/0","sqrt(-1)","missing + 1","__import__('os')","x^999999","-"*200+"1"]:
        assert (await ts.symbolic_math(operation="evaluate",expression=expression))["error"], expression
    assert (await ts.symbolic_math(operation="solve",expression="sin(x)=0"))["error"]
    monkeypatch.setenv("HIRARA_ALLOWED_TOOLS","")
    assert (await ts.symbolic_math(operation="evaluate",expression="1+1"))["error"]
