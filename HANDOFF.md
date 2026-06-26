# EVE Market Tool — Agent Handoff

Shared source of truth between two AI agents. Append-mostly. Read fully before acting; update your own section. Only memory that survives between sessions.

---

## 1. Roles

- **Claude (Opus) — Planner/Debugger + Context-assembler.** Plans steps, writes task prompts, reviews Codex output, diagnoses bugs, decides DONE/REDO. Does NOT write production code (only debug patches). **Owns ALL workspace exploration:** reads the tree, pins down cross-file contracts / data shapes / conventions, and packs them into each §6 task as a self-contained **Context Pack** so Codex never has to scan the repo.
- **GPT‑5.5 (Codex) — Executor (closed-world).** Writes the code for the files named in the current task's Context Pack — nothing else. Does NOT explore the workspace for context (no scanning/grepping/reading other files to "understand" the codebase), re-plan, expand scope, skip ahead, or invent architecture. Everything it needs is in the pack; if a symbol/signature/detail is missing, STOP + write §9 — do NOT go find it. Running `pytest`/`ruff` for verification is fine (mechanical, not exploration).

One step at a time. Claude packs context → Codex writes the named files → logs §8 → STOPS. Claude reviews → DONE/REDO + next prompt in §6. No batching milestones.

## 2. Update protocol

- Claude: every §6 task MUST open with a **Context Pack** (see template below) — all cross-file contracts/shapes/conventions Codex needs, so it writes blind to the rest of the tree. If the pack is incomplete, that's a planner bug, not a Codex excuse to explore.
- Codex: write ONLY the files named in the pack. Do not read/scan other files for context. After a task, append §8 entry (files changed, commands+result, verification pass/fail, deviations/questions), then STOP. Missing context → STOP + §9.
- Claude: after review, append §7 verdict + put next task in §6.
- Never delete log history; correct via new entry. If blocked, write §9 and stop.
- **Style rule (terse / "caveman"):** this file is AI↔AI only — no prose, no filler, no human niceties. Write entries as dense bullets/fragments. Keep load-bearing facts (commands, results, file paths, commit hashes, IDs, verdicts) verbatim; drop everything else. Periodically compact (collapse done tasks, strip duplicate dumps) rather than letting it grow.

**Context Pack template (Claude fills, opens every §6 task):**
- **Files in scope** — exact list to create/edit. For files being EDITED, paste current relevant contents/signatures so Codex doesn't guess. Codex touches nothing else.
- **Caller contracts** — verbatim signature + 1-line semantics of every cross-file symbol the task calls (functions, classes, config fields, exceptions). Not whole files — just what's invoked.
- **Data shapes** — exact JSON/dict structure + key types for any external/inter-module data the code handles.
- **Conventions to mirror** — project-specific rules in play (explicit polars schema, UTC `TIMESTAMPTZ`, no new deps, terse, etc.).
- **Boundary** — "Do not read/scan files outside this pack. Missing detail → STOP + §9."

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
- `polars` (dataframes), `pydantic` (validation), `typer` (CLI), `APScheduler` (scheduling), `pytz` (DuckDB TIMESTAMPTZ↔Python; approved M3-FIX2).
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
- M0 Scaffold ✅ | M1 SDE→`sde.duckdb` ✅ | REPO git+push ✅ | M2 ESI client ✅ | M3 Order snapshots + `ingest_runs` ✅ | M4a ESI daily history → `market_history` ✅ | M4b everef.net bulk backfill ✅ | M5a ESI prices → `market_prices` ✅
- **M5** Prices ✅ | scheduler (M5b) ✅ | data-quality (M5c) ← **CURRENT: M5c drafted (§6) — Codex to execute (LAST of Phase 1)**

**Phase 2 — deterministic analytics (stubbed):** `fees.py`, `opportunity.py` (ProfitOpportunity), `station_trade.py` (first scanner), then `haul.py`.

Definition of done is per-step in each task prompt.

## 6. Current Task (Codex) — M5c: data-quality checks → `quality.py` + `quality-check` CLI

M5b DONE (§7). **M5 split → M5a (prices) ✅ | M5b (scheduler) ✅ | M5c (data-quality, THIS — LAST of Phase 1).** This = M5c only: a READ-ONLY quality module that inspects the already-populated `market.duckdb` tables and returns pass/warn/fail check results, plus a CLI `quality-check` command. **NO writes/mutations to any table, NO new ingest, NO scheduler changes, NO analytics.** **CLOSED-WORLD: write only the listed files; all you need is in the Context Pack. Missing detail → STOP + §9, do NOT scan the tree.**

### CONTEXT PACK

**Files in scope (touch nothing else):**
- EDIT `src/evemarket/store/quality.py` — currently a stub (`"""Data quality checks stub."""` + `# TODO: M5`). Replace its body with the `QualityCheck` dataclass + `run_quality_checks` + private `_check_*` fns.
- EDIT `src/evemarket/cli.py` — add `quality-check` command (append a new `@app.command`; do NOT touch existing commands).
- CREATE `tests/test_quality.py`.
- EDIT `HANDOFF.md` §8 (log).

**DB tables to inspect (verbatim DDL — already created by `ensure_market_db`; quality.py only SELECTs, never writes):**
- `ingest_runs(run_id TEXT, source TEXT, region_id BIGINT, snapshot_ts TIMESTAMPTZ, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, status TEXT, order_count BIGINT, pages INTEGER, esi_expires TIMESTAMPTZ, snapshot_path TEXT, error TEXT)`. `status` ∈ {`'success'`,`'failed'`}.
- `market_history(region_id BIGINT, type_id BIGINT, date DATE, average DOUBLE, highest DOUBLE, lowest DOUBLE, order_count BIGINT, volume BIGINT, PK(region_id,type_id,date))`.
- `market_prices(type_id BIGINT, adjusted_price DOUBLE, average_price DOUBLE, snapshot_ts TIMESTAMPTZ, PK(type_id,snapshot_ts))`. NOTE: `average_price` is legitimately NULL for ~12% of rows (do NOT flag null `average_price`); `adjusted_price` is expected present + positive.

**Caller contracts (verbatim — already exist, just call them):**
- `evemarket.store.schema.ensure_market_db(path: str|Path) -> duckdb.DuckDBPyConnection` — opens `market.duckdb`, `SET TimeZone='UTC'`, ensures the 3 tables above, `with`-able. Reading TIMESTAMPTZ cols returns tz-aware UTC `datetime` (pytz is a declared dep). Reading a `DATE` col returns `datetime.date`.
- `evemarket.config.Config` — `data_dir: Path` (market db = `config.data_dir.expanduser()/"market.duckdb"`). `evemarket.config.load_config(path) -> Config`.
- DuckDB conn API: `conn.execute("SELECT ...").fetchone()` → tuple or `None`; `.fetchall()` → list of tuples.
- **For TESTS ONLY** (to seed rows — use these existing writers, all in `evemarket.store.writers`):
  - `write_prices(conn, prices: list[dict], snapshot_ts: datetime) -> int` — each dict `{"type_id": int, "adjusted_price": float|None, "average_price": float|None}`; upserts into `market_prices` at `snapshot_ts`.
  - `write_history_bulk(conn, rows: list[dict]) -> int` — each row carries ALL 8 keys: `date` (a `datetime.date`), `average`,`highest`,`lowest` (float), `order_count`,`volume` (int), `region_id`,`type_id` (int). Upserts into `market_history`.
  - `record_ingest_run(conn, **fields)` — required keys `run_id, source, region_id, snapshot_ts, started_at, finished_at, status, order_count, pages`; optional `esi_expires, snapshot_path, error`. Pass tz-aware UTC datetimes for ts cols.
  - (Tests may also seed via raw `conn.execute("INSERT ...")` using the DDL above — either is fine.)
- CLI pattern (mirror existing commands in `cli.py`): `@app.command("quality-check")`, `--config/-c` default `Path("config.toml")` → `load_config(...)`. `typer`, `Path`, `load_config` already imported at top of `cli.py`; add `from evemarket.store.schema import ensure_market_db` and `from evemarket.store.quality import run_quality_checks`.

