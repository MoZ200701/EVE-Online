# EVE Market Tool — Agent Handoff

Shared source of truth between two AI agents. Append-mostly. Read fully before acting; update your own section. Only memory that survives between sessions.

> **Completed-task history (full Context Packs, per-milestone planner notes, Codex execution logs, resolved blockers) lives in `HANDOFF_ARCHIVE.md`.** This file holds only current/load-bearing state. Commit ledger is in §7.

---

## 1. Roles

- **Claude (Opus) — Planner/Debugger.** Owns the **thinking**: plans steps, makes/holds architecture decisions, writes task prompts, reviews Codex output, diagnoses bugs, decides DONE/REDO. Does NOT write production code (only debug patches). Still owns all *judgment* — what the task is, which files are in scope, what the contracts mean, whether output is correct. **No longer required to pre-read and paste every file into the pack:** Claude scopes the work and may delegate the mechanical *gathering* (reading named files for current signatures/shapes/contents) to Codex.
- **GPT‑5.5 (Codex) — Executor + bounded gatherer.** Writes the code for the files named in the current task — and now may also **gather the files/info that task needs itself** (read/grep the in-scope or explicitly-named files to collect current signatures, data shapes, contents) instead of waiting for Claude to pre-paste them. This is mechanical retrieval *within the task Claude scoped* — NOT a license to re-plan, make architecture decisions, expand scope, skip ahead, or invent design. If gathering surfaces a contract mismatch, a missing piece, or anything that changes the plan, **STOP + write §9 — do NOT decide it yourself.** Running `pytest`/`ruff`/`mypy` for verification is fine.

One step at a time. Claude scopes the task + names what to gather → Codex gathers what it needs, writes the named files → logs §8 → STOPS. Claude reviews → DONE/REDO + next prompt in §6. No batching milestones. **Division of labor:** Claude still does the vast majority of the thinking; Codex absorbs the mechanical file/info-gathering and the coding so usage is more evenly split.

## 2. Update protocol

