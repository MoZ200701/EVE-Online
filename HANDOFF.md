# EVE Market Tool — Agent Handoff

This file is the shared source of truth between two AI agents working on this
project. It is append-mostly: read the whole thing before acting, then update
your own section. Keep it accurate — it is the only memory that survives between
sessions.

---

## 1. Roles

| Agent | Role | Does | Does NOT |
|-------|------|------|----------|
| **Claude (Opus)** | Planner / Debugger | Plans steps, writes task prompts, reviews GPT‑5.5's output, diagnoses bugs, decides "done or redo" | Write production code (only patches/snippets when debugging) |
| **GPT‑5.5 (Codex)** | Executor | Implements exactly the current task, writes code + tests, runs verification, reports back | Re-plan, expand scope, skip ahead, or invent architecture |

**Operating rule:** one step at a time. GPT‑5.5 executes the *current task only*,
reports back in the Execution Log, then stops. Claude reviews, marks the step
DONE or REDO, and writes the next task prompt. Do not batch multiple milestones.

---

## 2. Update protocol

- **GPT‑5.5**, after finishing a task, append an entry to **§8 Execution Log** with:
  files created/changed, commands run, verification output (pass/fail), and any
  deviations from the prompt or questions. Then STOP and wait for review.
- **Claude**, after reviewing, append to **§7 Planner/Debugger Notes**: a verdict
  (DONE / REDO + why), any bug diagnosis, and the next task prompt placed in
  **§6 Current Task**.
- Never delete log history. Correct mistakes by adding a new entry.
- If blocked, write it under **§9 Open Questions / Blockers** and stop.

---

## 3. Project overview (cold-start context)

**Goal:** A market trading helper for *EVE Online* that tells the user what to
buy, and what/when to sell — covering **station trading** and **hauling
(regional arbitrage)** now, with **industry/manufacturing deferred but
architected for**. Models train **locally** on EVE-only data (small models:
gradient-boosted trees / time-series — NOT LLM fine-tuning).

**Data is fully public:**
- **ESI** (EVE Swagger Interface), `https://esi.evetech.net`, OpenAPI at `/ui/`.
  Market endpoints are public (no auth):
  - `/markets/{region_id}/orders/` — live order book (paginated via `X-Pages`)
  - `/markets/{region_id}/history/` — daily OHLC-ish history (~13 months)
  - `/markets/prices/` — adjusted & average prices
  - `/markets/structures/{structure_id}/` — needs EVE SSO auth (later)
  - ESI is **cache-timed** (`Expires` header), not rate-limited the usual way.
    It enforces an **error budget** (`X-ESI-Error-Limit-Remain`/`-Reset`).
- **SDE** (Static Data Export): static reference (type_id↔name, item volume m³,
  regions, stations). Use the **Fuzzwork SQLite conversion**, not raw YAML.
- **everef.net**: bulk historical market dumps — used to backfill history fast
  instead of hammering ESI.

Key IDs: The Forge = `10000002` (Jita; ~dominant hub — start here only).

**Why this division of labor:** the real value is an honest backtest/eval loop
and fee-accurate deterministic analytics, not fancy ML. Build deterministic
first; ML is a later layer.

---

## 4. Architecture decisions (LOCKED — do not change without Claude sign-off)

- **Language:** Python 3.11+.
- **HTTP:** `httpx` (async, HTTP/2, concurrent pagination).
- **Storage, two-tier:**
  - **DuckDB** single file for reference + history + prices + derived tables + bookkeeping.
  - **Parquet** for raw order-book snapshots, partitioned `region=<id>/date=<YYYY-MM-DD>/<ts>.parquet`. DuckDB reads them in place.
- **Crunching:** `polars`.
- **Validation:** `pydantic`. **CLI:** `typer`. **Scheduling:** `APScheduler`.
- **Generic seam:** every trade is a `ProfitOpportunity` with pluggable
  `Acquisition` (now: `MarketBuy`; future: `Manufacture`) and `Disposal`.
  This is how industry slots in later without a rewrite.
- **ESI client is the load-bearing component:** must do caching (ETag/Expires +
  `If-None-Match`), error-budget backoff, pagination, gzip, retry-on-5xx, and
  send a **User-Agent with contact info** (from config).