**Deliverables / decisions (do exactly this):**
1. **`QualityCheck`** (frozen dataclass in `quality.py`): `name: str`, `status: str` (one of `"ok"`/`"warn"`/`"fail"`), `detail: str`.
2. **`run_quality_checks(conn, *, now=None, max_price_age_hours: float = 24.0, max_history_age_days: int = 3) -> list[QualityCheck]`** — `now = _ensure_utc(now or datetime.now(timezone.utc))` (inject `now` for deterministic stale tests). Returns the 5 checks below IN THIS ORDER. Each `_check_*` takes what it needs and returns one `QualityCheck`. Add a private `_ensure_utc(value)` helper (tz-naive→assume UTC; else `astimezone(UTC)`) mirroring the one in `writers.py`.
3. **`_check_stale_prices(conn, now, max_price_age_hours)`** — name `"stale_prices"`. `latest = conn.execute("SELECT max(snapshot_ts) FROM market_prices").fetchone()[0]`. If `None` → `("warn","no price snapshots")`. Else `latest=_ensure_utc(latest)`; `age_h=(now-latest).total_seconds()/3600`; status `"warn"` if `age_h > max_price_age_hours` else `"ok"`; detail `f"latest={latest.isoformat()} age={age_h:.1f}h"`.
4. **`_check_stale_history(conn, now, max_history_age_days)`** — name `"stale_history"`. `latest = SELECT max(date) FROM market_history`. If `None` → `("warn","no history rows")`. Else `age_d=(now.date()-latest).days`; status `"warn"` if `age_d > max_history_age_days` else `"ok"`; detail `f"latest={latest.isoformat()} age={age_d}d"`.
5. **`_check_price_anomalies(conn)`** — name `"price_anomalies"`, inspect the LATEST snapshot only. `latest_ts = SELECT max(snapshot_ts) FROM market_prices`. If `None` → `("ok","no price snapshots")`. Else: `neg = SELECT count(*) FROM market_prices WHERE snapshot_ts = ? AND adjusted_price < 0`; `nul = SELECT count(*) FROM market_prices WHERE snapshot_ts = ? AND adjusted_price IS NULL` (bind `latest_ts`). status: `"fail"` if `neg>0`; elif `nul>0` `"warn"`; else `"ok"`. detail `f"negative={neg} null_adjusted={nul} (latest snapshot)"`. (Do NOT consider `average_price` — legitimately nullable.)
6. **`_check_history_anomalies(conn)`** — name `"history_anomalies"`. `bad = SELECT count(*) FROM market_history WHERE highest < lowest OR average < 0 OR lowest < 0 OR highest < 0 OR volume < 0 OR order_count < 0`. status `"fail"` if `bad>0` else `"ok"`; detail `f"{bad} invalid rows"`. (Strict `< 0` / `highest<lowest` only — do NOT flag legit zeros, avoids false positives on real data.)
7. **`_check_failed_runs(conn)`** — name `"failed_runs"`. `bad = SELECT count(*) FROM ingest_runs WHERE status='failed'`. If `bad==0` → `("ok","no failed runs")`. Else fetch latest: `SELECT source, error FROM ingest_runs WHERE status='failed' ORDER BY started_at DESC LIMIT 1`; status `"warn"`; detail `f"{bad} failed runs; latest {source}: {error}"`.
8. **CLI `quality-check`** — opts `--config/-c` (default `config.toml`); `--max-price-age-hours` (float, default 24.0); `--max-history-age-days` (int, default 3). Flow: `cfg=load_config(config)`; `market_db = cfg.data_dir.expanduser()/"market.duckdb"`; `with ensure_market_db(market_db) as conn: checks = run_quality_checks(conn, max_price_age_hours=..., max_history_age_days=...)`; for each: `typer.echo(f"[{c.status.upper()}] {c.name}: {c.detail}")`. After printing, if `any(c.status=="fail" for c in checks)` → `raise typer.Exit(code=1)` (nonzero exit on FAIL is intentional for ops/monitoring; lines still print first).

**DEFERRED (do NOT add in M5c):** history **gap-detection** (missing dates between min/max per region/type) and **row-count-delta vs prior run** (compare latest two `ingest_runs.order_count` per source) — both are follow-up checks; out of scope here. Do not implement.

**Conventions to mirror:** READ-ONLY (SELECT only — never INSERT/UPDATE/DELETE in quality.py); tz-aware UTC handling via `_ensure_utc`; injectable `now` for deterministic stale tests; strict-`<0` anomaly predicates (no false positives on zeros); no new deps (`duckdb`/stdlib only); terse; `data/`/`*.duckdb` stay untracked.

**Constraints** — no new deps; don't change §4 locked decisions; do NOT modify existing `cli.py` commands or any ingest/store/schema code (quality.py is the only store file edited); `data/` untracked (gate `git status --short`). Blocked/missing-context → STOP, write §9.

**Verification (paste §8, terse per §2):**
- `python -m pytest -q` pass, network-free (seed a tmp `market.duckdb` via `ensure_market_db` + writers, inject `now`):
  - **all-good** db (fresh prices snapshot at `now`, history `date=now.date()`, valid values, no failed runs) → all 5 checks `"ok"`.
  - **stale** (prices `snapshot_ts=now-48h`, history `date=now-10d`) → `stale_prices` + `stale_history` `"warn"`.
  - **price_anomalies**: latest snapshot with a negative `adjusted_price` → `"fail"`; a snapshot whose only issue is a NULL `adjusted_price` → `"warn"`; a legit NULL `average_price` alone → `"ok"`.
  - **history_anomalies**: a row with `highest < lowest` → `"fail"`.
  - **failed_runs**: one `record_ingest_run(status='failed', ...)` → `"warn"` with the source/error in detail.
  - **empty** db → `stale_prices`/`stale_history` `"warn"` (no rows), other 3 `"ok"`.
  - Existing M5b/M5a/M4/M3 tests stay green.
