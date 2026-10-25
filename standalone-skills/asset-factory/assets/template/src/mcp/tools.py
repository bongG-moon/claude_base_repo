"""전사 제출 대상: 이 파일의 register_tools 안에 업무 도구를 구현합니다."""
import json
import logging
from datetime import datetime, timezone

from mcp.server.fastmcp import FastMCP

from config import cfg

logger = logging.getLogger(__name__)


def register_tools(mcp: FastMCP) -> None:
    """Register tools on the platform-provided MCP server."""

    @mcp.tool()
    async def echo(message: str) -> str:
        """연결 시험: 4096자 이내의 합성 문자열을 그대로 돌려줍니다."""
        if len(message) > 4096:
            raise ValueError("message는 4096자 이내여야 합니다.")
        # Do not log the message: it may contain private business data.
        return message

    @mcp.tool()
    async def get_server_info() -> str:
        """서버의 공개 이름과 도구 통신 방식을 JSON 문자열로 반환합니다."""
        return json.dumps(
            {"name": cfg.SERVICE_NAME, "version": "1.0.0",
             "transport": "streamable-http", "capabilities": ["tools"]},
            ensure_ascii=False,
        )

    @mcp.tool()
    async def get_current_time() -> str:
        """현재 UTC 시각을 ISO 8601 형식의 JSON 문자열로 반환합니다."""
        return json.dumps(
            {"current_time": datetime.now(timezone.utc).isoformat(), "timezone": "UTC"},
            ensure_ascii=False,
        )
