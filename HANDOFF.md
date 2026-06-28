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
  store/{__init__,schema,writers,quality}.py
  analytics/{__init__,fees,opportunity,station_trade,haul}.py
tests/
```

## 5. Phase plan (no jumping ahead)

**Phase 1 — data pipeline**
- M0 Scaffold ✅ | M1 SDE→`sde.duckdb` ✅ | REPO git+push ✅ | M2 ESI client ✅ | M3 Order snapshots + `ingest_runs` ✅ | M4a ESI daily history → `market_history` ✅ | M4b everef.net bulk backfill ✅ | M5a ESI prices → `market_prices` ✅
- **M5** Prices ✅ | scheduler (M5b) ✅ | data-quality (M5c) ✅ | M5-FIX mypy-clean ✅ — **Phase 1 COMPLETE & to-standard.** | M6 `analytics/fees.py` ✅ `2cee47b` | M7 `analytics/opportunity.py` seam ✅ `46261d0`. ← **CURRENT: Phase 2 / M8a — `analytics/station_trade.py` pure ranking core (§6).**

**Phase 2 — deterministic analytics (stubbed):** `fees.py` ✅, `opportunity.py` ✅, `station_trade.py` (first scanner — **decomposed: M8a pure ranking → M8b DuckDB reader → M8c CLI**), then `haul.py`.

Definition of done is per-step in each task prompt.

## 6. Current Task (Codex) — M8a: `analytics/station_trade.py` — pure ranking core

M7 DONE (§7). Begin the first scanner. **M8 is decomposed**: this task (M8a) is the **pure ranking core only** — given per-item market quotes + config, build `ProfitOpportunity` per item, compute per-unit economics, filter, and rank. **NO network, DB, file I/O, or CLI** (those are M8b DuckDB reader → M8c CLI, next). The scanner's *input row shape is defined here by us* — it does NOT depend on the DB schema, so M8a is fully self-contained. Reuse M7's `station_trade_opportunity`; do NOT re-derive fees or opportunity math.

**New-workflow note:** you MAY read the **To gather** files to pin live signatures. Write only the files in scope. Anything that changes this design → STOP + §9.

### CONTEXT PACK

**Files in scope (write only these):**
- EDIT `src/evemarket/analytics/station_trade.py` — currently a 3-line stub (`"""Station trading scanner stub."""` + `# TODO: M6`). Replace its body with the design below. (`analytics/__init__.py` is empty — do NOT touch it.)
- CREATE `tests/test_station_trade.py`.
- EDIT `HANDOFF.md` §8 (log).

