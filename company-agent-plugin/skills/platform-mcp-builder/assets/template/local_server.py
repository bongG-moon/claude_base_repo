"""로컬 시험 전용: 127.0.0.1의 /health 및 /mcp. 전사에 제출하지 않음."""
from __future__ import annotations

import argparse
import contextlib
from importlib.metadata import PackageNotFoundError, version

try:
    sdk_version = tuple(int(part) for part in version("mcp").split(".")[:2])
    if not (sdk_version[0] == 1 and sdk_version >= (1, 28)):
        raise RuntimeError("제공된 로컬 시험은 mcp>=1.28,<2가 필요합니다. 환경을 자동 변경하지 않습니다.")
except PackageNotFoundError as exc:
    raise RuntimeError("승인된 Python 환경에 MCP SDK 1.x를 준비해야 합니다.") from exc

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from config import cfg
from src.mcp.tools import register_tools


class MCPMiddleware:
    def __init__(self, app, mcp_asgi):
        self.app, self.mcp_asgi = app, mcp_asgi

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] in {"http", "websocket"} and (path == "/mcp" or path.startswith("/mcp/")):
            await self.mcp_asgi(scope, receive, send)
        else:
            await self.app(scope, receive, send)


async def health_check(request):
    return JSONResponse({"status": "healthy", "transport": "streamable-http"})


def create_app():
    server = FastMCP(
        name=cfg.MCP_SERVER_NAME,
        stateless_http=True,
        log_level="WARNING",
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*"],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
        ),
    )
    register_tools(server)
    mcp_asgi = server.streamable_http_app()

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with server.session_manager.run():
            yield

    app = Starlette(routes=[Route("/health", health_check)], lifespan=lifespan)
    app.add_middleware(MCPMiddleware, mcp_asgi=mcp_asgi)
    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("시험 포트는 1024~65535 중 선택하세요.")
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=args.port, access_log=False)


if __name__ == "__main__":
    main()
