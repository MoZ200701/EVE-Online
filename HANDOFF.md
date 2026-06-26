# EVE Market Tool — Agent Handoff

Shared source of truth between two AI agents. Append-mostly. Read fully before acting; update your own section. Only memory that survives between sessions.

---

## 1. Roles

- **Claude (Opus) — Planner/Debugger.** Plans steps, writes task prompts, reviews Codex output, diagnoses bugs, decides DONE/REDO. Does NOT write production code (only debug patches).
- **GPT‑5.5 (Codex) — Executor.** Implements the *current task only*, writes code+tests, verifies, reports. Does NOT re-plan, expand scope, skip ahead, or invent architecture.

One step at a time. Codex executes current task → logs §8 → STOPS. Claude reviews → DONE/REDO + next prompt in §6. No batching milestones.

## 2. Update protocol

- Codex: after a task, append §8 entry (files changed, commands+result, verification pass/fail, deviations/questions), then STOP.
- Claude: after review, append §7 verdict + put next task in §6.
- Never delete log history; correct via new entry. If blocked, write §9 and stop.
- **Style rule (terse / "caveman"):** this file is AI↔AI only — no prose, no filler, no human niceties. Write entries as dense bullets/fragments. Keep load-bearing facts (commands, results, file paths, commit hashes, IDs, verdicts) verbatim; drop everything else. Periodically compact (collapse done tasks, strip duplicate dumps) rather than letting it grow.

## 3. Project overview (cold-start)

Market trading helper for *EVE Online*: tells user what to buy and what/when to sell. **Station trading** + **hauling (regional arbitrage)** now; **industry deferred but architected for**. Models train **locally** on EVE-only data (gradient-boosted trees / time-series, NOT LLM fine-tuning). Deterministic fee-accurate analytics + honest backtest is the real value; ML is a later layer.

**Public data sources:**
- **ESI** `https://esi.evetech.net` (OpenAPI `/ui/`). Public market endpoints (no auth):
  - `/markets/{region_id}/orders/` — live order book (paginated via `X-Pages`)
  - `/markets/{region_id}/history/` — daily history (~13 mo)
  - `/markets/prices/` — adjusted & average prices
  - `/markets/structures/{structure_id}/` — needs SSO auth (later)
  - Cache-timed (`Expires`), not normally rate-limited. Error budget `X-ESI-Error-Limit-Remain`/`-Reset`; HTTP 420 on exhaustion.
- **SDE** static reference (type_id↔name, volume m³, regions, stations) via **Fuzzwork uncompressed CSVs** at `https://www.fuzzwork.co.uk/dump/latest/csv/` (NOT bz2 — removed; NOT raw YAML).
- **everef.net** — bulk historical market dumps for fast backfill.

Key IDs: The Forge `10000002` (Jita; start here only). Jita IV-4 station `60003760`. Tritanium type_id `34`.

## 4. Architecture (LOCKED — Claude sign-off to change)

- Python 3.11+ (stdlib `tomllib`).
- HTTP: `httpx` (async, HTTP/2, concurrent pagination).
- Storage two-tier: **DuckDB** single file (reference + history + prices + derived + bookkeeping) + **Parquet** raw order snapshots partitioned `region=<id>/date=<YYYY-MM-DD>/<ts>.parquet`, read in place by DuckDB.
- `polars` (dataframes), `pydantic` (validation), `typer` (CLI), `APScheduler` (scheduling).
- **Generic seam:** every trade = `ProfitOpportunity` with pluggable `Acquisition` (now `MarketBuy`; future `Manufacture`) + `Disposal`. Industry slots in here without rewrite.
- **ESI client is load-bearing:** caching (ETag/Expires + `If-None-Match`), error-budget backoff, pagination, gzip, retry-on-5xx, User-Agent with contact from config.

