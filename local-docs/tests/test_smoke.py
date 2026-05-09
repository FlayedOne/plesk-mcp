"""Smoke tests for the local-docs MCP server.

Requires `OPENAI_API_KEY` and network access to download/refresh the
ChromaDB knowledge base. The first run can take a while (download + warm-up).

Run with:

    OPENAI_API_KEY=sk-... uv run pytest -m smoke tests/test_smoke.py
"""

import os
import sys
from collections.abc import AsyncIterator, Sequence

from fastmcp import Client
from fastmcp.client.sampling import RequestContext, SamplingMessage, SamplingParams
from mcp.types import TextContent

import pytest
from plesk_local_docs_mcp import server as srv

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="OPENAI_API_KEY not set"),
]


def _text(content: Sequence[object]) -> str:
    block = content[0]
    assert isinstance(block, TextContent)
    return block.text


async def _passthrough(messages: list[SamplingMessage], _params: SamplingParams, _ctx: RequestContext) -> str:
    # Skip the LLM round-trip. Just echo the entire sampling input. The last user message will contain the original query.
    return "\n".join(msg.content.text for msg in messages if isinstance(msg.content, TextContent))


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    sys.argv = ["plesk-local-docs-mcp"]
    srv.args = srv.parse_args()
    async with Client(srv.mcp, sampling_handler=_passthrough) as c:
        yield c


async def test_real_query(client: Client) -> None:
    result = await client.call_tool(
        "query",
        {"query": "How do I restart Plesk services?"},
    )
    text = _text(result.content)
    print(text)
    # The passthrough handler echoes the prepared "Question" message, which always includes the original query.
    assert "restart Plesk services" in text
    # Should be a comprehensive answer, not just the query repeated.
    assert len(text) > 100
