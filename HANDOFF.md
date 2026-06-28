# EVE Market Tool — Agent Handoff

Shared source of truth between two AI agents. Append-mostly. Read fully before acting; update your own section. Only memory that survives between sessions.

> **Completed-task history (full Context Packs, per-milestone planner notes, Codex execution logs, resolved blockers) lives in `HANDOFF_ARCHIVE.md`.** This file holds only current/load-bearing state. Commit ledger is in §7.

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
- **Style rule (terse / "caveman"):** this file is AI↔AI only — no prose, no filler, no human niceties. Write entries as dense bullets/fragments. Keep load-bearing facts (commands, results, file paths, commit hashes, IDs, verdicts) verbatim; drop everything else. Periodically compact (collapse done tasks, strip duplicate dumps) rather than letting it grow — move old detail to `HANDOFF_ARCHIVE.md`, don't delete.

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
- **M5** Prices ✅ | scheduler (M5b) ✅ | data-quality (M5c) ✅ | M5-FIX mypy-clean ✅ — **Phase 1 COMPLETE & to-standard.** ← **CURRENT: Phase 2 / M6 — `analytics/fees.py` (broker fee + sales tax, skill/standings-aware) drafted (§6).**

**Phase 2 — deterministic analytics (stubbed):** `fees.py`, `opportunity.py` (ProfitOpportunity), `station_trade.py` (first scanner), then `haul.py`.

Definition of done is per-step in each task prompt.

## 6. Current Task (Codex) — M6: `analytics/fees.py` — deterministic broker fee + sales tax

Phase 1 COMPLETE (M5-FIX DONE, §7). First Phase-2 task: fill the `analytics/fees.py` stub with a **pure, deterministic** EVE fee model (broker fee + sales tax, skill/standings-aware). NO network, NO DB, NO file I/O, NO CLI this step (CLI lands later with the first scanner). This is the fee primitive `opportunity.py`/`station_trade.py` will consume. **CLOSED-WORLD: touch only the listed files; everything you need is in this pack. Missing detail → STOP + §9, do NOT scan the tree.**

### CONTEXT PACK

**Files in scope (touch nothing else):**
- EDIT `src/evemarket/analytics/fees.py` — currently a 4-line stub (`"""Fee model stub."""` + `# TODO: M6`). Replace its body with the implementation below.
- CREATE `tests/test_fees.py`.
- EDIT `HANDOFF.md` §8 (log).
- Do NOT touch `config.py`, `cli.py`, or anything else.

**EVE fee mechanics (authoritative — planner researched EVE University Tax wiki + CCP support; do NOT re-derive):**
- **Broker fee** — charged when a limit **buy OR sell** order is *placed* (duration longer than "immediate"); NOT refunded if cancelled/expired. Rate (fraction of order value):
  `rate = 0.03 − 0.003×broker_relations − 0.0003×faction_standing − 0.0002×corp_standing`, then **clamped to a 1% floor** (`max(rate, 0.01)`). Uses **unmodified** standings (standing-boosting skills do NOT apply — caller passes raw standings). Negative standings legitimately *increase* the rate (no upper clamp).
- **Sales tax** — charged when an item *sells*; paid by the seller, deducted from sale proceeds. Rate:
  `rate = 0.075 × (1 − 0.11×accounting)` (Accounting V → `0.075×0.45 = 0.03375`).
- **Station-trade round trip** = place buy order (broker fee on buy value) + place sell order (broker fee on sell value) + item sells (sales tax on sell value).

**Caller contracts (verbatim — for the `from_config` helper; already exist, just read them):**
- `evemarket.config.Config` has: `skills: SkillConfig` where `SkillConfig.accounting: int (0..5)` and `SkillConfig.broker_relations: int (0..5)`; `standings_factional: float` (faction standing); `standings_corp: float` (corp standing). Import as `from evemarket.config import Config`.

