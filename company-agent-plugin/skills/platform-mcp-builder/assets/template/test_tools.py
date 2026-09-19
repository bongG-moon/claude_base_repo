"""합성 입력의 실제 MCP/HTTP 시험. 업무 도구 변경 시 기대 결과도 추가하세요.

In-process ASGI transport: no port, network, Claude registration or external API.
This is not an enterprise deployment or authentication test.
"""
import asyncio
from datetime import datetime, timedelta
import json
import unittest

# Check the approved SDK range before importing its version-specific client API.
from local_server import create_app

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from config import cfg


class ToolContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_mcp_round_trip(self):
        app = create_app()

        async with asyncio.timeout(15), app.router.lifespan_context(app):
            async with (
                httpx.AsyncClient(transport=httpx.ASGITransport(app=app), timeout=5, trust_env=False) as client,
                streamable_http_client("http://127.0.0.1:8765/mcp", http_client=client) as (read, write, _),
                ClientSession(read, write, read_timeout_seconds=timedelta(seconds=5)) as session,
            ):
                await session.initialize()
                listing = await session.list_tools()
                tools = {tool.name: tool for tool in listing.tools}
                self.assertTrue({"echo", "get_server_info", "get_current_time"} <= tools.keys())
                self.assertEqual(tools["echo"].inputSchema["properties"]["message"]["type"], "string")
                self.assertIn("message", tools["echo"].inputSchema["required"])
                message = '한글 연결 시험: "따옴표"\n다음 줄'
                result = await session.call_tool("echo", {"message": message})
                self.assertFalse(result.isError)
                self.assertEqual(result.content[0].text, message)
                for arguments in ({}, {"message": 123}, {"message": "가" * 4097}):
                    result = await session.call_tool("echo", arguments)
                    self.assertTrue(result.isError)
                result = await session.call_tool("get_server_info", {})
                self.assertFalse(result.isError)
                self.assertEqual(json.loads(result.content[0].text)["name"], cfg.SERVICE_NAME)
                result = await session.call_tool("get_current_time", {})
                self.assertFalse(result.isError)
                payload = json.loads(result.content[0].text)
                self.assertEqual(payload["timezone"], "UTC")
                self.assertEqual(datetime.fromisoformat(payload["current_time"]).utcoffset(), timedelta(0))

    async def test_http_boundaries(self):
        app = create_app()
        async with asyncio.timeout(10), app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://127.0.0.1:8765", trust_env=False) as client:
                health = await client.get("/health")
                self.assertEqual(health.status_code, 200)
                self.assertEqual(health.json(), {"status": "healthy", "transport": "streamable-http"})
                self.assertEqual((await client.get("/mcp-other")).status_code, 404)
                self.assertEqual((await client.post("/mcp", json={}, headers={"Host": "untrusted.example"})).status_code, 421)
                self.assertEqual((await client.post("/mcp", json={}, headers={"Origin": "https://untrusted.example"})).status_code, 403)


if __name__ == "__main__":
    unittest.main()
