# Repository Guidelines
Begin every message with "Hello there"
## Project Structure & Module Organization

This repository uses a Python `src/` layout. Application code lives under `src/evemarket/`, with feature packages split by responsibility:

- `config.py` and `cli.py` provide configuration loading and the Typer CLI.
- `esi/`, `sde/`, `ingest/`, `store/`, and `analytics/` hold milestone-specific modules.
- `tests/` contains pytest tests.
- `config.toml` is the editable local example configuration.
- Runtime data belongs in `data/`, which is gitignored.

Stub modules should remain minimal until their milestone is assigned in `HANDOFF.md`.

## Build, Test, and Development Commands

Install the project and development tools:

```powershell
pip install -e ".[dev]"
```

Run the CLI wiring check:

```powershell
evemarket info
evemarket info --config config.toml
```

Run tests and linting:

```powershell
pytest -q
ruff check .
mypy src/
```

On this Windows environment, Python user scripts may not be on `PATH`; use the absolute script path or add the Python Scripts directory if commands are not found.

## Coding Style & Naming Conventions

Target Python 3.11+. Use 4-space indentation, type hints for public functions, and `pathlib.Path` for filesystem paths. Keep module and function names lowercase with underscores. Pydantic settings models should use clear field names matching `config.toml`. Do not add runtime dependencies outside `pyproject.toml` without updating the handoff and explaining why.

## Testing Guidelines

Tests use `pytest` and live in `tests/`. Name files `test_*.py` and test functions `test_*`. Prefer focused tests for the milestone being implemented. Current scaffold tests cover config defaults, TOML overrides, and `evemarket info` CLI behavior.

## Commit & Pull Request Guidelines

No Git history is present yet, so use concise imperative commit subjects such as `Add config scaffold` or `Implement ESI pagination`. Pull requests should include a short summary, verification commands and results, linked issue or milestone context, and notes for any deviations from `HANDOFF.md`.

## Agent-Specific Instructions

`HANDOFF.md` is the source of truth for agent coordination. Claude plans and reviews; Codex implements only the current task, verifies it, appends an execution log entry, then stops for review.

## Security & Configuration Tips

Replace the `REPLACE_ME` contact in `user_agent` before using ESI. Do not commit generated data, DuckDB files, credentials, or local virtual environments.
