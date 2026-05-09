"""Smoke tests exercising a real Plesk instance.

Run with (example with a Plesk Docker image):

    PLESK_HOST=https://localhost:8443 PLESK_PASSWORD=changeme1Q** \\
        uv run pytest -m smoke tests/test_smoke.py

These tests require a reachable Plesk server with valid credentials configured
via the `PLESK_*` environment variables.
Works with both Linux and Windows Plesk servers.
"""

import os
import sys
import warnings
from collections.abc import AsyncIterator, Sequence

from async_lru import AlruCacheLoopResetWarning
from fastmcp import Client
from mcp.types import TextContent

import pytest
from plesk_mcp.server import create_mcp_server, parse_args

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(not os.environ.get("PLESK_HOST"), reason="PLESK_HOST not set"),
]


def _text(content: Sequence[object]) -> str:
    block = content[0]
    assert isinstance(block, TextContent)
    return block.text


@pytest.fixture
async def client() -> AsyncIterator[Client]:
    # Suppress alru_cache loop reset warning in tests. It is caused by test isolation in separate event loops.
    warnings.filterwarnings("ignore", category=AlruCacheLoopResetWarning)
    # parse_args reads sys.argv; trim it down to a benign invocation.
    sys.argv = ["plesk-mcp"] + (["--insecure"] if os.environ.get("PLESK_INSECURE") else [])
    mcp = await create_mcp_server(parse_args())
    async with Client(mcp) as c:
        yield c


async def test_api_list_tags_returns_real_tags(client: Client) -> None:
    result = await client.call_tool("api_list_tags", {})
    assert "Available tags" in _text(result.content)


async def test_api_list_returns_some_apis(client: Client) -> None:
    result = await client.call_tool("api_list", {})
    assert "###" in _text(result.content)  # markdown headers for each API


async def test_api_help_returns_usage(client: Client) -> None:
    result = await client.call_tool("api_help", {"name": "Get_server_information"})
    assert "Retrieve server metadata" in _text(result.content)


async def test_api_call_returns_expected_data(client: Client) -> None:
    result = await client.call_tool("api_call", {"name": "Get_server_information", "params": {}})
    assert "platform" in _text(result.content)
    assert result.structured_content
    assert "platform" in result.structured_content


async def test_upload_returns_file_path(client: Client) -> None:
    result = await client.call_tool("upload", {"content": "Hello, world!"})
    # Returns a file path, typically under '/opt/psa/tmp/', '/usr/local/psa/tmp/', or 'C:/Program Files (x86)/Plesk/PrivateTemp/'
    assert _text(result.content)


async def test_exec_returns_command_output(client: Client) -> None:
    result = await client.call_tool("exec", {"command": ["ping"]})
    assert result.structured_content
    assert result.structured_content.keys() == {"code", "stdout", "stderr"}
    assert isinstance(result.structured_content["code"], int)
    assert isinstance(result.structured_content["stdout"], str)
    assert isinstance(result.structured_content["stderr"], str)
    # Either stdout or stderr contains help or an error message with "ping" in it
    assert "ping" in _text(result.content)
