# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Always begin each response with "Hello there"
## Role in this project

Claude is the **planner and debugger** — not the primary code author. GPT-5.5 (Codex) executes implementation tasks. The full protocol is in `HANDOFF.md`, which is the authoritative source of truth between agents.

**Before acting in any session:** read `HANDOFF.md` in full — especially §6 (Current Task), §7 (Planner Notes), and §8 (Execution Log).

**Claude's output goes into `HANDOFF.md`:** verdicts (DONE / REDO + why), bug diagnoses, and the next task prompt in §6.

## Commands (once M0 scaffold is complete)

```powershell
# Install (from project root)
pip install -e ".[dev]"

# Run tests
pytest -q

# Run a single test file
pytest tests/test_config.py -v

# Lint
ruff check .

# Type-check
mypy src/

# Verify CLI wiring
evemarket info
evemarket info --config config.toml
```

## Architecture

**Language:** Python 3.11+, `src/` layout, package name `evemarket`.

**Storage — two-tier:**
- `data/sde.duckdb` — static reference data (item names, volumes, regions) loaded from the Fuzzwork SDE SQLite conversion.
- `data/market.duckdb` — history, prices, derived tables, ingestion bookkeeping. Reads Parquet in-place.
- `data/snapshots/orders/region=<id>/date=<YYYY-MM-DD>/<ts>.parquet` — raw order-book snapshots.

**Key libraries:** `httpx` (async HTTP/2), `polars` (dataframes), `duckdb`, `pydantic`/`pydantic-settings`, `typer` (CLI), `APScheduler`.

**Core abstraction:** every trade is a `ProfitOpportunity` with a pluggable `Acquisition` (currently `MarketBuy`; future `Manufacture`) and `Disposal`. Industry/manufacturing slots in later via this seam without a rewrite.

**ESI client** (`src/evemarket/esi/client.py`) is load-bearing: must handle ETag/Expires caching, `X-ESI-Error-Limit-Remain` backoff, pagination (`X-Pages`), gzip, retry-on-5xx, and a `User-Agent` header with contact info from config.

**Data sources:**
- ESI `https://esi.evetech.net` — live order books, daily history, prices (public, no auth for market endpoints).
- Fuzzwork SDE SQLite — static reference.
- `everef.net` — bulk historical dumps for fast backfill without hammering ESI.

**Starting scope:** The Forge region only (`region_id = 10000002`, Jita).

## Phase plan

| Phase | Milestones | Status |
|-------|-----------|--------|
| **Phase 1 — data pipeline** | M0 Scaffold → M1 SDE → M2 ESI client → M3 Order snapshots → M4 History/backfill → M5 Prices/scheduler/quality | M0 pending |
| **Phase 2 — analytics** | fees.py, ProfitOpportunity interface, station_trade scanner, haul scanner | Stubbed during Phase 1 |

## Architecture decisions (locked — require explicit sign-off to change)

These are set and must not be altered without updating §4 of `HANDOFF.md` and getting explicit approval:

- Python 3.11+ (use `tomllib` from stdlib, not an extra dep).
- `httpx` for HTTP (not `requests` or `aiohttp`).
- DuckDB + Parquet two-tier storage (not SQLite-only, not a database server).
- `polars` for dataframes (not pandas).
- `pydantic-settings` for config loaded from `config.toml`.
- `typer` for CLI.
- `APScheduler` for scheduling.
