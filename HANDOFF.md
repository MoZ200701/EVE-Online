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
- **M5** Prices ✅ | scheduler (M5b) ✅ | data-quality (M5c) ✅ | M5-FIX mypy-clean ✅ — **Phase 1 COMPLETE & to-standard.** | M6 `analytics/fees.py` ✅ `2cee47b` | M7 `analytics/opportunity.py` seam ✅ `46261d0` | M8a `station_trade.py` ranking core ✅ `29f7a9c`. ← **CURRENT: Phase 2 / M8b — `store/readers.py` DuckDB→`MarketQuote` reader (§6).**

**Phase 2 — deterministic analytics (stubbed):** `fees.py` ✅, `opportunity.py` ✅, `station_trade.py` (first scanner — **decomposed: M8a pure ranking ✅ → M8b DuckDB reader → M8c CLI**), then `haul.py`.

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

## 6. Current Task (Codex) — M8b: `store/readers.py` — DuckDB → `MarketQuote` reader

M8a DONE (§7). Now the **I/O boundary** that feeds it: a DuckDB/Parquet reader that produces `MarketQuote` rows for one station from real ingested data. This is the **only impure layer** — `station_trade.py` stays pure (do NOT add I/O there). Next is M8c (CLI `scan` wiring reader→scanner). Schema is mostly pasted below (planner-gathered); only the SDE name table is yours to read.

**New-workflow note:** read the **To gather** files for the SDE name table + helper signatures; write only the files in scope. Anything that changes this design → STOP + §9.

### CONTEXT PACK

**Files in scope (write only these):**
- CREATE `src/evemarket/store/readers.py` (new module — planner-approved addition to §4 layout; mirror `writers.py` style).
- CREATE `tests/test_readers.py`.
- EDIT `HANDOFF.md` §8 (log).
- Do NOT touch `analytics/station_trade.py` (keep it pure), `writers.py`, `schema.py`, or anything else.

**To gather (read yourself — do not edit):**
- `src/evemarket/sde/load.py` — find the **SDE DuckDB table + columns mapping `type_id` → type name** (and confirm the sde db path/filename under `config.data_dir`, expected `sde.duckdb`). You'll join names off this; fall back to `f"#{type_id}"` when a name is missing or the sde db is absent.
- `src/evemarket/store/writers.py` — use `write_orders_snapshot(orders, region_id, snapshot_ts, snapshots_root)` to build snapshot **test fixtures**; confirm `ORDER_SCHEMA` columns.
- `src/evemarket/store/schema.py` — `ensure_market_db(path)` returns a connection (context-managed); table-name consts `INGEST_RUNS_TABLE='ingest_runs'`, `MARKET_HISTORY_TABLE='market_history'`.
- `src/evemarket/analytics/station_trade.py` — import `MarketQuote` (fields: `type_id:int, type_name:str, best_bid:float, best_ask:float, daily_volume:float`). The reader RETURNS these; it does not import the scanner.
- `src/evemarket/config.py` — confirm `Config.data_dir: Path` (root holding `market.duckdb`, `sde.duckdb`, `snapshots/`).

**Schema (planner-gathered — paste, trust these):**
- Order snapshot parquet at `data_dir/snapshots/orders/region=<id>/date=<YYYY-MM-DD>/<ts>.parquet`, cols: `order_id, type_id, is_buy_order(bool), price(double), volume_remain, volume_total, min_volume, location_id, system_id, range, duration, issued, region_id, snapshot_ts`.
- `ingest_runs(run_id, source, region_id, snapshot_ts, started_at, finished_at, status, order_count, pages, esi_expires, snapshot_path, error)` — orders snapshots are `source='esi_orders'`, success rows have `status='success'` and a non-null `snapshot_path`.
- `market_history(region_id, type_id, date, average, highest, lowest, order_count, volume)`, PK `(region_id,type_id,date)`.
- Key IDs: The Forge region `10000002`, Jita IV-4 station `location_id 60003760`.

**Deliverable — `def read_station_quotes(config: Config, region_id: int, station_id: int, *, volume_window_days: int = 30) -> list[MarketQuote]`:**
1. Paths from `config.data_dir.expanduser()`: `market.duckdb`, `sde.duckdb`. Open market db via `ensure_market_db` (context-managed; close it). Validate `volume_window_days >= 1` else `ValueError`.
2. **Latest snapshot:** `SELECT snapshot_path FROM ingest_runs WHERE source='esi_orders' AND status='success' AND region_id=? AND snapshot_path IS NOT NULL ORDER BY snapshot_ts DESC LIMIT 1`. None → return `[]`.
3. **Best bid/ask at station** from that parquet: `SELECT type_id, MAX(price) FILTER (WHERE is_buy_order) AS best_bid, MIN(price) FILTER (WHERE NOT is_buy_order) AS best_ask FROM read_parquet(?) WHERE location_id = ? GROUP BY type_id`. (One-sided types → NULL on a side.)
4. **Trailing daily volume:** ref date `SELECT MAX(date) FROM market_history WHERE region_id=?`; if non-null, `SELECT type_id, AVG(volume) AS daily_volume FROM market_history WHERE region_id=? AND date >= ? GROUP BY type_id` with window-start = ref − `(volume_window_days-1)` days. Missing → 0.0.
5. **Names:** if `sde.duckdb` exists, `ATTACH` it READ_ONLY and left-join `type_id`→name (table/cols from `sde/load.py`); else/ missing → `f"#{type_id}"`. DETACH/close.
6. **Assemble** one `MarketQuote` per type present in step-3, with `best_bid`/`best_ask`/`daily_volume` COALESCEd to `0.0` (NULL one-sided → 0.0 so the M8a scanner skips it). Return sorted by `type_id` (deterministic).

