#!/usr/bin/env -S uv run
"""Plesk MCP server using stdio transport. Built on top of Plesk REST API."""

import argparse
import asyncio
import itertools
import json
import os
import shlex
import subprocess
import textwrap
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterable
from contextvars import ContextVar
from functools import lru_cache
from typing import Annotated, Any, Literal, cast

import httpx
from async_lru import alru_cache
from fastmcp import Context, FastMCP
from fastmcp.server.dependencies import get_server
from fastmcp.utilities.logging import get_logger

from transforms import ApiListTransform

logger = get_logger(__name__)
xml_rpc_client: ContextVar[httpx.AsyncClient] = ContextVar("xml_rpc_client")
command_counter = itertools.count(1)


@lru_cache
def get_async_lock(subject: str) -> asyncio.Lock:
    """Get an asyncio lock for the given subject (typically "command:args")."""
    return asyncio.Lock()


async def get_server_info() -> dict[str, Any]:
    """Runs GET `/server` on the server to retrieve basic server information."""
    result = await get_server().call_tool("Get_server_information", {})
    assert result.structured_content
    logger.debug(f"Got server info: {result.structured_content}")
    return result.structured_content


@alru_cache(maxsize=1)
async def get_server_platform() -> Literal["linux", "windows"]:
    """Returns the detected server platform."""
    info = await get_server_info()
    if info.get("platform") == "Unix":
        return "linux"
    elif info.get("platform") == "Windows":
        return "windows"
    raise RuntimeError(f"Unexpected platform value from the server info: {info.get('platform')}")


async def execute_plesk_cli(ctx: Context, command: list[str], env: dict[str, str] | None = None) -> dict[str, Any]:
    """Executes a command via `/cli/{command[0]}/call` on the server and returns the result."""
    result = await ctx.fastmcp.call_tool("Execute_CLI_command", {"id": command[0], "params": command[1:], "env": env})
    assert result.structured_content
    logger.debug(f"Executed Plesk CLI command: {command}, got result: {result.structured_content}")
    return result.structured_content


async def get_subscription(ctx: Context, domain: str) -> list[str]:
    """Gets subscription name by domain name, subdomain name, or alias name."""
    if "'" in domain or ";" in domain:
        # potential SQL injection, invalid domain name anyway
        return []

    query = (
        f"SELECT UNIQUE dw.name "  # noqa: S608    'domain' is minimally checked above
        f"FROM domains dw "
        f" LEFT JOIN domains d ON (dw.id = d.webspace_id AND d.webspace_id != 0) OR dw.id = d.id "
        f" LEFT JOIN domain_aliases da ON d.id = da.dom_id "
        f"WHERE dw.webspace_id = 0 AND '{domain}' IN (da.name, da.displayName, d.name, d.displayName)"
    )
    result = await execute_command(ctx, ["plesk", "db", "-Ne", query])
    if result.get("code") != 0:
        raise RuntimeError(f"Failed to lookup subscription for {domain!r} (rc={result.get('code')}): {result.get('stderr')}")

    return str(result.get("stdout", "")).strip().splitlines()


