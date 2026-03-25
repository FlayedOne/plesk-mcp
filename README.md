# Plesk MCP Server

This [MCP server](https://modelcontextprotocol.io) for [Plesk](https://www.plesk.com) allows administrators to manage their Plesk servers using various AI agents and apps. It builds on top of [Plesk REST API](https://docs.plesk.com/en-US/obsidian/api-rpc/about-rest-api.79359/) and provides core administration capabilities, as well as ability to manage the server through shell commands and upload files to the server.

The MCP server runs locally on your machine, so important information doesn't leave your environment.

## Plesk Requirements

The MCP server is expected to support any sufficiently recent Plesk version (there are no strict limitations) and any OS (Linux or Windows) that Plesk supports. However, it was tested only on Plesk Obsidian 18.0.76, so prefer using a [supported Plesk version](https://endoflife.date/plesk).

Obviously, API access must not be disabled on the server.

## MCP Server Requirements

You will need `uv` Python package manager to run the server. Refer to the [official documentation](https://docs.astral.sh/uv/getting-started/installation/) for installation instructions.

## Usage

Configure the server in your `mcp.json` or equivalent using a configuration like:

```json
{
    "servers": {
        "plesk": {
            "command": "uv",
            "args": [
                "run",
                "pleskmcp.py"
            ],
            "env": {
                // Base URL of your Plesk server. May include port.
                // If you don't have a valid TLS certificate or want to use HTTP,
                // add the --insecure flag to the args above.
                // However, this is not recommended as you credentials may be leaked as a result.
                "PLESK_HOST": "https://plesk.example.net:8443",
                // API key (recommended).
                // Create via `plesk bin secret_key --create -description 'Plesk MCP'` on the server.
                "PLESK_API_KEY": "00000000-0000-0000-0000-000000000000",
                // Alternatively, you can use username and password.
                "PLESK_USERNAME": "admin",
                "PLESK_PASSWORD": "passwd"
            }
        }
    }
}
```

## Development

MCP server run command:

```bash
uv run pleskmcp.py --log-level debug --insecure
```

Before commit:

```bash
uv run ruff format
uv run ruff check --fix
uv run mypy .
```
