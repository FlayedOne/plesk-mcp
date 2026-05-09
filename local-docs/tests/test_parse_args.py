"""Tests for `plesk_local_docs_mcp.server.parse_args`."""

import sys

import pytest
from plesk_local_docs_mcp import server as srv


@pytest.fixture(autouse=True)
def _reset_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["plesk-local-docs-mcp"])
    for v in ("OPENAI_API_KEY", "PLESK_KB_URL"):
        monkeypatch.delenv(v, raising=False)


def test_requires_openai_key(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        srv.parse_args()
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_default_db_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    args = srv.parse_args()
    assert args.openai_api_key == "sk-x"
    assert args.db_url == srv.DEFAULT_DB_URL
    assert args.top_k == 5


def test_custom_db_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setenv("PLESK_KB_URL", "https://example.com/db.zip")
    args = srv.parse_args()
    assert args.db_url == "https://example.com/db.zip"


def test_rejects_zero_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setattr(sys, "argv", ["plesk-local-docs-mcp", "--top-k", "0"])
    with pytest.raises(SystemExit):
        srv.parse_args()


def test_rejects_zero_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
    monkeypatch.setattr(sys, "argv", ["plesk-local-docs-mcp", "--timeout", "0"])
    with pytest.raises(SystemExit):
        srv.parse_args()