**To gather (read these yourself for exact signatures — do not edit them):**
- `src/evemarket/analytics/opportunity.py` — confirm + import `station_trade_opportunity(config, buy_price, sell_price, quantity) -> ProfitOpportunity` and the `ProfitOpportunity` props you consume: `.cost`, `.profit`, `.roi` (all `float`). Build opportunities at **quantity=1** (fees are pure-%, so per-unit roi/profit are scale-invariant — see Deferred note). Do NOT reimplement fee/opportunity math.
- `src/evemarket/config.py` — confirm `Config` (passed straight through to `station_trade_opportunity`; you don't read its fields directly here).

**Why quantity=1 is correct (don't overthink):** M6 fees are percentage-only (the flat per-order ISK minimum is deferred-and-noted), so `roi` and per-unit `profit` are identical at any quantity. M8a evaluates per-unit economics; realistic order sizing / ISK-per-day projection (which needs a volume-capture assumption) is deferred to a later, explicitly-modeled step — do NOT bake a capture-rate guess in here (honest analytics per §3).

**Design (do EXACTLY this — `from __future__ import annotations`, full type hints, frozen dataclasses, terse docstrings mirroring `fees.py`/`opportunity.py`):**

1. **`@dataclass(frozen=True) class MarketQuote`** — one item's in-station two-sided market (input row; the DB reader will produce these in M8b).
   - Fields: `type_id: int`, `type_name: str`, `best_bid: float` (highest buy-order price in station — your effective station-trade BUY price), `best_ask: float` (lowest sell-order price — your effective SELL price), `daily_volume: float` (units/day traded, liquidity).

2. **`@dataclass(frozen=True) class StationTradeResult`** — one ranked suggestion (flat fields for easy CLI rendering in M8c).
   - Fields: `type_id: int`, `type_name: str`, `buy_price: float`, `sell_price: float`, `spread: float` (`sell_price − buy_price`), `unit_profit: float` (net per unit after all M6 fees), `roi: float`, `daily_volume: float`.

3. **`def scan_station_trades(quotes: Iterable[MarketQuote], config: Config, *, min_roi: float = 0.0, min_unit_profit: float = 0.0, min_daily_volume: float = 0.0, limit: int | None = None) -> list[StationTradeResult]`** — the core.
   - For each quote: **skip** if `best_bid <= 0` or `best_ask <= 0` (no two-sided market — can't station-trade).
   - Build `opp = station_trade_opportunity(config, buy_price=q.best_bid, sell_price=q.best_ask, quantity=1)`.
   - `unit_profit = opp.profit`; `roi = opp.roi`; `spread = q.best_ask − q.best_bid`.
   - **Filter** (inclusive): keep only if `unit_profit >= min_unit_profit` AND `roi >= min_roi` AND `q.daily_volume >= min_daily_volume`.
   - Build `StationTradeResult(...)` for survivors.
   - **Sort** deterministically: `roi` desc, then `daily_volume` desc, then `type_id` asc (stable tiebreak so tests are deterministic).
   - If `limit is not None`: validate `limit >= 1` else `ValueError`; return at most `limit` rows (slice after sort).
   - Validate the three `min_*` thresholds are `>= 0` else `ValueError`. (Do NOT re-validate prices — `station_trade_opportunity` → `MarketBuy`/`MarketSell` already raise on negatives; the `<=0` skip handles the "no market" case before that.)

**Conventions to mirror:** pure/deterministic (no I/O/global state); reuse `opportunity.py` (no duplicated fee math); explicit full type hints; `from __future__ import annotations`; keyword-only tuning params; raise `ValueError` (not assert); terse docstrings; no new deps (`dataclasses`, `typing`/`collections.abc` stdlib only — use `collections.abc.Iterable`).

**Boundary** — gather only the To-gather files; write only the in-scope files; do not add DB/CLI yet; do not expand scope. Design change needed → STOP + §9.

**Verification (paste §8, terse per §2):**
- `python -m pytest -q` (bundled-Python abs path if bare `python` missing) — prior **49 passed, 1 skipped stays green** + new `tests/test_station_trade.py` pass. Cover (pure, no I/O):
  - **Per-unit economics, zero-skill config** (`Config()` defaults — broker_relations 0/accounting 0/standings 0): a `MarketQuote(type_id=34, type_name="Tritanium", best_bid=100, best_ask=120, daily_volume=1_000_000)` → one `StationTradeResult` with `buy_price==100`, `sell_price==120`, `spread==pytest.approx(20)`, `unit_profit==pytest.approx(4.4)` (107.4 net − 103 cost), `roi==pytest.approx(4.4/103)`. (Mirrors M7's 44/1030 at 1/10 scale — confirms fee reuse.)
  - **Skip no-market quotes:** `best_bid=0` (or `best_ask=0`) → excluded from results.
  - **Threshold filters:** with the 4.4-profit item, `min_unit_profit=5` → empty; `min_roi=0.05` (> 0.0427) → empty; `min_daily_volume=2_000_000` → empty; defaults (all 0) → kept.
  - **Sort + limit:** feed ≥3 quotes with distinct roi; assert output ordered by roi desc (and `limit=2` returns the top 2). Add a roi tie broken by `daily_volume` desc to prove the tiebreak.
  - **`ValueError`:** `min_roi=-1`, `min_unit_profit=-1`, `min_daily_volume=-1`, `limit=0`.
  - Use `pytest.approx` for floats. Build `Config()` with no args for the zero-skill case (or set skills/standings explicitly if defaults aren't all-zero — read `config.py` to confirm defaults; if non-zero, pass explicit zeros).
- `python -m ruff check .` → clean.
- `python -m mypy src/` → **clean** (`Success: no issues found in … source files`) — gate stays green.
- NO live run (pure calc).
- Pre-commit `git status --short`: only `src/evemarket/analytics/station_trade.py`, `tests/test_station_trade.py`, `HANDOFF.md` (the untracked `HANDOFF_ARCHIVE.md` + modified `AGENTS.md` are unrelated planner docs — do NOT stage them); no `data/`/`*.duckdb`/parquet. Commit `feat: pure station-trade ranking core -> analytics/station_trade.py (M8a)`; `git push origin main` (no force). Include `HANDOFF.md`.

When done: append §8 entry (terse, **INCLUDE the commit hash**) and STOP. After M8a → **M8b** `station_trade` DuckDB reader (best bid/ask per type from latest order snapshot + history volume → `MarketQuote` rows; Claude will gather the store schema for that pack) → **M8c** CLI `scan` command.

> Completed task Context Packs (M4a–M7) archived/superseded — load-bearing facts retained in §7 (verdicts) + §8 (logs); full early packs in `HANDOFF_ARCHIVE.md` §A.

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

**Standing decisions / known non-blockers (carry forward):**
- **"No new deps" is hard:** if Codex needs one → STOP + §9 for planner sign-off; never silently `pip install` to make tests pass (M3-FIX hidden-pytz trap).
- **DuckDB↔polars bulk insert avoids `pyarrow`** (not a dep): stage explicit-schema rows into a TEMP duckdb table via `executemany` + set-based `ON CONFLICT` upsert (`_upsert_history_frame`). If true bulk needed later, declare `pyarrow` w/ sign-off.
- **ESI error-budget** state is shared but **unlocked** across concurrent paginated pages — fine for single hub; revisit if parallelizing regions.
- **everef present-but-empty day file** → counted NEITHER fetched NOR missing (`days_fetched+days_missing` can be < range); self-healing on idempotent re-run.
- **Env (Codex/Windows):** bare `python` not on PATH → use bundled Python abs path; AppData temp perm denied → `--basetemp .pytest-tmp`; live runs need network escalation; `git status` warns global ignore inaccessible (benign).
- **Deferred (non-blocking, M0):** switch `Config`/`SkillConfig` `BaseSettings`→`BaseModel` so TOML is sole config source (BaseSettings allows silent env-var overrides). Small future task. (Also tracked §9.)

**Recent verdicts:**
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

## 9. Open Questions / Blockers

> Resolved items (M5b-block, PII, REPLACE_ME, Fuzzwork) archived in `HANDOFF_ARCHIVE.md` §D.

- **Deferred (non-blocking, M0):** switch `Config`/`SkillConfig` from `pydantic_settings.BaseSettings` to `pydantic.BaseModel` so TOML is sole config source (BaseSettings allows silent env-var overrides). Future small task.