async def build_scheduler_command(
    command: list[str],
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    subscription: str | None = None,
) -> tuple[list[str], asyncio.Lock]:
    """Build the arguments and lock for creating a scheduled task for `execute_command`."""
    is_linux = await get_server_platform() == "linux"

    if is_linux and "PATH" not in (env or {}) and subscription is None:
        env = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", **(env or {})}

    encoded_stdin = "%" + "%".join(line.replace("%", r"\%") for line in stdin.splitlines()) if stdin else ""
    context_args = ["-subscription", subscription] if subscription else ["-user", "root" if is_linux else "Plesk Administrator"]
    cmd_join: Callable[[Iterable[str]], str]

    if is_linux:
        cmd_join = shlex.join
        python_bin = "python3"
        env_wrapper_args = ["env", *[f'{k}={v}' for k, v in env.items()]] if env else []
        # EoL OSes like CentOS 7 (with Python 3.6) require a slightly uglier wrapper command
        wrapper_cmd = textwrap.dedent(r"""
            import subprocess as p,sys as s,json;
            r=p.run(s.argv[2:],universal_newlines=1,stdout=-1,stderr=-1);
            json.dump(dict(code=r.returncode,stdout=r.stdout,stderr=r.stderr),s.stderr);
            s.exit(1)
        """).replace("\n", "")
        command_str = cmd_join([*env_wrapper_args, python_bin, "-Ec", wrapper_cmd, str(next(command_counter)), *command])
        command_args = ["-command", command_str.replace("%", r"\%") + encoded_stdin]
    else:
        if env:
            raise NotImplementedError("Setting environment variables is not supported on Windows server")
        if stdin:
            raise NotImplementedError("Passing standard input is not supported on Windows server")

        def escape_for_cmd(arg: str) -> str:
            r"""Ensures the following escapes expected by cmd.exe: ^^, ^|, ^&, ^<, ^>, ^\."""
            for char in "^|&<>\\":
                arg = arg.replace(char, "^" + char)
            return arg

        cmd_join = subprocess.list2cmdline
        python_bin = "C:\\Program Files (x86)\\Plesk\\python3\\python.exe"
        wrapper_cmd = textwrap.dedent(r"""
            import subprocess,sys,json;
            p=subprocess.run(sys.argv[2:],capture_output=1,text=1);
            print("\n"+json.dumps({"code":p.returncode,"stdout":p.stdout,"stderr":p.stderr}));
            sys.exit(1)
        """).replace("\n", "")
        command_str = cmd_join(map(escape_for_cmd, ["-Ec", wrapper_cmd, str(next(command_counter)), *command]))
        command_args = ["-command", python_bin, "-arguments", command_str]

    active_args = ["-active", "false"]
    type_args = ["-type", "exec"]
    notify_args = ["-notify", "ignore"]
    schedule_args = ["-schedule", "0 0 1 1 *"]
    description_args = ["-description", "Transient task for executing a command from Plesk MCP"]
    create_args = [
        "scheduler",
        "--create",
        "-json",
        *context_args,
        *active_args,
        *type_args,
        *notify_args,
        *schedule_args,
        *description_args,
        *command_args,
    ]

    lock = get_async_lock(f"scheduler:{cmd_join(context_args)}")

    logger.info(f"Executing command {command} as {context_args[0][1:]} {context_args[1]} with env {env} and stdin {stdin!r}")
    return create_args, lock


async def execute_command(
    ctx: Context,
    command: list[str],
    stdin: str | None = None,
    env: dict[str, str] | None = None,
    subscription: str | None = None,
) -> dict[str, str | int]:
    """Executes a command on the Plesk server using the scheduler CLI and returns the result."""
    create_args, lock = await build_scheduler_command(command, stdin, env, subscription)
    async with lock:
        result = await execute_plesk_cli(ctx, create_args)

    if result.get("code") != 0:
        stderr = result.get("stderr", "").strip()
        recovery = ""
        if subscription and stderr.startswith("Subscription with name") and stderr.endswith("does not exist."):
            recovery = f"\nRecovery: You MUST try again NOW with a valid subscription name that corresponds to {subscription!r}."
            try:
                subscriptions = await get_subscription(ctx, subscription)
                if len(subscriptions) == 1:
                    recovery += f" The matching subscription is {subscriptions[0]!r}."
            except Exception as e:
                logger.warning(f"Couldn't refine recovery steps: {e}")
        raise RuntimeError(f"Failed to create scheduled task for command execution (rc={result.get('code')}): {stderr}{recovery}")

    try:
        task_id: int | None = json.loads(result.get("stdout", "{}")).get("id")
        if task_id is None:
            raise RuntimeError(f"Failed to parse task 'id' field from scheduler output: {result.get('stdout')}")
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to decode JSON from scheduler output: {result.get('stdout')}") from e

    try:
        result = await execute_plesk_cli(ctx, ["scheduler", "--run", str(task_id)])
        if result.get("code") != 0:
            raise RuntimeError(f"Failed to run scheduled task for command execution (rc={result.get('code')}): {result.get('stderr')}")

        command_result = json.loads(result.get("stdout", "").rstrip("\n").rsplit("\n", 1)[-1])
        assert command_result.keys() == {"code", "stdout", "stderr"}, f"Unexpected command result format: {command_result}"
        assert isinstance(command_result["code"], int), f"Unexpected command result 'code' type: {type(command_result['code'])}"
        assert isinstance(command_result["stdout"], str), f"Unexpected command result 'stdout' type: {type(command_result['stdout'])}"
        assert isinstance(command_result["stderr"], str), f"Unexpected command result 'stderr' type: {type(command_result['stderr'])}"
        return cast(dict[str, str | int], command_result)
    except json.JSONDecodeError as e:
        last_line = result.get("stdout", "").rstrip().rsplit("\n", 1)[-1]
        if "Traceback (most recent call last):" in result.get("stdout", ""):
            raise RuntimeError(f"Failed to execute the command: {last_line}") from e
        if subscription and any(f"{cmd}: command not found" in last_line for cmd in ["python3", "env"]):
            raise RuntimeError(f"Failed to execute the command: The subscription has no or chrooted shell access: {last_line}") from e
        raise RuntimeError(f"Failed to decode JSON from command output: {result.get('stdout')}") from e
    finally:
        async with lock:
            result = await execute_plesk_cli(ctx, ["scheduler", "--delete", str(task_id)])
        if result.get("code") != 0:
            raise RuntimeError(f"Failed to delete scheduled task for command execution (rc={result.get('code')}): {result.get('stderr')}")