**Deliverables (do EXACTLY this — pure functions, full type hints, `from __future__ import annotations`, module + function docstrings to mirror the codebase):**
1. **Module constants** (named, module-level): `BASE_BROKER_FEE = 0.03`, `BROKER_RELATIONS_REDUCTION_PER_LEVEL = 0.003`, `FACTION_STANDING_REDUCTION_PER_POINT = 0.0003`, `CORP_STANDING_REDUCTION_PER_POINT = 0.0002`, `MIN_BROKER_FEE = 0.01`, `BASE_SALES_TAX = 0.075`, `ACCOUNTING_REDUCTION_PER_LEVEL = 0.11`.
2. `def broker_fee_rate(*, broker_relations: int = 0, faction_standing: float = 0.0, corp_standing: float = 0.0) -> float` — apply the formula above using the constants; return `max(rate, MIN_BROKER_FEE)`. Validate: `broker_relations` int in `0..5` else `ValueError`; `faction_standing`/`corp_standing` in `-10.0..10.0` else `ValueError`.
3. `def sales_tax_rate(*, accounting: int = 0) -> float` — `BASE_SALES_TAX * (1 - ACCOUNTING_REDUCTION_PER_LEVEL * accounting)`. Validate `accounting` int in `0..5` else `ValueError`.
4. `def broker_fee(order_value: float, *, broker_relations=0, faction_standing=0.0, corp_standing=0.0) -> float` — `order_value * broker_fee_rate(...)`. Validate `order_value >= 0` else `ValueError`.
5. `def sales_tax(sale_value: float, *, accounting=0) -> float` — `sale_value * sales_tax_rate(...)`. Validate `sale_value >= 0` else `ValueError`.
6. `@dataclass(frozen=True) class TradeFees` with float fields: `buy_broker_fee`, `sell_broker_fee`, `sales_tax`, `total`.
7. `def station_trade_fees(buy_price: float, sell_price: float, quantity: int, *, broker_relations=0, accounting=0, faction_standing=0.0, corp_standing=0.0) -> TradeFees` — `buy_value = buy_price*quantity`, `sell_value = sell_price*quantity`; `buy_broker_fee = broker_fee(buy_value, broker_relations=..., faction_standing=..., corp_standing=...)`; `sell_broker_fee = broker_fee(sell_value, ...)`; `tax_amount = sales_tax(sell_value, accounting=...)`; `total = buy_broker_fee + sell_broker_fee + tax_amount`; return `TradeFees(buy_broker_fee, sell_broker_fee, tax_amount, total)`. Validate `buy_price>=0`, `sell_price>=0`, `quantity` int `>= 1` else `ValueError`. (The `TradeFees.sales_tax` field name shadows the `sales_tax` function — compute `tax_amount` into a local var FIRST as shown, then build `TradeFees`.)
8. `def station_trade_fees_from_config(config: Config, buy_price: float, sell_price: float, quantity: int) -> TradeFees` — thin delegate pulling `broker_relations=config.skills.broker_relations, accounting=config.skills.accounting, faction_standing=config.standings_factional, corp_standing=config.standings_corp`.

**Conventions to mirror:** pure/deterministic (NO I/O, NO global state, no network/db); explicit full type hints; `from __future__ import annotations`; keyword-only tuning params as shown; raise `ValueError` (not assert) on bad input; named constants (no magic numbers in bodies); terse docstrings like sibling modules.

**Deferred-and-noted (do NOT implement):** flat 100-ISK per-order minimum broker fee (negligible vs the %, confirm later) — the 1% rate floor IS implemented; gap/atomicity not relevant here.

**Boundary** — Do not read/scan files outside this pack. No new deps (stdlib `dataclasses` only; `Config` already exists). Missing detail → STOP + §9.

**Verification (paste §8, terse per §2):**
- `python -m pytest -q` — prior **36 passed, 1 skipped stays green** + new `tests/test_fees.py` all pass (suite count rises). Test (pure, no I/O): `broker_fee_rate()` zero-args = `0.03`; Broker Relations 5 = `0.015`; BR5 + faction 10 + corp 10 → formula hits `0.01` floor (assert `== 0.01`, floor holds, not below); negative faction `-10` raises the rate (`> 0.03`); `sales_tax_rate(accounting=0)=0.075`, `accounting=5 ≈ 0.03375` (`pytest.approx`); `station_trade_fees(100, 120, 10)` all-zero skills → `buy_broker_fee=30`, `sell_broker_fee=36`, `sales_tax=90`, `total=156`; `station_trade_fees_from_config` delegates (build a `Config(skills=SkillConfig(broker_relations=5, accounting=5), standings_factional=10, standings_corp=10)` and assert it matches the explicit call); `ValueError` on `broker_relations=6`, `accounting=6`, `faction_standing=11`, negative `order_value`, `quantity=0`. Use `pytest.approx` for float compares.
- `python -m ruff check .` → clean.
- `python -m mypy src/` → **clean** (`Success: no issues found in ... source files`) — the M5-FIX gate stays green.
- NO live run (pure calc, no network/db).
- Pre-commit `git status --short`: only `src/evemarket/analytics/fees.py`, `tests/test_fees.py`, `HANDOFF.md`; no `data/`/`*.duckdb`/parquet staged. Commit `feat: deterministic broker-fee + sales-tax model -> analytics/fees.py (M6)`; `git push origin main` (no force). Include `HANDOFF.md`.

When done: append §8 entry (terse, **INCLUDE the commit hash**) and STOP. After M6 → M7 `opportunity.py` (`ProfitOpportunity`/`Acquisition`/`Disposal` seam) on review.

> Completed task Context Packs (M4a, M4b, M5a, M5b, M5c, M5-FIX) archived in `HANDOFF_ARCHIVE.md` §A.

## 7. Planner/Debugger Notes (Claude)

> Full per-milestone notes M0–M5c + Phase-1 audit archived in `HANDOFF_ARCHIVE.md` §B.

