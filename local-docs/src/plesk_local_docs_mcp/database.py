"""Knowledge database management."""

import argparse
import asyncio
import email.utils
import json
import shutil
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import chromadb
import chromadb.config
import httpx
import platformdirs
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from fastmcp.utilities.logging import get_logger

COLLECTION_NAME = "mcp"
EMBEDDING_MODEL = "text-embedding-3-small"
DATETIME_MIN = datetime.min.replace(tzinfo=timezone.utc)


logger = get_logger(__name__)


@dataclass
class CacheInfo:
    """Information about the downloaded database."""

    url: str
    etag: str | None
    last_modified: str | None

    def save(self, path: Path) -> None:
        """Save the cache info to a JSON file."""
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.__dict__, f, ensure_ascii=False, indent=4)

    @staticmethod
    def load(path: Path) -> "CacheInfo":
        """Load the cache info from a JSON file."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            return CacheInfo(**data)

    def next_update(self, delay: timedelta, cooldown: timedelta) -> datetime:
        """Next time to check for a database update."""
        next = datetime.now(tz=timezone.utc) + cooldown
        if self.last_modified:
            next = http_field_to_datetime(self.last_modified) + delay
        return next


def get_db_cache_info(db: Path | None = None) -> CacheInfo:
    """Get the cache info for the given unpacked database."""
    if db is None:
        return CacheInfo(url="", etag=None, last_modified=None)
    info_path = db.parent / "info.json"
    if not info_path.is_file():
        raise FileNotFoundError(f"Cache info file not found at {info_path}")
    return CacheInfo.load(info_path)


@dataclass
class Database:
    """ChromaDB collection and metadata for the knowledge base."""

    chroma: chromadb.Collection | None = None
    cache: CacheInfo = field(default_factory=get_db_cache_info)
    next_update_check: datetime = DATETIME_MIN
    update_lock: threading.Lock = field(default_factory=threading.Lock)


def get_chromadb(db_path: Path) -> chromadb.Collection:
    """Create and return a ChromaDB collection for the given database path."""

    # Workaround for:
    #   An embedding function already exists in the collection configuration, and a new one is provided.
    #   If this is intentional, please embed documents separately.
    #   Embedding function conflict: new: openai vs persisted: default
    class WrappedOpenAIEmbeddingFunction(OpenAIEmbeddingFunction):
        @staticmethod
        def name() -> str:
            return "default"

    return chromadb.PersistentClient(
        path=str(db_path),
        settings=chromadb.config.Settings(
            # Actually, no telemetry as of 1.5.4
            anonymized_telemetry=False,
        ),
    ).get_collection(
        name=COLLECTION_NAME,
        embedding_function=WrappedOpenAIEmbeddingFunction(model_name=EMBEDDING_MODEL),  # pyright: ignore[reportArgumentType]
    )


def is_valid_db(db_path: Path) -> bool:
    """Check if the unpacked database appears to be valid."""
    try:
        return db_path.is_dir() and get_chromadb(db_path).count() > 0
    except Exception as e:
        logger.debug(f"Database at {db_path} is not valid: {e}")
        return False


def http_field_to_datetime(field: str | None) -> datetime:
    """Parse an HTTP date field (e.g. Last-Modified) into a datetime object or 'now'."""
    if field is None:
        return datetime.now(tz=timezone.utc)
    return email.utils.parsedate_to_datetime(field)


def get_storage_dir(root: Path, cache_info: CacheInfo) -> Path:
    """Get the storage directory for the database based on its cache info."""
    modified_ts = http_field_to_datetime(cache_info.last_modified)
    return root / modified_ts.astimezone(tz=timezone.utc).strftime('%Y-%m-%d_%H-%M-%S')


def get_storage_path() -> Path:
    """Return the path to the local storage directory."""
    return platformdirs.user_cache_path("plesk-local-docs-mcp", "FlayedOne", ensure_exists=True)


def download_if_modified(url: str, storage: Path, cached: CacheInfo, opts: argparse.Namespace) -> Path | None:
    """Download the file from the URL if it has been modified since the last download."""
    headers = {}
    if cached.etag:
        headers["If-None-Match"] = cached.etag
    if cached.last_modified:
        headers["If-Modified-Since"] = cached.last_modified

    with httpx.Client(
        follow_redirects=True,
        verify=not opts.insecure,
        timeout=float(opts.timeout),
    ) as client:
        try:
            with client.stream("GET", url, headers=headers) as response:
                if response.status_code == 304:  # noqa: PLR2004
                    logger.info(f"{url} not modified since last download.")
                    return None
                response.raise_for_status()
                response_info = CacheInfo(
                    url=url,
                    etag=response.headers.get("ETag"),
                    last_modified=response.headers.get("Last-Modified"),
                )

                artifacts_dir = get_storage_dir(storage, response_info)
                artifacts_dir.mkdir(parents=True, exist_ok=False)

                file_path = artifacts_dir / url.rsplit("/", maxsplit=1)[-1]
                with open(file_path, "wb") as f:
                    for chunk in response.iter_bytes(256 * 1024):
                        f.write(chunk)

                response_info.save(artifacts_dir / "info.json")

                logger.info(f"Downloaded {url} to {file_path}")
                return file_path
        except Exception as e:
            logger.error(f"Failed to download {url}: {e}")
            return None


def find_latest_db() -> Path | None:
    """Find the latest unpacked database in the storage directory."""
    storage = get_storage_path()
    if not storage.is_dir():
        return None

    children = sorted(storage.iterdir(), key=lambda d: d.name, reverse=True)
    return next(filter(is_valid_db, (child / "db" for child in children)), None)


def clean_up_storage(max_items: int = 1) -> list[Path]:
    """Clean up old database versions in the storage directory, keeping only the latest ones."""
    storage = get_storage_path()
    if not storage.is_dir():
        return []

    children = sorted(storage.iterdir(), key=lambda d: d.name, reverse=True)
    valid: list[Path] = []
    for child in children:
        if len(valid) < max_items and is_valid_db(child / "db"):
            valid.append(child)
        else:
            try:
                shutil.rmtree(child)
                logger.info(f"Removed old database or junk at {child}")
            except Exception as e:
                logger.warning(f"Failed to remove old database or junk at {child}: {e}")

    return valid


def unpack_db(zip_path: Path, unpack_dir: Path, is_expected_member: Callable[[str], bool]) -> bool:
    """Unpack the database zip file to the unpack directory, ensuring it contains expected members."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                resolved = (unpack_dir / member).resolve()
                if not resolved.is_relative_to(unpack_dir):
                    logger.error(f"Zip file {zip_path} contains member with invalid path: {member}")
                    return False
                if not is_expected_member(member):
                    logger.error(f"Zip file {zip_path} contains unexpected member: {member}")
                    return False

            zf.extractall(unpack_dir)

        logger.info(f"Unpacked {zip_path} to {unpack_dir}")
        return True
    except Exception as e:
        logger.error(f"Failed to unpack {zip_path}: {e}")
        return False