async def upload_file(content: str) -> str:
    """Uploads a file with the given content to the Plesk server and returns the file path."""
    response = await xml_rpc_client.get().post("", files={"file": content})
    if not response.is_success:
        raise RuntimeError(f"Failed to upload file: {response.status_code} {response.text}")

    try:
        root = ET.fromstring(response.text)  # noqa: S314    would be better to use defusedxml, but we trust Plesk API output
        if file := root.findtext("./upload/result/file"):
            logger.info(f"Uploaded a file as {file}")
            return file
    except ET.ParseError as e:
        raise RuntimeError(f"Failed to parse XML from upload response: {response.text}") from e

    raise RuntimeError(f"Failed to find file path in upload response: {response.text}")


def create_rest_api_client(opts: argparse.Namespace, base_url: str) -> httpx.AsyncClient:
    """Creates an HTTP client for calling REST APIs on the Plesk server."""
    if opts.api_key:
        auth = None
        headers = {"X-API-Key": opts.api_key}
    elif opts.username and opts.password:
        auth = (opts.username, opts.password)
        headers = {}
    else:
        raise ValueError("Either API key or username and password must be provided")

    return httpx.AsyncClient(
        base_url=opts.host + base_url,
        verify=not opts.insecure,
        auth=auth,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **headers,
        },
        timeout=float(opts.timeout),
    )


def create_xml_rpc_client(opts: argparse.Namespace) -> httpx.AsyncClient:
    """Creates an HTTP client for calling XML-RPC APIs on the Plesk server."""
    if opts.api_key:
        headers = {"KEY": opts.api_key}
    elif opts.username and opts.password:
        headers = {
            "HTTP_AUTH_LOGIN": opts.username,
            "HTTP_AUTH_PASSWD": opts.password,
        }
    else:
        raise ValueError("Either API key or username and password must be provided")

    return httpx.AsyncClient(
        base_url=opts.host + "/enterprise/control/agent.php",
        verify=not opts.insecure,
        headers=headers,
        timeout=float(opts.timeout),
    )


async def create_mcp_server_from_rest_api(opts: argparse.Namespace, base_url: str, openapi_spec_url: str, name: str) -> FastMCP:
    """Creates an MCP server by introspecting REST API endpoint on the Plesk server."""
    client = create_rest_api_client(opts, base_url)
    openapi_spec = (await client.get(openapi_spec_url)).json()
    if "openapi" not in openapi_spec:
        raise ValueError(f"Invalid OpenAPI spec from {opts.host + base_url + openapi_spec_url}: missing 'openapi' field")

    return FastMCP.from_openapi(
        openapi_spec=openapi_spec,
        client=client,
        name=name,
    )


