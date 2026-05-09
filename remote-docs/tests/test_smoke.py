"""Smoke tests hitting the real remote knowledge-base service.

Run with:

    uv run pytest -m smoke tests/test_smoke.py

You may set `PLESK_COPILOT_API_BASE_URL` and `PLESK_COPILOT_AUTH_TOKEN` to override the defaults.
"""

import sys
from collections.abc import AsyncIterator, Sequence

from fastmcp import Client
from mcp.types import TextContent

import pytest
from plesk_remote_docs_mcp import server as srv

pytestmark = pytest.mark.smoke


def _text(content: Sequence[object]) -> str:
    block = content[0]
    assert isinstance(block, TextContent)
    return block.text


@pytest.fixture
async def mcp_client() -> AsyncIterator[Client]:
    sys.argv = ["plesk-remote-docs-mcp"]
    args = srv.parse_args()
    srv.api_client.set(srv.create_api_client(args))
    async with Client(srv.mcp) as c:
        yield c


async def test_real_query_returns_an_answer(mcp_client: Client) -> None:
    result = await mcp_client.call_tool("query", {"query": "How do I restart Plesk services?"})
    answer = _text(result.content).strip()
    print(answer)
    assert answer
    assert "restart" in answer.lower()