**Target project layout:**
```
eve-market-tool/
  pyproject.toml
  config.toml
  README.md
  data/                        # gitignored; created at runtime
    sde.duckdb
    market.duckdb
    snapshots/orders/region=.../date=.../*.parquet
  src/evemarket/
    __init__.py
    config.py                  # pydantic settings, loads config.toml
    cli.py                     # typer entrypoint
    esi/        __init__.py  client.py  models.py
    sde/        __init__.py  load.py
    ingest/     __init__.py  orders.py  history.py  prices.py  backfill.py
    store/      __init__.py  schema.py  writers.py  quality.py
    analytics/  __init__.py  fees.py  opportunity.py  station_trade.py  haul.py
  tests/
```

---

## 5. Phase plan (high level — do not jump ahead)

**Phase 1 — data pipeline**
- M0  Scaffold (repo, deps, config, CLI wiring)             ✅ DONE
- M1  SDE loaded into `sde.duckdb` and queryable            ✅ DONE
- REPO  git init + initial push to GitHub                   ← CURRENT (side-task)
- M2  ESI client (caching, error-budget, pagination) + live tests
- M3  Order-book snapshot ingestion (The Forge → Parquet) + `ingest_runs` log
- M4  History ingestion + everef.net backfill
- M5  Prices ingestion + scheduler + data-quality checks

**Phase 2 — deterministic analytics (stub during Phase 1)**
- `fees.py` (fee model), `opportunity.py` (ProfitOpportunity interface),
  `station_trade.py` (first scanner), later `haul.py`.

Definition of done is per-step and lives in each task prompt.

---

## 6. Current Task (for GPT‑5.5)

> **STEP REPO — Initialize git and make the initial push to GitHub.** A one-off
> infra side-task between M1 and M2. Execute exactly this; stop and report when
> done. (M0 and M1 are DONE — see §7/§8.)

**Context:** This local project is not yet a git repo. The user wants it pushed
to `https://github.com/MoZ200701/EVE-Online.git` as the project home. The single
biggest risk is accidentally committing large data artifacts — the ~18 MB SDE
CSVs in `data/sde_cache/` and `data/sde.duckdb`. Those live under `data/`, which
`.gitignore` (from M0) already excludes; **you must verify that before
committing.**

**Steps**

1. **Verify `.gitignore`** covers at least: `data/`, `*.duckdb`, `__pycache__/`,
   `.venv/`, `*.egg-info/`, build dirs. If `data/` is not covered, add it. Do
   NOT remove existing entries.
2. `git init` (if not already a repo); set the default branch: `git branch -M main`.
3. `git add -A`, then **run `git status --short` and confirm NO files under
   `data/`, no SDE `*.csv`, and no `*.duckdb` are staged.** If any are staged,
   fix `.gitignore` / unstage before continuing. **Paste the `git status --short`
   output into §8** so the staged set is reviewable.
4. Add the remote: `git remote add origin https://github.com/MoZ200701/EVE-Online.git`.
5. Commit. Suggested message: `chore: initial scaffold + SDE loader (M0–M1)`.
6. Push: `git push -u origin main`.
   - **If the remote already has commits** (e.g. a README/LICENSE created on
     GitHub) and the push is rejected, run `git pull --rebase origin main`, then
     push again. **Never force-push.** If a rebase conflict arises you cannot
     cleanly resolve, STOP and report in §9.
7. **Auth:** use whatever git credentials / `gh auth` your environment provides.
   If you have no push credentials, do NOT improvise — STOP and report in §9.

**Constraints**
- No production code changes; don't touch source modules or the §4 architecture.
- Never commit anything under `data/`, any secret, or any large binary. Never
  force-push. Never rewrite published history.

**Verification (paste into §8)**
- `git remote -v` shows `origin` → the repo URL.
- The `git status --short` from step 3 (proving no data/ or large files staged).
- `git log --oneline -1` shows the initial commit.
- The push summary confirming remote `main` was updated.

**When done:** append an Execution Log entry to §8 and STOP for review. M2 (ESI
client) is next.

---

## 7. Planner/Debugger Notes (Claude)

- 2026-06-26 — Project kicked off. Architecture locked in §4, phase plan in §5.
  First task M0 (scaffold) written in §6. Awaiting GPT‑5.5 execution.
  Review focus when it returns: (1) deps install clean on Windows, (2) `src/`
  layout importable, (3) config defaults match §6 exactly, (4) `evemarket info`
  wiring works, (5) no premature logic leaked into stubs.
- 2026-06-26 — **M0 verdict: DONE.** Independently verified: `python -m pytest`
  → 3 passed; `ruff check .` clean; full 22-module tree present; stubs are empty
  (docstring + TODO only); config defaults match §6 spec exactly; `evemarket
  info` wiring works. Two minor non-blocking notes carried forward (NOT redone
  now): (a) `Config`/`SkillConfig` subclass `BaseSettings`, which silently allows
  env-var overrides of file config — switch to plain `BaseModel` in a later step;
  (b) `evemarket info` says "User-Agent set: yes" even for the REPLACE_ME
  placeholder — turn into a real warning when the ESI client lands (M2). Next
  task M1 (SDE load) written to §6.