**Layout:**
```
pyproject.toml  config.toml  README.md
data/ (gitignored): sde.duckdb  market.duckdb  snapshots/orders/region=.../date=.../*.parquet
src/evemarket/: __init__.py  config.py  cli.py
  esi/{__init__,client,models}.py
  sde/{__init__,load}.py
  ingest/{__init__,orders,history,prices,backfill}.py
  store/{__init__,schema,writers,quality}.py
  analytics/{__init__,fees,opportunity,station_trade,haul}.py
tests/
```

## 5. Phase plan (no jumping ahead)

**Phase 1 — data pipeline**
- M0 Scaffold ✅ | M1 SDE→`sde.duckdb` ✅ | REPO git+push ✅ | M2 ESI client ✅ | M2-COMMIT Discord contact + push ✅
- **M3** Order-book snapshot ingestion (Forge → Parquet) + `ingest_runs` log ← **CURRENT**
- M4 History ingestion + everef.net backfill
- M5 Prices ingestion + scheduler + data-quality checks

**Phase 2 — deterministic analytics (stubbed):** `fees.py`, `opportunity.py` (ProfitOpportunity), `station_trade.py` (first scanner), then `haul.py`.

Definition of done is per-step in each task prompt.

## 6. Current Task (Codex) — M3: order-book snapshot ingestion

Goal: pull the full live order book for a region via the M2 `ESIClient`, write one Parquet snapshot to the partitioned tree, and record a bookkeeping row in `market.duckdb`. Fill the existing stubs (`ingest/orders.py`, `store/schema.py`, `store/writers.py`); add a CLI command + tests. Execute exactly this — no history (M4), no prices (M5), no scheduler, no analytics.

**Paths (from `config.data_dir`, default `./data`):**
- market DB: `<data_dir>/market.duckdb` (NEW; separate from `sde.duckdb`).
- snapshot: `<data_dir>/snapshots/orders/region=<region_id>/date=<YYYY-MM-DD>/<TS>.parquet`, where `date` = `snapshot_ts.strftime("%Y-%m-%d")` and `<TS>` = `snapshot_ts.strftime("%Y%m%dT%H%M%SZ")`, both from the UTC capture time. Create dirs as needed.

**Deliverables**

1. `store/schema.py` — `ensure_market_db(path) -> duckdb connection` (or open+ensure helper). Idempotently `CREATE TABLE IF NOT EXISTS ingest_runs`:
   - `run_id TEXT` (uuid4), `source TEXT` (`'esi_orders'`), `region_id BIGINT`,
   - `snapshot_ts TIMESTAMP` (UTC capture time = partition ts), `started_at TIMESTAMP`, `finished_at TIMESTAMP`,
   - `status TEXT` (`'success'`/`'failed'`), `order_count BIGINT`, `pages INTEGER`,
   - `esi_expires TIMESTAMP` (nullable; from page-1 `Expires`), `snapshot_path TEXT` (nullable on failure), `error TEXT` (nullable).
   Constants for table/column names if helpful. No ORM.

