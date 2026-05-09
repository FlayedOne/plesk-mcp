# Changelog

## 0.1.1 (Unreleased)

### Internal Changes

- Added a pytest test suite (unit tests plus opt-in smoke tests requiring `OPENAI_API_KEY`) covering the database management helpers and the `query` tool.
- Added a GitHub Actions workflow running ruff (lint + format check), mypy and the unit tests.

## 0.1.0 (2026-04-12)

### Features

- Initial release.
- Provided tools:
  - `query` for querying the documentation
- Automatic documentation database update.