def try_fetch_db(opts: argparse.Namespace, cached: CacheInfo) -> Path | None:
    """Try to fetch and unpack the new database, using caching and validation."""
    logger.debug(f"Trying to fetch new database. Previous one has: {cached}")

    storage = get_storage_path()
    zip_path = download_if_modified(opts.db_url, storage, cached, opts)
    if zip_path is None:
        return None

    unpack_dir = zip_path.parent / "unpacked"
    if not unpack_db(zip_path, unpack_dir, lambda member: member.startswith("db/")):
        return None

    unpacked_db = unpack_dir / "db"
    if not is_valid_db(unpacked_db):
        logger.error(f"Unpacked database at {unpacked_db} is not valid.")
        return None

    unpacked_db = unpacked_db.rename(zip_path.parent / "db")
    logger.info(f"Moved unpacked database from {unpack_dir / 'db'} to {unpacked_db}")

    shutil.rmtree(unpack_dir, ignore_errors=True)
    zip_path.unlink(missing_ok=True)

    logger.info(f"Downloaded and unpacked a fresh database to {unpacked_db}")
    return unpacked_db


database = Database()


def refresh_db(opts: argparse.Namespace) -> None:
    """Refresh the database if a cached or new version is available."""
    db_update_delay = timedelta(days=1, hours=1)

    global database  # noqa: PLW0603
    with database.update_lock:
        cache = None

        if database.chroma is None:
            if db_path := find_latest_db():
                cache = get_db_cache_info(db_path)
                database = Database(
                    chroma=get_chromadb(db_path),
                    cache=cache,
                    next_update_check=cache.next_update(db_update_delay, timedelta()),
                    update_lock=database.update_lock,
                )
                logger.info(f"Loaded cached database from {db_path}")

        if datetime.now(tz=timezone.utc) >= database.next_update_check:
            if db_path := try_fetch_db(opts, database.cache):
                cache = get_db_cache_info(db_path)
                database = Database(
                    chroma=get_chromadb(db_path),
                    cache=cache,
                    next_update_check=cache.next_update(db_update_delay, timedelta(hours=6)),
                    update_lock=database.update_lock,
                )
                logger.info(f"Loaded fresh database from {db_path}")
            else:
                database.next_update_check = datetime.now(tz=timezone.utc) + timedelta(hours=6)

        if cache:
            clean_up_storage()


async def get_db(opts: argparse.Namespace) -> chromadb.Collection:
    """Get the current database collection, waiting for it if necessary."""
    if db := database.chroma:
        return db

    logger.info("Database isn't available yet, waiting for it...")
    await asyncio.to_thread(refresh_db, opts)
    if db := database.chroma:
        return db

    raise RuntimeError("Failed to obtain knowledge database.")
