#!/usr/bin/env -S uv run
"""Plesk documentation MCP server implementation using a remote API."""

import argparse
import codecs
import os
from contextvars import ContextVar
from typing import Annotated, Any, cast

import httpx
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

DEFAULT_API_BASE_URL = codecs.encode("uggcf://frznagvp-frnepu.cyrfx.pbz", "rot_13")
DEFAULT_AUTH_TOKEN = codecs.encode("h8Wx2cDj9KmYe3IoGa6LsTuDj2QfCmKpX", "rot_13")

api_client: ContextVar[httpx.AsyncClient] = ContextVar("api_client")
mcp = FastMCP(name="Remote Plesk Knowledge Base", version="0.1.0")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
async def query(
    query: Annotated[
        str,
        "Question or topic about Plesk or its extensions. "
        "To ensure the query is not rejected, include 'Plesk' in it. "
        "When looking up CLI or API information, include 'CLI' or 'API' in the query, respectively.",
    ],
    plesk_version: Annotated[str | None, "Optional Plesk version to provide context. E.g. '18.0.76'."] = None,
    os_name: Annotated[str | None, "Optional OS name to provide context. E.g. 'Ubuntu', 'CentOS', 'Microsoft Windows'."] = None,
    os_version: Annotated[str | None, "Optional OS version to provide context. E.g. '20.04', '7', '2019'."] = None,
) -> str:
    """Query the Plesk knowledge base about Plesk or its extensions."""
    request_body: dict[str, Any] = {
        "query": query,
        "product": "plesk",
    }
    if metadata := build_metadata(plesk_version, os_name, os_version):
        request_body["metadata"] = metadata

    response = await api_client.get().post("/gen_answer", json=request_body)
    response.raise_for_status()
    return cast(str, response.json().get("answer", ""))


def build_metadata(plesk_version: str | None, os_name: str | None, os_version: str | None) -> dict[str, str]:
    """Build metadata dictionary for the API request based on provided context."""
    metadata = {}
    if plesk_version:
        metadata["plesk_version"] = plesk_version
    if os_name:
        metadata["os_name"] = os_name
        metadata["platform"] = "Windows" if "windows" in os_name.lower() else "Unix"
    if os_version:
        metadata["os_version"] = os_version
    return metadata


def create_api_client(opts: argparse.Namespace) -> httpx.AsyncClient:
    """Create an HTTP client for API requests."""
    return httpx.AsyncClient(
        base_url=opts.endpoint_url,
        headers={
            "Authorization": f"Bearer {opts.auth_token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        timeout=float(opts.timeout),
        verify=not opts.insecure,
        follow_redirects=True,
    )


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments and environment variables."""
    epilog = """Environment variables:
    PLESK_COPILOT_API_BASE_URL: Alternative query API base URL, optional
    PLESK_COPILOT_AUTH_TOKEN: Alternative API authentication token, optional
    """
    formatter = argparse.RawDescriptionHelpFormatter
    opt_bool_action = argparse.BooleanOptionalAction

    parser = argparse.ArgumentParser(description="Remote Plesk Documentation MCP Server", epilog=epilog, formatter_class=formatter)
    parser.add_argument("--log-level", type=str, default="INFO", help="logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    parser.add_argument("--insecure", action="store_true", help="disable SSL verification for HTTP client")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP client timeout in seconds (default: %(default)s)")
    parser.add_argument("--telemetry", action=opt_bool_action, help="enable/disable telemetry (there's no telemetry currently)")
    args = parser.parse_args()

    args.endpoint_url = os.environ.get("PLESK_COPILOT_API_BASE_URL", DEFAULT_API_BASE_URL)
    args.auth_token = os.environ.get("PLESK_COPILOT_AUTH_TOKEN", DEFAULT_AUTH_TOKEN)

    if args.timeout <= 0:
        parser.error("Timeout must be a positive integer")

    return args


def main() -> None:
    """Entry point for the MCP server."""
    args = parse_args()
    api_client.set(create_api_client(args))
    mcp.run(show_banner=False, log_level=args.log_level)


if __name__ == "__main__":
    main()
