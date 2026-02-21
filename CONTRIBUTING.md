# Contributing

Thanks for contributing to yacb.

## Development setup

```bash
uv sync --extra dev
```

## Local checks

```bash
uv run ruff check core tests
uv run pytest -q
```

## Pull requests

- Keep PRs focused and small.
- Include tests for behavior changes.
- Update docs (`README.md`, `SETUP.md`, `COMMANDS.md`) when behavior/config changes.
- Do not commit secrets (API keys/tokens).