**Conventions:** ALL I/O lives here (station_trade.py stays pure); pass values as DuckDB **query params** (`?`), never string-interpolate values (identifiers/table names are trusted consts); close every connection (context managers / try-finally); full type hints; `from __future__ import annotations`; terse docstrings mirroring `writers.py`; **no new deps** (`duckdb`, `polars`, stdlib only).

**Boundary** — gather only the To-gather files; write only the 3 in-scope; do NOT build the CLI (M8c) or touch the pure scanner. Design change needed → STOP + §9.

**Verification (paste §8, terse per §2) — tests are HERMETIC (tmp fixtures, NO network/live data):**
- Build fixtures under a `tmp_path` data_dir: (a) write an order snapshot via `write_orders_snapshot` with type 34 buy@100 + sell@120 at station `60003760`, type 35 sell@200 only, and a type-34 order at a DIFFERENT `location_id` (to prove the station filter); (b) `ensure_market_db` + insert an `ingest_runs` success row pointing at that parquet + `market_history` volume rows for 34; (c) a tiny `sde.duckdb` with the name table mapping 34→"Tritanium" (35 absent → fallback). Then:
  - `read_station_quotes(config, 10000002, 60003760)` → `MarketQuote(34,"Tritanium",100,120, avg-volume)` and `MarketQuote(35,"#35",0.0,200.0,0.0)` (one-sided bid→0.0; no name→fallback; no history→0.0). The off-station order is excluded.
  - **Latest-snapshot:** insert two success `ingest_runs` (older + newer ts, different parquet) → the NEWER one's quotes are returned.
  - **No snapshot** for the region → `[]`.
  - **End-to-end:** feed the returned quotes into `scan_station_trades(..., Config())` → type 34 survives, type 35 skipped (no bid).
  - `volume_window_days=0` → `ValueError`.
  - `pytest.approx` for floats.
- `python -m pytest -q` (bundled-Python abs path; `--basetemp .pytest-tmp` if AppData temp denied) — prior **57 passed, 1 skipped stays green** + new pass.
- `python -m ruff check .` → clean. `python -m mypy src/` → **clean** (file count rises by 1 — readers.py is new).
- Pre-commit `git status --short`: only `src/evemarket/store/readers.py`, `tests/test_readers.py`, `HANDOFF.md` (the untracked `HANDOFF_ARCHIVE.md` + modified `AGENTS.md` are unrelated planner docs — do NOT stage them); no `data/`/`*.duckdb`/parquet. Commit `feat: DuckDB station-quote reader -> store/readers.py (M8b)`; `git push origin main` (no force). Include `HANDOFF.md`.

When done: append §8 entry (terse, **INCLUDE the commit hash + what you gathered for the SDE name table**) and STOP. After M8b → **M8c** CLI `scan` command (wire `read_station_quotes` → `scan_station_trades` → formatted table output).

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

**Standing decisions / known non-blockers (carry forward):**
- **"No new deps" is hard:** if Codex needs one → STOP + §9 for planner sign-off; never silently `pip install` to make tests pass (M3-FIX hidden-pytz trap).
- **DuckDB↔polars bulk insert avoids `pyarrow`** (not a dep): stage explicit-schema rows into a TEMP duckdb table via `executemany` + set-based `ON CONFLICT` upsert (`_upsert_history_frame`). If true bulk needed later, declare `pyarrow` w/ sign-off.
- **ESI error-budget** state is shared but **unlocked** across concurrent paginated pages — fine for single hub; revisit if parallelizing regions.
- **everef present-but-empty day file** → counted NEITHER fetched NOR missing (`days_fetched+days_missing` can be < range); self-healing on idempotent re-run.
- **Env (Codex/Windows):** bare `python` not on PATH → use bundled Python abs path; AppData temp perm denied → `--basetemp .pytest-tmp`; live runs need network escalation; `git status` warns global ignore inaccessible (benign).
- **Deferred (non-blocking, M0):** switch `Config`/`SkillConfig` `BaseSettings`→`BaseModel` so TOML is sole config source (BaseSettings allows silent env-var overrides). Small future task. (Also tracked §9.)

**Recent verdicts:**
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

_(Append new entries below — next: M8a.)_

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

## 9. Open Questions / Blockers

> Resolved items (M5b-block, PII, REPLACE_ME, Fuzzwork) archived in `HANDOFF_ARCHIVE.md` §D.

- **Deferred (non-blocking, M0):** switch `Config`/`SkillConfig` from `pydantic_settings.BaseSettings` to `pydantic.BaseModel` so TOML is sole config source (BaseSettings allows silent env-var overrides). Future small task.
