# Plesk MCP Server

This [MCP server](https://modelcontextprotocol.io) for [Plesk](https://www.plesk.com) allows administrators to manage their Plesk servers using various AI agents and apps. It builds on top of [Plesk REST API](https://docs.plesk.com/en-US/obsidian/api-rpc/about-rest-api.79359/) and WP Toolkit REST API, and provides core administration capabilities, as well as ability to manage the server through shell commands and upload files to the server.

The MCP server runs locally on your machine, so important information doesn't leave your environment.

## Plesk Requirements

The MCP server is expected to support any sufficiently recent Plesk version (there are no strict limitations) and any OS (Linux or Windows) that Plesk supports. However, it was tested only on Plesk Obsidian 18.0.76, so prefer using a [supported Plesk version](https://endoflife.date/plesk).

Obviously, API access must not be disabled on the server.

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
                "plesk-mcp@latest"
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

You may want to use env file (e.g. via `"envFile"` parameter) if your agent or app supports it. This will avoid putting credentials directly in the config file.

See `uvx plesk-mcp@latest --help` for details on available options and environment variables.

## Recommended Usage

For better behavior, it's recommended to use this MCP server in combination with a documentation MCP server. Select either [plesk-local-docs-mcp](local-docs/README.md) or [plesk-remote-docs-mcp](remote-docs/README.md). This will allow the agent to get more accurate information about Plesk usage when needed.

You may also attach several Plesk servers at once if needed (e.g. for managing multiple servers).

Here's an example configuration:

```json
{
    "servers": {
        "plesk-docs": {
            "command": "uvx",
            "args": [
                "plesk-local-docs-mcp@latest"
            ],
            "env": {
                "OPENAI_API_KEY": "sk-..."
            }
        },
        "plesk1": {
            "command": "uvx",
            "args": [
                "plesk-mcp@latest"
            ],
            "env": {
                "PLESK_HOST": "https://plesk1.example.net:8443",
                "PLESK_API_KEY": "00000000-0000-0000-0000-000000000000"
            }
        },
        "plesk2": {
            "command": "uvx",
            "args": [
                "plesk-mcp@latest"
            ],
            "env": {
                "PLESK_HOST": "https://plesk2.example.net",
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
uv run plesk-mcp --log-level debug --insecure
```

Before commit:

```bash
uv run ruff format
uv run ruff check --fix
uv run mypy .
```

Publish:

```bash
uv build --clear
uv publish
```
