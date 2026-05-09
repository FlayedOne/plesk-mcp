"""Tests for `plesk_mcp.server.upload_file`."""

from collections.abc import Iterator

import httpx

import pytest
import respx
from plesk_mcp import server as srv

URL = "https://plesk.example.net/enterprise/control/agent.php/"


@pytest.fixture
def xml_rpc_set() -> Iterator[httpx.AsyncClient]:
    """Set the contextvar with an httpx client targeted by respx."""
    client = httpx.AsyncClient(base_url=URL)
    token = srv.xml_rpc_client.set(client)
    try:
        yield client
    finally:
        srv.xml_rpc_client.reset(token)


@respx.mock
async def test_upload_returns_path_from_xml(xml_rpc_set: httpx.AsyncClient) -> None:
    respx.post(URL).respond(
        200,
        text="<packet><upload><result><file>/tmp/uploaded.txt</file></result></upload></packet>",
    )
    assert await srv.upload_file("hello") == "/tmp/uploaded.txt"


@respx.mock
async def test_upload_raises_on_http_error(xml_rpc_set: httpx.AsyncClient) -> None:
    respx.post(URL).respond(500, text="boom")
    with pytest.raises(RuntimeError, match="Failed to upload file"):
        await srv.upload_file("data")


@respx.mock
async def test_upload_raises_on_missing_file_field(xml_rpc_set: httpx.AsyncClient) -> None:
    respx.post(URL).respond(200, text="<packet><upload><result/></upload></packet>")
    with pytest.raises(RuntimeError, match="Failed to find file path"):
        await srv.upload_file("data")


@respx.mock
async def test_upload_raises_on_malformed_xml(xml_rpc_set: httpx.AsyncClient) -> None:
    respx.post(URL).respond(200, text="<<<not xml")
    with pytest.raises(RuntimeError, match="Failed to parse XML"):
        await srv.upload_file("data")