- 2026-06-26 — M1 **not started; Codex correctly BLOCKED** on a source mismatch.
  Guardrail worked as designed. Confirmed myself via WebFetch: Fuzzwork's
  `*.csv.bz2` per-table files are gone; the five needed tables exist
  **uncompressed** at `https://www.fuzzwork.co.uk/dump/latest/csv/`
  (invTypes.csv ~18 MB, dated 2026-06-24). Revised §6 to use those uncompressed
  CSVs and dropped the bz2/decompress step. M1 is unblocked — Codex: re-run it.
- 2026-06-26 — **M1 verdict: DONE.** Independently verified against the real
  `data/sde.duckdb`: all 5 tables present with exactly the specified columns (no
  extra source columns leaked); counts match Codex's log (types 52630, regions
  114, stations 5210, market_groups 2102, solar_systems 8490); sanity lookups
  correct (Tritanium vol 0.01 / published 1; The Forge); `security_status` is a
  float; nullable `market_group_id` handled (33,009 null = items not sold on
  market). `python -m pytest` → 4 passed; ruff clean. Clean implementation
  (TableSpec-driven, idempotent DROP+CREATE, PKs added).
- 2026-06-26 — User added the target GitHub remote
  `https://github.com/MoZ200701/EVE-Online.git` and asked Codex to make the
  initial push. Inserted a one-off **REPO** side-task in §6 (between M1 and M2).
  Risk flagged to Codex: must NOT commit the ~18 MB SDE CSVs or the DuckDB file
  (both under gitignored `data/`); the task gates on a `git status` check before
  commit and forbids force-push. M2 (ESI client) follows.

---

## 8. Execution Log (GPT‑5.5)

_(empty — GPT‑5.5 appends the first entry here after M0)_

### M0 — Project scaffold — 2026-06-26
- Status: COMPLETE
- Files created/changed:
  - `pyproject.toml`
  - `config.toml`
  - `README.md`
  - `.gitignore`
  - `src/evemarket/__init__.py`
  - `src/evemarket/config.py`
  - `src/evemarket/cli.py`
  - `src/evemarket/esi/__init__.py`
  - `src/evemarket/esi/client.py`
  - `src/evemarket/esi/models.py`
  - `src/evemarket/sde/__init__.py`
  - `src/evemarket/sde/load.py`
  - `src/evemarket/ingest/__init__.py`
  - `src/evemarket/ingest/orders.py`
  - `src/evemarket/ingest/history.py`
  - `src/evemarket/ingest/prices.py`
  - `src/evemarket/ingest/backfill.py`
  - `src/evemarket/store/__init__.py`
  - `src/evemarket/store/schema.py`
  - `src/evemarket/store/writers.py`
  - `src/evemarket/store/quality.py`
  - `src/evemarket/analytics/__init__.py`
  - `src/evemarket/analytics/fees.py`
  - `src/evemarket/analytics/opportunity.py`
  - `src/evemarket/analytics/station_trade.py`
  - `src/evemarket/analytics/haul.py`
  - `tests/test_config.py`
- Commands run + result:
  - `pip install -e ".[dev]"` succeeded. Pip installed to the user Python 3.13 environment and warned that `C:\Users\M0obo\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.13_qbz5n2kfra8p0\LocalCache\local-packages\Python313\Scripts` is not on `PATH`.
  - `pytest -q`, `evemarket info`, and `ruff check .` failed when invoked by bare command name because the installed Scripts directory is not on `PATH`.
  - Equivalent commands run by absolute installed script path succeeded:
    - `pytest.exe -q`: `3 passed in 0.16s`
    - `evemarket.exe info`: printed `Data dir: C:\Users\M0obo\Desktop\Eve Market Tool\data`, `Tracked regions: [10000002]`, `User-Agent set: yes`
    - `ruff.exe check .`: `All checks passed!`
- Verification: package install succeeded; pytest passed; `evemarket info` passed via installed script path; ruff passed.
- Deviations from prompt: none in project code. Verification used absolute script paths after confirming the bare command names are unavailable on this Windows `PATH`.
- Questions for Claude: none.

Template:
```
### M<n> — <title> — <date>
- Status: COMPLETE / BLOCKED
- Files created/changed: ...
- Commands run + result: ...
- Verification: pytest <...>, evemarket info <...>, ruff <...>
- Deviations from prompt: none / <explain>
- Questions for Claude: none / <list>
```

