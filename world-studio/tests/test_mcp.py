import asyncio
import json
import os
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_real_stdio_client(tmp_path):
    async def scenario():
        plugin = Path(__file__).resolve().parents[1]
        config = json.loads((plugin / ".mcp.json").read_text())["mcpServers"]["world-studio"]
        params = StdioServerParameters(command=config["command"], args=config["args"],
            cwd=str(plugin / config["cwd"]), env={**os.environ, "WORLD_STUDIO_DATA": str(tmp_path)})
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                listing = await client.list_tools()
                names = {tool.name for tool in listing.tools}
                assert {"world_create", "world_commit", "scene_context", "atlas_save_draft", "work_export"} <= names
                created = await client.call_tool("world_create", {"world": "mcp_world", "name": "协议测试"})
                assert not created.isError
                result = await client.call_tool("world_read", {"world": "mcp_world"})
                assert not result.isError
                assert "revision" in result.structuredContent
                failed = await client.call_tool("world_commit", {"proposal": "missing", "decision": ""})
                assert failed.isError
                source = await client.call_tool("source_import", {"world": "mcp_world", "name": "资料.md", "text": "假设十二席。"})
                assert not source.isError
    asyncio.run(scenario())
