import os
import sys
import json
import pytest

pytestmark = pytest.mark.skipif(os.getenv("HIRARA_NATIVE_INTEGRATION") != "1", reason="native MCP integration opt-in")

@pytest.mark.asyncio
@pytest.mark.parametrize("module,names", [
    ("hirarafs.mcp_server",{"file_copy","file_move","file_rename","file_delete"}),
    ("hirarautil.mcp_server",{"json_query"}),
    ("hiraraweb.mcp_server",{"arxiv_search","pubmed_search"}),
])
async def test_native_stdio(module,names,tmp_path):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    env=dict(os.environ,CFS_ROOTS=str(tmp_path),CFS_ALLOW_ANY_PATH="false",WT_CACHE_PATH=str(tmp_path/"cache.db"))
    env.pop("HIRARA_ALLOWED_TOOLS",None)
    params=StdioServerParameters(command=sys.executable,args=["-m",module],env=env)
    async with stdio_client(params) as (read,write), ClientSession(read,write) as session:
        await session.initialize()
        listed=await session.list_tools()
        assert names <= {t.name for t in listed.tools}
        if module.startswith("hirarautil"):
            result=await session.call_tool("json_query",{"input":{"a":1},"expression":"a"})
            assert not result.is_error
            assert json.loads(result.content[0].text)["result"] == 1
        elif module.startswith("hirarafs"):
            path=tmp_path/"a";path.write_text("data")
            result=await session.call_tool("file_copy",{"path":str(path),"dest":str(tmp_path/"b")})
            assert not result.is_error
            assert json.loads(result.content[0].text)["bytes_copied"] == 4
            result=await session.call_tool("file_delete",{"path":str(tmp_path)})
            assert result.is_error
        else:
            result=await session.call_tool("arxiv_search",{"query":""})
            assert result.is_error
