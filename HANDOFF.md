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
- **UI layer (added 2026-06-29, planner sign-off — USER-APPROVED):** `streamlit` local browser dashboard, **optional** install only (`pip install -e ".[ui]"` extra; NOT a core dep — core CLI stays dep-light). Module `src/evemarket/ui/app.py`, launched via `streamlit run`. **Pure presentation:** reuses `load_config` + the M8/M9 readers + scanners; ZERO analytics/I-O logic of its own (same discipline as the CLI commands). This is the ONLY browser surface; everything else stays `typer` CLI.

**Layout:**
```
pyproject.toml  config.toml  README.md
data/ (gitignored): sde.duckdb  market.duckdb  snapshots/orders/region=.../date=.../*.parquet
src/evemarket/: __init__.py  config.py  cli.py
  esi/{__init__,client,models}.py
  sde/{__init__,load}.py
  ingest/{__init__,orders,history,prices,backfill}.py
  store/{__init__,schema,writers,quality,readers}.py   # readers.py added M8b (planner sign-off 2026-06-28)
  analytics/{__init__,fees,opportunity,station_trade,haul,backtest}.py   # backtest.py added P3-0a (planner sign-off 2026-06-29, pure leaf module)
  ui/{__init__,app}.py   # streamlit dashboard, added M10 (planner sign-off 2026-06-29, optional [ui] extra)
tests/
```

## 5. Phase plan (no jumping ahead)

**Phase 1 — data pipeline**
- M0 Scaffold ✅ | M1 SDE→`sde.duckdb` ✅ | REPO git+push ✅ | M2 ESI client ✅ | M3 Order snapshots + `ingest_runs` ✅ | M4a ESI daily history → `market_history` ✅ | M4b everef.net bulk backfill ✅ | M5a ESI prices → `market_prices` ✅
- **M5** Prices ✅ | scheduler (M5b) ✅ | data-quality (M5c) ✅ | M5-FIX mypy-clean ✅ — **Phase 1 COMPLETE & to-standard.** | M6 `analytics/fees.py` ✅ `2cee47b` | M7 `analytics/opportunity.py` seam ✅ `46261d0` | M8a `station_trade.py` ranking core ✅ `29f7a9c` | M8b `store/readers.py` DuckDB reader ✅ `55d5a3e` | M8c CLI `scan` ✅ `0bf9a99`. M9 `analytics/haul.py` regional arbitrage — M9a pure core ✅ `ab937a9` → M9b cross-region reader ✅ `81148ea` → M9c CLI `haul` ✅ `c8bae2d`. **Phase-2 scanners (station-trade + haul) COMPLETE end-to-end.** M10 Streamlit dashboard — M10a skeleton+station panel ✅ `788d295` → M10b haul panel ✅ `96d74da`. **M10 COMPLETE (both scanners in one browser view).** ← **CURRENT/NEXT: Phase 3 (P3-0 backtest harness) — needs planner scoping + ML-dep sign-off; NOT started.**

**Phase 2 — deterministic analytics (stubbed):** `fees.py` ✅, `opportunity.py` ✅, `station_trade.py` (first scanner — **decomposed: M8a pure ranking ✅ → M8b DuckDB reader ✅ → M8c CLI ✅**), then `haul.py` (**decomposed: M9a pure core ✅ → M9b cross-region reader → M9c CLI `haul`**).

**M10 — Streamlit local dashboard** (`src/evemarket/ui/app.py`) — **FIRST & only browser-visual milestone.** Queued AFTER M9c so it shows BOTH scanners (station-trade + haul) in one view. New dep `streamlit` via optional `[ui]` extra (signed off §4, 2026-06-29, user-approved). Pure presentation: reuse `load_config` + readers + scanners. Run: `streamlit run src/evemarket/ui/app.py`. **Note:** the dashboard only shows real numbers after a live ESI ingest has populated `data/` (else it renders the same "no snapshot" empty state the CLI does). May be decomposed when scoped.

**Phase 3 — forecasting & long-hold (position) trading** *(committed 2026-06-28; honest-backtest-first; starts only after Phase 2 scanners land — no jumping ahead).*
Goal: predict forward price/return over a **multi-week horizon** (target ~2–6 wks, configurable — covers "buy and hold a month+") and surface backtested long-hold suggestions via the existing `ProfitOpportunity` seam (a hold = a `Disposal` at a *predicted future* price). Trained **locally** on EVE history (GBM / time-series per §3), NOT LLM.
- **P3-0 Backtest harness FIRST (the gate):** walk-forward, strict out-of-sample, point-in-time (no lookahead/survivorship), realistic fills + reuse M6 fees. Baselines = naive persistence, seasonal-naive, buy-&-hold item, hold-ISK. Metrics: directional hit rate, **risk-adjusted expectancy (ISK/trade net fees)**, profit factor, max drawdown, return vs each baseline, sample size/significance. Nothing downstream is trusted until this exists. **Decomposed (2026-06-29): P3-0a pure metrics `analytics/backtest.py` (active) → P3-0b PIT series + baselines + walk-forward engine → P3-0c `market_history` reader + `backtest` CLI. NO new deps in P3-0 (existing stack + M6 fees); ML-dep sign-off is a separate P3-2 gate.**
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

## 6. Current Task (Codex) — ▶ P3-0a ACTIVE

**STATUS: M10 COMPLETE (`96d74da`). Phase 3 has begun. P3-0 (backtest harness — the GATE, §5) is decomposed: P3-0a pure metrics primitives → P3-0b PIT series + baselines + walk-forward engine → P3-0c history reader + `backtest` CLI. EXECUTE the P3-0a pack directly below. The `<details>` packs (M10b/M9c/M9b/M8c) are FINISHED references — do NOT execute them. NOTE: P3-0 uses NO new deps (existing stack + M6 fees); ML-dep sign-off is a SEPARATE gate at P3-2 — do NOT add any ML/stats library here.**

### P3-0a — pure backtest metrics primitives (`analytics/backtest.py`)

The measurement/scoring layer for all of Phase 3 — the literal definition of the §5 success bar ("risk-adjusted expectancy net of fees", hit rate, profit factor, drawdown, sample size/significance). This is the GATE's ruler: everything downstream (baselines, forecasts) reports into these numbers. **Pure, self-contained, zero I/O / no forecasting / no walk-forward** (those are P3-0b). *We define the input shape* here (a chronological list of per-trade outcomes), so P3-0a has ZERO dependency on the store schema or M6 — same pattern as M8a/M9a "define the input row, stay pure." Stdlib only (`math`, `statistics`); **no new deps**.

**New-workflow note:** read the **To gather** files for the exact frozen-dataclass + `ValueError`-validation idiom to mirror; write only the files in scope. Anything that changes this design → STOP + §9.

### CONTEXT PACK

**Files in scope (write only these):**
- CREATE `src/evemarket/analytics/backtest.py` — the pure metrics module (dataclasses + metric functions + aggregator).
- CREATE `tests/test_backtest.py`.
- EDIT `HANDOFF.md` §8 (log).
- Do NOT touch any other file (no reader, no CLI, no config, no engine yet).