### M1 — SDE load — 2026-06-26
- Status: BLOCKED
- Files created/changed: `HANDOFF.md` only
- Commands run + result:
  - Probed `https://www.fuzzwork.co.uk/dump/latest/invTypes.csv.bz2`, `mapRegions.csv.bz2`, `staStations.csv.bz2`, `invMarketGroups.csv.bz2`, and `mapSolarSystems.csv.bz2`: first expected file returned HTTP 404.
  - Inspected `https://www.fuzzwork.co.uk/dump/`: `latest/` exists.
  - Inspected `https://www.fuzzwork.co.uk/dump/latest/`: contains a `csv/` subdirectory and full database dumps, not per-table `*.csv.bz2` files at that level.
  - Inspected `https://www.fuzzwork.co.uk/dump/latest/csv/`: found uncompressed `invTypes.csv`, `mapRegions.csv`, `staStations.csv`, `invMarketGroups.csv`, and `mapSolarSystems.csv`.
- Verification: not run; implementation was not started because the source layout differs from the M1 prompt.
- Deviations from prompt: none. Followed the instruction to stop instead of guessing when the Fuzzwork layout differed.
- Questions for Claude: Should M1 be revised to use `https://www.fuzzwork.co.uk/dump/latest/csv/*.csv` uncompressed files instead of `https://www.fuzzwork.co.uk/dump/latest/*.csv.bz2`?

### M1 — SDE load — 2026-06-26
- Status: COMPLETE
- Files created/changed:
  - `src/evemarket/sde/load.py`
  - `src/evemarket/cli.py`
  - `tests/test_sde_load.py`
  - `tests/fixtures/sde/invTypes.csv`
  - `tests/fixtures/sde/mapRegions.csv`
  - `tests/fixtures/sde/staStations.csv`
  - `tests/fixtures/sde/invMarketGroups.csv`
  - `tests/fixtures/sde/mapSolarSystems.csv`
  - `HANDOFF.md`
- Commands run + result:
  - Verified live Fuzzwork filenames/headers at `https://www.fuzzwork.co.uk/dump/latest/csv/`:
    - `invTypes.csv`: includes `typeID`, `groupID`, `typeName`, `volume`, `published`, `marketGroupID`
    - `mapRegions.csv`: includes `regionID`, `regionName`
    - `staStations.csv`: includes `stationID`, `stationName`, `regionID`, `solarSystemID`
    - `invMarketGroups.csv`: includes `marketGroupID`, `parentGroupID`, `marketGroupName`
    - `mapSolarSystems.csv`: includes `solarSystemID`, `regionID`, `security`
  - `python -m pytest -q`: `4 passed in 8.68s`
  - `python -m pytest tests\test_sde_load.py -q`: `1 passed in 0.79s`
  - `python -m ruff check .`: `All checks passed!`
  - `evemarket.exe sde-load`: populated `data/sde.duckdb` with row counts:
    - `sde_types: 52630`
    - `sde_regions: 114`
    - `sde_stations: 5210`
    - `sde_market_groups: 2102`
    - `sde_solar_systems: 8490`
  - `evemarket.exe sde-info`: printed the same row counts and sanity lookups:
    - `type_id 34: Tritanium`
    - `region_id 10000002: The Forge`
- Verification: pytest passed; live SDE load succeeded; live SDE info sanity lookups succeeded; ruff clean.
- Deviations from prompt: none. Used absolute `evemarket.exe` script path because bare scripts are not on `PATH` in this environment, as noted in §6.
- Questions for Claude: none.

---

## 9. Open Questions / Blockers

- (deferred, non-blocking, from M0 review) Switch `Config`/`SkillConfig` from
  `pydantic_settings.BaseSettings` to `pydantic.BaseModel` so TOML is the sole
  config source (BaseSettings silently allows env-var overrides). Fold into a
  future small task, not M1.
- (deferred, from M0 review) `evemarket info` should warn when `user_agent`
  still contains `REPLACE_ME`. Address with the ESI client in M2.
- ~~BLOCKER for M1: Fuzzwork layout mismatch~~ **RESOLVED 2026-06-26 by Claude.**
  Confirmed via WebFetch that the `*.csv.bz2` per-table files are gone; the five
  needed tables are available **uncompressed** at
  `https://www.fuzzwork.co.uk/dump/latest/csv/`. §6 M1 prompt revised to use the
  uncompressed CSVs (no bz2 step). Codex: re-run M1.
