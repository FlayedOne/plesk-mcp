"""Tests for `plesk_local_docs_mcp.database` (cache and packaging helpers).

These tests avoid touching the network or ChromaDB. The download path is
exercised via the smoke test only.
"""

import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from plesk_local_docs_mcp import database as db


class TestCacheInfo:
    def test_roundtrip(self, tmp_path: Path) -> None:
        info = db.CacheInfo(url="https://x", etag='"abc"', last_modified="Wed, 21 Oct 2026 07:28:00 GMT")
        path = tmp_path / "info.json"
        info.save(path)
        loaded = db.CacheInfo.load(path)
        assert loaded == info

    def test_get_db_cache_info_returns_empty_when_no_path(self) -> None:
        info = db.get_db_cache_info(None)
        assert info.url == ""
        assert info.etag is None
        assert info.last_modified is None

    def test_get_db_cache_info_raises_when_missing(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            db.get_db_cache_info(tmp_path / "db")


class TestHttpFieldToDatetime:
    def test_parses_http_date(self) -> None:
        dt = db.http_field_to_datetime("Wed, 21 Oct 2026 07:28:00 GMT")
        assert dt == datetime(2026, 10, 21, 7, 28, 0, tzinfo=timezone.utc)

    def test_none_returns_now(self) -> None:
        before = datetime.now(tz=timezone.utc)
        dt = db.http_field_to_datetime(None)
        after = datetime.now(tz=timezone.utc)
        assert before <= dt <= after


class TestNextUpdate:
    def test_uses_last_modified_plus_delay(self) -> None:
        info = db.CacheInfo(url="x", etag=None, last_modified="Wed, 21 Oct 2026 07:28:00 GMT")
        nxt = info.next_update(timedelta(days=1), timedelta(hours=6))
        assert nxt == datetime(2026, 10, 22, 7, 28, 0, tzinfo=timezone.utc)

    def test_falls_back_to_cooldown_when_no_last_modified(self) -> None:
        info = db.CacheInfo(url="x", etag=None, last_modified=None)
        before = datetime.now(tz=timezone.utc)
        nxt = info.next_update(timedelta(days=1), timedelta(hours=6))
        # ~6 hours after "now", allow generous slack for slow CI
        assert timedelta(hours=5, minutes=59) <= nxt - before <= timedelta(hours=6, minutes=1)


class TestUnpackDb:
    def _make_zip(self, path: Path, members: dict[str, str]) -> None:
        with zipfile.ZipFile(path, "w") as zf:
            for name, content in members.items():
                zf.writestr(name, content)

    def test_unpacks_expected_members(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "x.zip"
        out = tmp_path / "out"
        self._make_zip(zip_path, {"db/a.txt": "hello", "db/b.txt": "world"})
        assert db.unpack_db(zip_path, out, lambda m: m.startswith("db/"))
        assert (out / "db" / "a.txt").read_text() == "hello"
        assert (out / "db" / "b.txt").read_text() == "world"

    def test_rejects_unexpected_member(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "x.zip"
        out = tmp_path / "out"
        self._make_zip(zip_path, {"db/a.txt": "hi", "evil.sh": "rm -rf /"})
        assert not db.unpack_db(zip_path, out, lambda m: m.startswith("db/"))
        assert not (out / "db" / "a.txt").exists()
        assert not (out / "evil.sh").exists()

    def test_rejects_path_traversal(self, tmp_path: Path) -> None:
        zip_path = tmp_path / "x.zip"
        out = tmp_path / "out"
        self._make_zip(zip_path, {"../escape.txt": "no"})
        assert not db.unpack_db(zip_path, out, lambda m: True)


class TestGetStorageDir:
    def test_uses_iso_dir_from_last_modified(self, tmp_path: Path) -> None:
        info = db.CacheInfo(url="x", etag=None, last_modified="Wed, 21 Oct 2026 07:28:00 GMT")
        result = db.get_storage_dir(tmp_path, info)
        assert result == tmp_path / "2026-10-21_07-28-00"


class TestIsValidDb:
    def test_returns_false_for_missing_dir(self, tmp_path: Path) -> None:
        assert not db.is_valid_db(tmp_path / "missing")

    def test_returns_false_for_non_db_dir(self, tmp_path: Path) -> None:
        # Empty existing dir → can't load a Chroma collection from it.
        empty = tmp_path / "db"
        empty.mkdir()
        assert not db.is_valid_db(empty)
