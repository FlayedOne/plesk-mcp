"""Tests for the local-docs MCP `query` tool.

The query tool needs:
- A ChromaDB collection (we patch `get_db` to return a stub returning fake hits).
- An MCP `ctx.sample(...)` call (we provide a sampling handler on the client).

We don't touch ChromaDB or the network here.
"""

import argparse
from collections.abc import Sequence
from typing import Any
from unittest.mock import MagicMock

from fastmcp import Client
from fastmcp.client.sampling import RequestContext, SamplingMessage, SamplingParams
from mcp.types import TextContent

import pytest
from plesk_local_docs_mcp import server as srv


def _text(content: Sequence[object]) -> str:
    block = content[0]
    assert isinstance(block, TextContent)
    return block.text


def _fake_query_response(documents: list[str], metadatas: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Shape that ChromaDB's `Collection.query` returns."""
    return {
        "ids": [[f"id-{i}" for i in range(len(documents))]],
        "documents": [documents],
        "metadatas": [metadatas or [{"_node_content": '{"metadata": {"source": "doc"}}'} for _ in documents]],
        "distances": [[0.1 * (i + 1) for i in range(len(documents))]],
    }


@pytest.fixture
def fake_collection() -> MagicMock:
    coll = MagicMock()
    coll.query.return_value = _fake_query_response(["Doc body 0", "Doc body 1"])
    return coll


@pytest.fixture
def patch_db(monkeypatch: pytest.MonkeyPatch, fake_collection: MagicMock) -> MagicMock:
    async def fake_get_db(_opts: object) -> MagicMock:
        return fake_collection

    monkeypatch.setattr(srv, "get_db", fake_get_db)
    # The query tool reads global `args` for `top_k`; ensure it's set.
    srv.args = argparse.Namespace(top_k=3)
    return fake_collection


async def _no_sampling_handler(*_args: object, **_kwargs: object) -> str:
    raise RuntimeError("sampling unavailable")


async def _ok_sampling_handler(messages: list[SamplingMessage], params: SamplingParams, context: RequestContext) -> str:
    # Return a deterministic answer that mentions a unique marker so we can assert it.
    return "ANSWER: " + (params.systemPrompt or "")[:5]


class TestQueryTool:
    async def test_returns_sampled_answer(self, patch_db: MagicMock) -> None:
        async with Client(srv.mcp, sampling_handler=_ok_sampling_handler) as c:
            result = await c.call_tool("query", {"query": "How to restart Plesk?"})
        assert _text(result.content).startswith("ANSWER:")

    async def test_falls_back_to_raw_context_when_sampling_fails(self, patch_db: MagicMock) -> None:
        async with Client(srv.mcp, sampling_handler=_no_sampling_handler) as c:
            result = await c.call_tool("query", {"query": "How to restart Plesk?"})
        text = _text(result.content)
        assert "Doc body 0" in text
        assert "Doc body 1" in text
        assert "Context item id-0" in text
        assert "Context item id-1" in text

    async def test_no_results_raises(self, monkeypatch: pytest.MonkeyPatch, patch_db: MagicMock) -> None:
        patch_db.query.return_value = _fake_query_response([])
        async with Client(srv.mcp, sampling_handler=_ok_sampling_handler) as c:
            with pytest.raises(Exception, match="No results"):
                await c.call_tool("query", {"query": "no matches"})

    async def test_os_name_is_passed_as_platform_filter(self, patch_db: MagicMock) -> None:
        async with Client(srv.mcp, sampling_handler=_ok_sampling_handler) as c:
            await c.call_tool(
                "query",
                {"query": "anything", "os_name": "Microsoft Windows"},
            )
        # Inspect the kwargs Chroma was queried with.
        kwargs = patch_db.query.call_args.kwargs
        assert kwargs["where"] == {"Platform": {"$in": ["windows", "any"]}}

    async def test_no_os_name_means_no_filter(self, patch_db: MagicMock) -> None:
        async with Client(srv.mcp, sampling_handler=_ok_sampling_handler) as c:
            await c.call_tool("query", {"query": "anything"})
        assert patch_db.query.call_args.kwargs["where"] is None


class TestDerivePlatform:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Ubuntu", "linux"),
            ("CentOS", "linux"),
            ("Microsoft Windows", "windows"),
            ("WINDOWS Server", "windows"),
        ],
    )
    def test_derive_platform(self, name: str, expected: str) -> None:
        assert srv.derive_platform(name) == expected
