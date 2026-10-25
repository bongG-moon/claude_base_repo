"""로컬 시험 전용. 전사 config를 교체하거나 제출하지 마세요."""
from types import SimpleNamespace

# Only public, synthetic values. Real platform configuration is supplied there.
cfg = SimpleNamespace(
    SERVICE_NAME="로컬 MCP 개발 시험",
    MCP_SERVER_NAME="platform-mcp-local-test",
    MCP_SERVER_VERSION="1.0.0",
)
