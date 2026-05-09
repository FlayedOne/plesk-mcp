"""Tests for `plesk_mcp.server.parse_args`."""

import sys

import pytest
from plesk_mcp.server import parse_args


@pytest.fixture(autouse=True)
def _clear_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["plesk-mcp"])
    for var in ("PLESK_HOST", "PLESK_API_KEY", "PLESK_USERNAME", "PLESK_PASSWORD"):
        monkeypatch.delenv(var, raising=False)


def test_requires_host(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        parse_args()
    assert "PLESK_HOST" in capsys.readouterr().err


def test_requires_credentials(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("PLESK_HOST", "https://plesk.example.net")
    with pytest.raises(SystemExit):
        parse_args()
    assert "PLESK_API_KEY" in capsys.readouterr().err


def test_rejects_http_without_insecure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("PLESK_HOST", "http://plesk.example.net")
    monkeypatch.setenv("PLESK_API_KEY", "k")
    with pytest.raises(SystemExit):
        parse_args()
    assert "https://" in capsys.readouterr().err


def test_accepts_http_when_insecure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLESK_HOST", "http://plesk.example.net")
    monkeypatch.setenv("PLESK_API_KEY", "k")
    monkeypatch.setattr(sys, "argv", ["plesk-mcp", "--insecure"])
    args = parse_args()
    assert args.insecure is True
    assert args.api_key == "k"


def test_username_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLESK_HOST", "https://plesk.example.net")
    monkeypatch.setenv("PLESK_USERNAME", "joe")
    monkeypatch.setenv("PLESK_PASSWORD", "p")
    args = parse_args()
    assert args.username == "joe"
    assert args.password == "p"


def test_default_username_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLESK_HOST", "https://plesk.example.net")
    monkeypatch.setenv("PLESK_PASSWORD", "p")
    args = parse_args()
    assert args.username == "admin"


def test_rejects_non_positive_timeout(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("PLESK_HOST", "https://plesk.example.net")
    monkeypatch.setenv("PLESK_API_KEY", "k")
    monkeypatch.setattr(sys, "argv", ["plesk-mcp", "--timeout", "0"])
    with pytest.raises(SystemExit):
        parse_args()
    assert "Timeout" in capsys.readouterr().err
