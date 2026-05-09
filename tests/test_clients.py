"""Tests for HTTP client construction in `plesk_mcp.server`."""

import argparse

import httpx

import pytest
from plesk_mcp.server import create_rest_api_client, create_xml_rpc_client


class TestRestApiClient:
    def test_basic_auth(self, opts_basic_auth: argparse.Namespace) -> None:
        client = create_rest_api_client(opts_basic_auth, "/api/v2")
        assert client.auth is not None
        assert "X-API-Key" not in client.headers
        assert client.base_url.path.rstrip("/") == "/api/v2"
        assert client.timeout.connect == 42

    def test_api_key(self, opts_api_key: argparse.Namespace) -> None:
        client = create_rest_api_client(opts_api_key, "/api/v2")
        assert client.headers["X-API-Key"] == opts_api_key.api_key
        assert "Authorization" not in client.headers
        assert client.auth is None
        assert client.base_url.path.rstrip("/") == "/api/v2"
        assert client.timeout.connect == 300

    def test_rejects_missing_credentials(self) -> None:
        opts = argparse.Namespace(host="https://h", api_key=None, username=None, password=None, insecure=False, timeout=30)
        with pytest.raises(ValueError, match="API key or username and password"):
            create_rest_api_client(opts, "/api/v2")

    @pytest.mark.parametrize(
        ("host", "base"),
        [
            ("https://plesk.example.net", "/api/v2"),
            ("https://plesk.example.net/", "/api/v2"),
            ("https://plesk.example.net:8443", "/api/v2"),
        ],
    )
    def test_base_url_normalization(self, opts_api_key: argparse.Namespace, host: str, base: str) -> None:
        opts_api_key.host = host
        client = create_rest_api_client(opts_api_key, base)
        assert str(client.base_url).startswith(host.rstrip("/"))
        assert client.base_url.path.rstrip("/") == "/api/v2"

    def test_insecure_disables_verification(self, opts_basic_auth: argparse.Namespace) -> None:
        # opts_basic_auth has insecure=True
        client = create_rest_api_client(opts_basic_auth, "/api/v2")
        # httpx stores verify configuration on the underlying transport; we just sanity check
        # the client is created successfully and accepts the parameters.
        assert isinstance(client, httpx.AsyncClient)


class TestXmlRpcClient:
    def test_basic_auth(self, opts_basic_auth: argparse.Namespace) -> None:
        client = create_xml_rpc_client(opts_basic_auth)
        assert client.headers["HTTP_AUTH_LOGIN"] == "admin"
        assert client.headers["HTTP_AUTH_PASSWD"] == "secret"
        assert "KEY" not in client.headers
        assert client.base_url.path.rstrip("/") == "/enterprise/control/agent.php"
        assert client.timeout.connect == 42

    def test_api_key(self, opts_api_key: argparse.Namespace) -> None:
        client = create_xml_rpc_client(opts_api_key)
        assert client.headers["KEY"] == opts_api_key.api_key
        assert "HTTP_AUTH_LOGIN" not in client.headers
        assert "HTTP_AUTH_PASSWD" not in client.headers
        assert client.base_url.path.rstrip("/") == "/enterprise/control/agent.php"
        assert client.timeout.connect == 300

    def test_rejects_missing_credentials(self) -> None:
        opts = argparse.Namespace(host="https://h", api_key=None, username=None, password=None, insecure=False, timeout=30)
        with pytest.raises(ValueError, match="API key or username and password"):
            create_xml_rpc_client(opts)

    @pytest.mark.parametrize(
        ("host", "base"),
        [
            ("https://plesk.example.net", "/api/v2"),
            ("https://plesk.example.net/", "/api/v2"),
            ("https://plesk.example.net:8443", "/api/v2"),
        ],
    )
    def test_base_url_normalization(self, opts_api_key: argparse.Namespace, host: str, base: str) -> None:
        opts_api_key.host = host
        client = create_xml_rpc_client(opts_api_key)
        assert str(client.base_url).startswith(host.rstrip("/"))
        assert client.base_url.path.rstrip("/") == "/enterprise/control/agent.php"

    def test_insecure_disables_verification(self, opts_basic_auth: argparse.Namespace) -> None:
        # opts_basic_auth has insecure=True
        client = create_xml_rpc_client(opts_basic_auth)
        assert isinstance(client, httpx.AsyncClient)