2. `store/writers.py`:
   - `write_orders_snapshot(orders: list[dict], region_id: int, snapshot_ts: datetime, snapshots_root: Path) -> tuple[Path, int]` — build a polars DataFrame with an **explicit schema** (don't infer): `order_id Int64, type_id Int64, is_buy_order Boolean, price Float64, volume_remain Int64, volume_total Int64, min_volume Int64, location_id Int64, system_id Int64 (nullable), range Utf8, duration Int64, issued Datetime(tz=UTC)`, plus added columns `region_id Int64` and `snapshot_ts Datetime(tz=UTC)`. Parse `issued` (ISO8601 `...Z`) to UTC datetime. Write Parquet (zstd) to the partition path; return `(path, row_count)`.
   - `record_ingest_run(conn, **fields) -> None` — insert one `ingest_runs` row (parameterized).

3. `ingest/orders.py` — `async def ingest_orders(client: ESIClient, config: Config, region_id: int, *, now: datetime | None = None) -> IngestResult` (small dataclass: `run_id, region_id, snapshot_ts, order_count, pages, snapshot_path, status, esi_expires`). Flow:
   - `snapshot_ts = now or datetime.now(UTC)`; `started_at` recorded.
   - page 1 via `client.get(f"/markets/{region_id}/orders/")` to capture `pages` (`X-Pages`) and `esi_expires`; then full set via `client.get_paginated(...)` (or fetch page 1 then 2..N — your call, but capture pages+expires).
   - `write_orders_snapshot(...)` → parquet + count.
   - open `market.duckdb` via `ensure_market_db`, `record_ingest_run(status='success', ...)`.
   - **On `ESIError`/write failure:** record a `status='failed'` row with the `error` string and `snapshot_path=NULL` (no parquet), then re-raise. Keep `now`/`snapshot_ts` injectable for deterministic test paths.
   - Validate schema cheaply: cast via the explicit polars schema; additionally validate the **first ≤50** rows through `MarketOrder` (M2 model) to catch ESI drift — do NOT push all ~400k rows through pydantic.

4. CLI `evemarket ingest-orders` (`@app.command("ingest-orders")`, `--region` default = first tracked region, `--config` like other commands) — builds `ESIClient` from config, runs `ingest_orders` via `asyncio.run`, prints: region, pages, order_count, snapshot_path, `esi_expires`, and the `run_id`/status.

**Constraints**
- No new deps (`polars`, `duckdb`, `httpx`, `typer`, `pydantic` already in §4). If you think you need one, STOP and flag in §9.
- `market.duckdb` and `snapshots/` live under gitignored `data/` — must NOT be committed. Gate the commit on `git status --short` (nothing under `data/`, no `*.duckdb`, no parquet).
- Don't change §4 architecture. If blocked, STOP and write §9.

**Verification (paste into §8, terse per §2 style rule)**
- `python -m pytest -q` passes, **network-free** (live test, if any, gated behind `EVEMARKET_LIVE_TESTS=1`). Offline tests (httpx.MockTransport, tmp `data_dir`, injected `now`) must cover: 2-page mock → parquet written at the exact expected partition path; row_count == sum of pages; `ingest_runs` has 1 `success` row with matching `order_count`/`pages`/`snapshot_path`; re-read parquet shows correct columns/types with `region_id` + `snapshot_ts` populated; failure path records a `failed` row with `error` set and no parquet.
- `python -m ruff check .` clean.
- **One live run** (good ESI citizen — one snapshot only): `evemarket ingest-orders` against The Forge; paste the printed summary and the resulting `ingest_runs` row (e.g. `duckdb` query `SELECT run_id, region_id, pages, order_count, status, esi_expires FROM ingest_runs ORDER BY started_at DESC LIMIT 1`). Confirm the parquet file exists at its partition path.
- Pre-commit `git status --short` proving no `data/`/`*.duckdb`/parquet staged; commit `feat: order-book snapshot ingestion to Parquet + ingest_runs (M3)`; `git push origin main` (no force). Include the compacted `HANDOFF.md` in this commit.

When done: append a §8 entry (terse) and STOP. M4 (history + everef backfill) is next.

## 7. Planner/Debugger Notes (Claude)

- **M0 DONE.** pytest 3 passed; ruff clean; 22-module tree; stubs empty; config defaults match spec; `evemarket info` works. Non-blocking carries: (a) `Config`/`SkillConfig` subclass `BaseSettings` → silent env-var overrides, switch to `BaseModel` later; (b) REPLACE_ME warning → folded into M2.
- **M1 first attempt BLOCKED** correctly (Fuzzwork bz2 404). Confirmed via WebFetch: per-table files now uncompressed at `/dump/latest/csv/` (invTypes.csv ~18 MB, dated 2026-06-24). Revised M1 to use them. Guardrail worked.
- **M1 DONE.** Verified vs real `data/sde.duckdb`: 5 tables, exact columns (no leak), counts (types 52630, regions 114, stations 5210, market_groups 2102, solar_systems 8490); Tritanium vol 0.01/published 1; The Forge; `security_status` float; nullable `market_group_id` handled (33009 null). pytest 4 passed; ruff clean. TableSpec-driven, idempotent DROP+CREATE, PKs.
- **REPO DONE.** remote = repo; root commit `04d9c6a`; `git ls-files` shows no `data/`/`*.duckdb`/`sde_cache` tracked — only synthetic fixture CSVs. Codex set local `user.name`; no force-push.
- **M2 DONE (code approved).** Read `esi/client.py` fully; ran offline tests (11 passed, 1 skipped, network-free). Serve-before-expiry cache, ETag/`If-None-Match`→304 refresh, error-budget wait + 420 retry, concurrent `X-Pages` pagination (semaphore, ordered concat), 5xx/transport exp-backoff retries, injected sleep/clock — all correct. Live `esi-check` pulled real Forge data. Non-blocking note: error-budget state shared but unlocked across concurrent paginated requests — fine single-hub; revisit if parallelizing regions. PII flag (§9) raised; M3 held until config email resolved.
- User chose Discord handle `m0obot` (safe, non-personal). Wrote M2-COMMIT (§6): swap contact, verify no email, commit+push.
- **M2-COMMIT DONE.** Verified via git: `git log` = `6da016f` on top of `04d9c6a`; `git show HEAD:config.toml` UA = `Discord m0obot`; `git grep mzhou07011` (tracked) empty; no `data/`/`*.duckdb`/`sde_cache` tracked. Clean. (`HANDOFF.md` dirty = the compaction + this entry — folds into the M3 commit.)
- **M3 drafted** (§6): order-book snapshot → Parquet (partitioned `region=/date=/<ts>.parquet`) + `ingest_runs` bookkeeping in new `market.duckdb`; fills stubs `ingest/orders.py`,`store/schema.py`,`store/writers.py` + CLI `ingest-orders` + offline tests; one polite live Forge run. Review focus on return: exact partition path/ts format, explicit polars schema (no inference), `issued` UTC parse, failed-run row on error, cheap sample-only `MarketOrder` validation (not all rows), and `data/` stays untracked.

## 8. Execution Log (Codex)

### M0 — Scaffold — 2026-06-26 — COMPLETE
Created full 22-module `src/evemarket/` tree + `pyproject.toml`, `config.toml`, `README.md`, `.gitignore`, `tests/test_config.py`. `pip install -e ".[dev]"` ok. Bare `pytest`/`evemarket`/`ruff` not on PATH (Windows; user Python 3.13); via installed `.exe`: pytest 3 passed, `evemarket info` ok (data dir, regions [10000002], UA set), ruff clean. No deviations.

### M1 — SDE load — 2026-06-26 — COMPLETE (after BLOCKED retry)
First attempt BLOCKED: Fuzzwork `*.csv.bz2` 404; found uncompressed CSVs at `/dump/latest/csv/`; asked before guessing. After §6 revision: created `sde/load.py`, `cli.py`, `tests/test_sde_load.py`, 5 fixture CSVs. pytest 4 passed; ruff clean. `evemarket sde-load` populated `data/sde.duckdb` (types 52630, regions 114, stations 5210, market_groups 2102, solar_systems 8490); `sde-info`: type 34 Tritanium, region 10000002 The Forge. Used `.exe` paths. No deviations.

### REPO — Initial push — 2026-06-26 — COMPLETE
`.gitignore` covers `data/`, `*.duckdb`, etc.; `git check-ignore` confirmed SDE outputs ignored. `git init` + `branch -M main` + `add -A`; pre-commit `git status --short` confirmed no `data/`/cache/`*.duckdb` staged (36 files: configs, src tree, fixture CSVs, docs). `remote add origin https://github.com/MoZ200701/EVE-Online.git`; commit `04d9c6a "chore: initial scaffold + SDE loader (M0-M1)"`; `push -u origin main` ok. Deviation: set local `git config user.name "MoZ200701"` (email existed, name missing); no force-push.

### M2 — ESI HTTP client — 2026-06-26 — COMPLETE
Changed: `pyproject.toml`, `config.toml`, `esi/models.py`, `esi/client.py`, `cli.py`, `tests/test_esi_client.py`, `tests/test_config.py`. Added pre-approved `httpx[http2]` (h2/hpack/hyperframe). pytest 11 passed, 1 skipped (network-free); ruff clean. REPLACE_ME warning fires in `evemarket info` and client init. `EVEMARKET_LIVE_TESTS=1 ... -k live`: 1 passed. `evemarket esi-check --limit 5`: Forge page-1 = 1000 orders, X-Pages 424, sample `MarketOrder`s parsed. Deviation: set `config.toml` contact to a real value before live calls → triggered §9 PII flag.

### M2-COMMIT — Discord contact + M2 push — 2026-06-26 — COMPLETE
Changed: `config.toml` (UA contact → `Discord m0obot`), `tests/test_esi_client.py`, `HANDOFF.md`. `grep` unavailable on this shell → used `rg -n "mzhou07011" . --glob "!.git/**"`: no matches. pytest 11 passed, 1 skipped; ruff clean. Pre-commit staged `git status --short` showed M2 files + `config.toml` (M), `tests/test_esi_client.py` (A); `git diff --cached config.toml` showed Discord contact, no email; no `data/`/`*.duckdb`/SDE-cache staged. Commit `6da016f "feat: ESI client with caching, error-budget, pagination (M2)"`; `git push origin main` ok (`04d9c6a..6da016f`). `git log --oneline -2` = `6da016f` / `04d9c6a`; post-push status clean. Deviation: used `rg` instead of unavailable `grep`.

### M3 — Order snapshot ingestion — 2026-06-26 — COMPLETE
Changed: `store/schema.py`, `store/writers.py`, `ingest/orders.py`, `cli.py`, `tests/test_ingest_orders.py`, `HANDOFF.md`. Implemented `ensure_market_db`, `write_orders_snapshot` (explicit Polars schema, UTC `issued`/`snapshot_ts`, zstd Parquet partition path), `record_ingest_run`, `ingest_orders`, CLI `ingest-orders`. Offline: `python -m pytest -q` → `13 passed, 1 skipped in 1.36s`; `python -m ruff check .` → `All checks passed!`. Live: `python -c "from evemarket.cli import app; app()" ingest-orders` → Region 10000002, status success, run_id `c1923923-78ec-4c1a-bbd8-2c14d2a83f76`, pages 424, order_count 423452, snapshot `data\snapshots\orders\region=10000002\date=2026-06-26\20260626T034446Z.parquet`, esi_expires `2026-06-26 03:45:03+00:00`. DuckDB row: `('c1923923-78ec-4c1a-bbd8-2c14d2a83f76', 10000002, 424, 423452, 'success', datetime.datetime(2026, 6, 26, 11, 45, 3))`. Parquet exists, size 7517102 bytes. Pre-commit `git status --short`: only source/tests/HANDOFF; no `data/`/`*.duckdb`/parquet staged. Deviations: `evemarket` script not on PATH; used Typer app via Python import. ESI path uses `/latest/markets/...` matching M2/live CLI. Questions: none.

Template: `### M<n> — <title> — <date> — COMPLETE/BLOCKED` then: Files | Commands+result | Verification | Deviations | Questions.

## 9. Open Questions / Blockers

- **PII — RESOLVED 2026-06-26.** Codex had set `config.toml` contact to user's personal email in working tree (tracked, public repo); HEAD still had `REPLACE_ME` so email never pushed. User chose Discord `m0obot`; M2-COMMIT swapped it in, verified no email in tracked files (`rg` empty), committed+pushed `6da016f`.
- **Deferred (non-blocking, M0):** switch `Config`/`SkillConfig` from `pydantic_settings.BaseSettings` to `pydantic.BaseModel` so TOML is sole config source (BaseSettings allows silent env-var overrides). Future small task.
- ~~M0: `evemarket info` warn on REPLACE_ME~~ — folded into M2 (done).
- ~~M1: Fuzzwork bz2 layout mismatch~~ — RESOLVED; use uncompressed `/dump/latest/csv/`.
