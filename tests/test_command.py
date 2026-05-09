"""Tests for command/scheduler helpers in `plesk_mcp.server`.

`build_scheduler_command` consults cached `get_server_platform()`.
We patch the underlying platform getter so tests stay fully synchronous and don't touch any network.
"""

import warnings
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

from async_lru import AlruCacheLoopResetWarning

import pytest
from plesk_mcp import server as srv


@pytest.fixture(autouse=True)
async def _reset_platform_cache() -> AsyncIterator[None]:
    """Ensure the cached platform doesn't leak between tests."""
    # Suppress alru_cache loop reset warning in tests. It is caused by test isolation in separate event loops.
    warnings.filterwarnings("ignore", category=AlruCacheLoopResetWarning)
    srv.get_server_platform.cache_clear()
    yield
    srv.get_server_platform.cache_clear()


@pytest.fixture
def linux(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _info() -> dict[str, str]:
        return {"platform": "Unix"}

    monkeypatch.setattr(srv, "get_server_info", _info)


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _info() -> dict[str, str]:
        return {"platform": "Windows"}

    monkeypatch.setattr(srv, "get_server_info", _info)


class TestBuildSchedulerCommand:
    @pytest.mark.usefixtures("linux")
    async def test_linux_basic_command(self) -> None:
        args, _lock = await srv.build_scheduler_command(["ls", "-la"])
        assert args[0:2] == ["scheduler", "--create"]
        assert "-user" in args
        assert "root" in args
        assert "-active" in args
        assert "false" in args
        cmd = args[args.index("-command") + 1]
        assert "ls" in cmd
        assert "-la" in cmd
        assert "PATH=/usr/sbin:/usr/bin:/sbin:/bin" in cmd

    @pytest.mark.usefixtures("linux")
    async def test_linux_subscription_uses_subscription_context(self) -> None:
        args, _ = await srv.build_scheduler_command(["whoami"], subscription="example.com")
        assert "-subscription" in args
        assert "example.com" in args
        assert "-user" not in args
        # No default PATH injection in subscription context.
        cmd = args[args.index("-command") + 1]
        assert "PATH=/usr/sbin" not in cmd

    @pytest.mark.usefixtures("linux")
    async def test_linux_stdin_is_percent_encoded(self) -> None:
        args, _ = await srv.build_scheduler_command(["cat"], stdin="hello\nworld%")
        cmd = args[args.index("-command") + 1]
        assert "%hello%world" in cmd
        # Existing % characters must be escaped.
        assert r"\%" in cmd

    @pytest.mark.usefixtures("linux")
    async def test_linux_env_is_passed_through_env_wrapper(self) -> None:
        args, _ = await srv.build_scheduler_command(["printenv"], env={"FOO": "bar"})
        cmd = args[args.index("-command") + 1]
        assert "env" in cmd
        assert "FOO=bar" in cmd

    @pytest.mark.usefixtures("windows")
    async def test_windows_basic_command(self) -> None:
        args, _ = await srv.build_scheduler_command(["dir"])
        assert "-user" in args
        assert "Plesk Administrator" in args
        # Windows uses -arguments separately
        assert "-arguments" in args

    @pytest.mark.usefixtures("windows")
    async def test_windows_rejects_env(self) -> None:
        with pytest.raises(NotImplementedError, match="environment"):
            await srv.build_scheduler_command(["dir"], env={"X": "1"})

    @pytest.mark.usefixtures("windows")
    async def test_windows_rejects_stdin(self) -> None:
        with pytest.raises(NotImplementedError, match="standard input"):
            await srv.build_scheduler_command(["dir"], stdin="data")


class TestGetSubscription:
    async def test_rejects_sql_injection_chars(self) -> None:
        ctx = AsyncMock()
        for bad in ["';drop", "a;b", "x'y"]:
            assert await srv.get_subscription(ctx, bad) == []
        ctx.assert_not_called()

    async def test_returns_lines_from_stdout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_execute(ctx: object, command: list[str]) -> dict[str, object]:
            assert command[:3] == ["plesk", "db", "-Ne"]
            return {"code": 0, "stdout": "example.com\nother.com\n", "stderr": ""}

        monkeypatch.setattr(srv, "execute_command", fake_execute)
        result = await srv.get_subscription(AsyncMock(), "example.com")
        assert result == ["example.com", "other.com"]

    async def test_raises_on_db_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        async def fake_execute(ctx: object, command: list[str]) -> dict[str, object]:
            return {"code": 1, "stdout": "", "stderr": "boom"}

        monkeypatch.setattr(srv, "execute_command", fake_execute)
        with pytest.raises(RuntimeError, match="Failed to lookup subscription"):
            await srv.get_subscription(AsyncMock(), "example.com")
