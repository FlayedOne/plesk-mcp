"""Shared pytest fixtures for plesk-mcp tests."""

import argparse

import pytest


@pytest.fixture
def opts_api_key() -> argparse.Namespace:
    """Argparse namespace authenticated via API key."""
    return argparse.Namespace(
        host="https://plesk.example.net:8443",
        api_key="00000000-0000-0000-0000-000000000000",
        username="admin",
        password=None,
        insecure=False,
        timeout=300,
    )


@pytest.fixture
def opts_basic_auth() -> argparse.Namespace:
    """Argparse namespace authenticated via username/password."""
    return argparse.Namespace(
        host="https://plesk.example.net:8443",
        api_key=None,
        username="admin",
        password="secret",
        insecure=True,
        timeout=42,
    )
