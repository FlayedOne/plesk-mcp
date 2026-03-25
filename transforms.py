"""FastMCP transforms."""

from collections.abc import Sequence
from typing import Annotated, Any

from fastmcp import Context
from fastmcp.server.transforms import GetToolNext
from fastmcp.server.transforms.catalog import CatalogTransform
from fastmcp.server.transforms.search.base import serialize_tools_for_output_markdown
from fastmcp.tools import Tool, ToolResult
from fastmcp.utilities.logging import get_logger
from fastmcp.utilities.versions import VersionSpec
from mcp.types import ToolAnnotations

logger = get_logger(__name__)


class ApiListTransform(CatalogTransform):
    """Transforms all tools into `api_call`, `api_list`, `api_list_tags`, and `api_help` tools."""

    _call_tool_name: str = "api_call"
    _help_tool_name: str = "api_help"
    _list_tool_name: str = "api_list"
    _list_tags_tool_name: str = "api_list_tags"

    def __init__(self, name: str, always_visible: list[str] | None = None) -> None:
        """Creates an ApiListTransform.

        `name` is used in tool descriptions when referencing the API.
        `always_visible` is a list of tool names that should not be transformed.
        """
        super().__init__()
        self._name = name
        self._always_visible = set(always_visible or [])

    async def transform_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        """Transform the tool catalog."""
        logger.debug(f"Transforming {len(tools)} tools with ApiListTransform")
        call_api_tool = self._make_call_api_tool()
        list_api_tool = self._make_list_api_tool()
        help_api_tool = self._make_help_api_tool()
        list_tags_api_tool = self._make_list_tags_api_tool()
        pinned = [t for t in tools if t.name in self._always_visible]
        return [list_tags_api_tool, list_api_tool, help_api_tool, call_api_tool, *pinned]

    async def get_tool(self, name: str, call_next: GetToolNext, *, version: VersionSpec | None = None) -> Tool | None:
        """Get a tool by name."""
        if name == self._call_tool_name:
            return self._make_call_api_tool()
        elif name == self._list_tool_name:
            return self._make_list_api_tool()
        elif name == self._help_tool_name:
            return self._make_help_api_tool()
        elif name == self._list_tags_tool_name:
            return self._make_list_tags_api_tool()
        else:
            return await call_next(name, version=version)

    def _is_synthetic_tool(self, name: str) -> bool:
        return name in {self._call_tool_name, self._list_tool_name, self._help_tool_name, self._list_tags_tool_name}

    async def _get_tools_to_transform(self, ctx: Context) -> Sequence[Tool]:
        tools = await self.get_tool_catalog(ctx)
        return [t for t in tools if not self._is_synthetic_tool(t.name) and t.name not in self._always_visible]

    def _reject_synthetic_tools(self, name: str) -> None:
        if self._is_synthetic_tool(name):
            raise ValueError(f"{name!r} name is reserved and cannot be used in this tool.")

    def _make_call_api_tool(self) -> Tool:
        """Dynamically creates `api_call` tool that executes a transformed tool."""

        async def call_api(
            ctx: Context,
            name: Annotated[str, f"Name of the API to call. List available with {self._list_tool_name} tool."],
            params: Annotated[dict[str, Any], f"API call parameters. MUST check expected schema with {self._help_tool_name} tool."],
        ) -> ToolResult:
            self._reject_synthetic_tools(name)
            logger.info(f"Calling API {name!r} with params {params!r}")
            return await ctx.fastmcp.call_tool(name, params)

        return Tool.from_function(
            fn=call_api,
            name=self._call_tool_name,
            description=(
                f"Call {self._name} API. "
                f"Do not use any preconceived notions about how to use {self._name} API. "
                f"Instead validate usage with {self._help_tool_name} tool."
            ),
        )

    def _make_list_api_tool(self) -> Tool:
        """Dynamically creates `api_list` tool that lists available transformed tools."""

        async def list_api(
            ctx: Context,
            tags: Annotated[
                list[str] | None,
                f"Optional list of tags to filter APIs (otherwise all APIs are listed). "
                f"List tags with {self._list_tags_tool_name} tool. Prefer setting this field to reduce output.",
            ] = None,
        ) -> str:
            tools = await self._get_tools_to_transform(ctx)
            if tags:
                tools = [t for t in tools if any(tag in t.tags for tag in tags)]

            if tools:
                blocks = [
                    f"Each Markdown header is an API name. Use it as is in the {self._help_tool_name} tool to understand how to call it.",
                    f"List of APIs matching {tags or []} tags.",
                ]
                blocks += [f"### `{t.name}`\n{t.description or 'No description.'}" for t in tools]
                return "\n\n".join(blocks)
            return f"No APIs found matching {tags or []} tags. List tags with {self._list_tags_tool_name} tool."

        return Tool.from_function(
            fn=list_api,
            name=self._list_tool_name,
            description=f"List available {self._name} APIs.",
            annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
        )

    def _make_list_tags_api_tool(self) -> Tool:
        """Dynamically creates `api_list_tags` tool that lists available tool tags."""

        async def list_tags_api(
            ctx: Context,
        ) -> str:
            tools = await self._get_tools_to_transform(ctx)
            all_tags = sorted({tag for t in tools for tag in t.tags})
            if all_tags:
                return (
                    f"Available tags: {', '.join(all_tags)} . "
                    f"Call {self._list_tool_name}(tags=[\"tag1\", \"tag2\"]) tool to list APIs matching relevant tags."
                )
            else:
                return f"No tags are available. Call {self._list_tool_name}() tool now."

        return Tool.from_function(
            fn=list_tags_api,
            name=self._list_tags_tool_name,
            description=f"List available {self._name} API tags. Start here to explore {self._name} APIs.",
            annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
        )

    def _make_help_api_tool(self) -> Tool:
        """Dynamically creates `api_help` tool that provides help for a specific tool."""

        async def help_api(
            ctx: Context,
            name: Annotated[str, "Name of the API to describe."],
        ) -> str:
            self._reject_synthetic_tools(name)
            tool = await ctx.fastmcp.get_tool(name)
            if tool is None:
                return f"No API found with name {name!r}. Select the name as is from the {self._list_tool_name} tool output."  # noqa: S608
            else:
                return serialize_tools_for_output_markdown([tool])

        return Tool.from_function(
            fn=help_api,
            name=self._help_tool_name,
            description=f"Explain how to call a specific {self._name} API.",
            annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True),
        )