**To gather (read yourself — do not edit):**
- `src/evemarket/analytics/station_trade.py` — mirror the module idiom EXACTLY: module docstring, `from __future__ import annotations`, `collections.abc` typing imports (use `Sequence` here), `@dataclass(frozen=True)` with a one-line docstring, keyword-only args after `*`, and the `ValueError` validation style (e.g. how `scan_station_trades` raises on bad thresholds). `analytics/haul.py` for a second example of the same conventions if useful.

**Caller contracts:** none — this module is a leaf (stdlib only). It does NOT import `Config`, fees, readers, or anything from `evemarket`.

**Deliverable — `src/evemarket/analytics/backtest.py`:**
- `@dataclass(frozen=True) class TradeOutcome` — one realized backtest trade:
  - `net_isk: float` — the trade's profit/loss **already net of M6 fees** (the engine fee-adjusts upstream; P3-0a only aggregates).
  - `correct_direction: bool` — did the forecast's predicted direction match the realized move (for hit rate).
  - (Outcomes are passed to metrics as a **chronological** `Sequence[TradeOutcome]` — order matters for the drawdown equity curve.)
- `@dataclass(frozen=True) class BacktestMetrics` — the scorecard:
  - `sample_size: int`, `hit_rate: float`, `expectancy: float`, `profit_factor: float`, `max_drawdown: float`, `total_net_isk: float`, `expectancy_t_stat: float`.
- Pure metric functions over `Sequence[TradeOutcome]` (each raises `ValueError` on an EMPTY sequence — they are only called with ≥1 trade; the aggregator guards n=0):
  - `directional_hit_rate(outcomes) -> float` — fraction with `correct_direction` True (0.0–1.0).
  - `expectancy_per_trade(outcomes) -> float` — mean `net_isk` (THE binding metric per §5).
  - `profit_factor(outcomes) -> float` — `sum(net_isk>0) / abs(sum(net_isk<0))`; **all-wins (zero gross loss) → `float("inf")`**; all-losses → `0.0`.
  - `max_drawdown(outcomes) -> float` — worst peak-to-trough drop of the cumulative `net_isk` equity curve (running peak − running value), returned as a **non-negative** ISK magnitude; `0.0` if monotonically non-decreasing. (Equity starts at 0 before the first trade.)
  - `total_net_isk(outcomes) -> float` — `sum(net_isk)`.
  - `expectancy_t_stat(outcomes) -> float` — one-sample t-stat of `net_isk` vs 0: `mean / (stdev / sqrt(n))` using `statistics.stdev`; **n < 2 or zero variance → `0.0`** (undefined significance; honest neutral). Stdlib only — NO scipy.
- `compute_metrics(outcomes: Sequence[TradeOutcome]) -> BacktestMetrics` — the aggregator; the ONLY function that accepts an empty sequence:
  - **n == 0** (full abstention is first-class per §5): return `BacktestMetrics(sample_size=0, hit_rate=nan, expectancy=nan, profit_factor=nan, max_drawdown=0.0, total_net_isk=0.0, expectancy_t_stat=nan)` (use `float("nan")`; do NOT raise).
  - **n ≥ 1**: call the functions above and pack the scorecard.

**Conventions to mirror:** frozen dataclasses w/ docstrings; `from __future__ import annotations`; full type hints; `Sequence` from `collections.abc`; named module-level constants if any thresholds appear; pure (no I/O, no `evemarket` imports, no `Config`); stdlib `math`/`statistics` only; **no new deps**; terse.

**Boundary** — write only the 2 files (+ §8). NO reader, NO CLI, NO baselines, NO walk-forward, NO forecasting — those are P3-0b/P3-0c. Do NOT import `Config`/fees/readers. "Return vs baseline" comparison is a trivial expectancy subtraction the report does later — NOT in 0a. Anything that changes this design → STOP + §9.