- `python -m ruff check .` clean.
- Live (READ-ONLY, no network): `evemarket quality-check` against the real `market.duckdb` (already holds M5a prices + M4 history); paste the 5 printed `[STATUS] name: detail` lines + the process exit code. (A nonzero exit only if a real FAIL is present — that's the check working.)
- Pre-commit `git status --short`: no `data/`/`*.duckdb`/parquet staged (expect `store/quality.py`, `cli.py`, `tests/test_quality.py`, `HANDOFF.md`). Commit `feat: data-quality checks + quality-check CLI (M5c)`; `git push origin main` (no force). Include `HANDOFF.md`.

When done: append §8 entry (terse, **INCLUDE the commit hash**) and STOP. M5c completes Phase 1 — after it, Phase 2 (deterministic analytics: `fees.py` → `opportunity.py` → `station_trade.py`) begins.

<!-- ===== M5b task (DONE, kept for reference) ===== -->
### [DONE] M5b: APScheduler wiring → recurring ingest jobs

`scheduler.py`: `build_scheduler(config, *, scheduler=None, orders_interval_minutes=5, prices_interval_minutes=60)` → UTC `BlockingScheduler` with 2 interval jobs (`orders`, `prices`, `coalesce/max_instances=1/replace_existing`); sync `run_orders_job`/`run_prices_job` wrappers (`asyncio.run` + `ESIClient`, injectable `ingest=`, swallow+log exceptions → `None`/`[]`). CLI `schedule --orders-interval/--prices-interval/--dry-run`. History scheduling deferred. Committed `169bde0` (also cleared the AGENTS.md closed-world workflow loose end).

<!-- ===== M5a task (DONE, kept for reference) ===== -->
### [DONE] M5a: ESI market prices ingestion → `market_prices`

Endpoint `client.get("/latest/markets/prices/")` — public, GLOBAL, NOT paginated, ~16k entries `{type_id, adjusted_price, average_price}` (`average_price` optional). `MarketPrice` model (both prices `float|None`); `market_prices(type_id,adjusted_price,average_price,snapshot_ts, PK(type_id,snapshot_ts))`; `write_prices` explicit `PRICE_SCHEMA` + temp-stage `ON CONFLICT` upsert; async `ingest_prices` (`region_id=None`, source='esi_prices', sample-validate ≤50); CLI `ingest-prices`. Committed `9666724`. Full pack preserved in git history if needed.

<!-- ===== M4b task (DONE, kept for reference) ===== -->
### [DONE] M4b: everef.net bulk backfill → `market_history`

### CONTEXT PACK

**Files in scope (touch nothing else):**
- CREATE `src/evemarket/ingest/backfill.py` — `backfill_history_everef(...)` + `BackfillResult`.
- EDIT `src/evemarket/store/writers.py` — add `write_history_bulk`; refactor existing `write_history` to share a private upsert helper (behavior-preserving — M4a tests MUST stay green).
- EDIT `src/evemarket/cli.py` — add `backfill-history` command.
- CREATE `tests/test_backfill_history.py`.
- EDIT `HANDOFF.md` §8 (log).

**everef data source (researched, verbatim):**
- URL pattern: `https://data.everef.net/market-history/{YYYY}/market-history-{YYYY-MM-DD}.csv.bz2` (year subdir = the date's year). bz2-compressed CSV, ONE file per day = ALL regions & ALL types (~53.7k rows/day). Decompress with stdlib `bz2`. Same data as ESI `/history/` but full history (no ~13mo cap).
- CSV header (exact order): `average,date,highest,lowest,order_count,volume,http_last_modified,region_id,type_id`
- Sample row: `1.88,2025-06-15,1.88,1.88,24,2034687,2025-06-16T11:01:54Z,10000001,34`
- `date` = `YYYY-MM-DD`. `http_last_modified` = ISO ts metadata → **DROP** (not in our table). Filter to ONE region via `region_id == <region>`.
- A given day file may be ABSENT (HTTP 404) → that's normal, skip it (count it), do NOT fail the run.

**Caller contracts (verbatim — already exist, just call them):**
- `evemarket.store.schema.ensure_market_db(path: str|Path) -> duckdb.DuckDBPyConnection` — opens `market.duckdb`, `SET TimeZone='UTC'`, ensures `ingest_runs` + `market_history` tables. Supports `with` (context-managed). Table `market_history(region_id BIGINT, type_id BIGINT, date DATE, average DOUBLE, highest DOUBLE, lowest DOUBLE, order_count BIGINT, volume BIGINT, PRIMARY KEY(region_id,type_id,date))`.
- `evemarket.store.writers.record_ingest_run(conn, **fields) -> None` — INSERTs one `ingest_runs` row. Required keys: `run_id, source, region_id, snapshot_ts, started_at, finished_at, status, order_count, pages`. Optional (default NULL): `esi_expires, snapshot_path, error`. (`ingest_runs` ts cols are TIMESTAMPTZ — pass tz-aware UTC datetimes.)
- Existing `evemarket.store.writers.write_history(conn, region_id, type_id, days: list[dict]) -> int` — builds polars DF on `HISTORY_SCHEMA`, stages into a TEMP duckdb table via `executemany`, then `INSERT INTO market_history ... ON CONFLICT (region_id,type_id,date) DO UPDATE SET ...`. **Refactor:** extract its temp-stage+upsert body into private `_upsert_history_frame(conn, frame: pl.DataFrame) -> int` (frame cols exactly = `HISTORY_SCHEMA` order); `write_history` builds its frame then calls it; new `write_history_bulk` does the same with multi-(type,date) rows. Keep `write_history`'s public behavior identical.
- `HISTORY_SCHEMA` (already in writers.py) = `{date: pl.Date, average: pl.Float64, highest: pl.Float64, lowest: pl.Float64, order_count: pl.Int64, volume: pl.Int64, region_id: pl.Int64, type_id: pl.Int64}`.
- `evemarket.config.Config` fields used: `data_dir: Path` (market db = `config.data_dir.expanduser()/"market.duckdb"`), `user_agent: str` (send as `User-Agent` header on downloads), `tracked_regions: list[int]` (CLI default region = `[0]`). `load_config(path)->Config`.
- CLI pattern: Typer `@app.command("backfill-history")`, `--config/-c` default `Path("config.toml")`, `--region` default None→`load_config(...).tracked_regions[0]`. (No ESIClient — everef is plain static files, sync.)

**Deliverables / decisions (do exactly this):**
1. `BackfillResult` dataclass (frozen): `run_id: str, region_id: int, start_date: date, end_date: date, days_fetched: int, days_missing: int, row_count: int, status: str`.
2. `def backfill_history_everef(config, region_id, start_date: date, end_date: date, *, fetch=None, sleep=None, now=None) -> BackfillResult` — **sync** (not async).
   - Injectables for offline test: `fetch: Callable[[str], bytes | None]` (returns raw bz2 bytes, or `None` for HTTP 404/missing → skip); `sleep: Callable[[float], None]` (politeness delay between files, default `time.sleep`, ~0.5s); `now` → snapshot_ts (default `datetime.now(timezone.utc)`).
   - Default `fetch`: `httpx.Client` GET with `User-Agent: config.user_agent`; status 404 → return `None`; other non-2xx → `resp.raise_for_status()`; return `resp.content`.
   - Flow: `run_id=uuid4`; `started_at=now_utc`; iterate dates `start_date..end_date` inclusive; build URL; `raw = fetch(url)`; if `None` → `days_missing += 1`, continue; else `data = bz2.decompress(raw)`; parse with polars `pl.read_csv(io.BytesIO(data), schema_overrides=EVEREF_CSV_SCHEMA)` (explicit schema, NO inference — define `EVEREF_CSV_SCHEMA` for all 9 cols; read `date` as `pl.Utf8` then `.with_columns(pl.col("date").str.to_date("%Y-%m-%d"))`); `.filter(pl.col("region_id")==region_id)`; select the 8 `HISTORY_SCHEMA` cols in order; if non-empty collect its `.to_dicts()` into the accumulator and `days_fetched += 1`; `sleep(delay)` between files.
   - After loop: open `with ensure_market_db(...)`; `row_count = write_history_bulk(conn, all_rows)` (0 if none); `record_ingest_run(status='success', source='everef_history', region_id, snapshot_ts=now, started_at, finished_at=now_utc, order_count=row_count, pages=days_fetched, esi_expires=None, snapshot_path=None)`. Return success `BackfillResult`.
   - On ANY exception (after a non-404 fetch error / decompress / parse / write): open a fresh `ensure_market_db`, `record_ingest_run(status='failed', source='everef_history', order_count=0, pages=days_fetched, error=str(exc), esi_expires=None, snapshot_path=None, ...)`, re-raise. (404→None is NOT an error.)
3. `write_history_bulk(conn, rows: list[dict]) -> int` in writers.py — rows carry the 8 `HISTORY_SCHEMA` keys (`date` already a `datetime.date`); build polars DF on `HISTORY_SCHEMA` (strict), call shared `_upsert_history_frame`. Return rows upserted (frame height). Empty rows → return 0 (no-op, don't crash).
4. CLI `backfill-history` — opts `--config`, `--region` (default first tracked), `--start`/`--end` as `YYYY-MM-DD` strings (parse to `date`). If BOTH omitted → polite default: `end = (utcnow - 1 day).date()` (yesterday UTC; today's file may not exist yet), `start = end - 2 days` (3 files). Call `backfill_history_everef`; print region, status, run_id, start, end, days_fetched, days_missing, row_count.

**Conventions to mirror:** explicit polars schemas (no inference); idempotent upsert on PK (re-run = stable count, the KEY test); tz-aware UTC datetimes for `ingest_runs`; no new deps (`bz2`,`csv`,`io`,`time` stdlib; `httpx`,`polars`,`duckdb` already deps); terse; `data/`/`*.duckdb`/parquet stay untracked.

**Constraints** — no new deps; don't change §4 locked decisions; `data/` untracked (gate `git status --short`). Blocked/missing-context → STOP, write §9.

**Verification (paste §8, terse per §2):**
- `python -m pytest -q` pass, network-free (inject `fetch` returning in-memory bz2 bytes, inject `sleep` no-op, tmp `data_dir`, injected `now`): build bz2 CSV with 2 dates incl rows for `10000002` AND another region → assert `market_history` has ONLY region `10000002` rows w/ correct values+types (date=`pl.Date`, floats/ints right); **re-run same range = no dupes** (row count stable); `ingest_runs` 1 `success` row `source='everef_history'`, `order_count`=rows, `pages`=days_fetched; a 404 date (fetch→None) → `days_missing` increments, run still `success`; a non-404 fetch error → `failed` row (error set) + raises; existing M4a + M3 tests stay green.
- `python -m ruff check .` clean.
- One polite live run: `backfill-history` (default 3-day range) vs Forge; paste printed summary + `SELECT count(*), min(date), max(date) FROM market_history WHERE region_id=10000002` + the `ingest_runs` row (`source='everef_history'`).
- Pre-commit `git status --short`: no `data/`/`*.duckdb`/parquet staged. Commit `feat: everef.net bulk market-history backfill → market_history (M4b)`; `git push origin main` (no force). Include `HANDOFF.md`.

When done: append §8 entry (terse, **INCLUDE the commit hash**) and STOP. After M4b → M5 (prices + scheduler + data-quality).

<!-- ===== M4a task (DONE, kept for reference) ===== -->
### [DONE] M4a: ESI daily history ingestion → `market_history`

Endpoint: `client.get("/latest/markets/{region_id}/history/", params={"type_id": tid})` — public, NOT paginated (one JSON array per type). Each day row: `date` (`YYYY-MM-DD`), `average`, `highest`, `lowest` (float ISK), `order_count` (int), `volume` (int). ~13 months/type.

Storage: DuckDB `market.duckdb` table `market_history` (§4: history lives in DuckDB, NOT parquet). Reuse `ensure_market_db` + existing `ingest_runs` for bookkeeping.

**Deliverables**

1. `esi/models.py` — add `MarketHistoryDay` (pydantic): `date: datetime.date, average: float, highest: float, lowest: float, order_count: int, volume: int`.

2. `store/schema.py` — in `ensure_market_db` also `CREATE TABLE IF NOT EXISTS market_history`:
   - `region_id BIGINT, type_id BIGINT, date DATE, average DOUBLE, highest DOUBLE, lowest DOUBLE, order_count BIGINT, volume BIGINT`
   - `PRIMARY KEY (region_id, type_id, date)`. Leave `ingest_runs` unchanged.

3. `store/writers.py` — `write_history(conn, region_id, type_id, days: list[dict]) -> int`: build polars DF with **explicit schema** (`date pl.Date, average/highest/lowest pl.Float64, order_count/volume pl.Int64`) + add `region_id`/`type_id` cols; parse `date` str→date. **Idempotent UPSERT** on PK via `INSERT INTO market_history ... ON CONFLICT (region_id, type_id, date) DO UPDATE SET ...` (or DELETE-by-(region,type)+INSERT in one txn). Return rows written. Register DF with DuckDB to insert (no row-by-row).

4. `ingest/history.py` — `async def ingest_history(client, config, region_id, type_ids: list[int], *, now=None) -> HistoryIngestResult` (dataclass: `run_id, region_id, type_ids, day_count, types_fetched, status, esi_expires`). Flow: record `started_at`/`run_id`/`snapshot_ts=now or utcnow`; for each tid → `client.get(...)`, capture `esi_expires` from FIRST call, validate **first ≤50** day rows/type via `MarketHistoryDay` (sample, not all), `write_history(...)` accumulate `day_count`. Then open `ensure_market_db`, `record_ingest_run(status='success', source='esi_history', region_id, snapshot_ts, order_count=day_count, pages=len(type_ids), snapshot_path=NULL, esi_expires)`. On any `ESIError`/write fail → record `status='failed'` row (source='esi_history', error set, order_count=0, snapshot_path NULL) + re-raise. `now` injectable.

5. CLI `evemarket ingest-history` — `--region` default first tracked region, `--type` repeatable int (default `[34]` Tritanium for polite first run), `--config`. Build `ESIClient`, `asyncio.run`, print region, types_fetched, day_count, run_id/status, esi_expires.

**Constraints** — no new deps; `market.duckdb`/parquet stay untracked (gate `git status --short`); don't change §4. Blocked → STOP, write §9.

**Verification (paste §8, terse per §2):**
- `python -m pytest -q` pass, network-free (MockTransport, tmp `data_dir`, injected `now`): 2 types × N days → `market_history` rows correct (region_id+type_id+date, right types); **re-run same data = no dupes** (idempotent, row count stable); `ingest_runs` has 1 `success` row `source='esi_history'` w/ matching `order_count`(day_count)/`pages`; failure path → `failed` row, error set; existing M3 tests stay green.
- `python -m ruff check .` clean.
- One polite live run: `ingest-history --type 34` vs Forge; paste printed summary + `SELECT type_id, count(*), min(date), max(date) FROM market_history GROUP BY type_id` + the `ingest_runs` row (`source='esi_history'`).
- Pre-commit `git status --short`: no `data/`/`*.duckdb`/parquet staged. Commit `feat: ESI daily market history ingestion → market_history (M4)`; `git push origin main` (no force). Include `HANDOFF.md`.

When done: append §8 entry (terse, **INCLUDE the commit hash** — M3-FIX2 omitted it) and STOP. M4b (everef.net bulk backfill) next.

## 7. Planner/Debugger Notes (Claude)

- **M0 DONE.** pytest 3 passed; ruff clean; 22-module tree; stubs empty; config defaults match spec; `evemarket info` works. Non-blocking carries: (a) `Config`/`SkillConfig` subclass `BaseSettings` → silent env-var overrides, switch to `BaseModel` later; (b) REPLACE_ME warning → folded into M2.
- **M1 first attempt BLOCKED** correctly (Fuzzwork bz2 404). Confirmed via WebFetch: per-table files now uncompressed at `/dump/latest/csv/` (invTypes.csv ~18 MB, dated 2026-06-24). Revised M1 to use them. Guardrail worked.
- **M1 DONE.** Verified vs real `data/sde.duckdb`: 5 tables, exact columns (no leak), counts (types 52630, regions 114, stations 5210, market_groups 2102, solar_systems 8490); Tritanium vol 0.01/published 1; The Forge; `security_status` float; nullable `market_group_id` handled (33009 null). pytest 4 passed; ruff clean. TableSpec-driven, idempotent DROP+CREATE, PKs.
- **REPO DONE.** remote = repo; root commit `04d9c6a`; `git ls-files` shows no `data/`/`*.duckdb`/`sde_cache` tracked — only synthetic fixture CSVs. Codex set local `user.name`; no force-push.
- **M2 DONE (code approved).** Read `esi/client.py` fully; ran offline tests (11 passed, 1 skipped, network-free). Serve-before-expiry cache, ETag/`If-None-Match`→304 refresh, error-budget wait + 420 retry, concurrent `X-Pages` pagination (semaphore, ordered concat), 5xx/transport exp-backoff retries, injected sleep/clock — all correct. Live `esi-check` pulled real Forge data. Non-blocking note: error-budget state shared but unlocked across concurrent paginated requests — fine single-hub; revisit if parallelizing regions. PII flag (§9) raised; M3 held until config email resolved.
- User chose Discord handle `m0obot` (safe, non-personal). Wrote M2-COMMIT (§6): swap contact, verify no email, commit+push.
- **M2-COMMIT DONE.** Verified via git: `git log` = `6da016f` on top of `04d9c6a`; `git show HEAD:config.toml` UA = `Discord m0obot`; `git grep mzhou07011` (tracked) empty; no `data/`/`*.duckdb`/`sde_cache` tracked. Clean. (`HANDOFF.md` dirty = the compaction + this entry — folds into the M3 commit.)
- **M3 drafted** (§6): order-book snapshot → Parquet (partitioned `region=/date=/<ts>.parquet`) + `ingest_runs` bookkeeping in new `market.duckdb`; fills stubs `ingest/orders.py`,`store/schema.py`,`store/writers.py` + CLI `ingest-orders` + offline tests; one polite live Forge run. Review focus on return: exact partition path/ts format, explicit polars schema (no inference), `issued` UTC parse, failed-run row on error, cheap sample-only `MarketOrder` validation (not all rows), and `data/` stays untracked.
- **M3 REVIEW: REDO-lite.** Read all M3 code; `13 passed,1 skipped`; ruff clean. Code strong — explicit polars schema, partition path/ts format, `issued` UTC parse, success/fail split, sample-only `MarketOrder` validation, `data/` untracked: all correct. 1 REAL bug: `ingest_runs` ts cols stored LOCAL not UTC (tz-aware datetime → DuckDB naive `TIMESTAMP` localizes wall-clock + strips tz). Reproduced `03:45:03+00:00`→`11:45:03` (UTC+8); visible in M3 §8 log (printed esi_expires `03:45:03+00:00` vs DB row `11:45:03`). Breaks DB `snapshot_ts` ↔ parquet partition-ts tie + cross-machine reproducibility. Tests missed: DuckDB asserts skip both ts cols (parquet asserts OK b/c polars preserves tz). Fix → M3-FIX (§6): TIMESTAMPTZ + ts read-back test. Minors folded into §6: esi_expires falls back to `now()` on missing Expires header (spec=nullable, low-pri); Config still `BaseSettings` (deferred §9). M0–M2 stay DONE.
- **M3-FIX REVIEW: REDO (hidden dep).** Schema fix correct (4 `TIMESTAMPTZ`, `SET TimeZone='UTC'`), committed `c1dacf8`, tree clean, read-back test good. But Codex verification INVALID: `13 passed` only b/c manual `pip install pytz` (noted §8, never declared in `pyproject.toml`). Planner clean-env `python -m pytest -q` → `1 failed, 12 passed, 1 skipped`: `InvalidInputException: Required module 'pytz' failed to import` at TIMESTAMPTZ `fetchone()` (L143). DuckDB needs pytz to read tz cols → Python; writes OK (failed-row insert passes). Latent crash for M4/M5/quality/analytics (all read `ingest_runs`) on fresh install. Fix → M3-FIX2 (§6): declare pytz dep (planner sign-off; §4 deps line updated). Process note for Codex: "no new deps" means STOP+flag in §9 if you need one — never silently `pip install` to make tests pass. M4 held until suite green in clean env. M0–M2 stay DONE.
- **M3-FIX2 DONE — M3 fully COMPLETE.** `pytz` declared in `pyproject.toml` deps (L17); committed `c228ca9`, pushed (no unpushed, tree clean). Planner verified in the SAME env that failed before: fresh `pip install -e .` pulled `pytz 2026.2` (transitive via declared dep, not manual), then `python -m pytest -q` → `13 passed, 1 skipped`. Clean-env regression closed. Codex §8 omitted the commit hash (minor log gap) but commit exists + pushed. **M3 (order ingestion + UTC TIMESTAMPTZ + pytz) signed off DONE.** Next: M4 (history ingestion + everef backfill).
- **M4 drafted (split M4a/M4b).** Milestone "history + everef" too big for one step → M4a = ESI daily history → DuckDB `market_history` (PK region+type+date, idempotent upsert, sample-only `MarketHistoryDay` validation, `ingest_runs` source='esi_history', CLI `ingest-history`, offline+1 polite live run); M4b = everef.net bulk backfill (next). History → DuckDB table NOT parquet (§4). Review focus on return: explicit polars schema, idempotent re-run (no dupes is the key test), date parse, failed-run row, history in DuckDB not parquet, `data/` untracked, AND commit hash present in §8 (chased Codex on this).
- **M4a REVIEW: DONE.** Read all M4a code (`models.py`,`schema.py`,`writers.py`,`history.py`,`cli.py`,test). Planner clean-env (bare `python`, all deps present, NO manual installs — M3-FIX2 trap closed): `pytest --basetemp <scratch>` → `16 passed,1 skipped`; `ruff` clean. All focus pts pass: explicit `HISTORY_SCHEMA` polars (strict); idempotent via `ON CONFLICT (region,type,date) DO UPDATE` — test confirms count stable=2 across 2 runs; `date` str→`pl.Date` (`date.fromisoformat`); `market_history` in DuckDB not parquet; failed path → `failed` row, order_count=0, error set (test asserts `HTTP 400`); `data/` untracked (`git status` clean, `check-ignore data/market.duckdb`=`.gitignore:1:data/`); commit `b51e885` present in §8 (+ `afac067` docs log). Live: Tritanium 420 days `2025-05-01..2026-06-24`, success `ingest_runs` row correct. **Deviations (accepted, Codex-flagged):** (a) `conn.register(polars_df)` needs `pyarrow` (new dep, disallowed) → staged explicit-schema rows into TEMP duckdb table via `executemany` then set-based `ON CONFLICT` upsert. Literal "no row-by-row" bent for the temp-stage insert, but net upsert is set-based + idempotent + zero new dep = right call. If M5/analytics wants true bulk polars↔duckdb, revisit declaring `pyarrow` (planner sign-off) then. (b) added `.pytest-tmp/` to `.gitignore` — fine. **Low-pri note (no redo):** writes autocommit per-stmt → mid-loop type failure leaves earlier types' upserts persisted while run logs `failed`/order_count=0; not required atomic (idempotent re-run heals). M0–M3 stay DONE. **WORKFLOW CHANGE this session:** §1/§2 + AGENTS.md now mandate closed-world Codex + Claude-authored Context Pack per §6 task — M4b is the first task drafted in that format.
- **M4b drafted (first Context-Pack task).** everef.net bulk backfill → `market_history`. Planner researched the source live: URL `data.everef.net/market-history/{YYYY}/market-history-{YYYY-MM-DD}.csv.bz2`, bz2 CSV, 1 file/day = ALL regions (~53.7k rows/day); confirmed header verbatim `average,date,highest,lowest,order_count,volume,http_last_modified,region_id,type_id` by pulling+decompressing `2025-06-15` (`bz2`). Pack pins: files-in-scope (new `ingest/backfill.py`, edit `writers.py`+`cli.py`, new test), everef format, caller contracts (`ensure_market_db`/`record_ingest_run`/`write_history`/`HISTORY_SCHEMA`/`Config`). Design: SYNC (no ESIClient — static files), injectable `fetch`(bytes|None, None=404-skip)/`sleep`/`now`; filter to one region; drop `http_last_modified`; refactor `write_history` to share private `_upsert_history_frame` + add `write_history_bulk` (M4a tests must stay green); 1 `ingest_runs` row source='everef_history' (pages=days_fetched, esi_expires NULL); 404→skip (days_missing, still success), non-404 err→failed+raise; CLI `backfill-history --region/--start/--end` default polite 3-day range (end=yesterday UTC). Review focus on return: explicit polars schema, region filter correct, idempotent re-run (no dupes = key test), `write_history` behavior unchanged, 404-skip vs hard-fail split, history in DuckDB, `data/` untracked, commit hash in §8.
- **M4b REVIEW: DONE.** Read all M4b code (`backfill.py`,`writers.py` refactor,`cli.py`,test). Planner clean-env (bare `python`, all deps, NO manual installs): `pytest --basetemp <scratch>` → `19 passed,1 skipped`; `ruff` clean. Commit `e1ce7b2` (+`c0dc702` docs) present; `data/market.duckdb` ignored. All focus pts pass: explicit `EVEREF_CSV_SCHEMA`(date Utf8→`str.to_date`)+`HISTORY_SCHEMA`; region filter correct (test: other-region rows excluded, only 10000002 lands); `write_history` behavior preserved via extracted private `_upsert_history_frame` (M4a/M3 tests green); idempotent re-run stable; 404(`fetch→None`)→`days_missing`++ + success vs non-404→`failed` row+raise — both tested; `write_history_bulk` empty→0 guard; coexists w/ M4a rows in same table. Live: `2026-06-23..25`, days_fetched 2, days_missing 0, row_count 20046; DB region 10000002 count 20464 (M4a Tritanium history coexists, min date 2025-05-01), per-day 06-23=9773/06-24=10273; `everef_history` run row correct. **Low-pri note (my Context-Pack rule, no redo):** file present but 0 region rows → counted NEITHER fetched NOR missing (live `2026-06-25` hit this), so `days_fetched+days_missing` can be < range length. Self-healing (idempotent re-run picks it up once everef populates). Future tweak: add `days_empty` counter or treat present-but-empty as missing. Codex followed the rule exactly + flagged it. Minor: fetch-None/else loop bodies duplicated (style only). **LOOSE END:** `AGENTS.md` closed-world workflow edit left UNCOMMITTED (HANDOFF.md workflow edit WAS committed in `e1ce7b2`/`c0dc702`) — needs committing so Codex's repo-level instructions match. M0–M4 DONE.
- **M5 split + M5a drafted (Context Pack).** M5 too big → M5a prices ingest (THIS) | M5b APScheduler wiring | M5c data-quality checks. Planner researched `/markets/prices/` live (`curl`): GLOBAL (no region), NOT paginated, `Expires`-cached, ~16071 entries; fields `{type_id, adjusted_price, average_price}` with **`average_price` OPTIONAL (~1981/16071 omit key)**, `adjusted_price`/`type_id` present. Confirmed `ESIResponse(data,expires,etag,pages,...)` contract from `esi/client.py`. M5a pack: new `market_prices(type_id,adjusted_price,average_price,snapshot_ts, PK(type_id,snapshot_ts))`, `MarketPrice` model (both prices `float|None`), `write_prices` (explicit `PRICE_SCHEMA`, normalize missing avg→None, temp-stage+ON CONFLICT upsert), async `ingest_prices`(single global call, `region_id=None` in ingest_runs source='esi_prices', sample-validate ≤50), CLI `ingest-prices`. Review focus on return: explicit schema, **null `average_price` handled** (test must include a no-average entry), idempotent re-run (same `now`=stable), `region_id` NULL in ingest_runs, sample-only validation, `data/` untracked, commit hash in §8.

- **M5a REVIEW: DONE.** Read all M5a code (`models.py`,`schema.py`,`writers.py`,`prices.py`,`cli.py`,test). Planner clean-env (bare `python`, all deps, NO manual installs): `pytest --basetemp <scratch>` → `22 passed,1 skipped`; `ruff` clean. Commit `9666724` (+`ce7aeca` docs) pushed, nothing unpushed; only `AGENTS.md` dirty (known loose end). All focus pts pass: explicit `PRICE_SCHEMA`; **null `average_price` handled** — test asserts no-avg entry (type 34)→NULL AND null `adjusted_price` (type 35)→NULL (exceeds spec); `market_prices` PK(type_id,snapshot_ts); idempotent re-run same `now`→count stable 3, 2 success runs; `region_id` NULL in `ingest_runs` source='esi_prices'; sample-only validation (≤50); temp-stage+`ON CONFLICT` upsert mirrors `_upsert_history_frame`; `data/` untracked. Live: 16071 prices, 14090 w/ avg (~1981 omit, matches my research), `esi_prices` run region_id NULL/order_count 16071/pages 1 correct. No deviations. M0–M5a DONE. Next: M5b (APScheduler wiring).
- **LOOSE END still open:** `AGENTS.md` closed-world workflow edit uncommitted across M4b/M5a (user deferred commit). Fold into M5b commit or a standalone `docs:` commit when user clears it.

- **M5b drafted (Context Pack).** APScheduler wiring → recurring ingest jobs. Verified prerequisites against the live tree (no exploration debt left for Codex): `apscheduler 3.11.2` installed + declared in `pyproject.toml` (3.x `BlockingScheduler` API); `ingest_orders(client,config,region_id)`→`IngestResult(.run_id/.region_id/.order_count/.status)` and `ingest_prices(client,config)`→`PricesIngestResult(.run_id/.price_count/.status)` signatures read from source; `cli.py` already imports `asyncio`/`typer`/`Path`/`load_config`/`ESIClient`; `pytz` is a dep (scheduler tz). **Scope held tight:** new `scheduler.py` (`build_scheduler` + `run_orders_job`/`run_prices_job`, jobs swallow+log exceptions for resilience, injectable `ingest=` kwarg for offline tests) + CLI `schedule` (`--orders-interval`/`--prices-interval`/`--dry-run`) + offline test. **Two jobs only (orders+prices); history scheduling explicitly DEFERRED** (needs a "which type_ids daily" universe decision — its own task). Live verification = `schedule --dry-run` (lists 2 jobs, no `.start()`, no network, no hang) since the underlying ingests are already proven live (M3/M5a); tests MUST never call `.start()` (blocks). **M5b commit also clears the AGENTS.md loose end** (pack instructs Codex to stage the already-modified workflow paragraph). Review focus on return: exactly 2 jobs w/ correct interval triggers, jobs swallow exceptions (raising fake `ingest`→None/[]), injectable-ingest offline tests (no network, no `.start()`), no new deps, existing commands/tests untouched, `data/` untracked, commit hash + AGENTS.md in §8.

- **M5b REVIEW: DONE.** Read all M5b code (`scheduler.py`, `cli.py` schedule cmd, `test_scheduler.py`). Planner clean-env (bare `python`, all deps, NO manual installs): `pytest --basetemp <scratch>` → `28 passed, 1 skipped`; `ruff` clean. Commit `169bde0` (+`abd8393` docs); tree clean. All focus pts pass: `build_scheduler` registers exactly 2 jobs `{orders,prices}` w/ `IntervalTrigger` 5/60 min (custom intervals reflected — test); `run_prices_job`/`run_orders_job` swallow+log exceptions (raising fake → `None`/`[]` — tested), injectable `ingest=` keeps tests network-free, NO `.start()` in tests; UTC `BlockingScheduler(timezone=pytz.utc)`, `coalesce/max_instances=1/replace_existing`; orders loops `tracked_regions` (2-region test → 2 calls in order); existing commands/ingest/store untouched, M5a/M4/M3 green; no new deps; `data/` untracked. Planner-ran live dry-run: `schedule --dry-run` → `Job orders: interval[0:05:00]` / `Job prices: interval[1:00:00]` / `Dry run: scheduler not started.` (no `.start()`, no network, no hang). **AGENTS.md loose end CLEARED** — closed-world workflow paragraph committed in `169bde0` (2-line add). No deviations of note (Codex flagged a benign `git status` warning re: inaccessible global ignore — no behavior impact). **M0–M5b DONE.** Next: M5c (data-quality checks) — awaiting user go to draft the Context Pack.

- **M5c drafted (Context Pack) — LAST of Phase 1.** Data-quality checks. Verified all contracts against live source (`schema.py` 3-table DDL, `writers.py` signatures, the `quality.py` stub): pack pastes the verbatim DDL of `ingest_runs`/`market_history`/`market_prices` so Codex writes SQL blind, + writer signatures (`write_prices`/`write_history_bulk`/`record_ingest_run`) for test seeding. **Design:** fill the `store/quality.py` stub with `QualityCheck(name,status,detail)` frozen dataclass + `run_quality_checks(conn, *, now=None, max_price_age_hours=24, max_history_age_days=3)` returning 5 READ-ONLY checks in order: `stale_prices` (newest `market_prices.snapshot_ts` age, warn>24h), `stale_history` (newest `market_history.date` age, warn>3d), `price_anomalies` (latest snapshot: `adjusted_price<0`→fail, NULL→warn; `average_price` NULL ignored — legit ~12%), `history_anomalies` (`highest<lowest`/negative→fail; strict `<0` to avoid false-positives on zeros), `failed_runs` (`ingest_runs.status='failed'` count→warn + latest source/error). CLI `quality-check --max-price-age-hours/--max-history-age-days`, prints `[STATUS] name: detail` per check, `typer.Exit(1)` on any FAIL (ops signal). **Held tight:** quality.py SELECTs only (never mutates); injectable `now` for deterministic stale tests; explicitly DEFERRED history gap-detection + row-count-delta-vs-prior-run (heavier follow-ups, noted in §6 as do-not-implement). Live check is READ-ONLY (no network) against the real db. Review focus on return: read-only (no INSERT/UPDATE in quality.py), all 5 checks correct status logic, `average_price` NULL NOT flagged, strict-`<0` predicates, injectable-`now` offline tests cover ok/warn/fail/empty, exit-1-on-fail, existing commands/tests untouched, no new deps, `data/` untracked, commit hash in §8.

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

### M3-FIX — UTC ingest_run timestamps — 2026-06-26 — COMPLETE
Changed: `store/schema.py`, `tests/test_ingest_orders.py`, `HANDOFF.md`. `ingest_runs` ts cols `TIMESTAMPTZ`; `ensure_market_db` sets DuckDB `TimeZone='UTC'`; success test reads DB with UTC session and asserts `snapshot_ts`, `esi_expires`, `started_at`, `finished_at` tz-aware UTC. Deleted throwaway `data/market.duckdb` before live rebuild. Offline: bare `python` absent; installed `.[dev]` into bundled Python; installed `pytz` for DuckDB `TIMESTAMPTZ` Python fetch; first pytest blocked by AppData temp permission, reran workspace temp. `...\python.exe -m pytest -q -p no:cacheprovider --basetemp .pytest-tmp` -> `13 passed, 1 skipped in 1.49s`; `...\python.exe -m ruff check .` -> `All checks passed!`. Live: `...\Scripts\evemarket.exe ingest-orders` -> region `10000002`, status `success`, run_id `ac42358f-0534-4ce3-8739-d1d1d509d5bd`, pages `424`, order_count `423548`, snapshot `data\snapshots\orders\region=10000002\date=2026-06-26\20260626T040005Z.parquet`, esi_expires `2026-06-26 04:05:03+00:00`. UTC query (`SET TimeZone='UTC'; SELECT snapshot_ts, esi_expires FROM ingest_runs ORDER BY started_at DESC LIMIT 1`) -> `[(datetime.datetime(2026, 6, 26, 4, 0, 5, 697187, tzinfo=<UTC>), datetime.datetime(2026, 6, 26, 4, 5, 3, tzinfo=<UTC>))]`; matches partition path `20260626T040005Z`, no +8 skew. `DESCRIBE ingest_runs` confirms four `TIMESTAMP WITH TIME ZONE` cols. Pre-commit `git status --short`: only `HANDOFF.md`, `src/evemarket/store/schema.py`, `tests/test_ingest_orders.py`; `git check-ignore` confirmed `data/market.duckdb` + live parquet ignored. Deviation: missing-`Expires` NULL tweak left untouched; client API always returns fallback `expires`, avoiding refactor per low-pri note. Questions: none.
### M3-FIX2 — declare pytz dependency — 2026-06-26 — COMPLETE
Changed: `pyproject.toml`, `HANDOFF.md`. Added runtime `pytz` dependency for DuckDB `TIMESTAMPTZ` read conversion; no code/schema/test changes. Verification: `...\python.exe -m pip uninstall -y pytz` -> uninstalled `pytz 2026.2`; `...\python.exe -m pip install -e ".[dev]"` -> `Collecting pytz (from evemarket==0.1.0)`, `Successfully installed evemarket-0.1.0 pytz-2026.2`; `...\python.exe -c "import pytz; print(pytz.__version__)"` -> `2026.2`. Offline: `...\python.exe -m pytest -q -p no:cacheprovider --basetemp .pytest-tmp` -> `13 passed, 1 skipped in 1.34s`; `...\python.exe -m ruff check .` -> `All checks passed!`. Pre-commit `git status --short`: only `HANDOFF.md`, `pyproject.toml`; no `data/`/`*.duckdb`/parquet staged. Deviations: used bundled Python absolute path because bare `python` unavailable; pytest used workspace basetemp due AppData temp permission issue. Questions: none.
### M4a — ESI daily history ingestion -> market_history — 2026-06-26 — COMPLETE
Files: `.gitignore`, `src/evemarket/esi/models.py`, `src/evemarket/store/schema.py`, `src/evemarket/store/writers.py`, `src/evemarket/ingest/history.py`, `src/evemarket/cli.py`, `tests/test_ingest_history.py`, `HANDOFF.md`. Commit: `b51e885`.
Implemented `MarketHistoryDay`; `market_history` PK table in `ensure_market_db`; `write_history` typed Polars DF + DuckDB temp staging + set-based `ON CONFLICT` upsert; `ingest_history` success/fail `ingest_runs` source=`esi_history`; CLI `ingest-history --type`.
Offline: bare `python -m pytest -q -p no:cacheprovider --basetemp .pytest-tmp` failed (`python` not on PATH). Bundled Python: `...\python.exe -m pytest -q -p no:cacheprovider --basetemp .pytest-tmp` -> first failed due duplicate stub header, second failed because `conn.register(polars_df)` needs missing `pyarrow`; final -> `16 passed, 1 skipped in 1.60s`. `...\python.exe -m ruff check .` -> `All checks passed!`.
Tests added: 2 types x 2 days rows correct; rerun same data row count stable (2 rows, 2 success runs); failure path records `failed` row with error; M3 tests still green.
Live: `...\Scripts\evemarket.exe ingest-history --type 34` -> Region `10000002`, Status `success`, Run ID `546c78f2-1f2b-48bc-9c8f-e459c62e89b7`, Types fetched `1`, Type IDs `[34]`, Day count `420`, ESI expires `2026-06-26 11:05:00+00:00`.
DuckDB: `SELECT type_id, count(*), min(date), max(date) FROM market_history GROUP BY type_id` -> `[(34, 420, 2025-05-01, 2026-06-24)]`. Latest `ingest_runs` history row -> `('546c78f2-1f2b-48bc-9c8f-e459c62e89b7','esi_history',10000002,1,420,'success',2026-06-26 11:05:00+00:00,NULL,NULL)`.
Pre-commit `git status --short`: `.gitignore`, source files, `tests/test_ingest_history.py`, `HANDOFF.md`; no `data/`/`*.duckdb`/parquet staged; `git check-ignore -v data\market.duckdb` -> `.gitignore:1:data/`.
Deviations: no new deps allowed; DuckDB `register(polars_df)` required absent `pyarrow`, so writer stages explicit-schema Polars rows into temp DuckDB table then upserts set-wise. Added `.pytest-tmp/` to `.gitignore`; Windows denied deleting generated basetemp. Used bundled Python absolute path; live run required network escalation. Questions: none.
### M4b — everef.net bulk history backfill -> market_history — 2026-06-26 — COMPLETE
Files: `src/evemarket/ingest/backfill.py`, `src/evemarket/store/writers.py`, `src/evemarket/cli.py`, `tests/test_backfill_history.py`, `HANDOFF.md`. Commit: `e1ce7b2`.
Workflow: closed-world honored; opened/edited only files named in Context Pack plus `AGENTS.md`/`HANDOFF.md` initial user-requested workflow read; did not scan tree for context.
Implemented sync `backfill_history_everef`; `BackfillResult`; Everef URL builder; bz2 decompress; explicit `EVEREF_CSV_SCHEMA`; region filter; `write_history_bulk`; shared `_upsert_history_frame`; CLI `backfill-history` with default 3-day UTC-yesterday range.
Offline: bare `python -m pytest -q` failed (`python` not on PATH). Bundled Python: `...\python.exe -m pytest -q -p no:cacheprovider --basetemp .pytest-tmp` -> `19 passed, 1 skipped in 2.31s`. `...\python.exe -m ruff check .` -> `All checks passed!`.
Tests added: in-memory bz2 CSV, 2 dates + other-region rows -> only `10000002` rows; DuckDB types `DATE`/`DOUBLE`/`BIGINT`; rerun same range row count stable; 404 (`fetch->None`) increments `days_missing` and success; non-404 fetch error raises + records `failed` row; M4a/M3 tests still green.
Live: `...\Scripts\evemarket.exe backfill-history` -> Region `10000002`, Status `success`, Run ID `e7c4c351-79e2-442c-90c0-d0d865a2caab`, Start `2026-06-23`, End `2026-06-25`, Days fetched `2`, Days missing `0`, Row count `20046`.
DuckDB: `SELECT count(*), min(date), max(date) FROM market_history WHERE region_id=10000002` -> `[(20464, 2025-05-01, 2026-06-24)]`; date counts for live range -> `[(2026-06-23, 9773), (2026-06-24, 10273)]`; latest `everef_history` run -> `('e7c4c351-79e2-442c-90c0-d0d865a2caab','everef_history',10000002,2,20046,'success',NULL,NULL,NULL)`.
Pre-commit `git status --short`: `AGENTS.md` + `HANDOFF.md` pre-existing workflow edits; scoped source/test files; no `data/`/`*.duckdb`/parquet staged; `git check-ignore -v data\market.duckdb` -> `.gitignore:1:data/`.
Deviations: live default range file `2026-06-25` was present but yielded no Forge rows, so not counted fetched or missing by Context Pack rule (`days_fetched += 1` only when rows non-empty). Used bundled Python absolute path; live run required network escalation. Questions: none.
### M5a — ESI market prices ingestion -> market_prices — 2026-06-26 — COMPLETE
Files: `src/evemarket/esi/models.py`, `src/evemarket/store/schema.py`, `src/evemarket/store/writers.py`, `src/evemarket/ingest/prices.py`, `src/evemarket/cli.py`, `tests/test_ingest_prices.py`, `HANDOFF.md`. Commit: `9666724`.
Implemented `MarketPrice`; `market_prices(type_id, adjusted_price, average_price, snapshot_ts, PK(type_id,snapshot_ts))`; `PRICE_SCHEMA`; `write_prices` temp-stage + `ON CONFLICT` upsert; async `ingest_prices` source=`esi_prices`/`region_id=NULL`; CLI `ingest-prices`.
Offline: bare `python -m pytest -q` failed (`python` not on PATH). Bundled Python: `...\python.exe -m pytest -q -p no:cacheprovider --basetemp .pytest-tmp` -> `22 passed, 1 skipped in 2.50s`. `...\python.exe -m ruff check .` -> `All checks passed!`.
Tests added: MockTransport prices array incl missing `average_price`; `market_prices` rows correct; no-average entry -> NULL; nullable adjusted_price covered; `snapshot_ts` TIMESTAMPTZ UTC; rerun same `now` row count stable; `ingest_runs` success row `source='esi_prices'`, `region_id` NULL, `order_count=3`, `pages=1`; failure path records `failed` row + error; M4/M3 tests still green.
Live: `...\Scripts\evemarket.exe ingest-prices` -> Status `success`, Run ID `664e33bc-7bf8-45cd-a32c-4737fe329d32`, Price count `16071`, ESI expires `2026-06-26 08:52:00+00:00`, Snapshot ts `2026-06-26 08:17:44.117069+00:00`.
DuckDB: `SELECT count(*), count(average_price), count(adjusted_price), min(snapshot_ts) FROM market_prices` -> `[(16071, 14090, 16071, 2026-06-26 08:17:44.117069+00:00)]`; latest `esi_prices` run -> `('664e33bc-7bf8-45cd-a32c-4737fe329d32','esi_prices',NULL,1,16071,'success',2026-06-26 08:52:00+00:00,NULL,NULL)`.
Pre-commit `git status --short`: `AGENTS.md` + `HANDOFF.md` pre-existing/new handoff edits; scoped source/test files; no `data/`/`*.duckdb`/parquet staged; `git check-ignore -v data\market.duckdb` -> `.gitignore:1:data/`.
Deviations: used bundled Python absolute path; live run required network escalation. `AGENTS.md` still modified/uncommitted loose end from workflow update, not touched/staged (outside M5a scope). Questions: none.
Template: `### M<n> — <title> — <date> — COMPLETE/BLOCKED` then: Files | Commands+result | Verification | Deviations | Questions.

### M5b - APScheduler recurring ingest jobs + schedule CLI - 2026-06-26 - COMPLETE
Files: `src/evemarket/scheduler.py`, `src/evemarket/cli.py`, `tests/test_scheduler.py`, `AGENTS.md`, `HANDOFF.md`. Commit: `169bde0`.
Implemented `build_scheduler` with exactly 2 interval jobs (`orders`, `prices`), UTC `BlockingScheduler`, coalesce/max_instances/replace_existing; sync `run_orders_job` + `run_prices_job` wrappers using `asyncio.run`, `ESIClient`, injectable `ingest=`, swallow+log exceptions; CLI `schedule` with `--orders-interval`, `--prices-interval`, `--dry-run`.
Offline: bare `python -m pytest -q` failed (`python` not on PATH). Bundled Python: `...\python.exe -m pytest -q -p no:cacheprovider --basetemp .pytest-tmp` -> `28 passed, 1 skipped in 3.12s`. `...\python.exe -m ruff check .` -> `All checks passed!`.
Dry-run: `...\Scripts\evemarket.exe schedule --dry-run` -> `Job orders: interval[0:05:00]`; `Job prices: interval[1:00:00]`; `Dry run: scheduler not started.`
Tests added: scheduler has ids `{"orders","prices"}` + 5/60 minute intervals; custom intervals reflected; prices fake called once and returned; prices raising fake -> `None`; orders fake called once per configured region and returned len 2; orders raising fake -> `[]`; no `.start()`.
Pre-commit `git status --short`: `AGENTS.md`, `HANDOFF.md`, `src/evemarket/cli.py`, `src/evemarket/scheduler.py`, `tests/test_scheduler.py`; no `data/`/`*.duckdb`/parquet staged.
Deviations: used bundled Python absolute path; `git status` warned user global ignore inaccessible (`C:\Users\M0obo/.config/git/ignore` permission denied); no behavior impact. Questions: none.

### M5c - data-quality checks + quality-check CLI - 2026-06-26 - COMPLETE
Files: `src/evemarket/store/quality.py`, `src/evemarket/cli.py`, `tests/test_quality.py`, `HANDOFF.md`. Commit: pending until commit creation.
Implemented `QualityCheck`; `run_quality_checks` with ordered checks `stale_prices`, `stale_history`, `price_anomalies`, `history_anomalies`, `failed_runs`; UTC `_ensure_utc`; read-only SELECT checks; CLI `quality-check --max-price-age-hours/--max-history-age-days`, prints `[STATUS]`, exits 1 on fail.
Offline: bare `python -m pytest -q` failed (`python` not on PATH). Bundled Python: `...\python.exe -m pytest -q -p no:cacheprovider --basetemp .pytest-tmp` -> `36 passed, 1 skipped in 3.21s`. `...\python.exe -m ruff check .` -> `All checks passed!`.
Live read-only: `...\Scripts\evemarket.exe quality-check` -> `[OK] stale_prices: latest=2026-06-26T08:17:44.117069+00:00 age=0.5h`; `[OK] stale_history: latest=2026-06-24 age=2d`; `[OK] price_anomalies: negative=0 null_adjusted=0 (latest snapshot)`; `[OK] history_anomalies: 0 invalid rows`; `[OK] failed_runs: no failed runs`; `EXIT_CODE=0`.
Tests added: all-good all 5 ok; stale prices/history warn; negative adjusted fail; null adjusted warn; null average only ok; highest<lowest fail; failed run warn with source/error; empty db warns stale only; existing M5b/M5a/M4/M3 green.
Pre-commit `git status --short`: `HANDOFF.md`, `src/evemarket/cli.py`, `src/evemarket/store/quality.py`, `tests/test_quality.py`; no `data/`/`*.duckdb`/parquet staged.
Deviations: used bundled Python absolute path; `git status` warned user global ignore inaccessible (`C:\Users\M0obo/.config/git/ignore` permission denied); no behavior impact. Questions: none.

## 9. Open Questions / Blockers

- ~~**BLOCKED 2026-06-26 (Codex):** awaiting M5b Context Pack (§6 still held completed M5a pack).~~ **RESOLVED 2026-06-26 (Claude):** M5b Context Pack now in §6; M5a demoted to DONE reference. Codex unblocked — execute M5b.

- **PII — RESOLVED 2026-06-26.** Codex had set `config.toml` contact to user's personal email in working tree (tracked, public repo); HEAD still had `REPLACE_ME` so email never pushed. User chose Discord `m0obot`; M2-COMMIT swapped it in, verified no email in tracked files (`rg` empty), committed+pushed `6da016f`.
- **Deferred (non-blocking, M0):** switch `Config`/`SkillConfig` from `pydantic_settings.BaseSettings` to `pydantic.BaseModel` so TOML is sole config source (BaseSettings allows silent env-var overrides). Future small task.
- ~~M0: `evemarket info` warn on REPLACE_ME~~ — folded into M2 (done).
- ~~M1: Fuzzwork bz2 layout mismatch~~ — RESOLVED; use uncompressed `/dump/latest/csv/`.