**Milestone ledger (status · commit):**
- M0 Scaffold ✅ `04d9c6a` · M1 SDE ✅ `04d9c6a` · REPO ✅ `04d9c6a`
- M2 ESI client ✅ `6da016f` · M3 Orders ✅ `c1dacf8` → FIX2 `c228ca9`
- M4a ESI history ✅ `b51e885` · M4b everef backfill ✅ `e1ce7b2`
- M5a prices ✅ `9666724` · M5b scheduler ✅ `169bde0` · M5c quality ✅ `7eb3760`
- M5-FIX mypy-clean ✅ `f654b2f` (+docs `e7c851e`) — **Phase 1 COMPLETE to standard.**

**Standing decisions / known non-blockers (carry forward):**
- **"No new deps" is hard:** if Codex needs one → STOP + §9 for planner sign-off; never silently `pip install` to make tests pass (M3-FIX hidden-pytz trap).
- **DuckDB↔polars bulk insert avoids `pyarrow`** (not a dep): stage explicit-schema rows into a TEMP duckdb table via `executemany` + set-based `ON CONFLICT` upsert (`_upsert_history_frame`). If true bulk needed later, declare `pyarrow` w/ sign-off.
- **ESI error-budget** state is shared but **unlocked** across concurrent paginated pages — fine for single hub; revisit if parallelizing regions.
- **everef present-but-empty day file** → counted NEITHER fetched NOR missing (`days_fetched+days_missing` can be < range); self-healing on idempotent re-run.
- **Env (Codex/Windows):** bare `python` not on PATH → use bundled Python abs path; AppData temp perm denied → `--basetemp .pytest-tmp`; live runs need network escalation; `git status` warns global ignore inaccessible (benign).
- **Deferred (non-blocking, M0):** switch `Config`/`SkillConfig` `BaseSettings`→`BaseModel` so TOML is sole config source (BaseSettings allows silent env-var overrides). Small future task. (Also tracked §9.)

**Recent verdicts:**
- **M5-FIX REVIEW: DONE — PHASE 1 FULLY TO-STANDARD.** Verified via git: commits `f654b2f` (fix) + `e7c851e` (docs log) on `main`, tree clean, nothing unpushed. Codex §8: `mypy src/` → `Success: no issues found in 23 source files` (the new gate), `pytest` → `36 passed, 1 skipped` (UNCHANGED = behavior-preserving), `ruff` clean; only the 4 intended files touched (`pyproject.toml`, `writers.py`, `sde/load.py`, `HANDOFF.md`); no `data/` staged. The lone Phase-1 audit gap is closed. **Phase 1 data pipeline COMPLETE to standard. M0–M5-FIX DONE.**
- **M6 drafted (Context Pack) — FIRST Phase-2 task.** `analytics/fees.py` deterministic broker-fee + sales-tax (skill/standings-aware). Planner researched live/authoritative (EVE University Tax wiki + CCP support article): broker fee = `3% − 0.3%×BrokerRelations − 0.03%×factionStanding − 0.02%×corpStanding`, 1% floor, charged on buy AND sell order *placement*, **unmodified** standings (negative → higher fee); sales tax = `7.5% × (1 − 0.11×Accounting)` (Accounting V → 3.375%), paid by seller on sale proceeds. Verified the seam already exists in `Config` (`config.skills.{accounting,broker_relations}` 0–5 ge/le-validated, `config.standings_factional`, `config.standings_corp`) — design is **skill/standings-aware from the start** (flat rate is just the degenerate case; "fee-accurate" is the core value per §3). Pure module (no I/O/CLI): named constants, `broker_fee_rate`/`sales_tax_rate` (validated + 1% clamp), `broker_fee`/`sales_tax` amounts, `TradeFees` frozen dataclass + `station_trade_fees(...)` round-trip + `station_trade_fees_from_config(config, ...)`. CLI deferred to land with the first scanner. Deferred-and-noted: flat 100-ISK per-order broker minimum (negligible vs %, confirm later). Review focus on return: exact constants/formulas, 1% floor holds + negative-standing raises fee, Accounting-V tax = 0.03375, `ValueError` validation, `station_trade_fees(100,120,10)` = 30/36/90/156, pure (no I/O), no new deps, only `fees.py`+test touched, mypy/ruff clean, commit hash in §8.

## 8. Execution Log (Codex)

> Full per-task logs M0–M5-FIX archived in `HANDOFF_ARCHIVE.md` §C.
> Template: `### M<n> — <title> — <date> — COMPLETE/BLOCKED` then: Files | Commands+result | Verification | Deviations | Questions.

_(Append new entries below — next: M6.)_

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
- Commit: pending.

## 9. Open Questions / Blockers

> Resolved items (M5b-block, PII, REPLACE_ME, Fuzzwork) archived in `HANDOFF_ARCHIVE.md` §D.

- **Deferred (non-blocking, M0):** switch `Config`/`SkillConfig` from `pydantic_settings.BaseSettings` to `pydantic.BaseModel` so TOML is sole config source (BaseSettings allows silent env-var overrides). Future small task.
