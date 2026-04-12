# Plesk Documentation MCP Server

This [MCP server](https://modelcontextprotocol.io) provides information from [Plesk documentation](https://docs.plesk.com) and [Plesk support portal](https://support.plesk.com/hc/en-us) to AI agents and apps. It allows them to answer questions about Plesk features and capabilities, and provide instructions on how to perform various tasks in Plesk.

This MCP server is read-only. It runs locally on your machine, and uses only the following to process queries:
1. OpenAI embeddings API to convert queries into vectors. This is very cheap. This helps to find relevant documents in the database.
2. LLM sampling feature of the MCP protocol to generate answers based on the retrieved documents. This is billed as part of your agent or app usage.

Compared to the [plesk-remote-docs-mcp MCP server](../remote-docs/README.md), this server doesn't post queries to a remote service controlled by Plesk developers. Instead, it uses a local database that is periodically updated with the latest Plesk documentation and support articles.

## MCP Server Requirements

You will need `uv` Python package manager to run the server. Refer to the [official documentation](https://docs.astral.sh/uv/getting-started/installation/) for installation instructions.

You will also need to provide an OpenAI API key with access to the embeddings API.

## Usage

Configure the server in your VS Code `mcp.json` or equivalent (in other agents or apps) using a configuration like:

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
        }
    }
}
```

You may want to use env file (e.g. via `"envFile"` parameter) if your agent or app supports it. This will avoid putting the API key directly in the config file.

See `uvx plesk-local-docs-mcp@latest --help` for details on available options and environment variables.
