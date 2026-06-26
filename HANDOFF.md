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
- REPO  git init + initial push to GitHub                   ✅ DONE
- M2  ESI client (caching, error-budget, pagination) + live tests   ✅ DONE
- M2-COMMIT  fix ESI contact (Discord) + commit/push M2              ← CURRENT
- M3  Order-book snapshot ingestion (The Forge → Parquet) + `ingest_runs` log
- M4  History ingestion + everef.net backfill
- M5  Prices ingestion + scheduler + data-quality checks

**Phase 2 — deterministic analytics (stub during Phase 1)**
- `fees.py` (fee model), `opportunity.py` (ProfitOpportunity interface),
  `station_trade.py` (first scanner), later `haul.py`.

Definition of done is per-step and lives in each task prompt.

---

## 6. Current Task (for GPT‑5.5)

> **STEP M2-COMMIT — Fix the ESI contact, then commit & push the approved M2
> work.** Small wrap-up. M2 code is already reviewed/approved (§7); this only
> swaps in a safe contact and lands M2 on GitHub. Do exactly this; stop and report.

**Why:** Codex set `config.toml`'s contact to the user's personal email. The repo
is public and `config.toml` is tracked, so that must not be committed. The user
chose to use their **Discord handle** as the ESI contact instead (a valid,
non-personal contact).

**Steps**
1. In `config.toml`, set the User-Agent contact to the Discord handle (NOT the
   email):
   `user_agent = "eve-market-tool/0.1 (contact: Discord m0obot)"`
2. Confirm **no personal email remains in any tracked file**:
   `grep -ri "<personal-email-token>" . --exclude-dir=.git` must return nothing.
3. `python -m pytest -q` still passes (live skipped); ruff clean.
4. Stage the M2 work + the config change, then **run `git status --short` and
   confirm: nothing under `data/`, no `*.duckdb`, no SDE-cache CSVs, and
   `config.toml` shows the Discord handle (no email).** Paste it into §8.
5. Commit: `feat: ESI client with caching, error-budget, pagination (M2)`.
6. `git push origin main` (never force). If rejected, `git pull --rebase origin
   main` then push; STOP on an unresolved conflict.

**Verification (paste into §8):** the `git status --short` from step 4,
`git log --oneline -2`, the push summary, and confirmation that
the personal-email search is empty.

**When done:** append a §8 entry and STOP. M3 (order-book ingestion) is next.

<!-- M2 task (DONE) preserved below for reference -->

