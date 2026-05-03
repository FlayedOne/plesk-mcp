# Changelog

## 0.1.1 (Unreleased)

### Bug Fixes

- Fixed incorrect URL construction in API client configuration when `PLESK_HOST` ends with a trailing slash.

### Internal Changes

- Added demo mode, which doesn't require a Plesk instance. Activated by setting `PLESK_HOST` to a URL like `https://demo.example.net` or `https://windows.demo.example.net:8443`.

## 0.1.0 (2026-03-26)

### Features

- Initial release.
- Provided tools:
  - `api_list_tags`, `api_list`, `api_help`, `api_call` for REST API access
  - `exec` for executing shell commands on the server
  - `upload` for uploading files to the server
- Supported REST APIs:
  - Plesk
  - WP Toolkit (WordPress management extension for Plesk), if installed
- Supported authentication methods:
  - API key (recommended)
  - Username and password, note that REST API supports only administrator accounts
- Supported Plesk versions: expected to work on any recent version, but tested only on Plesk Obsidian 18.0.76.
- Supported server OSes: all OSes supported by Plesk (Linux and Windows). `exec` tool support on Windows is limited.
- Support for insecure connection methods (`--insecure` flag).
- Customizable API clients timeout (`--timeout` option).
