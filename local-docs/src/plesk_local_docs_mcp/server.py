#!/usr/bin/env -S uv run
"""Plesk documentation MCP server implementation using a local DB."""

import argparse
import asyncio
import json
import os
from typing import Annotated, Any, cast

from fastmcp import Context, FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.utilities.logging import get_logger
from mcp.types import ToolAnnotations

from plesk_local_docs_mcp.database import get_db, refresh_db

DEFAULT_DB_URL = "https://autoinstall.plesk.com/MCP_0.0.2/db.zip"
SYSTEM_PROMPT = """\
You are an expert assistant for the Plesk hosting panel.
Answer the user's question based on the provided knowledge base context.
Use the context documents to build a comprehensive, accurate answer.
Format your response in Markdown.
Include relevant source links from the context when applicable.
If the provided context doesn't contain enough information to fully answer
the question, say so clearly and provide what information you can.
Do not invent information not present in the context.
Prioritize practical, actionable instructions.
When providing commands or file paths, prefer CLI-based and/or REST API-based instructions if available,
unless the query explicitly asks for UI-based instructions or the context contains only UI-based instructions.
"""


class DatabaseUpdateMiddleware(Middleware):
    """Middleware to trigger database refresh in the background if needed."""

    def __init__(self) -> None:
        """Constructor."""
        self.tasks: set[asyncio.Task] = set()

    async def on_message(self, context: MiddlewareContext, call_next: CallNext) -> Any:
        """On initialize and any request or notification."""
        self.tasks.add(asyncio.ensure_future(asyncio.to_thread(refresh_db, args)))
        for task in self.tasks.copy():
            if task.done():
                self.tasks.remove(task)
        return await call_next(context)


logger = get_logger(__name__)
args = argparse.Namespace()
mcp = FastMCP(name="Local Plesk Knowledge Base", version="0.1.0", middleware=[DatabaseUpdateMiddleware()])


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def query(
    ctx: Context,
    query: Annotated[
        str,
        "Question or topic about Plesk or its extensions. "
        "When looking up CLI or API information, include 'CLI' or 'API' in the query, respectively.",
    ],
    plesk_version: Annotated[str | None, "Optional Plesk version to provide context. E.g. '18.0.76'."] = None,
    os_name: Annotated[str | None, "Optional OS name to provide context. E.g. 'Ubuntu', 'CentOS', 'Microsoft Windows'."] = None,
    os_version: Annotated[str | None, "Optional OS version to provide context. E.g. '20.04', '7', '2019'."] = None,
) -> str:
    """Query the Plesk knowledge base about Plesk or its extensions."""
    where: dict[str, Any] | None = None
    if os_name:
        where = {"Platform": {"$in": [derive_platform(os_name), "any"]}}

    results = (await get_db(args)).query(
        query_texts=[query],
        n_results=args.top_k,
        where=where,
    )

    ids = results["ids"][0]
    documents = results["documents"][0] if results["documents"] else []
    metadatas = results["metadatas"][0] if results["metadatas"] else []
    distances = results["distances"][0] if results["distances"] else []
    if not ids:
        raise RuntimeError("No results found in the knowledge base for the query.")

    context = []
    for id, doc, meta, dist in zip(ids, documents, metadatas, distances, strict=True):
        try:
            node_content = json.loads(cast(str, meta["_node_content"]))
            metadata = node_content.get("metadata", {})
        except Exception:
            metadata = {}
        data = {
            "distance": dist,
            **metadata,
        }
        data_json = json.dumps(data, ensure_ascii=False, indent=4)
        context.append(f"## Context item {id}\n\n```json\n{data_json}\n```\n\n{doc}\n\n----\n\n")

    env = {
        "plesk_version": plesk_version,
        "os_name": os_name,
        "os_version": os_version,
    }
    env = {k: v for k, v in env.items() if v is not None}

    messages = [
        "# Context\n\n" + "".join(context),
        "# Environment\n\n" + "```json\n" + json.dumps(env, ensure_ascii=False, indent=4) + "\n```",
        "# Question\n\n" + query,
    ]

    try:
        result = await ctx.sample(
            system_prompt=SYSTEM_PROMPT,
            messages=messages,
            max_tokens=2048,
            temperature=0.3,
            model_preferences=[
                "gpt-5-mini",
                "claude-haiku-4.5",
                "grok-code-fast-1",
            ],
        )
        if result.text:
            return result.text
    except Exception as e:
        logger.error(f"LLM sampling failed: {e}")
    return "".join(context)


def derive_platform(os_name: str) -> str:
    """Derive platform value from OS name."""
    return "windows" if "windows" in os_name.lower() else "linux"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments and environment variables."""
    epilog = """Environment variables:
    OPENAI_API_KEY: API key for OpenAI embeddings, required
    PLESK_KB_URL: Alternative packed ChromaDB URL, optional
    """
    formatter = argparse.RawDescriptionHelpFormatter
    opt_bool_action = argparse.BooleanOptionalAction

    parser = argparse.ArgumentParser(description="Local Plesk Documentation MCP Server", epilog=epilog, formatter_class=formatter)
    parser.add_argument("--log-level", type=str, default="INFO", help="logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    parser.add_argument("--insecure", action="store_true", help="disable SSL verification for HTTP client")
    parser.add_argument("--timeout", type=int, default=120, help="HTTP client timeout in seconds (default: %(default)s)")
    parser.add_argument("--telemetry", action=opt_bool_action, help="enable/disable telemetry (there's no telemetry currently)")
    parser.add_argument("--top-k", type=int, default=5, help="number of top relevant documents to use (default: %(default)s)")
    args = parser.parse_args()

    args.db_url = os.environ.get("PLESK_KB_URL", DEFAULT_DB_URL)
    args.openai_api_key = os.environ.get("OPENAI_API_KEY")

    if args.timeout <= 0:
        parser.error("Timeout must be a positive integer")
    if args.top_k <= 0:
        parser.error("Top-k must be a positive integer")
    if not args.openai_api_key:
        parser.error("OPENAI_API_KEY environment variable is required")

    return args


def main() -> None:
    """Entry point for the MCP server."""
    global args  # noqa: PLW0603
    args = parse_args()
    mcp.run(show_banner=False, log_level=args.log_level)


if __name__ == "__main__":
    main()