> **STEP M2 — Build the ESI HTTP client (caching, error-budget, pagination,
> retries) with offline unit tests + one gated live test.** This is the
> load-bearing component of the whole pipeline. Execute exactly this and nothing
> more — **no ingestion, no storage, no analytics** (that's M3+). The client
> returns parsed objects in memory only. Stop and report when done.

**Context:** Per §3/§4, ESI is **cache-timed, not rate-limited the usual way**:
every response carries an `Expires` header and an **error budget**
(`X-ESI-Error-Limit-Remain` / `X-ESI-Error-Limit-Reset`). Polling faster than
`Expires` just returns stale cache and wastes requests; burning the error budget
gets you throttled (HTTP 420). The client must respect all of this so M3's
ingestion can lean on it. Base URL `https://esi.evetech.net`. We test against the
**public, no-auth** market endpoints.

**Deliverables**

1. **`esi/models.py`** — pydantic model `MarketOrder` matching ESI
   `/markets/{region_id}/orders/` items: `order_id:int`, `type_id:int`,
   `is_buy_order:bool`, `price:float`, `volume_remain:int`, `volume_total:int`,
   `min_volume:int`, `location_id:int`, `system_id:int|None`, `range:str`,
   `duration:int`, `issued:datetime`. (Only the model we need to validate the
   live test — other endpoint models come with their milestones.)

2. **`esi/client.py`** — an **async** client (`httpx.AsyncClient`, HTTP/2 on,
   gzip via default `Accept-Encoding`, `base_url`, `User-Agent` from `Config`):
   - `class ESIClient` constructed from a `Config` (or explicit `user_agent` +
     options). **On init, if `user_agent` still contains `REPLACE_ME`, log a
     loud WARNING** (this also resolves the deferred §9 item — and update
     `evemarket info` to print a warning in that case).
   - A small **in-memory response cache** keyed by `(path, sorted params)`
     storing `{etag, expires, payload, pages}`. (Persistent cache is deferred to
     a later milestone — in-memory is fine for M2; note it in a docstring.)
   - `async def get(path, params=None) -> ESIResponse` (define a small
     `ESIResponse` dataclass: `data`, `expires`, `etag`, `pages`,
     `error_limit_remain`, `error_limit_reset`). Behavior:
     - If a cached entry exists and `now < expires`, **return it without a
       network call**.
     - Otherwise send the request; if we hold an `etag` for this key, send
       `If-None-Match`. On **304**, refresh expiry and return the cached payload.
     - Parse `Expires` (RFC-1123 via `email.utils.parsedate_to_datetime`),
       `ETag`, `X-Pages`, and the two error-limit headers; update the cache and
       the client's tracked error-budget state.
     - **Error budget:** before issuing a request, if the last-seen
       `error_limit_remain <= ERROR_LIMIT_THRESHOLD` (default 5), wait
       `error_limit_reset` seconds. On HTTP **420**, wait out the reset then
       retry.
     - **Retries:** on 5xx and transport errors, exponential backoff
       (`MAX_RETRIES` default 3). Raise a clear `ESIError` on non-retryable 4xx
       (except 304).
   - `async def get_paginated(path, params=None) -> list[dict]` — fetch page 1,
     read `X-Pages`, then fetch pages `2..N` **concurrently** with a bounded
     `asyncio.Semaphore` (`MAX_CONCURRENCY` default 8), concatenate in page order.
   - Make backoff **testable**: inject the sleep coroutine and a `now()` clock
     (constructor args defaulting to `asyncio.sleep` / `datetime.now(timezone.utc)`)
     so unit tests don't actually sleep or depend on wall-clock.
   - Tunables (`ERROR_LIMIT_THRESHOLD`, `MAX_RETRIES`, `MAX_CONCURRENCY`,
     backoff base) as module constants.

3. **CLI `evemarket esi-check`** (`@app.command("esi-check")`, `--region` default
   from config's first tracked region, `--limit` default 5) — uses the client to
   fetch **page 1 only** of that region's orders, then prints: total orders on
   the page, the `X-Pages` value, and `--limit` sample parsed `MarketOrder`s.
   Runs the async client via `asyncio.run`. (Keep it to one page — be polite.)

4. **`tests/test_esi_client.py`** — **offline unit tests using
   `httpx.MockTransport`** (no network), covering:
   - pagination: `X-Pages: 3` → `get_paginated` issues 3 requests and
     concatenates results;
   - caching: a second `get` before `expires` makes **no** new request;
   - 304: when expired and an ETag is held, a `304` returns the cached payload;
   - error budget: a response with `remain <= threshold` causes the injected
     sleep to be called with the reset duration (assert via a fake sleep);
   - retry: two 5xx then a 200 → succeeds after retries (fake sleep);
   - `MarketOrder` parses a representative payload.
   Use the injected sleep/clock so tests are instant and deterministic.

5. **One gated live test** in the same file, `test_live_forge_orders`, marked
   `@pytest.mark.skipif` unless env var **`EVEMARKET_LIVE_TESTS=1`** is set:
   fetch page 1 of The Forge (10000002) orders against real ESI and assert ≥1
   row parses as `MarketOrder` and `X-Pages` is present. Default `pytest` runs
   must NOT hit the network.

**Constraints**
- No ingestion/storage/analytics. The client hands back in-memory objects only.
- **One new dependency is pre-approved:** add `httpx[http2]` (pulls in `h2`) to
  enable HTTP/2 per §4. No other new deps without flagging in §9.
- Async core; the CLI bridges via `asyncio.run`. Cross-platform paths; Windows.
- Don't change the §4 architecture. If something there blocks you, STOP and
  raise it in §9.

**Verification (paste into §8)**
- `python -m pytest -q` passes with **live tests skipped** (network-free run).
- `EVEMARKET_LIVE_TESTS=1 python -m pytest -q -k live` passes against real ESI
  (run once; paste the result).
- `evemarket esi-check` prints a page-1 order count, `X-Pages`, and sample
  orders for The Forge. Paste the output.
- `python -m ruff check .` clean.
- Confirm the `REPLACE_ME` User-Agent warning fires (note: set a real contact in
  `config.toml` before the live test so you're a good ESI citizen).

**When done:** append an Execution Log entry to §8 (files, the unit + live test
results, `esi-check` output, deviations/questions). Then STOP for review.

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
- 2026-06-26 — **REPO verdict: DONE.** Independently verified via git: remote =
  the repo; root commit `04d9c6a`; `git ls-files` shows **no `data/`, `*.duckdb`,
  or `sde_cache` tracked** — only the small synthetic fixture CSVs (intended).
  Working tree clean except the HANDOFF log entry. Codex set local `user.name`
  (Git had email but no name) — fine, no force-push. Next task **M2 (ESI
  client)** written to §6 — the load-bearing component; folds in the deferred
  REPLACE_ME User-Agent warning. Review focus when it returns: correct
  Expires/ETag(304) caching, error-budget backoff (HTTP 420), concurrent
  pagination, testable injected sleep/clock, and that default `pytest` stays
  network-free (live test gated behind `EVEMARKET_LIVE_TESTS=1`).
- 2026-06-26 — **M2 verdict: DONE (code approved).** Read `esi/client.py` in full;
  ran offline tests myself (11 passed, 1 skipped, network-free). Caching
  (serve-before-expiry, no network), ETag/`If-None-Match`→304 refresh,
  error-budget wait + HTTP-420 retry, concurrent `X-Pages` pagination (semaphore,
  ordered concat), 5xx/transport retries w/ exp backoff, injected sleep/clock —
  all present and correct. Live `esi-check` pulled real Forge data. Minor
  non-blocking note: error-budget state is shared but unlocked across concurrent
  paginated requests — fine for single-hub; revisit if we parallelize regions.
  ⚠️ PII flag raised in §9 — **M3 NOT drafted until the config.toml email issue
  is resolved.**
- 2026-06-26 — User chose **Discord handle `m0obot`** as the ESI contact (safe,
  non-personal). Wrote **M2-COMMIT** task in §6: swap contact, verify no email in
  tracked files, then commit+push the approved M2 work. M3 follows after.

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

### REPO — Initial git push — 2026-06-26
- Status: COMPLETE
- Files created/changed: `HANDOFF.md` only for this log entry after push; committed project files are listed in the initial commit.
- Commands run + result:
  - Verified `.gitignore` includes `data/`, `*.duckdb`, `__pycache__/`, `.venv/`, `*.egg-info/`, `build/`, and `dist/`.
  - `git check-ignore -v data/sde.duckdb data/sde_cache/invTypes.csv data/sde_cache/mapRegions.csv` confirmed generated SDE outputs are ignored by `.gitignore:1:data/`.
  - `git init`: initialized empty repository in `C:/Users/M0obo/Desktop/Eve Market Tool/.git/`.
  - `git branch -M main`: succeeded.
  - `git add -A`: staged project files; only Windows LF-to-CRLF warnings.
  - Pre-commit `git status --short`:
    ```text
    A  .gitignore
    A  AGENTS.md
    A  CLAUDE.md
    A  HANDOFF.md
    A  README.md
    A  config.toml
    A  pyproject.toml
    A  src/evemarket/__init__.py
    A  src/evemarket/analytics/__init__.py
    A  src/evemarket/analytics/fees.py
    A  src/evemarket/analytics/haul.py
    A  src/evemarket/analytics/opportunity.py
    A  src/evemarket/analytics/station_trade.py
    A  src/evemarket/cli.py
    A  src/evemarket/config.py
    A  src/evemarket/esi/__init__.py
    A  src/evemarket/esi/client.py
    A  src/evemarket/esi/models.py
    A  src/evemarket/ingest/__init__.py
    A  src/evemarket/ingest/backfill.py
    A  src/evemarket/ingest/history.py
    A  src/evemarket/ingest/orders.py
    A  src/evemarket/ingest/prices.py
    A  src/evemarket/sde/__init__.py
    A  src/evemarket/sde/load.py
    A  src/evemarket/store/__init__.py
    A  src/evemarket/store/quality.py
    A  src/evemarket/store/schema.py
    A  src/evemarket/store/writers.py
    A  tests/fixtures/sde/invMarketGroups.csv
    A  tests/fixtures/sde/invTypes.csv
    A  tests/fixtures/sde/mapRegions.csv
    A  tests/fixtures/sde/mapSolarSystems.csv
    A  tests/fixtures/sde/staStations.csv
    A  tests/test_config.py
    A  tests/test_sde_load.py
    ```
  - Confirmed no staged files under `data/`, no live SDE cache CSVs, and no `*.duckdb` files.
  - `git remote add origin https://github.com/MoZ200701/EVE-Online.git`: succeeded.
  - `git commit -m "chore: initial scaffold + SDE loader (M0-M1)"`: created root commit `04d9c6a` with 36 files changed.
  - `git push -u origin main`: succeeded:
    ```text
    To https://github.com/MoZ200701/EVE-Online.git
     * [new branch]      main -> main
    branch 'main' set up to track 'origin/main'.
    ```
- Verification:
  - `git remote -v`:
    ```text
    origin  https://github.com/MoZ200701/EVE-Online.git (fetch)
    origin  https://github.com/MoZ200701/EVE-Online.git (push)
    ```
  - `git log --oneline -1`: `04d9c6a chore: initial scaffold + SDE loader (M0-M1)`
  - Post-push `git status --short` was clean before this log entry was appended.
- Deviations from prompt: set local `git config user.name "MoZ200701"` because Git had `user.email` configured but no author name. Did not force-push.
- Questions for Claude: none.

### M2 — ESI HTTP client — 2026-06-26
- Status: COMPLETE
- Files created/changed:
  - `pyproject.toml`
  - `config.toml`
  - `src/evemarket/esi/models.py`
  - `src/evemarket/esi/client.py`
  - `src/evemarket/cli.py`
  - `tests/test_esi_client.py`
  - `tests/test_config.py`
  - `HANDOFF.md`
- Commands run + result:
  - `python -m pip install -e ".[dev]"`: succeeded; installed pre-approved `httpx[http2]` extras (`h2`, `hpack`, `hyperframe`).
  - `python -m pytest -q`: `11 passed, 1 skipped in 0.94s` (live test skipped by default; no network).
  - `python -m ruff check .`: `All checks passed!`
  - `evemarket info --config missing-placeholder-check.toml`: confirmed CLI warning:
    ```text
    Config file missing-placeholder-check.toml not found; using defaults.
    Data dir: C:\Users\M0obo\Desktop\Eve Market Tool\data
    Tracked regions: [10000002]
    User-Agent set: yes
    WARNING: User-Agent still contains REPLACE_ME contact placeholder.
    ```
  - `python -c "import asyncio; from evemarket.esi.client import ESIClient; client=ESIClient(); asyncio.run(client.aclose())"`: confirmed client log warning:
    ```text
    ESI User-Agent still contains REPLACE_ME; set a real contact before live ESI requests.
    ```
  - `EVEMARKET_LIVE_TESTS=1 python -m pytest -q -k live`: `1 passed, 11 deselected in 2.06s`
  - `evemarket esi-check --limit 5`:
    ```text
    Region: 10000002
    Page 1 orders: 1000
    X-Pages: 424
    Order 7307526145: type=5321 side=sell price=500000.0 remain=44/56
    Order 7325351938: type=27121 side=sell price=124000000.0 remain=1/1
    Order 7139753989: type=211 side=sell price=14.54 remain=880000/880000
    Order 7361003532: type=7291 side=sell price=9480.0 remain=5/17
    Order 7302283280: type=55719 side=sell price=4450000000.0 remain=1/1
    ```
- Verification: offline pytest passed with live test skipped; gated live ESI test passed; `esi-check` fetched page 1 only and parsed sample `MarketOrder`s; ruff clean; placeholder User-Agent warning confirmed in CLI and client.
- Deviations from prompt: none. Updated `config.toml` contact from `REPLACE_ME` to a real contact before live ESI calls as requested.
- Questions for Claude: none.

---

## 9. Open Questions / Blockers

- ⚠️ **PII / leak risk (NEW, 2026-06-26):** Codex set `config.toml` contact to the
  user's personal email in the **working tree**. `config.toml` is a TRACKED file;
  HEAD still has `REPLACE_ME` (email NOT yet pushed — good). **Do NOT commit
  config.toml with the personal email to the public repo.** Awaiting user
  decision on contact handling. Until resolved, do not stage `config.toml`.
  **RESOLVED 2026-06-26:** user chose Discord handle `m0obot`; M2-COMMIT task
  (§6) swaps it in and verifies no email in tracked files before committing.
- (deferred, non-blocking, from M0 review) Switch `Config`/`SkillConfig` from
  `pydantic_settings.BaseSettings` to `pydantic.BaseModel` so TOML is the sole
  config source (BaseSettings silently allows env-var overrides). Fold into a
  future small task, not M1.
- ~~(deferred, from M0 review) `evemarket info` should warn on `REPLACE_ME`
  User-Agent~~ **folded into the M2 task (§6)** — client logs a loud warning and
  `evemarket info` updated.
- ~~BLOCKER for M1: Fuzzwork layout mismatch~~ **RESOLVED 2026-06-26 by Claude.**
  Confirmed via WebFetch that the `*.csv.bz2` per-table files are gone; the five
  needed tables are available **uncompressed** at
  `https://www.fuzzwork.co.uk/dump/latest/csv/`. §6 M1 prompt revised to use the
  uncompressed CSVs (no bz2 step). Codex: re-run M1.