**Verification (paste §8, terse per §2) — tests are PURE (hand-computed expected values, NO fixtures/network):**
- Use a hand-worked dataset, e.g. `net_isk = [+100, -40, +60, -20]`, `correct_direction = [T, F, T, F]`:
  - `total_net_isk == 100.0`; `expectancy_per_trade == 25.0`; `directional_hit_rate == 0.5`.
  - `profit_factor == 160/60` (≈ `2.6667`, assert with tolerance).
  - `max_drawdown == 40.0` — equity curve `0→100→60→120→100`, running peak `100/100/120/120`, drawdowns `0/40/0/20` → max `40.0`. (Add a monotonic-up case → `0.0`.)
  - `expectancy_t_stat`: assert finite and `> 0` for this net-positive set (don't hard-pin the float).
- Edge cases: `profit_factor` all-positive → `float("inf")`; all-negative → `0.0`. `expectancy_t_stat` with n==1 → `0.0`; with all-equal net_isk (zero variance) → `0.0`.
- `compute_metrics([])` → `sample_size == 0`, `max_drawdown == 0.0`, `total_net_isk == 0.0`, and `math.isnan(hit_rate)`/`isnan(expectancy)`/`isnan(profit_factor)`/`isnan(expectancy_t_stat)`.
- Each individual metric function on `[]` → `pytest.raises(ValueError)`.
- `python -m pytest -q` (bundled-Python abs path `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`; AppData temp denied → `--basetemp` at a FRESH dir, e.g. `.pytest-tmp-p30a`). Prior **97 passed, 1 skipped** stays green + new pass.
- `python -m ruff check .` → clean. `python -m mypy src/` → clean (now **27** source files: `analytics/backtest.py` added).
- Pre-commit `git status --short`: only `src/evemarket/analytics/backtest.py`, `tests/test_backtest.py`, `HANDOFF.md` (untracked `HANDOFF_ARCHIVE.md` + `.pytest-tmp*/` are unrelated — do NOT stage them); no `data/`/`*.duckdb`/parquet. Commit `feat: pure backtest metrics primitives (P3-0a)`; `git push origin main` (no force). Include `HANDOFF.md`.

When done: append §8 entry (terse, **INCLUDE the commit hash + the module idiom you mirrored from `station_trade.py`**) and STOP. After P3-0a → **P3-0b** (PIT history series shape + baseline forecasters [naive persistence, seasonal-naive, buy-&-hold item, hold-ISK] + walk-forward engine that produces `TradeOutcome`s using realistic fills + M6 fees, scored via `compute_metrics`).

<details><summary>Completed — M10b: haul panel in the Streamlit dashboard (reference)</summary>

### M10b — haul panel in the Streamlit dashboard (completes M10)

Second/final M10 slice. ADD a **Hauling** section to the existing `ui/app.py` (below the Station Trading section) — the GUI twin of `haul_command`, the cross-region complement of M10a's station panel. After M10b the single dashboard shows BOTH scanners. **Pure presentation only** (same discipline as M10a / the CLI commands): load config, read haul quotes, scan, render — ZERO analytics/I-O logic of its own. Reuse `read_haul_quotes` + `scan_haul_opportunities`; do NOT reimplement or wrap their math.

**New-workflow note:** read the **To gather** files for exact signatures + the `haul_command` flow to mirror and the existing M10a `app.py`/test patterns to extend; write only the files in scope. The existing 3 station tests MUST stay green. Anything that changes this design → STOP + §9.

### CONTEXT PACK

**Files in scope (write only these):**
- EDIT `src/evemarket/ui/app.py` — ADD the haul section + its sidebar inputs + ONE helper (mirror M10a's `_result_rows`, or widen it to accept any dataclass list). ADD imports `from evemarket.analytics.haul import HaulResult, scan_haul_opportunities` and add `read_haul_quotes` to the existing `from evemarket.store.readers import read_station_quotes` line. **Do NOT alter the existing station-trade section, its sidebar widgets, or `_result_rows`'s station behavior.**
- EDIT `tests/test_ui_app.py` — ADD haul tests; **reuse the existing fixture helpers** (`_write_config`/`_write_snapshot`/`_write_market_db`/`_write_sde_db`/`_order`/`_app_path`). Extend them for a SECOND (destination) region the same way `test_cli_haul.py` does. The existing 3 station tests stay unchanged + green.
- EDIT `HANDOFF.md` §8 (log).
- Do NOT touch `cli.py`, `store/readers.py`, `analytics/*`, `config.py`, `pyproject.toml`, or anything else.

**To gather (read yourself — do not edit):**
- `src/evemarket/ui/app.py` — the M10a script you're extending: reuse `loaded_config`, the resolved `selected_region`/`selected_station` (= the haul SOURCE hub), `selected_limit`, `selected_volume_window_days`, and the shared `min_roi`/`min_daily_volume` sidebar values. Mirror the station section's `st.header`→read→scan→`st.caption`→empty-states→`st.dataframe` shape.
- `src/evemarket/cli.py` — `haul_command` (lines ~448-553): the source-resolution, the `read_haul_quotes(...,volume_window_days=)` → `scan_haul_opportunities(...,min_roi/min_total_profit/min_daily_volume/max_days_to_sell/limit)` call, and the two empty-state strings ("No market snapshot found for the source/destination regions. Run ingest-orders for both first." / "No haul opportunities met the filters."). NOTE the dest-required semantics — translated to a GUI prompt below, NOT a raised error.
- `tests/test_cli_haul.py` — how it builds a TWO-region hermetic fixture (source region `10000002` + a DEST region e.g. `10000043`; dest `market_history`; tmp `sde.duckdb` with `volume`). Reuse that shape to extend `test_ui_app.py`.

**Caller contracts (paste — trust these):**
- `read_haul_quotes(config: Config, source_region_id: int, source_station_id: int, dest_region_id: int, dest_station_id: int, *, volume_window_days: int = 30) -> list[HaulQuote]` — sync; `[]` when EITHER region's snapshot is missing; `ValueError` if `volume_window_days < 1`.
- `scan_haul_opportunities(quotes, config, *, min_roi=0.0, min_total_profit=0.0, min_daily_volume=0.0, max_days_to_sell=None, limit=None) -> list[HaulResult]` — `ValueError` on negative thresholds / `max_days_to_sell<=0` / `limit<1`. **Pass `None` (NOT `0.0`) when there is no max-days filter — `max_days_to_sell=0.0` RAISES.**
- `HaulResult(type_id:int, type_name:str, source_price:float, dest_price:float, quantity:int, total_volume_m3:float, unit_profit:float, total_profit:float, roi:float, profit_per_m3:float, daily_volume:float, days_to_sell:float)` — `roi` a fraction; `days_to_sell` may be `inf`.

**Deliverable — extend `src/evemarket/ui/app.py`:**
- **New sidebar inputs** (keyed; ADD after the existing ones — do NOT reorder/rename existing keys):
  - `dest_region = st.sidebar.number_input("Dest region ID", value=0, step=1, key="dest_region")` (cast `int`).
  - `dest_station = st.sidebar.number_input("Dest station ID", value=0, step=1, key="dest_station")` (cast `int`).
  - `min_total_profit = st.sidebar.number_input("Minimum total profit", value=0.0, key="min_total_profit")`.
  - `max_days_to_sell = st.sidebar.number_input("Max days to sell (0 = no limit)", value=0.0, key="max_days_to_sell")`.
- **Hauling panel:** `st.header("Hauling")`.
  - **Dest gate (GUI form of `haul_command`'s required-dest):** `if int(dest_region) <= 0 or int(dest_station) <= 0:` → `st.info("Enter a destination region and station to scan hauls.")` and SKIP the rest of the haul section (no read). This default-`0` gate is load-bearing: it keeps the haul panel from rendering a dataframe when dest is unset, so M10a's `len(at.dataframe) == 1` station test stays valid.
  - Else: `md = max_days_to_sell if max_days_to_sell > 0 else None`.
  - `haul_quotes = read_haul_quotes(loaded_config, selected_region, selected_station, int(dest_region), int(dest_station), volume_window_days=selected_volume_window_days)`.
  - `haul_results = scan_haul_opportunities(haul_quotes, loaded_config, min_roi=min_roi, min_total_profit=min_total_profit, min_daily_volume=min_daily_volume, max_days_to_sell=md, limit=selected_limit)`.
  - `st.caption(f"Source: {selected_region}/{selected_station}  Dest: {int(dest_region)}/{int(dest_station)}  Quotes: {len(haul_quotes)}")`.
  - `if not haul_quotes:` → `st.info("No market snapshot found for the source/destination regions. Run ingest-orders for both first.")`
  - `elif not haul_results:` → `st.info("No haul opportunities met the filters.")`
  - `else:` → `st.dataframe([asdict(r) for r in haul_results], use_container_width=True)` (reuse the M10a helper, widened to any dataclass list, or a parallel `_haul_rows`). Raw numerics (no formatting — optional polish only).
- NO `st.cache_data`, NO analytics, NO new deps.

**Conventions to mirror:** pure presentation (only the same read→scan wiring `haul_command` does); reuse readers/scanners as-is; haul SOURCE = the station panel's already-resolved region/station; shared `min_roi`/`min_daily_volume`/`limit`/`volume_window_days` widgets are reused (do not duplicate them); `from __future__ import annotations` already present.

**Boundary** — gather only the named files; write only the 3 in scope; do NOT modify the reader/scanner/CLI/config/pyproject or add a data-access layer; do NOT alter the station section. Design change → STOP + §9.

**Verification (paste §8, terse per §2) — tests HERMETIC (tmp two-region fixtures + `AppTest`, NO network/live data, NO real browser):**
- **Existing 3 station tests stay UNCHANGED and green** (they never set `dest_region`/`dest_station` → default `0` → haul panel shows the "Enter a destination…" prompt, renders no dataframe → the happy-path `len(at.dataframe) == 1` still holds). Confirm this.
- Extend `test_ui_app.py` with a two-region fixture (mirror `test_cli_haul.py`): SOURCE region `10000002`/station `60003760` with type 34 SELL@100 (ask); DEST region `10000043`/dest station with type 34 BUY@130 (bid) + dest `market_history` volume; tmp `sde.duckdb` giving type 34 a small `volume` so quantity ≥ 1. Set `session_state` `config_path` + `dest_region=10000043` + `dest_station=<ds>`, `at.run()`. Then:
  - **Haul happy path:** `not at.exception`; a haul dataframe rendered whose text contains `Tritanium`/`34` AND a haul-only column (e.g. `days_to_sell` or `total_profit`). (The station panel at the SOURCE sees 34 ask-only → not two-sided → it shows "No station-trade opportunities", so the haul table is the rendered dataframe — assert via the haul-only column to disambiguate.)
  - **Dest set but no dest snapshot** (only source recorded) → `read_haul_quotes` `[]` → assert an `st.info` contains `"No market snapshot found for the source/destination regions"`.
  - **Filter excludes all:** populated two-region fixture but `session_state` `min_total_profit=1e15` → assert an `st.info` contains `"No haul opportunities"`.
  - (Optional) dest left at `0` → assert an `st.info` contains `"Enter a destination"`.
- `python -m pytest -q` (bundled-Python abs path `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`; AppData temp denied → `--basetemp` at a FRESH dir, e.g. `.pytest-tmp-m10b`; reusing an existing `.pytest-tmp` triggers a Windows delete PermissionError). streamlit `[ui]` is already installed from M10a — the new tests must RUN, not skip. Prior **93 passed, 1 skipped** stays green + new haul tests pass.
- `python -m ruff check .` → clean. `python -m mypy src/` → clean (still **26** source files — only `app.py` edited, no new module).
- Pre-commit `git status --short`: only `src/evemarket/ui/app.py`, `tests/test_ui_app.py`, `HANDOFF.md` (untracked `HANDOFF_ARCHIVE.md` is an unrelated planner doc — do NOT stage it); no `data/`/`*.duckdb`/parquet/`.pytest-tmp*`. Commit `feat: haul panel in Streamlit dashboard (M10b)`; `git push origin main` (no force). Include `HANDOFF.md`.

When done: append §8 entry (terse, **INCLUDE the commit hash + what you gathered from `haul_command`/the M10a app**) and STOP. After M10b → **M10 COMPLETE** (both scanners in one dashboard). Optional non-blocking follow-ups for later (do NOT do now): `,.2f` column formatting via `st.column_config`, `st.cache_data`, a data-freshness indicator. Next milestone is Phase 3 (P3-0 backtest harness) — needs planner scoping + ML-dep sign-off, do NOT start.

</details>

---

<details><summary>Original M9c build pack (reference — code already written from this)</summary>

### M9c — CLI `haul` command

Final piece of the haul scanner. ADD a Typer `haul` command that wires the M9b reader → the M9a pure scanner → a formatted ISK table — the cross-region twin of M8c's `scan`. This completes the M9 vertical slice (live two-region data → ranked haul trades). **No analytics logic here** — `haul` only loads config, resolves hubs, calls the two existing functions, and formats output. After M9c, both scanners are end-to-end and M10 (Streamlit dashboard) can show both.

**New-workflow note:** read the **To gather** files for exact signatures + the existing `scan` command style to mirror; write only the files in scope. Anything that changes this design → STOP + §9.

### CONTEXT PACK

**Files in scope (write only these):**
- EDIT `src/evemarket/cli.py` — ADD one `@app.command("haul")` function + ONE new private formatter `_format_haul_table(results) -> str` (mirror `_format_scan_table`). ADD imports `from evemarket.analytics.haul import HaulResult, scan_haul_opportunities` and `read_haul_quotes` to the existing `from evemarket.store.readers import ...` line. Do NOT alter `scan_command`, `_format_scan_table`, or any other existing command.
- CREATE `tests/test_cli_haul.py`.
- EDIT `HANDOFF.md` §8 (log).
- Do NOT touch `store/readers.py`, `analytics/haul.py`, `analytics/station_trade.py`, `config.py`, or anything else.

**To gather (read yourself — do not edit):**
- `src/evemarket/cli.py` — mirror `scan_command` + `_format_scan_table` EXACTLY: the `--config`/`-c` `typer.Option` block, `load_config(config)`, the `region or loaded_config.tracked_regions[0]` / `station if station is not None else loaded_config.home_hub_station_id` resolution, `typer.echo`, and the plain f-string column-width table builder (no `rich`, no table dep). Also mirror `_parse_backfill_dates`' use of `typer.BadParameter` for required-together params.
- `src/evemarket/store/readers.py` — `read_haul_quotes` (signature pasted below; confirm).
- `src/evemarket/analytics/haul.py` — `scan_haul_opportunities` + `HaulResult` fields (pasted below; confirm).
- `tests/test_cli_scan.py` — reuse its hermetic fixture approach verbatim (tmp `CliRunner` + `write_orders_snapshot`/`record_ingest_run`/`market_history` rows + tmp `sde.duckdb` with `volume` col + a `config.toml` pointing `data_dir` at `tmp_path`).

**Caller contracts (paste — trust these):**
- `read_haul_quotes(config: Config, source_region_id: int, source_station_id: int, dest_region_id: int, dest_station_id: int, *, volume_window_days: int = 30) -> list[HaulQuote]` — sync; `[]` when EITHER region's snapshot is missing; raises `ValueError` if `volume_window_days < 1`.
- `scan_haul_opportunities(quotes, config, *, min_roi=0.0, min_total_profit=0.0, min_daily_volume=0.0, max_days_to_sell=None, limit=None) -> list[HaulResult]` — raises `ValueError` on negative thresholds / `max_days_to_sell<=0` / `limit<1`.
- `HaulResult(type_id:int, type_name:str, source_price:float, dest_price:float, quantity:int, total_volume_m3:float, unit_profit:float, total_profit:float, roi:float, profit_per_m3:float, daily_volume:float, days_to_sell:float)` — `roi` is a fraction; `days_to_sell` may be `float("inf")` (zero daily volume).
- `Config` has `tracked_regions: list[int]` (default `[10000002]`) and `home_hub_station_id: int` (default `60003760`). **No dest-hub field exists** — dest must be supplied on the CLI.

**Deliverable — `@app.command("haul")` `def haul_command(...)`:**
- Options (mirror `scan_command` style; `--config`/`-c` Path default `config.toml`):
  - `--source-region` `int | None` default `None` → resolve to `source_region or loaded_config.tracked_regions[0]`.
  - `--source-station` `int | None` default `None` → resolve to `source_station if source_station is not None else loaded_config.home_hub_station_id`.
  - `--dest-region` `int | None` default `None` — **required** (see body).
  - `--dest-station` `int | None` default `None` — **required** (see body).
  - `--min-roi` `float` default `0.0`, `--min-total-profit` `float` default `0.0`, `--min-daily-volume` `float` default `0.0`.
  - `--max-days-to-sell` `float | None` default `None` (no filter when unset; pass straight through — the scanner validates `>0`).
  - `--limit` `int` default `20`, `typer.Option(..., min=1)`.
  - `--volume-window-days` `int` default `30`, `typer.Option(..., min=1)`.
- Body:
  - `load_config(config)`; resolve source region+station as above.
  - **Required dest:** `if dest_region is None or dest_station is None: raise typer.BadParameter("--dest-region and --dest-station are required.")` (mirror `_parse_backfill_dates`' paired-required pattern). Do this BEFORE any reads.
  - `quotes = read_haul_quotes(loaded_config, src_region, src_station, dest_region, dest_station, volume_window_days=...)`.
  - `results = scan_haul_opportunities(quotes, loaded_config, min_roi=..., min_total_profit=..., min_daily_volume=..., max_days_to_sell=..., limit=...)`.
- Output:
  - Echo header: `Source: <sr>/<ss>  Dest: <dr>/<ds>  Quotes: <len(quotes)>`.
  - `quotes == []` → echo `No market snapshot found for the source/destination regions. Run ingest-orders for both first.` and return (exit 0).
  - `results == []` → echo `No haul opportunities met the filters.` and return (exit 0).
  - Else `typer.echo(_format_haul_table(results))`.
- `_format_haul_table(results: list[HaulResult]) -> str`: same builder shape as `_format_scan_table` — header row + one row per result; right-align numerics with `f"{v:,.2f}"`, `type_name` left-aligned, `type_id`/`quantity` as `str(...)`, roi as `f"{result.roi*100:,.2f}"`. Columns (in order): `type_id`, `type_name`, `source`, `dest`, `qty`, `total_m3`, `unit_profit`, `total_profit`, `roi%`, `profit/m3`, `daily_vol`, `days_to_sell`. (`days_to_sell` `inf` formats as `inf` via `f"{float('inf'):,.2f}"` — fine.)

**Conventions:** NO analytics/I/O logic in the command beyond the two calls + formatting; full type hints; reuse the file's existing `from __future__ import annotations`; terse; **no new deps** (`typer`, stdlib only — `typer.testing.CliRunner` ships with typer).

**Boundary** — gather only the To-gather files; write only the 3 in-scope; do NOT modify the reader/scanner or add new analytics. Design change needed → STOP + §9.

**Verification (paste §8, terse per §2) — tests are HERMETIC (tmp fixtures + `CliRunner`, NO network/live data):**
- Reuse `test_cli_scan.py`'s fixture approach. Build **two** order snapshots under a `tmp_path` data_dir: a SOURCE region (e.g. `10000002`, source station) + a DEST region (e.g. `10000043`, dest station); record each via `record_ingest_run` (`source='esi_orders'`, `status='success'`, `snapshot_path` set). Add `market_history` rows for the DEST region. Build a tmp `sde.duckdb` `sde_types` with `(type_id, type_name, volume)` (give type 34 a small `volume` so quantity ≥ 1 under default `cargo_m3`/`capital_isk`). Write a `config.toml` in `tmp_path` setting `data_dir` to that dir. Invoke `CliRunner().invoke(app, ["haul", "--config", <cfg>, "--source-region", "10000002", "--source-station", "<ss>", "--dest-region", "10000043", "--dest-station", "<ds>"])`. Then:
  - **Happy path:** source has type 34 SELL@100 (ask); dest has type 34 BUY@130 (bid) + history volume → `exit_code == 0`; output contains `Tritanium` and `34` and a positive `total_profit`.
  - **Missing dest required:** invoke without `--dest-region`/`--dest-station` → non-zero exit (`typer.BadParameter`); output mentions `--dest-region`.
  - **No snapshot:** point at an empty market db (no ingest_runs) → `exit_code == 0` and output contains `No market snapshot`.
  - **Filter excludes all:** pass `--min-total-profit 1e15` → `exit_code == 0` and output contains `No haul opportunities`.
  - (Optional) `--limit 1` returns at most one data row.
- `python -m pytest -q` (bundled-Python abs path `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`; if AppData temp denied → `--basetemp .pytest-tmp` at a fresh dir) — prior **85 passed, 1 skipped** stays green + new pass.
- `python -m ruff check .` → clean. `python -m mypy src/` → **clean** (still **24** source files — only `cli.py` edited, no new module).
- Pre-commit `git status --short`: only `src/evemarket/cli.py`, `tests/test_cli_haul.py`, `HANDOFF.md` (untracked `HANDOFF_ARCHIVE.md` is an unrelated planner doc — do NOT stage it); no `data/`/`*.duckdb`/parquet. Commit `feat: CLI haul command -> cross-region table (M9c)`; `git push origin main` (no force). Include `HANDOFF.md`.

When done: append §8 entry (terse, **INCLUDE the commit hash + what you gathered from the existing `scan` style**) and STOP. After M9c → **M10** Streamlit dashboard (`[ui]` extra + `ui/app.py`; shows BOTH scanners — to be scoped/decomposed by the planner).

</details>

---

<details><summary>Completed — M9b: cross-region DuckDB haul reader (reference)</summary>

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

</details>

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
- **Phase 3 STARTED; P3-0 decomposed; P3-0a drafted (Context Pack).** M10 complete → next milestone is P3-0, the backtest harness GATE (§5: nothing downstream is trusted until it exists). Split **P3-0a pure metrics → P3-0b PIT series + baselines + walk-forward engine → P3-0c history reader + `backtest` CLI** (mirrors M8/M9: pure core → engine → reader/CLI). **Key boundary call:** P3-0 needs NO new deps (existing polars/duckdb/stdlib + M6 fees) — the ML-dep sign-off (§5/§7 "no new deps") is a SEPARATE gate at **P3-2** (the forecast model), so P3-0a proceeds without blocking on it; Codex is explicitly told NOT to add any ML/stats lib (t-stat via stdlib `statistics`, not scipy). P3-0a = `analytics/backtest.py` (planner-signed-off addition to §4 analytics layout, mirrors station_trade.py/haul.py — pure leaf module). Design: *we define the input shape* (`TradeOutcome{net_isk (already fee-net), correct_direction}`, chronological `Sequence` — order matters for drawdown) so 0a is fully self-contained/pure with ZERO store/M6/Config dependency (M8a/M9a pattern). Metrics encode the §5 success bar: `expectancy_per_trade` (THE binding metric — ISK/trade net fees), `directional_hit_rate` (the >50% sanity floor, NOT the goal), `profit_factor`, `max_drawdown` (equity-curve peak-to-trough), `total_net_isk`, `expectancy_t_stat` (honest significance via stdlib, n<2/zero-var → 0.0), packed by `compute_metrics` which alone accepts n=0 → all-nan/`sample_size=0` (**abstention is first-class** per §5 — full abstain is a valid, non-raising result, not an error). "Return vs baseline" deferred to the report layer (trivial expectancy subtraction once baselines land in P3-0b). Review focus on return: hand-computed metrics ([+100,-40,+60,-20] → expectancy 25 / hit 0.5 / PF 160/60 / maxDD 40 / total 100), profit_factor inf (all-wins) & 0.0 (all-losses) sentinels, t-stat n=1/zero-var → 0.0, `compute_metrics([])` nan-scorecard (no raise) vs individual funcs raising `ValueError` on empty, pure (no I/O / no `evemarket` imports), no new deps, only 2 files+HANDOFF, mypy(27 files)/ruff clean, commit hash §8.
- **M10b REVIEW: DONE — M10 COMPLETE, both scanners in one dashboard.** `ui/app.py` haul panel + `tests/test_ui_app.py` haul tests match the pack. Reviewer re-ran locally (fresh `--basetemp`) → **97 passed, 1 skipped** (prior 93 + 4 new haul), ruff clean, mypy clean (**26** files — only `app.py` edited, no new module). Verified: imports added (`HaulResult, scan_haul_opportunities` from analytics.haul; `read_haul_quotes` added to the readers import); `_result_rows` widened to `list[StationTradeResult] | list[HaulResult]` (asdict works for both — no duplicated logic); 4 new keyed sidebar inputs (`dest_region`/`dest_station` default `0`, `min_total_profit`, `max_days_to_sell`); **dest gate** `int(dest_region)<=0 or int(dest_station)<=0` → "Enter a destination…" + skip read (the load-bearing default that keeps the haul panel from rendering a dataframe when dest unset → M10a's `len(at.dataframe)==1` station test stays green); **`max_days_to_sell` trap handled** (`md = max_days_to_sell if >0 else None` — never passes `0.0` which would raise); `read_haul_quotes(source=resolved station-panel region/station, dest, volume_window_days=)` → `scan_haul_opportunities(min_roi/min_total_profit/min_daily_volume/max_days_to_sell/limit)` → caption `Source: r/s  Dest: r/s  Quotes: n`; both haul empty-state strings verbatim from `haul_command`; `st.dataframe(_result_rows(haul_results))`. **Station section untouched.** Pure presentation, no analytics/I-O, no new deps, source hub reuses the station widgets, shared filters not duplicated. Tests hermetic (two-region tmp fixtures, dest history): dest-prompt, happy-path (source 34 ask-only + dest 34 bid-only → only the haul table renders, disambiguated by the `days_to_sell` column, `len==1`), missing-dest-snapshot, filter-excludes-all; existing 3 station tests unchanged + green. Git `96d74da` + docs `504ef8b`; scoped files only, no `data/`. **Minor (non-blocking), both fine:** (a) happy-path asserts the `days_to_sell` haul-only column (st.dataframe's str repr truncates middle cols) — sufficient to disambiguate from a station table; (b) Codex cleaned up its fresh `.pytest-tmp-m10b*` dirs; the pre-existing untracked `.pytest-tmp2/` (a prior reviewer-run scratch dir, perm-denied to delete) remains unstaged — harmless, not in any commit. **M10 Streamlit dashboard COMPLETE end-to-end (station-trade + haul in one browser view).**
- **M10a REVIEW: DONE — first browser surface is live.** `pyproject.toml` `[ui]` extra + `ui/__init__.py` + `ui/app.py` + `tests/test_ui_app.py` match the pack. Reviewer re-ran locally (fresh `--basetemp` to dodge the Windows `.pytest-tmp` reuse PermissionError) → **93 passed, 1 skipped** (prior 90 + 3 new UI), ruff clean, mypy clean (**26** files); the 3 AppTest tests genuinely RAN (streamlit 1.58.0 installed via `[ui]`, not skipped). Verified: `[ui]=["streamlit"]` optional, streamlit absent from core deps; `app.py` is pure `scan_command` read→scan wiring (`load_config`→`read_station_quotes`→`scan_station_trades`→`st.dataframe(list[dict])`), both empty-state strings mirrored verbatim, ZERO analytics/I-O of its own; no haul code (correctly held for M10b); keyed sidebar widgets so config path resolves region/station defaults AND AppTest can inject. Tests hermetic (tmp config/snapshot/market.duckdb/sde.duckdb): empty-state ("No market snapshot"), happy-path (34/Tritanium rendered, sell-only 35 skipped → exactly 1 dataframe), filter-excludes-all (min_roi=999 → "No station-trade opportunities"). Git `788d295` + docs `0a531e4`; exactly the 5 scoped files, no `data/`. **Deviations, both accepted:** (a) AppTest 1.58 can't set keyed widget values before the first run → tests pre-seed `session_state` (valid/cleaner idiom); (b) Codex corrected my pack's arithmetic — src is **26** files not 25 (both `ui/__init__.py` + `ui/app.py` new from a base of 24), and streamlit ships `py.typed` so NO `streamlit.*` mypy override was needed (pyproject got only the `[ui]` extra). Good catches, honestly logged. Dashboard station-trade panel to-standard → unblocks M10b. **Note for M10b:** the station happy-path test asserts `len(at.dataframe) == 1` — M10b's haul panel MUST default to no-dest (so it renders an info prompt, not a dataframe) or that assertion breaks; the existing 3 tests must stay green.
- **M10 decomposed; M10a drafted (Context Pack) — first browser-visual milestone.** M10 (Streamlit dashboard) split **M10a packaging+skeleton+station-trade panel+AppTest harness → M10b haul panel** (one-step-at-a-time; the new `streamlit` dep + an unfamiliar `streamlit.testing.v1.AppTest` test harness is the risk M10a de-risks before doubling the panels). M10a scope: `pyproject.toml` `[ui]` extra (`streamlit`, optional — NOT core, honors "no new deps" via the §4/§5 sign-off) + `ui/__init__.py` + `ui/app.py` (the GUI twin of `scan_command`: sidebar config/region/station/filters → `read_station_quotes`→`scan_station_trades`→`st.dataframe`, with both empty-state messages mirrored) + `tests/test_ui_app.py`. **Pure presentation, zero analytics/I-O** (same discipline as the CLI commands — reuses readers/scanners as-is, no data-access layer, no wrapped math). Key design calls: (a) app reads config path from a keyed sidebar `text_input` so region/station defaults resolve from the loaded `Config` AND so AppTest can point it at a tmp config (hermetic, never touches repo `./data`); (b) fixture uses region `10000002`/station `60003760` = the `Config` defaults, so AppTest auto-resolves to fixture data without overriding widgets; (c) tests guarded by `pytest.importorskip("streamlit")` so the suite stays green when `[ui]` isn't installed — but Codex is told to INSTALL `[ui]` and RUN them (an unrun harness ≠ verified; skip-only → §9); (d) render via `st.dataframe(list[dict])` — no pandas (not a dep), polars acceptable; raw numerics (`,.2f` formatting deferred to M10b polish); (e) mypy `streamlit.*` → `ignore_missing_imports` if stubs missing (pyproject in scope; src now 25 files). Review focus on return: `[ui]` extra correct + streamlit absent from core deps; app is pure read→scan wiring (no analytics); both empty states + happy-path dataframe (34 shown, 35 sell-only skipped) + filter-empty via AppTest; tests actually RAN (not skipped); only the 5 scoped files touched, no `data/`; mypy(25)/ruff clean; commit hash §8. After M10a → M10b haul panel → M10 complete.
- **M9c REVIEW: DONE & FINALIZED (`c8bae2d`, docs `0d8f328`) — M9 + Phase-2 scanners COMPLETE end-to-end.** Codex finalized cleanly: §8 logged with hash; commit touched exactly the 3 scoped files (`cli.py` +171, `tests/test_cli_haul.py` +301, `HANDOFF.md`), no `data/`/duckdb/parquet; untracked `HANDOFF_ARCHIVE.md` correctly left unstaged; tree now clean. §8 reconciles the minor test note I'd flagged: an earlier fixture seeded type 36 with NO SDE volume (relying on the reader `#tid` name-fallback) but the reader/scanner skips zero-volume items so the `--limit 1` row never rendered → Codex fixed it by giving type 36 explicit volume metadata (the passing version reviewed). Final state matches the earlier code review below.
- **M9c REVIEW (code, pre-commit): DONE.** Codex wrote `cli.py` `haul` command + `_format_haul_table` + `tests/test_cli_haul.py` in the working tree but initially **stopped before commit/push/§8 log** (now finalized — see above). Reviewer (Claude) re-ran locally: **90 passed, 1 skipped** (prior 85 + 5 new haul tests), `ruff` clean, `mypy` clean (24 files). Verified against the pack: imports added (`HaulResult, scan_haul_opportunities` from analytics.haul; `read_haul_quotes` added to the readers import); options mirror `scan_command`; source resolved `source_region or tracked_regions[0]` / `source_station ?? home_hub_station_id`; **dest required via `typer.BadParameter` BEFORE any reads** (non-interactive, correct); `read_haul_quotes(...,volume_window_days=)` → `scan_haul_opportunities(...,min_roi/min_total_profit/min_daily_volume/max_days_to_sell/limit)` → `_format_haul_table`; header `Source: r/s  Dest: r/s  Quotes: n`; empty-quotes → "No market snapshot…" and empty-results → "No haul opportunities…" both exit 0; `_format_haul_table` has the 12 spec cols in order, numerics right-aligned `,.2f`, `days_to_sell` `inf` renders fine. No analytics/I/O logic in the command; no new deps; existing `scan_command`/`_format_scan_table` untouched. Tests hermetic (two-region tmp snapshots + dest history + tmp `sde.duckdb` w/ `volume`): happy-path (34 paired, 35 source-only + 36 dest-only excluded → Quotes:1), required-dest, no-snapshot, filter-excludes-all, `--limit 1` (36 outranks 34 on profit). **Code is to-standard → M9 station+haul scanners complete end-to-end once committed.** Remaining = mechanical finalize (Codex: stage 3 files → §8 log → commit → push) per §6. **Minor (non-blocking):** the `--limit 1` test seeds SDE `type_name="#36"` literally rather than omitting type 36 to exercise the real reader `#{tid}` fallback — harmless (fallback already covered in `test_readers.py`); the CLI test only needs a 2nd item for ranking/limit. NOT a REDO.
- **M9c drafted (Context Pack) — final M9 slice.** CLI `haul` command = cross-region twin of M8c `scan`: pure wiring `read_haul_quotes` (M9b) → `scan_haul_opportunities` (M9a) → f-string table, mirroring `scan_command`/`_format_scan_table`. Key design call: `Config` has NO dest-hub field (source defaults to `tracked_regions[0]`/`home_hub_station_id`; dest has no sensible default), so `--dest-region`/`--dest-station` are **required** — enforced via `typer.BadParameter` BEFORE any reads (mirrors `_parse_backfill_dates`' paired-required pattern), not via prompts (non-interactive). New formatter `_format_haul_table` adds haul-specific cols (`qty`, `total_m3`, `total_profit`, `profit/m3`, `days_to_sell`); `days_to_sell=inf` formats cleanly as `inf`. Scoped to `cli.py` + new `tests/test_cli_haul.py` + HANDOFF; no analytics logic, no new deps, no module added (still 24 src files). Review focus on return: required-dest BadParameter, source-default resolution, both empty-state messages exit 0, happy-path table w/ positive profit, filter-empty path, `--limit` cut; hermetic tmp two-region fixtures (no network); mypy(24)/ruff clean; commit hash §8. After M9c → M10 Streamlit (shows both scanners).
- **M9b REVIEW: DONE.** `store/readers.py` (`read_haul_quotes` + new `_read_type_metadata`) + `tests/test_readers.py` match the pack. Reviewer re-ran locally → **85 passed, 1 skipped**, ruff clean, mypy clean (24 files). Verified: single `ensure_market_db` connection; both region snapshots via `_latest_snapshot_path`, either None → `[]`; source asks = `_read_best_quotes(...) best_ask>0`, dest bids = `... best_bid>0` (reuses M8b helper — no new order-book SQL); **executable pairs = `source_asks.keys() & dest_bids.keys()` sorted by type_id**, empty → `[]`; daily_volume from **dest** region (`_read_daily_volumes(dest_region_id)`); new `_read_type_metadata` mirrors `_read_type_names` ATTACH/DETACH `(READ_ONLY)` + escaped-literal pattern, returns `(name, volume)`; SDE-absent/row-missing → `(f"#{tid}", 0.0)` fallback (0-vol quote returned as-is; M9a scanner then skips it). `read_station_quotes` + existing helpers untouched. Tests hermetic (two-region snapshots, dest history, tmp `sde.duckdb` w/ `volume` col): executable-pair join (34 paired; 35 source-only + 36 dest-only excluded), both no-snapshot paths → `[]`, SDE fallback (#37 / 0.0), haul-scanner feed-through, bad-window `ValueError`. Git `81148ea` + docs `02113ee`; scoped files only, no `data/`. Reader to-standard → unblocks M9c.
  - **Minor (non-blocking, later):** `_read_type_metadata` casts `float(volume)` — a NULL SDE `volume` would raise. Real `invTypes.volume` is always populated so not a live risk; if ever hit, `COALESCE(volume, 0.0)`. NOT a REDO.
- **M10 Streamlit dashboard committed to roadmap (user-approved, 2026-06-29).** User asked when a browser-checkable visual lands; tool was CLI-only by design. User chose a **Streamlit** local dashboard. Planner sign-off recorded in §4 (new UI layer) + §5 (M10). Key decisions: (a) `streamlit` is an **optional `[ui]` extra**, NOT a core dep — core CLI stays dep-light, honors the "no new deps" rule via explicit sign-off; (b) dashboard is **pure presentation** — reuses `load_config` + M8/M9 readers + scanners, no analytics of its own (same discipline as CLI commands); (c) **sequenced AFTER M9c** (don't interrupt active M9b; one-task-at-a-time) so it can show station-trade AND haul together — avoids building a station-only dashboard then reworking. M10 pack to be written once M9c lands; will likely decompose (pyproject `[ui]` extra + `ui/app.py` skeleton → wire scanners → polish). **Data caveat flagged to user:** dashboard only shows real numbers after a live ESI ingest populates `data/`; otherwise it renders the empty "no snapshot" state. **No interruption to M9 — M9b remains the active §6 task.**
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

_(Append new entries below — next: P3-0a.)_

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
- Commit: `81148ea`.

### M9c - CLI haul command - 2026-06-29 - COMPLETE
- Files: `src/evemarket/cli.py`, `tests/test_cli_haul.py`, `HANDOFF.md`.
- Gathered/read: `src/evemarket/cli.py` (`scan_command`, `_format_scan_table`, `_parse_backfill_dates` style); `src/evemarket/store/readers.py` (`read_haul_quotes` signature/behavior); `src/evemarket/analytics/haul.py` (`HaulResult`, `scan_haul_opportunities`); `tests/test_cli_scan.py` hermetic CLI fixture style.
- Commands+result:
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_cli_haul.py -q --basetemp .pytest-tmp` -> FAIL: limit fixture expected fallback `#36`, but haul reader skips missing SDE volume; fixture fixed with explicit type 36 volume metadata.
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_cli_haul.py -q --basetemp .pytest-tmp` -> `5 passed, 1 warning` (pytest cache WinError 5 only).
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q --basetemp .pytest-tmp` -> `90 passed, 1 skipped, 1 warning` (pytest cache WinError 5 only).
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check .` -> `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m mypy src/` -> `Success: no issues found in 24 source files`
  - `git status --short` -> scoped files + unrelated untracked `HANDOFF_ARCHIVE.md`; no `data/`/duckdb/parquet.
- Verification: PASS; source/default hub resolution, required dest params, no-snapshot message, filter-empty message, limit-one table, formatted ISK/ROI columns covered with hermetic tmp fixtures.
- Deviations: used bundled Python abs path; bare `python` known unavailable. No live run/network; CLI tests use tmp DuckDB/parquet/SDE fixtures only. Did not touch/stage unrelated `HANDOFF_ARCHIVE.md`.
- Questions: none.
- Commit: `c8bae2d`.

### M10a - Streamlit UI extra + station-trade panel - 2026-06-29 - COMPLETE
- Files: `pyproject.toml`, `src/evemarket/ui/__init__.py`, `src/evemarket/ui/app.py`, `tests/test_ui_app.py`, `HANDOFF.md`.
- Gathered/read: `src/evemarket/cli.py` (`scan_command` read->scan flow + empty-state strings); `tests/test_cli_scan.py` hermetic tmp DuckDB/parquet/SDE fixture style; `streamlit.testing.v1.AppTest` (`from_file`, `.run()`, keyed widget lookup after run; pre-run keyed lookup raises `KeyError`, so tests pre-seed `session_state` for hermetic first run).
- Commands+result:
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -c "import streamlit"` -> FAIL: `ModuleNotFoundError: No module named 'streamlit'`.
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pip install -e ".[ui]"` -> PASS; installed `streamlit-1.58.0`; tests RAN, not skipped.
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_ui_app.py -q --basetemp .pytest-tmp` -> `3 passed, 1 warning` (pytest cache WinError 5 only).
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check tests\test_ui_app.py src\evemarket\ui\app.py` -> `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q --basetemp .pytest-tmp` -> `93 passed, 1 skipped, 1 warning` (pytest cache WinError 5 only).
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check .` -> `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m mypy src/` -> `Success: no issues found in 26 source files`
  - `git status --short` -> scoped files + unrelated untracked `HANDOFF_ARCHIVE.md`; no new `data/`/duckdb/parquet/`.pytest-tmp` staged.
- Verification: PASS; optional `[ui]` extra, Streamlit package marker/script, empty snapshot state, happy-path dataframe, filter-empty state covered with hermetic AppTest tmp fixtures.
- Deviations: AppTest 1.58 cannot set keyed widget values before first run; used pre-seeded `session_state` for `config_path`/`min_roi` so first run is hermetic. Mypy reports 26 source files, not 25, because both `ui/__init__.py` and `ui/app.py` are new under `src/`. No `streamlit.*` mypy override needed.
- Questions: none.
- Commit: `788d295`.

### M10b - haul panel in Streamlit dashboard - 2026-06-29 - COMPLETE
- Files: `src/evemarket/ui/app.py`, `tests/test_ui_app.py`, `HANDOFF.md`.
- Gathered/read: `src/evemarket/ui/app.py` M10a station panel + shared sidebar state; `src/evemarket/cli.py` `haul_command` read->scan flow + empty-state strings; `tests/test_cli_haul.py` two-region tmp DuckDB/parquet/SDE fixture shape.
- Commands+result:
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_ui_app.py -q --basetemp .pytest-tmp-m10b` -> FAIL: dataframe string truncated middle columns, hid `total_profit`; assertion narrowed to required haul-only `days_to_sell`.
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_ui_app.py -q --basetemp .pytest-tmp-m10b2` -> `7 passed, 1 warning` (pytest cache WinError 5 only).
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check src\evemarket\ui\app.py tests\test_ui_app.py` -> `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q --basetemp .pytest-tmp-m10b-full` -> `97 passed, 1 skipped, 1 warning` (pytest cache WinError 5 only).
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check .` -> `warning: Encountered error: Access is denied. (os error 5)` + `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m mypy src/` -> `Success: no issues found in 26 source files`
  - `git status --short` -> scoped files + unrelated untracked `HANDOFF_ARCHIVE.md`; pre-existing `.pytest-tmp2/` permission warning; no new `data/`/duckdb/parquet.
- Verification: PASS; existing 3 station tests unchanged + green; dest prompt, haul happy-path dataframe, missing dest snapshot, filter-empty states covered with hermetic two-region AppTest fixtures.
- Deviations: `st.dataframe` string repr truncates middle columns; happy-path asserts `days_to_sell` haul-only column instead of both `days_to_sell` and hidden `total_profit`. Removed fresh `.pytest-tmp-m10b*` dirs after tests; pre-existing `.pytest-tmp2/` remains permission-denied and unstaged.
- Questions: none.
- Commit: `96d74da`.

### P3-0a - pure backtest metrics primitives - 2026-06-29 - COMPLETE
- Files: `src/evemarket/analytics/backtest.py`, `tests/test_backtest.py`, `HANDOFF.md`.
- Gathered/read: `src/evemarket/analytics/station_trade.py` frozen dataclass/module style + `ValueError` validation; `src/evemarket/analytics/haul.py` second dataclass/validation example.
- Commands+result:
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests\test_backtest.py -q --basetemp .pytest-tmp-p30a` -> `11 passed, 1 warning` (pytest cache WinError 5 only).
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check src\evemarket\analytics\backtest.py tests\test_backtest.py` -> `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest -q --basetemp .pytest-tmp-p30a-full` -> `108 passed, 1 skipped, 1 warning` (pytest cache WinError 5 only).
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m ruff check .` -> two access-denied warnings + `All checks passed!`
  - `C:\Users\M0obo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m mypy src/` -> `Success: no issues found in 27 source files`
  - `git status --short` -> scoped files + unrelated untracked `HANDOFF_ARCHIVE.md`; pre-existing `.pytest-tmp-rev/` and `.pytest-tmp2/` permission warnings; no new `data/`/duckdb/parquet.
- Verification: PASS; hand-worked metrics, drawdown, profit-factor edges, t-stat undefined cases, empty aggregate abstention, individual empty-input `ValueError` paths covered. Module is pure stdlib; no `evemarket` imports/no config/readers/fees.
- Deviations: fresh `.pytest-tmp-p30a*` dirs removed after tests; pre-existing `.pytest-tmp-rev/` and `.pytest-tmp2/` remain permission-denied and unstaged. `profit_factor` returns `inf` whenever gross loss is zero, including zero-only sequences; no separate zero-only behavior specified.
- Questions: none.
- Commit: pending.

## 9. Open Questions / Blockers

> Resolved items (M5b-block, PII, REPLACE_ME, Fuzzwork) archived in `HANDOFF_ARCHIVE.md` §D.

- **Deferred (non-blocking, M0):** switch `Config`/`SkillConfig` from `pydantic_settings.BaseSettings` to `pydantic.BaseModel` so TOML is sole config source (BaseSettings allows silent env-var overrides). Future small task.
