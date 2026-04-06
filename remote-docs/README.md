# Plesk Documentation MCP Server

This [MCP server](https://modelcontextprotocol.io) provides information from [Plesk documentation](https://docs.plesk.com) and [Plesk support portal](https://support.plesk.com/hc/en-us) to AI agents and apps. It allows them to answer questions about Plesk features and capabilities, and provide instructions on how to perform various tasks in Plesk.

This MCP server is read-only, and doesn't require additional configuration. It runs locally on your machine, but the queries themselves are posted to a remote service controlled by Plesk developers.

## MCP Server Requirements

You will need `uv` Python package manager to run the server. Refer to the [official documentation](https://docs.astral.sh/uv/getting-started/installation/) for installation instructions.

## Usage

Configure the server in your VS Code `mcp.json` or equivalent (in other agents or apps) using a configuration like:

```json
{
    "servers": {
        "plesk": {
            "command": "uvx",
            "args": [
                "plesk-remote-docs-mcp@latest"
            ]
        }
    }
}
```

See `uvx plesk-remote-docs-mcp@latest --help` for details on available options and environment variables.
