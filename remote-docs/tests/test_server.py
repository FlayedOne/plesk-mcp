"""Tests for `plesk_remote_docs_mcp.server`."""

import argparse
import sys
from collections.abc import AsyncIterator, Iterator, Sequence

import httpx
from fastmcp import Client
from mcp.types import TextContent

import pytest
import respx
from plesk_remote_docs_mcp import server as srv

ENDPOINT = "https://api.example.com"


def _text(content: Sequence[object]) -> str:
    block = content[0]
    assert isinstance(block, TextContent)
    return block.text


@pytest.fixture
def api_client() -> Iterator[httpx.AsyncClient]:
    """Bind a fresh httpx client for the duration of one test."""
    client = httpx.AsyncClient(base_url=ENDPOINT)
    token = srv.api_client.set(client)
    try:
        yield client
    finally:
        srv.api_client.reset(token)


@pytest.fixture
async def mcp_client(api_client: httpx.AsyncClient) -> AsyncIterator[Client]:
    """In-memory MCP client wired to the module's FastMCP instance."""
    async with Client(srv.mcp) as c:
        yield c


class TestBuildMetadata:
    def test_empty_when_no_inputs(self) -> None:
        assert srv.build_metadata(None, None, None) == {}

    def test_plesk_version_only(self) -> None:
        assert srv.build_metadata("18.0.76", None, None) == {"plesk_version": "18.0.76"}

    @pytest.mark.parametrize(
        ("os_name", "expected_platform"),
        [
            ("Ubuntu", "Unix"),
            ("CentOS", "Unix"),
            ("Microsoft Windows", "Windows"),
            ("WINDOWS Server", "Windows"),
        ],
    )
    def test_os_name_derives_platform(self, os_name: str, expected_platform: str) -> None:
        meta = srv.build_metadata(None, os_name, None)
        assert meta == {"os_name": os_name, "platform": expected_platform}

    def test_full_metadata(self) -> None:
        meta = srv.build_metadata("18.0.76", "Ubuntu", "22.04")
        assert meta == {
            "plesk_version": "18.0.76",
            "os_name": "Ubuntu",
            "platform": "Unix",
            "os_version": "22.04",
        }


class TestQueryTool:
    @respx.mock
    async def test_basic_query_posts_minimal_body(self, mcp_client: Client) -> None:
        route = respx.post(f"{ENDPOINT}/gen_answer").respond(200, json={"answer": "To restart Plesk, run `plesk restart`."})

        result = await mcp_client.call_tool("query", {"query": "How do I restart Plesk?"})

        assert "plesk restart" in _text(result.content)
        assert route.called
        sent = route.calls.last.request
        body = sent.read().decode()
        assert '"query":"How do I restart Plesk?"' in body
        assert '"product":"plesk"' in body
        assert "metadata" not in body

    @respx.mock
    async def test_query_with_full_context(self, mcp_client: Client) -> None:
        route = respx.post(f"{ENDPOINT}/gen_answer").respond(200, json={"answer": "Use the Plesk Installer."})

        await mcp_client.call_tool(
            "query",
            {
                "query": "How to upgrade Plesk?",
                "plesk_version": "18.0.76",
                "os_name": "Ubuntu",
                "os_version": "22.04",
            },
        )

        body = route.calls.last.request.read().decode()
        assert "metadata" in body
        assert "Ubuntu" in body
        assert "Unix" in body
        assert "22.04" in body

    @respx.mock
    async def test_empty_answer_returns_empty_string(self, mcp_client: Client) -> None:
        respx.post(f"{ENDPOINT}/gen_answer").respond(200, json={})
        result = await mcp_client.call_tool("query", {"query": "anything"})
        assert _text(result.content) == ""

    @respx.mock
    async def test_http_error_propagates(self, mcp_client: Client) -> None:
        respx.post(f"{ENDPOINT}/gen_answer").respond(500, text="boom")
        with pytest.raises(Exception, match="500"):
            await mcp_client.call_tool("query", {"query": "anything"})


class TestCreateApiClient:
    def test_sets_authorization_header(self) -> None:
        opts = argparse.Namespace(
            endpoint_url=ENDPOINT,
            auth_token="token-xyz",
            timeout=10,
            insecure=False,
        )
        client = srv.create_api_client(opts)
        assert client.headers["Authorization"] == "Bearer token-xyz"
        assert "json" in client.headers["Content-Type"]


class TestParseArgs:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["plesk-remote-docs-mcp"])
        for v in ("PLESK_COPILOT_API_BASE_URL", "PLESK_COPILOT_AUTH_TOKEN"):
            monkeypatch.delenv(v, raising=False)
        args = srv.parse_args()
        # The default URL is rot_13 of an internal one; we don't care about its value,
        # just that one is present and the auth token is too.
        assert args.endpoint_url
        assert args.auth_token
        assert args.timeout == 20

    def test_override_via_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["plesk-remote-docs-mcp"])
        monkeypatch.setenv("PLESK_COPILOT_API_BASE_URL", "https://my.example/")
        monkeypatch.setenv("PLESK_COPILOT_AUTH_TOKEN", "tok")
        args = srv.parse_args()
        assert args.endpoint_url == "https://my.example/"
        assert args.auth_token == "tok"

    def test_rejects_zero_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["plesk-remote-docs-mcp", "--timeout", "0"])
        with pytest.raises(SystemExit):
            srv.parse_args()
