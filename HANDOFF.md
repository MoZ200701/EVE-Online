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

## 6. Current Task (Codex) — M3-FIX: UTC timestamp storage + tz round-trip test

M3 code DONE but REDO-lite. Bug: `ingest_runs` timestamps stored in LOCAL time, not UTC. Cause: tz-aware datetime → DuckDB `TIMESTAMP` (naive) localizes wall-clock + strips tz. Reproduced: insert `03:45:03+00:00` → stored `11:45:03` (machine UTC+8). Visible in M3 §8 log itself: printed `esi_expires 03:45:03+00:00` vs DB row `11:45:03`. Breaks: `snapshot_ts` in DB ≠ UTC ts in parquet partition path (`20260626T034446Z`); non-reproducible cross-machine. Tests missed it — DuckDB asserts read back source/region/pages/count/status/path/error but never the ts cols.

Fix EXACTLY this. No new scope (no M4/M5/analytics).

1. `store/schema.py` — change ALL four ts cols in `ingest_runs` from `TIMESTAMP` → `TIMESTAMPTZ`: `snapshot_ts`, `started_at`, `finished_at`, `esi_expires`. Keeps UTC explicit on round-trip. `data/market.duckdb` is gitignored throwaway — delete it so `CREATE TABLE IF NOT EXISTS` rebuilds with new types; no migration.

2. `tests/test_ingest_orders.py` — extend success test: add DuckDB read-back asserting `snapshot_ts` == injected `snapshot_ts` (UTC, tz-aware) and `esi_expires` == page-1 `Expires` (UTC, tz-aware). Must FAIL before fix (proves bug), PASS after. Keep existing parquet assertions. Also assert `started_at`/`finished_at` come back tz-aware UTC.

3. Minor (esi_expires null-on-missing) — spec: `esi_expires` nullable from page-1 `Expires`. Currently `client._parse_expires` falls back to `now()` when header absent → records capture-time not NULL. ESI always sends `Expires` so harmless, but tighten if cheap: in `ingest/orders.py` record `esi_expires=None` when page-1 had no `Expires` header rather than relying on client fallback. If client API makes this awkward, LEAVE + note in §8 — low priority, do NOT expand scope to refactor the client.

**Deferred — NOT this task (do not touch):**
- Config/SkillConfig `BaseSettings` → `BaseModel` (§9 carry; env vars silently override TOML). Future standalone task.

**Constraints** — no new deps; `data/`,`*.duckdb`,parquet stay untracked (gate on `git status --short`); don't change §4. Blocked → STOP, write §9.

**Verification (paste into §8, terse per §2):**
- `python -m pytest -q` pass, network-free; new ts read-back asserts present.
- `python -m ruff check .` clean.
- One live `ingest-orders` Forge run; paste `SELECT snapshot_ts, esi_expires FROM ingest_runs ORDER BY started_at DESC LIMIT 1` — must show UTC matching partition-path ts (no +8 skew).
- Pre-commit `git status --short`: no `data/`/`*.duckdb`/parquet staged. Commit `fix: store ingest_runs timestamps as UTC TIMESTAMPTZ (M3)`; `git push origin main` (no force). Include `HANDOFF.md`.

When done: append §8 entry (terse) and STOP. M4 (history + everef backfill) next.

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
Template: `### M<n> — <title> — <date> — COMPLETE/BLOCKED` then: Files | Commands+result | Verification | Deviations | Questions.

## 9. Open Questions / Blockers

- **PII — RESOLVED 2026-06-26.** Codex had set `config.toml` contact to user's personal email in working tree (tracked, public repo); HEAD still had `REPLACE_ME` so email never pushed. User chose Discord `m0obot`; M2-COMMIT swapped it in, verified no email in tracked files (`rg` empty), committed+pushed `6da016f`.
- **Deferred (non-blocking, M0):** switch `Config`/`SkillConfig` from `pydantic_settings.BaseSettings` to `pydantic.BaseModel` so TOML is sole config source (BaseSettings allows silent env-var overrides). Future small task.
- ~~M0: `evemarket info` warn on REPLACE_ME~~ — folded into M2 (done).
- ~~M1: Fuzzwork bz2 layout mismatch~~ — RESOLVED; use uncompressed `/dump/latest/csv/`.