- Claude: every §6 task MUST open with a **Context Pack** (see template below). The pack defines the *scope and intent* — files to touch, what the result must do, conventions, contracts that matter. Claude may either **paste** a contract inline OR **point Codex at the file to read it** ("read `config.py` for the current `Config`/`SkillConfig` fields"). Either is fine; the pack just has to make the scope unambiguous. An incomplete *scope* is a planner bug; a contract Codex can read for itself is not.
- Codex: write ONLY the files named in the pack. You MAY read/grep the in-scope files and any files Claude explicitly names, to gather current signatures/shapes/contents needed for THIS task — but do not wander beyond that, re-plan, or expand scope. After a task, append §8 entry (files changed, **what you gathered/read**, commands+result, verification pass/fail, deviations/questions), then STOP. Gathering reveals a mismatch or missing piece that changes the plan → STOP + §9 (don't decide it).
- Claude: after review, append §7 verdict + put next task in §6.
- Never delete log history; correct via new entry. If blocked, write §9 and stop.
- **Style rule (terse / "caveman"):** this file is AI↔AI only — no prose, no filler, no human niceties. Write entries as dense bullets/fragments. Keep load-bearing facts (commands, results, file paths, commit hashes, IDs, verdicts) verbatim; drop everything else. Periodically compact (collapse done tasks, strip duplicate dumps) rather than letting it grow — move old detail to `HANDOFF_ARCHIVE.md`, don't delete.

**Context Pack template (Claude fills, opens every §6 task):**
- **Files in scope** — exact list to create/edit. For files being EDITED, either paste the relevant current contents/signatures OR tell Codex to read them ("read current body before editing"). Codex writes nothing outside this list.
- **To gather** — files/symbols Codex should read itself for this task (Claude names them; Codex collects the live signatures/shapes). Use this instead of pasting when the contract is stable and easy to read; paste inline when it's subtle, load-bearing, or easy to misread.
- **Caller contracts** — for anything NOT delegated to "To gather": verbatim signature + 1-line semantics of the cross-file symbols the task calls. Just what's invoked, not whole files.
- **Data shapes** — exact JSON/dict structure + key types for any external/inter-module data the code handles (paste if subtle; otherwise name the file to read).
- **Conventions to mirror** — project-specific rules in play (explicit polars schema, UTC `TIMESTAMPTZ`, no new deps, terse, etc.).
- **Boundary** — "Gather only the named/in-scope files; write only the files in scope. Don't re-plan or expand scope. Anything that changes the plan → STOP + §9."

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
  store/{__init__,schema,writers,quality,readers}.py   # readers.py added M8b (planner sign-off 2026-06-28)
  analytics/{__init__,fees,opportunity,station_trade,haul}.py
tests/
```

## 5. Phase plan (no jumping ahead)

**Phase 1 — data pipeline**
- M0 Scaffold ✅ | M1 SDE→`sde.duckdb` ✅ | REPO git+push ✅ | M2 ESI client ✅ | M3 Order snapshots + `ingest_runs` ✅ | M4a ESI daily history → `market_history` ✅ | M4b everef.net bulk backfill ✅ | M5a ESI prices → `market_prices` ✅
- **M5** Prices ✅ | scheduler (M5b) ✅ | data-quality (M5c) ✅ | M5-FIX mypy-clean ✅ — **Phase 1 COMPLETE & to-standard.** | M6 `analytics/fees.py` ✅ `2cee47b` | M7 `analytics/opportunity.py` seam ✅ `46261d0` | M8a `station_trade.py` ranking core ✅ `29f7a9c` | M8b `store/readers.py` DuckDB reader ✅ `55d5a3e` | M8c CLI `scan` ✅ `0bf9a99`. ← **CURRENT: Phase 2 / M9 `analytics/haul.py` regional arbitrage — M9a pure core ✅ `ab937a9` → M9b cross-region reader (ACTIVE, §6) → M9c CLI `haul`.**

**Phase 2 — deterministic analytics (stubbed):** `fees.py` ✅, `opportunity.py` ✅, `station_trade.py` (first scanner — **decomposed: M8a pure ranking ✅ → M8b DuckDB reader ✅ → M8c CLI ✅**), then `haul.py` (**decomposed: M9a pure core → M9b cross-region reader → M9c CLI `haul`**).

**Phase 3 — forecasting & long-hold (position) trading** *(committed 2026-06-28; honest-backtest-first; starts only after Phase 2 scanners land — no jumping ahead).*
Goal: predict forward price/return over a **multi-week horizon** (target ~2–6 wks, configurable — covers "buy and hold a month+") and surface backtested long-hold suggestions via the existing `ProfitOpportunity` seam (a hold = a `Disposal` at a *predicted future* price). Trained **locally** on EVE history (GBM / time-series per §3), NOT LLM.
- **P3-0 Backtest harness FIRST (the gate):** walk-forward, strict out-of-sample, point-in-time (no lookahead/survivorship), realistic fills + reuse M6 fees. Baselines = naive persistence, seasonal-naive, buy-&-hold item, hold-ISK. Metrics: directional hit rate, **risk-adjusted expectancy (ISK/trade net fees)**, profit factor, max drawdown, return vs each baseline, sample size/significance. Nothing downstream is trusted until this exists.
- **P3-1 Feature pipeline:** point-in-time features (returns, realized vol, volume/liquidity trends, rolling stats, calendar/seasonality, spread). Zero future leakage.
- **P3-2 Forecast model:** horizon-return forecaster with probability/confidence; trained + persisted locally.
- **P3-3 Position-trade scanner:** forecasts → ranked long-hold opportunities (future-priced `Disposal`), gated by backtested edge + confidence, shown WITH downside/uncertainty.
- **P3-4 Acceptance gate:** a model ships only if it beats the baselines out-of-sample on expectancy at adequate sample size.

**Success bar — "net even" by construction (the honest form of the ">50% hit rate" ask):**
- **Abstention is a first-class output.** A long-hold trade is surfaced ONLY when its backtested expectancy net of fees is positive; otherwise the app recommends *nothing* (or falls back to the deterministic station/haul edge). The decision rule's downside floor is therefore "do nothing = 0 loss", never "act and bleed" — that is what makes net-even defensible.
- **>50% directional hit rate = sanity floor ONLY, not the goal.** Binding gate = positive risk-adjusted expectancy net of fees that **beats the naive + buy-&-hold baselines out-of-sample** at significant sample size. (Hit rate alone lies: you can win >50% and still lose ISK, or hit >50% trivially in a rising market while lagging buy-&-hold.)
- **Hard honesty limit (per §3):** exogenous shocks (balance patches, scarcity changes, wars, releases) are NOT predictable from price history — Phase 3 sells *backtested probabilistic edges with explicit downside*, never certainty. Tail risk on any single month-long position is real and must be surfaced.

**Deps:** Phase 3 needs ML libs (GBM and/or time-series) — declared at P3 kickoff **with sign-off** per the "no new deps" rule (§7); do NOT add before then.

Definition of done is per-step in each task prompt.

## 6. Current Task (Codex) — ✅ M9b ACTIVE

**STATUS: M9b ACTIVE — cross-region DuckDB haul reader. M9a COMPLETE (`ab937a9`), reviewed DONE (§7). Execute the M9b Context Pack directly below. The collapsed M8c pack further down is finished reference only — do NOT execute it.**

---

### M9b — cross-region DuckDB haul reader

Second haul slice. ADD a reader that returns `list[HaulQuote]` (the M9a input shape) for a **source hub → destination hub** pair: buy at source-station best ASK, sell at dest-station best BID. Mirrors M8b's `read_station_quotes` (same module, same patterns) but reads **two** snapshots (source region + dest region) and joins to **executable pairs only** (an item must be buyable at source AND sellable at dest). **Reuse M8b's existing helpers** (`_latest_snapshot_path`, `_read_best_quotes`, `_read_daily_volumes`, `_duckdb_string_literal`) — the only genuinely new query is the SDE `type_name + volume` lookup. NO analytics logic; NO new fee math.

**New-workflow note:** read the **To gather** files for exact signatures + the existing reader patterns to mirror; write only the files in scope. Anything that changes this design → STOP + §9.

### CONTEXT PACK

**Files in scope (write only these):**
- EDIT `src/evemarket/store/readers.py` — ADD `read_haul_quotes(...)` (public) + ONE new private helper `_read_type_metadata(...)` (name **and** volume). Import `HaulQuote` from `evemarket.analytics.haul`. **Do NOT alter** `read_station_quotes`, `_read_best_quotes`, `_read_daily_volumes`, `_latest_snapshot_path`, `_read_type_names`, or `_duckdb_string_literal`.
- EDIT `tests/test_readers.py` — ADD haul-reader tests; **reuse the existing fixture helpers** in that file (snapshot writer, `ensure_market_db`/`record_ingest_run`, `market_history` rows, the tmp `sde.duckdb` builder). Extend the SDE fixture so `sde_types` includes a `volume` column.
- EDIT `HANDOFF.md` §8 (log).
- Do NOT touch `analytics/haul.py`, `station_trade.py`, `config.py`, `store/schema.py`, `store/writers.py`, or anything else.

**To gather (read yourself — do not edit):**
- `src/evemarket/store/readers.py` — mirror EXACTLY: `read_station_quotes` flow (`data_dir/market.duckdb` + `data_dir/sde.duckdb`, `with ensure_market_db(market_path) as connection:`, `volume_window_days<1` → `ValueError`), and the helpers you'll reuse: `_latest_snapshot_path(connection, region_id) -> Path | None`, `_read_best_quotes(connection, snapshot_path, station_id) -> list[(type_id, best_bid, best_ask)]` (COALESCE one-sided→0.0), `_read_daily_volumes(connection, region_id, *, volume_window_days) -> dict[int,float]`, `_read_type_names`/`_duckdb_string_literal` (copy the ATTACH/DETACH `(READ_ONLY)` + escaped-literal pattern for the new metadata helper).
- `src/evemarket/analytics/haul.py` — `HaulQuote` field order/types (the return shape).
- `tests/test_readers.py` — reuse its fixtures; see how it builds the tmp `sde.duckdb` (`sde_types`) so you can add the `volume` column.

**Caller contracts (paste — trust these):**
- `HaulQuote(type_id:int, type_name:str, source_price:float, dest_price:float, volume_m3:float, daily_volume:float)` — frozen; `source_price`=source-station best ask, `dest_price`=dest-station best bid.
- SDE table `sde_types(type_id, type_name, group_id, market_group_id, volume, published)` at `config.data_dir/sde.duckdb` (per `sde/load.py`). Need `type_name` + `volume` (DOUBLE m³).

**Deliverable — `read_haul_quotes`:**

```python
def read_haul_quotes(
    config: Config,
    source_region_id: int,
    source_station_id: int,
    dest_region_id: int,
    dest_station_id: int,
    *,
    volume_window_days: int = 30,
) -> list[HaulQuote]:
```

- `volume_window_days < 1` → `ValueError` (mirror `read_station_quotes`).
- Open `ensure_market_db(market_path)` once (single connection for everything, like M8b).
- `source_snapshot = _latest_snapshot_path(connection, source_region_id)`; `dest_snapshot = _latest_snapshot_path(connection, dest_region_id)`. If **either** is None → `return []`.
- Source asks: `_read_best_quotes(connection, source_snapshot, source_station_id)` → keep `{type_id: best_ask}` where `best_ask > 0`.
- Dest bids: `_read_best_quotes(connection, dest_snapshot, dest_station_id)` → keep `{type_id: best_bid}` where `best_bid > 0`.
- **Executable pairs = inner join** on `type_id` (present in BOTH maps). If empty → `return []`.
- `volumes = _read_daily_volumes(connection, dest_region_id, volume_window_days=volume_window_days)` (liquidity that matters is **destination** demand).
- `meta = _read_type_metadata(connection, sde_path, type_ids)` → `dict[int, tuple[str, float]]` (name, volume).
- Build one `HaulQuote` per paired `type_id`, **sorted by `type_id`**:
  - `type_name = meta.get(tid, (f"#{tid}", 0.0))[0]`; `volume_m3 = meta.get(tid, (f"#{tid}", 0.0))[1]`.
  - `source_price = source_ask`; `dest_price = dest_bid`; `daily_volume = volumes.get(tid, 0.0)`.
- New helper `_read_type_metadata(connection, sde_path, type_ids) -> dict[int, tuple[str, float]]`: copy `_read_type_names`' structure (early-return `{}` if no ids or `not sde_path.exists()`; `ATTACH … (READ_ONLY)` via `_duckdb_string_literal`; `SELECT type_id, type_name, volume … WHERE type_id IN (SELECT UNNEST(?))`; `DETACH` in `finally`); return `{int(tid): (str(name), float(volume)) for …}`.

**Conventions to mirror:** explicit param-binding for all query VALUES (`?`); the SDE path stays a built string literal in `ATTACH` (DuckDB rejects `?` there — the M8b-accepted deviation, do the same); single connection in a `with ensure_market_db(...)`; `int()/float()/str()` casts on row values; **no new deps**; full type hints; `from __future__ import annotations` already present. **Fallbacks (honest, mirror M8b):** type missing from SDE (or SDE file absent) → `type_name=f"#{tid}"`, `volume_m3=0.0` (a 0-volume quote is returned as-is; the M9a scanner then skips it — reader's job is to report, not filter).

**Boundary** — gather only the named files; write only the 3 in scope; reuse the existing helpers (don't rewrite the order-book/volume SQL). No analytics, no CLI, no schema changes. Anything that changes the plan → STOP + §9.

**Verification (paste §8, terse per §2) — tests are HERMETIC (tmp fixtures + DuckDB/parquet/SDE, NO network/live data):**
- Reuse `test_readers.py` fixtures. Build **two** order snapshots under `tmp_path` data_dir: a SOURCE region (e.g. `10000002`, source station) and a DEST region (e.g. `10000043`, dest station); record each via `record_ingest_run` (`source='esi_orders'`, `status='success'`, `snapshot_path` set). Add `market_history` rows for the DEST region. Build a tmp `sde.duckdb` `sde_types` with `(type_id, type_name, volume)`.
- **Happy path / executable-pair join:** source has type 34 SELL@100 (ask) + type 35 SELL@100; dest has type 34 BUY@130 (bid) + type 36 BUY@200. → result is **exactly one** `HaulQuote` for type 34: `source_price==100`, `dest_price==130`, `volume_m3==<sde vol>`, `daily_volume==<dest history avg>`, `type_name=='Tritanium'`. Type 35 (source-only) and 36 (dest-only) excluded.
- **No source snapshot** (only dest recorded) → `[]`. **No dest snapshot** (only source recorded) → `[]`.
- **SDE fallback:** a paired type absent from `sde_types` (or point `data_dir` at a dir w/o `sde.duckdb`) → that quote has `type_name==f"#{tid}"` and `volume_m3==0.0`.
- **Feeds the scanner (integration sanity):** pass the happy-path result to `scan_haul_opportunities(quotes, Config())` → at least one `HaulResult` (use a non-trivial `volume_m3` so quantity ≥ 1).
- **`volume_window_days < 1` → `ValueError`.**
- `python -m pytest -q` (bundled-Python abs path `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`; if AppData temp denied → `--basetemp .pytest-tmp` at a fresh dir) — prior **79 passed, 1 skipped** stays green + new pass.
- `python -m ruff check .` → clean. `python -m mypy src/` → **clean** (still **24** source files — only `readers.py` edited, no new module).
- Pre-commit `git status --short`: only `src/evemarket/store/readers.py`, `tests/test_readers.py`, `HANDOFF.md` (untracked `HANDOFF_ARCHIVE.md` is unrelated — do NOT stage). No `data/` / duckdb / parquet. Commit `feat: cross-region haul reader -> store/readers.py (M9b)`; `git push origin main` (no force).

When done: append §8 entry (terse, **INCLUDE the commit hash + what you gathered/reused**) and STOP. After M9b → **M9c** CLI `haul` command (wires `read_haul_quotes` → `scan_haul_opportunities` → formatted table; mirrors M8c `scan`).

---

<details><summary>Completed — M8c: CLI `scan` command (reference)</summary>

M8b DONE (§7). Final piece of the first scanner: a Typer `scan` command that wires the M8b reader → the M8a pure scanner → a formatted ISK table. This completes the M8 vertical slice (live data → ranked station trades). **No analytics logic here** — `scan` only loads config, calls the two existing functions, and formats output. After M8c the station-trade scanner is end-to-end; next is `haul.py`.

**New-workflow note:** read the **To gather** files for the exact signatures + the existing CLI command style to mirror; write only the files in scope. Anything that changes this design → STOP + §9.

### CONTEXT PACK

**Files in scope (write only these):**
- EDIT `src/evemarket/cli.py` — ADD one `@app.command("scan")` function (+ a small private formatting helper if useful). Do NOT alter existing commands.
- CREATE `tests/test_cli_scan.py`.
- EDIT `HANDOFF.md` §8 (log).
- Do NOT touch `store/readers.py`, `analytics/station_trade.py`, `config.py`, or anything else.

**To gather (read yourself — do not edit):**
- `src/evemarket/cli.py` — mirror the EXISTING command style exactly: `@app.command(...)`, the `--config`/`-c` `typer.Option` block, `load_config(config)`, and the `region or loaded_config.tracked_regions[0]` default pattern. Use `typer.echo` for all output (no new deps; no `rich`).
- `src/evemarket/store/readers.py` — `read_station_quotes` (signature pasted below; confirm).
- `src/evemarket/analytics/station_trade.py` — `scan_station_trades` + `StationTradeResult` fields (pasted below; confirm).

**Caller contracts (paste — trust these):**
- `read_station_quotes(config: Config, region_id: int, station_id: int, *, volume_window_days: int = 30) -> list[MarketQuote]` — sync; `[]` when no snapshot.
- `scan_station_trades(quotes, config, *, min_roi=0.0, min_unit_profit=0.0, min_daily_volume=0.0, limit=None) -> list[StationTradeResult]` — raises `ValueError` on negative thresholds / `limit<1`.
- `StationTradeResult(type_id:int, type_name:str, buy_price:float, sell_price:float, spread:float, unit_profit:float, roi:float, daily_volume:float)` — `roi` is a fraction (e.g. `0.04` = 4%).
- `Config` has `tracked_regions: list[int]` (default `[10000002]`) and `home_hub_station_id: int` (default `60003760`).

**Deliverable — `@app.command("scan")` `def scan_command(...)`:**
- Options (mirror existing style; `--config`/`-c` Path default `config.toml`):
  - `--region` `int | None` default `None` → resolve to `region or loaded_config.tracked_regions[0]`.
  - `--station` `int | None` default `None` → resolve to `station if station is not None else loaded_config.home_hub_station_id`.
  - `--min-roi` `float` default `0.0`, `--min-unit-profit` `float` default `0.0`, `--min-daily-volume` `float` default `0.0`.
  - `--limit` `int` default `20`, `typer.Option(..., min=1)`.
  - `--volume-window-days` `int` default `30`, `typer.Option(..., min=1)`.
- Body: `load_config(config)`; resolve region+station; `quotes = read_station_quotes(loaded_config, region, station, volume_window_days=...)`; `results = scan_station_trades(quotes, loaded_config, min_roi=..., min_unit_profit=..., min_daily_volume=..., limit=...)`.
- Output:
  - Echo a header line: `Region: <r>  Station: <s>  Quotes: <len(quotes)>`.
  - `quotes == []` → echo `No market snapshot found for region <r>. Run ingest-orders first.` and return (exit 0).
  - `results == []` → echo `No station-trade opportunities met the filters.` and return (exit 0).
  - Else echo an aligned table — a header row + one row per result: columns `type_id`, `type_name`, `buy`, `sell`, `spread`, `unit_profit`, `roi%`, `daily_vol`. Right-align numerics with thousands separators (`f"{v:,.2f}"`); show roi as percent (`f"{result.roi*100:,.2f}"`). Keep it plain f-string column widths (mirror the terse `typer.echo` style — do NOT add a table dep).

**Conventions:** NO analytics/I/O logic in the command beyond the two calls + formatting; full type hints; reuse the file's existing `from __future__ import annotations`; terse; **no new deps** (`typer`, stdlib only — `typer.testing.CliRunner` ships with typer).

**Boundary** — gather only the To-gather files; write only the 3 in-scope; do NOT modify the reader/scanner or add new analytics. Design change needed → STOP + §9.

**Verification (paste §8, terse per §2) — tests are HERMETIC (tmp fixtures + `CliRunner`, NO network/live data):**
- Reuse the M8b fixture approach (`write_orders_snapshot` + `ensure_market_db`/`record_ingest_run` + `market_history` rows + a tiny `sde.duckdb`) under a `tmp_path` data_dir; write a minimal `config.toml` in `tmp_path` setting `data_dir` to that dir (or rely on `load_config` defaults if `data_dir` matches — but a TOML pointing at `tmp_path` is cleanest). Invoke via `from typer.testing import CliRunner; CliRunner().invoke(app, ["scan", "--config", <cfg>, "--region", "10000002"])`. Then:
  - **Happy path:** snapshot with type 34 buy@100/sell@120 + type 35 sell@200-only → `result.exit_code == 0`; output contains `Tritanium` and `34`; does NOT list `35` (no bid → scanner skips it).
  - **No snapshot** (empty market db, no ingest_runs) → `exit_code == 0` and output contains `No market snapshot`.
  - **Filter excludes all:** pass `--min-roi 999` → `exit_code == 0` and output contains `No station-trade opportunities`.
  - (Optional) `--limit 1` returns at most one data row.
- `python -m pytest -q` (bundled-Python abs path: `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`; if AppData temp denied, use `--basetemp .pytest-tmp` — note prior session hit a Windows perm-denied on **deleting** `.pytest-tmp`; if so, point `--basetemp` at a fresh dir) — prior **62 passed, 1 skipped stays green** + new pass.
- `python -m ruff check .` → clean. `python -m mypy src/` → **clean** (still 24 source files — no new `src/` module, only `cli.py` edited).
- Pre-commit `git status --short`: only `src/evemarket/cli.py`, `tests/test_cli_scan.py`, `HANDOFF.md` (untracked `HANDOFF_ARCHIVE.md` is an unrelated planner doc — do NOT stage it); no `data/`/`*.duckdb`/parquet. Commit `feat: CLI scan command -> station-trade table (M8c)`; `git push origin main` (no force). Include `HANDOFF.md`.

When done: append §8 entry (terse, **INCLUDE the commit hash + what you gathered from the existing CLI style**) and STOP. After M8c → **M9** `analytics/haul.py` (regional arbitrage scanner — to be decomposed when scoped).

</details>

> Completed task Context Packs (M4a–M8a) archived/superseded — load-bearing facts retained in §7 (verdicts) + §8 (logs); full early packs in `HANDOFF_ARCHIVE.md` §A.

## 7. Planner/Debugger Notes (Claude)

> Full per-milestone notes M0–M5c + Phase-1 audit archived in `HANDOFF_ARCHIVE.md` §B.

**Milestone ledger (status · commit):**
- M0 Scaffold ✅ `04d9c6a` · M1 SDE ✅ `04d9c6a` · REPO ✅ `04d9c6a`
- M2 ESI client ✅ `6da016f` · M3 Orders ✅ `c1dacf8` → FIX2 `c228ca9`
- M4a ESI history ✅ `b51e885` · M4b everef backfill ✅ `e1ce7b2`
- M5a prices ✅ `9666724` · M5b scheduler ✅ `169bde0` · M5c quality ✅ `7eb3760`
- M5-FIX mypy-clean ✅ `f654b2f` (+docs `e7c851e`) — **Phase 1 COMPLETE to standard.**
- M6 fees ✅ `2cee47b` (+docs `f10b9c5`) — first Phase-2 primitive.
- M7 opportunity seam ✅ `46261d0` (+docs `18af9c7`) — `ProfitOpportunity`/`Acquisition`/`Disposal`.
- M8a station-trade ranking core ✅ `29f7a9c` (+docs `281363b`) — pure scan/rank.
- M8b DuckDB station-quote reader ✅ `55d5a3e` (+docs `8fbe063`, `f9e9571`) — `store/readers.py`.
- M8c CLI `scan` command ✅ `0bf9a99` (+docs `2812307`) — **M8 station-trade scanner complete end-to-end.**

**Standing decisions / known non-blockers (carry forward):**
- **"No new deps" is hard:** if Codex needs one → STOP + §9 for planner sign-off; never silently `pip install` to make tests pass (M3-FIX hidden-pytz trap).
- **DuckDB↔polars bulk insert avoids `pyarrow`** (not a dep): stage explicit-schema rows into a TEMP duckdb table via `executemany` + set-based `ON CONFLICT` upsert (`_upsert_history_frame`). If true bulk needed later, declare `pyarrow` w/ sign-off.
- **ESI error-budget** state is shared but **unlocked** across concurrent paginated pages — fine for single hub; revisit if parallelizing regions.
- **everef present-but-empty day file** → counted NEITHER fetched NOR missing (`days_fetched+days_missing` can be < range); self-healing on idempotent re-run.
- **Env (Codex/Windows):** bare `python` not on PATH → use bundled Python abs path; AppData temp perm denied → `--basetemp .pytest-tmp`; live runs need network escalation; `git status` warns global ignore inaccessible (benign).
- **Deferred (non-blocking, M0):** switch `Config`/`SkillConfig` `BaseSettings`→`BaseModel` so TOML is sole config source (BaseSettings allows silent env-var overrides). Small future task. (Also tracked §9.)

**Recent verdicts:**
- **M9a REVIEW: DONE.** `analytics/haul.py` + `tests/test_haul.py` match the pack. Reviewer re-ran locally → **79 passed, 1 skipped**, ruff clean, mypy clean (24 files). Verified: `HaulQuote`/`HaulResult` frozen w/ exact fields; `quantity = min(floor(cargo/vol), floor(capital/per_unit_cost))` with `per_unit_cost` from a qty=1 `station_trade_opportunity().cost` (exact b/c fee is linear, no per-order min); all skip paths (src/dest/vol≤0, `quantity<1` incl the too-bulky `vol>cargo` case); ONE opp call at full qty for profit/roi (**no duplicated math** — the parity test confirms `result.total_profit == station_trade_opportunity(...).profit`); `days_to_sell=inf` at zero volume; inclusive threshold filters incl `max_days_to_sell`; deterministic sort `(-total_profit,-roi,type_id)` verified by the `[34,35,36,37]` case (34 wins on 300>200; among the 200-tie 35 leads on ROI from qty=5/unit40 → cost 515, then 36<37 by type_id); `ValueError` on all 5 bad inputs. The test's `_dest_price_for_unit_profit` correctly inverts the zero-skill fee math (`dest*0.895 − src*1.03`). Codex's lone deviation: it fixed its OWN sort-test fixture (first run expected roi-before-total-profit) to match the spec's total-profit-primary order — correct direction (test→spec), logged §8. Git `ab937a9` + docs `01cad84`; scoped files only, no `data/`. Pure core to-standard → unblocks M9b.
- **M9 decomposed; M9a drafted (Context Pack).** Haul (regional arbitrage) split **M9a pure core → M9b cross-region reader → M9c CLI `haul`** (mirrors M8). M9a is self-contained: *we define the input shape* (`HaulQuote`: type_id/type_name/source_price=src ask/dest_price=dst bid/volume_m3/daily_volume), so **zero store-schema dependency** (DB internals gathered at M9b). Design: `HaulQuote`+`HaulResult` frozen + `scan_haul_opportunities(quotes, config, *, min_roi, min_total_profit, min_daily_volume, max_days_to_sell, limit)`. New value over M8a = **quantity sizing under cargo + capital constraints**: `quantity = min(floor(cargo_m3/volume_m3), floor(capital_isk/per_unit_cost))`, skip if `<1`; then ONE `station_trade_opportunity(...,quantity)` call gives profit/roi (reuses M6/M7 — **no duplicated math**). Per-unit cost from a qty=1 opp; capital cap is **exact** (fee linear, no per-order min). **Honesty decisions encoded (per §3):** (a) prices are guaranteed-executable (src ask/dst bid) + full station-trade fees both legs → profit is a *conservative floor*, immediate-fill lower-fee variant deferred; (b) liquidity *surfaced not baked* — `daily_volume`+`days_to_sell`(=load/turnover)+optional `min_daily_volume`/`max_days_to_sell` filters, NOT a capture-rate guess in headline profit (same stance as M8a). Sort `(-total_profit,-roi,type_id)`. Review focus on return: cargo-bound vs capital-bound quantity, the five skip paths, no-spread exclusion, each filter, `days_to_sell==inf` at zero volume, sort+limit+tiebreak, `ValueError` on bad thresholds/`limit=0`/`max_days_to_sell=0`, profit cross-checked against a direct `station_trade_opportunity` call (no duplicated math), pure (no I/O), no new deps, mypy(24 files)/ruff clean, only 2 files+HANDOFF touched, commit hash §8.
- **M8c REVIEW: DONE — M8 station-trade scanner COMPLETE end-to-end.** `cli.py` `scan` command + `tests/test_cli_scan.py` match the pack. Reviewer re-ran locally → **66 passed, 1 skipped**, ruff clean, mypy clean (24 files). Command is pure wiring: `load_config` → resolve `region or tracked_regions[0]` / `station ?? home_hub_station_id` → `read_station_quotes(...,volume_window_days=)` → `scan_station_trades(...,min_roi/min_unit_profit/min_daily_volume/limit)` → `_format_scan_table`; no analytics/I/O logic added. Imports correct (`StationTradeResult,scan_station_trades` from station_trade; `read_station_quotes` from store.readers). Options mirror existing style (`--config`/`-c`, `--limit`/`--volume-window-days` `min=1`); empty-quotes → "No market snapshot…" and empty-results → "No station-trade opportunities…" both exit 0. Table: aligned f-string widths, numerics right-aligned w/ `,.2f`, roi as `roi*100`. Tests hermetic (tmp `CliRunner` + DuckDB/parquet/SDE fixtures, no network). The `--limit 1` test is strong — verifies ordering (type 36's 30-spread outranks 34's 20-spread), the limit cut, AND the `#36` name-fallback together; happy-path confirms two-sided 34 shown / sell-only 35 skipped. Git `0bf9a99` + docs `2812307`; scoped files only, no `data/`. **First scanner is live data → ranked trades end-to-end.** Next: M9 `haul.py` (needs scoping/decomposition).
- **M8b REVIEW: DONE.** `store/readers.py` + `tests/test_readers.py` match the pack. Reviewer re-ran the suite locally → **62 passed, 1 skipped**, ruff clean, mypy clean (24 files). `read_station_quotes` is the single impure layer (station_trade.py untouched/pure). Verified each step: latest-snapshot resolved via `ingest_runs` (`source='esi_orders' AND status='success' AND snapshot_path IS NOT NULL ORDER BY snapshot_ts DESC LIMIT 1`); best bid/ask = `MAX(price)FILTER(is_buy_order)`/`MIN(price)FILTER(NOT is_buy_order)` at `location_id` with `COALESCE(...,0.0)` so one-sided→0 (scanner skips); trailing avg volume window-start = `MAX(date) − (window−1)` days, missing→0.0; SDE name left-join with `f"#{type_id}"` fallback when sde db / row absent; returned sorted by `type_id` via `ORDER BY type_id` in the quotes query. All query **values** parameterized (`?`). **Deviation accepted:** DuckDB's grammar genuinely rejects a `?` placeholder in `ATTACH`/`DETACH`, so the SDE path uses a built string literal via `_duckdb_string_literal` (single-quote doubling); path is from trusted `config.data_dir` and the escaping preserves the no-injection intent → behavior/security unchanged, no design change, correctly logged §8. SDE table gathered correctly (`sde_types(type_id,type_name)` per `sde/load.py`). Git `55d5a3e` + docs `8fbe063`/`f9e9571`; scoped files only, no `data/`. Reader to-standard → unblocks M8c.
- **M8a REVIEW: DONE.** `analytics/station_trade.py` + tests match the pack. `MarketQuote`/`StationTradeResult` frozen; `scan_station_trades` skips non-two-sided quotes, builds `station_trade_opportunity` at qty=1 (reuses M7 — no duplicated math), inclusive threshold filters, deterministic sort `(-roi, -daily_volume, type_id)`, validated `min_*>=0`/`limit>=1`. Hand-verified per-unit `4.4 / (4.4·103⁻¹)` (1/10-scale echo of M7) + the sort case `[35,36,37,34]` (35 wins on roi from the 30-spread; 36<37 by type_id tiebreak at equal roi/vol; 34 last on lower vol). Git `29f7a9c` + docs `281363b` pushed, exactly 3 files, no `data/`; §8 `57 passed,1 skip`/ruff/mypy clean. Pure core to-standard → unblocks M8b.
- **PHASE 3 COMMITTED + M8b drafted.** (a) **Phase 3 added to §5** (long-hold forecasting): user wants month+ predictions; gated on my confidence it can be ≥ net-even — defensible because **abstention is first-class** (only surface a trade with backtested positive expectancy net fees; else recommend nothing / fall back to deterministic edge → downside floor = 0). Encoded success bar: >50% hit rate = floor only; binding gate = expectancy beating naive + buy-&-hold baselines out-of-sample. ML deps deferred to P3 kickoff w/ sign-off. (b) **M8b drafted (§6):** NEW `store/readers.py` (planner-signed-off addition to §4 layout — mirrors `writers.py`; keeps `station_trade.py` pure I/O-free) with `read_station_quotes(config, region_id, station_id, *, volume_window_days=30) -> list[MarketQuote]`. I gathered the full store schema (ORDER_SCHEMA parquet cols: `type_id/is_buy_order/price/location_id/region_id/snapshot_ts`; `market_history` cols; `ingest_runs.snapshot_path`) and pasted the exact query design; delegated only the SDE type-name table lookup to Codex ("To gather" `sde/load.py`). Hermetic tmp-fixture tests (no live data/network). Review focus on return: latest-snapshot resolution via `ingest_runs`, `MAX(price)FILTER(is_buy_order)`/`MIN(price)FILTER(NOT is_buy_order)` best bid/ask at station, NULL→0 one-sided drop, trailing-window avg volume, SDE name join + fallback, returns `MarketQuote` list feeding M8a, no new deps, mypy/ruff clean, commit hash §8.
- **M7 REVIEW: DONE.** `analytics/opportunity.py` + `tests/test_opportunity.py` match the pack exactly. The abstract-property gotcha was handled right: `quantity` is a plain annotation on both ABCs, only `total_cost`/`net_proceeds` abstract → concrete frozen dataclasses instantiate (49 tests construct them). Legs reuse M6 `broker_fee`/`sales_tax` (no duplicated formulas); `MarketBuy.total_cost = gross+broker`, `MarketSell.net_proceeds = gross−broker−tax`; `ProfitOpportunity` has quantity-match validation + `cost`/`revenue`/`profit`/`roi`(cost≤0 guard)/`quantity`; factory mirrors M6 config delegate. Verified math: zero-skill `1030/1074/44`, `roi=44/1030`; invariant `profit = spread − station_trade_fees.total` (=137.5 at BR5/acc5/f10/c10); factory floor case `1010/1147.5/137.5`; all 4 `ValueError` paths. Git: `46261d0` + docs `18af9c7` on `main`, pushed; commit touched exactly the 3 intended files, no `data/`. §8 verification (`49 passed, 1 skipped` / ruff clean / mypy 23 files clean) matches. **Codex's first run as bounded gatherer under the new workflow — read `fees.py`/`config.py`/the stub itself, stayed in scope, logged what it read (§8). Workflow change validated.** Seam to-standard → unblocks M8.
- **M8 decomposed; M8a drafted (Context Pack).** First scanner split into **M8a pure ranking core → M8b DuckDB reader → M8c CLI** (one-step-at-a-time; mirrors Phase-1's M4a/b, M5a/b/c). M8a is fully self-contained: *we define the input row shape* (`MarketQuote`: type_id/type_name/best_bid/best_ask/daily_volume), so it has **zero dependency on the store schema** — that's why it can be packed precisely now without me gathering DB internals (those I'll gather for M8b). Design: `MarketQuote` + `StationTradeResult` (flat, CLI-ready) frozen dataclasses + `scan_station_trades(quotes, config, *, min_roi, min_unit_profit, min_daily_volume, limit)` — skip non-two-sided quotes (`best_bid/ask<=0`), build `station_trade_opportunity(...)` at **quantity=1** (fees pure-%, so roi/unit-profit scale-invariant; ISK/day projection w/ capture-rate assumption deferred to keep it honest per §3), filter on thresholds, sort roi desc → volume desc → type_id asc (deterministic), optional limit. Reuses M7 (no duplicated math). Review focus on return: per-unit numbers (4.4 / 4.4/103, the 1/10-scale echo of M7), no-market skip, threshold filters, deterministic sort+limit+tiebreak, `ValueError` on negative thresholds/`limit=0`, pure (no I/O/DB/CLI), no new deps, only the 2 files+HANDOFF touched, mypy/ruff clean, commit hash in §8.
- **M6 REVIEW: DONE.** `analytics/fees.py` + `tests/test_fees.py` match the pack exactly. Verified every formula/constant by hand: broker rate floor `BR5+f10+c10 → 0.01` exactly (holds, not below); negative faction `−10 → 0.033 > 0.03`; `sales_tax_rate(5)=0.03375`; `station_trade_fees(100,120,10)=30/36/90/156`; `from_config` floor case `=10/12/40.5/62.5`. Pure (no I/O), `ValueError` on bad input, `TradeFees` frozen, named constants, no new deps; bonus `bool`-rejection on int params (correct). Git: `2cee47b` + docs `f10b9c5` on `main`, pushed, no `data/` staged; §8 verification (`45 passed, 1 skipped` / ruff clean / mypy 23 files clean) matches. Fee primitive is to-standard → unblocks M7.
- **M7 drafted (Context Pack) — the §4 generic seam.** `analytics/opportunity.py`: `Acquisition`/`Disposal` ABCs (only `total_cost`/`net_proceeds` abstract; `quantity` a plain annotation to dodge the no-default-field-vs-abstract-property trap → keeps concrete dataclasses instantiable) + frozen `MarketBuy`/`MarketSell` reusing M6 `broker_fee`/`sales_tax` (buy leg = gross+broker; sell leg = gross−broker−tax) + frozen `ProfitOpportunity(acquisition, disposal)` exposing `cost`/`revenue`(net)/`profit`/`roi`(guard cost≤0)/`quantity` with quantity-match validation + `station_trade_opportunity(config,…)` factory mirroring M6's config delegate. First use of the new workflow: delegated the stable `fees.py`/`config.py` signature-gathering to Codex ("To gather"), pasted only the load-bearing seam design + the abstract-property gotcha. Review focus on return: ABCs correct & instantiable (no abstract `quantity`), legs reuse fees (no duplicated formulas), the cross-check invariant `profit == spread − station_trade_fees.total` holds, zero-skill numbers (1030/1074/44) + factory floor case (1010/1147.5/137.5), `ValueError` on quantity-mismatch/negative/zero, pure (no I/O), no new deps, mypy/ruff clean, only the 2 files+HANDOFF touched, commit hash in §8.
- **M5-FIX REVIEW: DONE — PHASE 1 FULLY TO-STANDARD.** Verified via git: commits `f654b2f` (fix) + `e7c851e` (docs log) on `main`, tree clean, nothing unpushed. Codex §8: `mypy src/` → `Success: no issues found in 23 source files` (the new gate), `pytest` → `36 passed, 1 skipped` (UNCHANGED = behavior-preserving), `ruff` clean; only the 4 intended files touched (`pyproject.toml`, `writers.py`, `sde/load.py`, `HANDOFF.md`); no `data/` staged. The lone Phase-1 audit gap is closed. **Phase 1 data pipeline COMPLETE to standard. M0–M5-FIX DONE.**
- **M6 drafted (Context Pack) — FIRST Phase-2 task.** `analytics/fees.py` deterministic broker-fee + sales-tax (skill/standings-aware). Planner researched live/authoritative (EVE University Tax wiki + CCP support article): broker fee = `3% − 0.3%×BrokerRelations − 0.03%×factionStanding − 0.02%×corpStanding`, 1% floor, charged on buy AND sell order *placement*, **unmodified** standings (negative → higher fee); sales tax = `7.5% × (1 − 0.11×Accounting)` (Accounting V → 3.375%), paid by seller on sale proceeds. Verified the seam already exists in `Config` (`config.skills.{accounting,broker_relations}` 0–5 ge/le-validated, `config.standings_factional`, `config.standings_corp`) — design is **skill/standings-aware from the start** (flat rate is just the degenerate case; "fee-accurate" is the core value per §3). Pure module (no I/O/CLI): named constants, `broker_fee_rate`/`sales_tax_rate` (validated + 1% clamp), `broker_fee`/`sales_tax` amounts, `TradeFees` frozen dataclass + `station_trade_fees(...)` round-trip + `station_trade_fees_from_config(config, ...)`. CLI deferred to land with the first scanner. Deferred-and-noted: flat 100-ISK per-order broker minimum (negligible vs %, confirm later). Review focus on return: exact constants/formulas, 1% floor holds + negative-standing raises fee, Accounting-V tax = 0.03375, `ValueError` validation, `station_trade_fees(100,120,10)` = 30/36/90/156, pure (no I/O), no new deps, only `fees.py`+test touched, mypy/ruff clean, commit hash in §8.

## 8. Execution Log (Codex)

> Full per-task logs M0–M5-FIX archived in `HANDOFF_ARCHIVE.md` §C.
> Template: `### M<n> — <title> — <date> — COMPLETE/BLOCKED` then: Files | Commands+result | Verification | Deviations | Questions.

_(Append new entries below — next: M9b.)_

### M6 — deterministic broker fee + sales tax — 2026-06-28 — COMPLETE
- Files: `src/evemarket/analytics/fees.py`, `tests/test_fees.py`, `HANDOFF.md`.
- Commands+result:
  - `python -m pytest -q --basetemp .pytest-tmp` → FAIL: `python` not on PATH.
  - `python -m ruff check .` → FAIL: `python` not on PATH.
  - `python -m mypy src/` → FAIL: `python` not on PATH.
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q --basetemp .pytest-tmp` → `45 passed, 1 skipped, 1 warning` (pytest cache WinError 5 only).
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check .` → `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m mypy src/` → `Success: no issues found in 23 source files`
  - `git status --short` → intended tracked files + unrelated untracked `HANDOFF_ARCHIVE.md`; no `data/`/duckdb/parquet.
- Verification: PASS; fee formulas, 1% floor, negative-standing increase, Accounting V, round-trip totals, config delegate, ValueError cases covered.
- Deviations: used bundled Python abs path; bare `python` unavailable. No live run; pure calc.
- Questions: none.
- Commit: `2cee47b`.

### M7 — ProfitOpportunity seam — 2026-06-28 — COMPLETE
- Files: `src/evemarket/analytics/opportunity.py`, `tests/test_opportunity.py`, `HANDOFF.md`.
- Gathered/read: `src/evemarket/analytics/opportunity.py` stub; `src/evemarket/analytics/fees.py` signatures (`broker_fee`, `sales_tax`, `station_trade_fees`, `TradeFees`); `src/evemarket/config.py` (`Config`, `SkillConfig` fields).
- Commands+result:
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q --basetemp .pytest-tmp` → `49 passed, 1 skipped, 1 warning` (pytest cache WinError 5 only).
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check .` → `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m mypy src/` → `Success: no issues found in 23 source files`
  - `git status --short` → scoped files + unrelated modified `AGENTS.md` + unrelated untracked `HANDOFF_ARCHIVE.md`; no `data/`/duckdb/parquet.
- Verification: PASS; ABCs instantiable, fee reuse invariant, zero-skill totals, config factory, ValueError cases covered.
- Deviations: used bundled Python abs path; bare `python` known unavailable. No live run; pure calc. Did not touch/stage unrelated `AGENTS.md` or `HANDOFF_ARCHIVE.md`.
- Questions: none.
- Commit: `46261d0`.

### M8a — pure station-trade ranking core — 2026-06-28 — COMPLETE
- Files: `src/evemarket/analytics/station_trade.py`, `tests/test_station_trade.py`, `HANDOFF.md`.
- Gathered/read: `src/evemarket/analytics/station_trade.py` stub; `src/evemarket/analytics/opportunity.py` (`station_trade_opportunity`, `ProfitOpportunity.cost/profit/roi`); `src/evemarket/config.py` (`Config` defaults zero skills/standings).
- Commands+result:
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q --basetemp .pytest-tmp` → `57 passed, 1 skipped, 1 warning` (pytest cache WinError 5 only).
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check .` → `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m mypy src/` → `Success: no issues found in 23 source files`
  - `git status --short` → scoped files + unrelated modified `AGENTS.md` + unrelated untracked `HANDOFF_ARCHIVE.md`; no `data/`/duckdb/parquet.
- Verification: PASS; per-unit economics, no-market skip, threshold filters, deterministic sort+limit+tiebreak, ValueError cases covered.
- Deviations: used bundled Python abs path; bare `python` known unavailable. No live run; pure calc. Did not touch/stage unrelated `AGENTS.md` or `HANDOFF_ARCHIVE.md`.
- Questions: none.
- Commit: `29f7a9c`.

### M8b — DuckDB station-quote reader — 2026-06-28 — COMPLETE
- Files: `src/evemarket/store/readers.py`, `tests/test_readers.py`, `HANDOFF.md`.
- Gathered/read: `src/evemarket/sde/load.py` (`sde_types(type_id,type_name)`, SDE path `config.data_dir/sde.duckdb`); `src/evemarket/store/writers.py` (`write_orders_snapshot`, `ORDER_SCHEMA`, `record_ingest_run`); `src/evemarket/store/schema.py` (`ensure_market_db`, `ingest_runs`, `market_history`); `src/evemarket/analytics/station_trade.py` (`MarketQuote`); `src/evemarket/config.py` (`Config.data_dir`).
- Commands+result:
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q --basetemp .pytest-tmp` → FAIL: DuckDB `ATTACH ? AS ...` parser rejects parameter placeholder.
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check .` → `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m mypy src/` → `Success: no issues found in 24 source files`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q --basetemp .pytest-tmp` → `62 passed, 1 skipped, 1 warning` (pytest cache WinError 5 only).
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check .` → `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m mypy src/` → `Success: no issues found in 24 source files`
  - `git status --short` → scoped files + user-requested modified `AGENTS.md` + unrelated untracked `HANDOFF_ARCHIVE.md`; no `data/`/duckdb/parquet.
- Verification: PASS; latest snapshot, station filter, one-sided NULL→0, trailing avg volume, SDE name lookup + fallback, no snapshot, scanner feed, bad volume window covered.
- Deviations: DuckDB `ATTACH` does not accept query params; used escaped DuckDB string literal for SDE path only, normal query values remain parameterized. No live run; hermetic tmp fixtures only. `AGENTS.md` committed separately per user request.
- Questions: none.
- Commit: `55d5a3e`.

### M8c — CLI scan command — 2026-06-28 — COMPLETE
- Files: `src/evemarket/cli.py`, `tests/test_cli_scan.py`, `HANDOFF.md`.
- Gathered/read: `src/evemarket/cli.py` existing style (`@app.command`, `Path("config.toml")` `--config`/`-c`, `load_config(config)`, `region or loaded_config.tracked_regions[0]`, `typer.echo`); `src/evemarket/store/readers.py` (`read_station_quotes`); `src/evemarket/analytics/station_trade.py` (`scan_station_trades`, `StationTradeResult` fields).
- Commands+result:
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q --basetemp .pytest-tmp` → `66 passed, 1 skipped, 1 warning` (pytest cache WinError 5 only).
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check .` → `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m mypy src/` → `Success: no issues found in 24 source files`
  - `git status --short` → scoped files + unrelated untracked `HANDOFF_ARCHIVE.md`; no `data/`/duckdb/parquet.
- Verification: PASS; happy-path table, no-snapshot message, filter-empty message, limit-one output covered with hermetic tmp fixtures.
- Deviations: used bundled Python abs path; bare `python` known unavailable. No live run/network; CLI tests use tmp DuckDB/parquet/SDE fixtures only.
- Questions: none.
- Commit: `0bf9a99`.

### M9a — pure haul ranking core — 2026-06-29 — COMPLETE
- Files: `src/evemarket/analytics/haul.py`, `tests/test_haul.py`, `HANDOFF.md`.
- Gathered/read: `src/evemarket/analytics/haul.py` stub; `src/evemarket/analytics/opportunity.py` (`station_trade_opportunity`, `ProfitOpportunity.cost/profit/roi`); `src/evemarket/analytics/station_trade.py` structure; `src/evemarket/config.py` (`cargo_m3`, `capital_isk`, skills/standings defaults).
- Commands+result:
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q --basetemp .pytest-tmp` → FAIL: sort fixture expected ROI before total profit; test fixed.
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check .` → `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m mypy src/` → `Success: no issues found in 24 source files`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q --basetemp .pytest-tmp` → `79 passed, 1 skipped, 1 warning` (pytest cache WinError 5 only).
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check .` → `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m mypy src/` → `Success: no issues found in 24 source files`
  - `git status --short` → scoped files + unrelated untracked `HANDOFF_ARCHIVE.md`; no `data/`/duckdb/parquet.
- Verification: PASS; cargo-bound, capital-bound, invalid skip paths, no-spread exclusion, filters, zero-volume `days_to_sell=inf`, sort+limit+tiebreak, ValueError cases, direct `station_trade_opportunity` profit parity covered.
- Deviations: used bundled Python abs path; bare `python` known unavailable. No live run/network; pure calc tests only. Did not touch/stage unrelated `HANDOFF_ARCHIVE.md`.
- Questions: none.
- Commit: `ab937a9`.

### M9b — cross-region DuckDB haul reader — 2026-06-29 — COMPLETE
- Files: `src/evemarket/store/readers.py`, `tests/test_readers.py`, `HANDOFF.md`.
- Gathered/read: `src/evemarket/store/readers.py` (`read_station_quotes`, `_latest_snapshot_path`, `_read_best_quotes`, `_read_daily_volumes`, `_read_type_names`, `_duckdb_string_literal`); `src/evemarket/analytics/haul.py` (`HaulQuote`, scanner integration); `tests/test_readers.py` fixtures/helpers.
- Commands+result:
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q --basetemp .pytest-tmp` → `85 passed, 1 skipped, 1 warning` (pytest cache WinError 5 only).
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check .` → `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m mypy src/` → `Success: no issues found in 24 source files`
  - `git status --short` → scoped files + unrelated untracked `HANDOFF_ARCHIVE.md`; no `data/`/duckdb/parquet.
- Verification: PASS; executable-pair join, missing source/dest snapshots, SDE fallback name+0.0 volume, scanner feed, `volume_window_days<1` covered.
- Deviations: used bundled Python abs path; bare `python` known unavailable. No live run/network; hermetic tmp DuckDB/parquet/SDE fixtures only. Did not touch/stage unrelated `HANDOFF_ARCHIVE.md`.
- Questions: none.
- Commit: pending.

## 9. Open Questions / Blockers

> Resolved items (M5b-block, PII, REPLACE_ME, Fuzzwork) archived in `HANDOFF_ARCHIVE.md` §D.

- **Deferred (non-blocking, M0):** switch `Config`/`SkillConfig` from `pydantic_settings.BaseSettings` to `pydantic.BaseModel` so TOML is sole config source (BaseSettings allows silent env-var overrides). Future small task.
