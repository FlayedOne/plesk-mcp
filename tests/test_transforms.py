"""Tests for `plesk_mcp.transforms.ApiListTransform`."""

from collections.abc import AsyncIterator, Sequence

from fastmcp import Client, FastMCP
from mcp.types import TextContent

import pytest
from plesk_mcp.transforms import ApiListTransform


def _text(content: Sequence[object]) -> str:
    """Extract text from the first content block, asserting it's a `TextContent`."""
    block = content[0]
    assert isinstance(block, TextContent)
    return block.text


@pytest.fixture
def mcp() -> FastMCP:
    """Build a small FastMCP server with the `ApiListTransform` applied."""
    server: FastMCP = FastMCP(
        name="Test",
        transforms=[ApiListTransform(name="Test", always_visible=["pinned"])],
    )

    @server.tool(tags={"alpha"})
    def first(x: int) -> int:
        """First tool."""
        return x + 1

    @server.tool(tags={"beta"})
    def second(x: int) -> int:
        """Second tool."""
        return x * 2

    @server.tool
    def pinned(x: int) -> int:
        """Always visible."""
        return x

    return server


@pytest.fixture
async def client(mcp: FastMCP) -> AsyncIterator[Client]:
    """In-memory client connected to the test server."""
    async with Client(mcp) as c:
        yield c


async def test_synthetic_tools_replace_originals(client: Client) -> None:
    names = {t.name for t in await client.list_tools()}
    assert {"api_call", "api_list", "api_list_tags", "api_help", "pinned"} == names


async def test_list_tags_returns_unique_sorted_tags(client: Client) -> None:
    result = await client.call_tool("api_list_tags", {})
    text = _text(result.content)
    assert "alpha" in text
    assert "beta" in text
    assert text.index("alpha") < text.index("beta")


async def test_list_filters_by_tag(client: Client) -> None:
    result = await client.call_tool("api_list", {"tags": ["alpha"]})
    text = _text(result.content)
    assert "first" in text
    assert "second" not in text


async def test_list_without_tags_lists_all_non_pinned(client: Client) -> None:
    result = await client.call_tool("api_list", {})
    text = _text(result.content)
    assert "first" in text
    assert "second" in text
    assert "pinned" not in text  # pinned is not transformed


async def test_help_describes_an_existing_tool(client: Client) -> None:
    result = await client.call_tool("api_help", {"name": "first"})
    assert "first" in _text(result.content)


async def test_help_for_unknown_tool(client: Client) -> None:
    result = await client.call_tool("api_help", {"name": "nonexistent"})
    assert "No API found" in _text(result.content)


async def test_call_executes_underlying_tool(client: Client) -> None:
    result = await client.call_tool("api_call", {"name": "first", "params": {"x": 41}})
    assert _text(result.content) == "42"


@pytest.mark.parametrize("tool", ["api_call", "api_help"])
async def test_synthetic_names_are_rejected(client: Client, tool: str) -> None:
    params: dict[str, object] = {"name": "api_list"}
    if tool == "api_call":
        params["params"] = {}
    with pytest.raises(Exception, match="reserved"):
        await client.call_tool(tool, params)