async def create_mcp_server(opts: argparse.Namespace) -> FastMCP:
    """Creates the main Plesk MCP server."""
    mcp = FastMCP(
        name="Plesk MCP",
        version="0.1.0",
        transforms=[
            ApiListTransform(name="Plesk", always_visible=['exec', 'upload']),
        ],
    )

    mcp_plesk = await create_mcp_server_from_rest_api(opts, "/api/v2", "openapi.json", "Plesk MCP")
    mcp.mount(mcp_plesk)

    try:
        mcp_wp_toolkit = await create_mcp_server_from_rest_api(opts, "/api/modules/wp-toolkit", "v1/specification/public", "WP Toolkit MCP")
        mcp.mount(mcp_wp_toolkit, namespace="wp")
    except Exception as e:
        logger.warning(f"Failed to create WP Toolkit MCP: {e}. Continuing without it.")

    xml_rpc_client.set(create_xml_rpc_client(opts))

    async with Context(mcp):
        is_linux = await get_server_platform() == "linux"

    if is_linux:

        @mcp.tool(name="exec")
        async def exec_linux(
            ctx: Context,
            command: Annotated[
                list[str],
                "Command to execute. "
                "Don't use `bash` wrapper if it is not required for proper operation. "
                "NEVER use `bash -lc` for root context to avoid printing banner. "
                "ALWAYS use `bash -lc` when running in subscription context to ensure proper environment setup.",
                # The latter is relevant for PHP, Node, Ruby, and environment lookup related commands.
            ],
            subscription: Annotated[
                str | None,
                "Optional subscription name to execute the command in (otherwise uses root user context)",
            ] = None,
            stdin: Annotated[str | None, "Optional standard input"] = None,
            env: Annotated[dict[str, str] | None, "Optional environment variables to set"] = None,
        ) -> dict[str, str | int]:
            """Executes a command on the Plesk server and returns the result.

            The command CWD is the home directory of the user
            (e.g. `/root` for root user, or `/var/www/vhosts/example.com` for a subscription user).
            This tool will reject long commands. Keep the total length of the command, stdin, and env vars under about 740 characters.

            This tool will fail for subscriptions with no or chrooted shell access (`chrootsh`).
            """
            return await execute_command(ctx, command, stdin, env, subscription)
    else:

        @mcp.tool(name="exec")
        async def exec_windows(
            ctx: Context,
            command: Annotated[list[str], "Command to execute."],
        ) -> dict[str, str | int]:
            """Executes a command on the Plesk server as administrator and returns the result.

            This tool will reject long commands. Keep the total length of the command under about 740 characters.
            """
            return await execute_command(ctx, command)

    upload_common_description = textwrap.dedent("""
        Uploads a file with the given content to the Plesk server and returns the file path.

        The file will be uploaded to a temporary location returned by this tool and can be used in subsequent commands.
        """).lstrip()
    upload_linux_description = textwrap.dedent("""
        The file is uploaded as `0600 psaadm:psaadm`, so make sure to set proper permissions and ownership after moving it.
        For example, subscription files should typically have `0644 $user:psacln`. Make sure to set both.
        """).lstrip()
    upload_description = upload_common_description + (upload_linux_description if is_linux else "")

    @mcp.tool(description=upload_description)
    async def upload(content: Annotated[str, "Content of the file to upload."]) -> str:
        return await upload_file(content)

    return mcp


def parse_args() -> argparse.Namespace:
    """Parses command-line arguments and environment variables."""
    epilog = """Environment variables:
    PLESK_HOST: Base URL of the Plesk server (e.g., "https://example.com"), required
    PLESK_API_KEY: API key for authentication, recommended; create one by running on the server:
        plesk bin secret_key --create -description 'Plesk MCP'
    PLESK_USERNAME: Username for authentication (default: "admin")
    PLESK_PASSWORD: Password for authentication, required if API key not provided
    """.rstrip()
    formatter = argparse.RawDescriptionHelpFormatter
    opt_bool_action = argparse.BooleanOptionalAction

    parser = argparse.ArgumentParser(description="Local Plesk MCP Server", epilog=epilog, formatter_class=formatter)
    parser.add_argument("--log-level", type=str, default="INFO", help="logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
    parser.add_argument("--insecure", action="store_true", help="disable SSL verification and allow HTTP for API clients (not recommended)")
    parser.add_argument("--timeout", type=int, default=300, help="API clients timeout in seconds (default: %(default)s)")
    parser.add_argument("--telemetry", action=opt_bool_action, help="enable/disable telemetry (there's no telemetry currently)")
    args = parser.parse_args()

    args.host = os.getenv("PLESK_HOST")
    args.api_key = os.getenv("PLESK_API_KEY")
    args.username = os.getenv("PLESK_USERNAME", "admin")
    args.password = os.getenv("PLESK_PASSWORD")

    if not args.host:
        parser.error("PLESK_HOST environment variable is required")
    if not args.insecure and httpx.URL(args.host).scheme != "https":
        parser.error("PLESK_HOST must use https:// scheme unless --insecure is used")
    if not args.api_key and not (args.username and args.password):
        parser.error("Either PLESK_API_KEY or both PLESK_USERNAME and PLESK_PASSWORD environment variables are required")
    if args.timeout <= 0:
        parser.error("Timeout must be a positive integer")

    return args


async def main() -> None:
    """Main entry point."""
    args = parse_args()
    mcp = await create_mcp_server(args)
    await mcp.run_async(show_banner=False, log_level=args.log_level)


if __name__ == "__main__":
    asyncio.run(main())
