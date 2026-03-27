# Batch 53 — Repo Root & `app/__init__.py` Audit

**Date:** 2026-03-27  
**Auditor:** Perplexity / War Machine Audit System  
**Files audited:** 8  
**Issues found:** 2 (Issue #50, Issue #51)  
**Fixes applied this batch:** 0 (issues logged; fixes pending)

---

## Scope

This batch covers **every file at the repository root level** plus `app/__init__.py`.
These files control how the system is built, deployed, tested, and packaged.
They are the outermost shell of War Machine — a change to any one of them
affects every module in the system.

### Root-level inventory

| File / Dir | Type | Purpose |
|---|---|---|
| `app/__init__.py` | Python package init | Declares `app/` as a package; intentionally empty |
| `nixpacks.toml` | Railway build config | Controls Python version, dependencies, start command |
| `railway.toml` | Railway deploy config | Deploy settings, restart policy, health check, cron |
| `requirements.txt` | pip manifest | All runtime Python dependencies with version pins |
| `pytest.ini` | Test runner config | Test discovery, markers, timeout, strictness |
| `.railway_trigger` | Railway rebuild trigger | Forces a Nixpacks clean rebuild when touched |
| `.gitignore` | Git config | Files excluded from version control |
| `README.md` | Repo overview | High-level project description |
| `CONTEXT.md` | AI/LLM context doc | System design context for AI assistants |
| `CODEBASE_DOCUMENTATION.md` | Dev reference | High-level codebase map |
| `REBUILD_PLAN.md` | Strategy doc | Architectural rebuild roadmap |
| `CONTRIBUTING.md` | Dev guidelines | Contribution rules and workflow |
| `LICENSE` | Legal | MIT license |
| `.github/` | GitHub Actions | CI workflow definitions |
| `app/` | Python package | All application source code |
| `docs/` | Documentation | All audit docs, changelogs, architecture notes |
| `scripts/` | Utility scripts | Standalone operational/maintenance scripts |
| `tests/` | Test suite | All pytest tests |
| `utils/` | Utility library | Shared helpers not part of `app/` |
| `migrations/` | DB migrations | PostgreSQL schema evolution scripts |
| `backtests/` | Backtest results | Output data from offline backtest runs |
| `audit_reports/` | Audit output | Generated audit/report artefacts |

---

## File-by-File Documentation

---

### `app/__init__.py`

**Role:** Makes `app/` a Python package so all `app.*` imports resolve correctly.

**Contents:**
```python
"""
War Machine Application Package
"""

__all__ = []
```

**Key facts:**
- `__all__ = []` means `from app import *` imports nothing — this is intentional.
  All real imports are done explicitly at the sub-package level.
- No import-time side effects. Adding code here would run on **every** import of
  any `app.*` module, so it must stay clean.
- The only purpose of this file is the `__init__.py` existence itself, which
  makes `app/` a package. The docstring is informational only.

---

### `nixpacks.toml`

**Role:** Tells Railway's Nixpacks builder how to build the Docker image.

**Current contents:**
```toml
[phases.setup]
nixPkgs = ["python310", "python310Packages.pip", "postgresql", "gcc"]

[phases.install]
cmds = ["pip install -r requirements.txt --break-system-packages"]

[start]
cmd = "python -m app.core.scanner"

[variables]
NIXPACKS_PATH = ""
```

**Key facts:**
- **Python 3.10 is locked** — `python310`. Upgrading to 3.11/3.12 requires
  changing this and retesting all dependencies.
- **PostgreSQL is installed at the OS level** (`postgresql` nixPkg) — this
  provides the `libpq` native library required by `psycopg2-binary`. Without
  it the build fails.
- **`gcc` is required** by certain pip packages that build C extensions at
  install time (numpy, psycopg2).
- **`--break-system-packages`** is required because Nixpacks 2024+ creates
  a system Python environment; this flag allows pip to install into it.
  This flag was added after the 2026-03-16 rebuild triggered by `.railway_trigger`.
- **Entry point:** `python -m app.core.scanner` — the scanner is the main
  process. All other functionality is invoked by the scanner's internal
  scheduler or signal chain.
- **`NIXPACKS_PATH = ""`** — left blank intentionally. This prevents Nixpacks
  from auto-resolving a conflicting PATH that could override the nix-managed
  Python binary.

**Gotchas:**
- `nixpacks.toml` and `railway.toml` both define `startCommand`/`cmd`. Railway
  uses `railway.toml`'s `startCommand` if both are present. **They must stay
  in sync** or the deployed start command will silently differ from what
  `nixpacks.toml` specifies. (**Issue #50**)

---

### `railway.toml`

**Role:** Railway platform deployment configuration — overrides defaults for
build, deploy, health checks, and scheduled jobs.

**Current contents:**
```toml
[build]
builder = "NIXPACKS"

[deploy]
startCommand = "python -m app.core.scanner"
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10
healthcheckPath = "/health"
healthcheckTimeout = 30

# ML Confidence Booster - Weekly Retrain
[[cron]]
name = "ml-retrain"
schedule = "0 7 * * 0"  # Sunday 7 AM UTC (2 AM ET)
command = "python app/ml/train_ml_booster.py"
```

**Key facts:**
- **`restartPolicyType = "ON_FAILURE"`** — Railway restarts the container only
  on crash/exit with non-zero code, not on every deploy. This means a hung
  process (e.g. infinite loop, deadlock) will NOT restart automatically.
- **`restartPolicyMaxRetries = 10`** — after 10 consecutive crash-restarts,
  Railway stops restarting and marks the service as failed. Requires manual
  intervention to recover.
- **`healthcheckPath = "/health"`** — Railway calls `GET /health` on the
  container. If this endpoint returns non-200 or times out after 30 seconds,
  Railway marks the deploy as unhealthy. **`/health` must be implemented in
  `app/core/scanner.py` or a WSGI layer.** Confirm this endpoint exists.
  (**Issue #51**)
- **`healthcheckTimeout = 30`** — 30 seconds. If the app takes longer than
  30s to start and respond to `/health`, Railway will mark the deploy failed
  even on a healthy first boot. This is tight for cold starts on a large
  dependency set.
- **Cron: `ml-retrain`** — Runs `python app/ml/train_ml_booster.py` every
  Sunday at 07:00 UTC (02:00 ET). This is **separate from the main scanner
  process** — it spawns a new container just for the retrain.
  - `train_ml_booster.py` must be self-contained and exit with code 0 on success.
  - If the cron job fails, Railway logs the failure but does NOT alert by default.
  - No fallback or retry logic for the cron job. A missed Sunday retrain means
    the model runs on stale data until the following Sunday.

**Relationship to `nixpacks.toml`:**  
Both files define `startCommand = "python -m app.core.scanner"`. They are
currently in sync. Any change to the entry point must be updated in **both files**.

---

### `requirements.txt`

**Role:** Defines all runtime Python dependencies for the Railway environment.

**Current pinned dependencies:**

| Package | Version pin | Purpose |
|---|---|---|
| `requests` | `>=2.31.0` | HTTP calls to EODHD, Tradier, Unusual Whales APIs |
| `psycopg2-binary` | `>=2.9.9` | PostgreSQL driver (binary build = no libpq compile needed) |
| `pytz` | `>=2023.3` | Timezone handling for market hours |
| `backports.zoneinfo` | `>=0.2.1; python < 3.9` | Backport of `zoneinfo` stdlib module (redundant on 3.10+) |
| `pandas` | `>=1.5.0,<2.0.0` | DataFrame operations in backtesting, ML training |
| `numpy` | `>=1.24.0,<2.0.0` | Numerical computation — pinned `<2.0.0` due to API breaks |
| `scikit-learn` | `>=1.3.0,<2.0.0` | `RandomForestClassifier` in `MLSignalScorerV2` |
| `joblib` | `>=1.3.0` | Model serialisation (`.pkl` save/load) |
| `xgboost` | `>=2.0.0,<3.0.0` | XGBoost classifier (available in `MLSignalScorerV2` but RF is default) |
| `websockets` | `>=12.0` | WebSocket client for Tradier streaming feed |
| `sqlalchemy` | `>=2.0.0` | `pd.read_sql_query()` backend in `metrics_cache.py` |

**Key facts:**
- **`numpy<2.0.0` pin is critical** — numpy 2.x broke several API contracts
  used by pandas 1.x and scikit-learn 1.x. This pin was added on 2026-03-16
  during the Nixpacks rebuild (see `.railway_trigger`). Removing it would
  likely cause runtime errors in the ML and data processing pipeline.
- **`pandas<2.0.0`** — pandas 2.x introduced breaking changes to indexing
  and dtype inference. All DataFrame code was written against 1.x API.
- **`backports.zoneinfo` condition** — `python_version < '3.9'` makes this
  effectively dead code since the system runs Python 3.10. Safe to remove.
- **`xgboost` is installed but not the default model** — `MLSignalScorerV2`
  uses `RandomForestClassifier` by default. XGBoost adds ~50MB to the image
  for a feature that isn't active. Consider making it optional or removing
  until XGBoost becomes the active model.
- **No `flask` / `fastapi` / web framework** in requirements. The
  `healthcheckPath = "/health"` in `railway.toml` implies an HTTP endpoint —
  this must be served by some mechanism. If `scanner.py` uses a minimal HTTP
  server (e.g. `http.server` stdlib), it isn't declared here. (**Related to
  Issue #51**)
- **No `pytest` or test dependencies** — correct. Test deps should not be in
  the production requirements file. Developers must install them separately
  locally (`pip install pytest pytest-timeout`).

---

### `pytest.ini`

**Role:** Configures pytest for local and CI test runs.

**Key settings:**

| Setting | Value | Meaning |
|---|---|---|
| `testpaths` | `tests` | Only look in `tests/` for test files |
| `python_files` | `test_*.py` | Match files starting with `test_` |
| `python_classes` | `Test*` | Match classes starting with `Test` |
| `python_functions` | `test_*` | Match functions starting with `test_` |
| `addopts` | `--tb=short --strict-markers -q` | Short tracebacks, no unknown markers, quiet output |
| `timeout` | `60` | Kill any test hung for > 60 seconds |
| `minversion` | `7.0` | Requires pytest 7.0+ |

**Custom markers:**

| Marker | Use |
|---|---|
| `@pytest.mark.slow` | Long-running tests; skip with `-m "not slow"` |
| `@pytest.mark.integration` | Requires live DB or API keys; never run in CI |
| `@pytest.mark.unit` | Pure unit tests; no external dependencies |

**Key facts:**
- **`--strict-markers`** — any test using an unregistered `@pytest.mark.*`
  causes a hard failure. New markers must be added to `pytest.ini` before use.
- **`timeout = 60`** requires `pytest-timeout` to be installed. It is **not**
  in `requirements.txt` (correct — it's a dev-only dep). Developers must
  `pip install pytest-timeout` or the timeout setting is silently ignored.
- **`integration` marker tests will fail in CI** if they require `DATABASE_URL`,
  `TRADIER_API_KEY`, etc. These must never be run in the GitHub Actions
  workflow unless secrets are configured there.
- **No `conftest.py` referenced** here — any test fixtures must be in
  `tests/conftest.py` which pytest auto-discovers.

---

### `.railway_trigger`

**Role:** A dummy file touched to force Railway to perform a clean Nixpacks rebuild.

**Current contents:**
```
2026-03-16 11:32:00 - Force clean Nixpacks rebuild: numpy<2.0 pin + stdenv.cc.cc.lib
```

**Key facts:**
- Railway triggers a new build on **any file change** in the repo. By touching
  this file with a new timestamp/message, you force a full clean rebuild without
  changing any source code.
- The 2026-03-16 entry records the rebuild that pinned `numpy<2.0.0` and added
  `stdenv.cc.cc.lib` (the GCC standard library) to fix a compile-time failure
  in the Nixpacks environment.
- **Convention:** When a build-environment-only fix is needed, append a new
  timestamped line to this file rather than making a meaningless code change.
- This file is NOT read by any Python code. It is purely a Git-tracked
  build trigger mechanism.

---

### `.gitignore`

**Role:** Prevents secrets, compiled files, and local artefacts from being
committed to the repository.

**Key exclusion categories:**

| Category | Examples |
|---|---|
| Python compiled | `__pycache__/`, `*.py[cod]`, `*.so`, `*.egg` |
| Virtual environments | `venv/`, `.venv/`, `env/` |
| Secrets / env files | `.env`, `.env.*`, `*.key`, `secrets.json` |
| IDE / editor | `.vscode/`, `.idea/`, `*.swp` |
| OS artefacts | `.DS_Store`, `Thumbs.db` |
| Logs | `*.log`, `logs/` |
| Test artefacts | `.pytest_cache/`, `htmlcov/`, `.coverage` |
| Build artefacts | `dist/`, `build/`, `*.egg-info/` |
| ML model files | `*.pkl`, `*.joblib`, `*.h5` |
| Data files | `*.csv` (output data, not tracked) |

**Key facts:**
- **`*.pkl` and `*.joblib` are gitignored** — ML model files are never committed
  to the repo. On Railway, models are either retrained on deploy or loaded from
  a persistent volume / object storage. If no model file exists on first deploy,
  `MLSignalScorerV2` falls back to its rule-based confidence scoring.
- **`.env` is excluded** — all secrets must be set as Railway environment
  variables, never hardcoded or committed.
- **`*.csv` exclusion** — backtest result CSVs and training data exports are
  generated at runtime and not tracked. The `backtests/` and `audit_reports/`
  directories exist in the repo but their generated output is gitignored.

---

## Issues Found This Batch

### Issue #50 — LOW — Duplicate `startCommand` in `nixpacks.toml` and `railway.toml`

**Files:** `nixpacks.toml` (`[start] cmd`), `railway.toml` (`[deploy] startCommand`)  
**Symptom:** Both files define the same start command. If they ever diverge,
Railway silently uses `railway.toml`'s value, meaning `nixpacks.toml`'s `cmd`
is effectively dead. There is no warning.

**Current state:** Both are `python -m app.core.scanner` — currently in sync.  
**Risk:** Medium. Any developer editing the entry point could update only one
file, causing a silent mismatch.

**Fix required:** Add a comment in both files cross-referencing each other,
or remove `[start] cmd` from `nixpacks.toml` entirely and rely solely on
`railway.toml` `startCommand`.

**Status:** ⚠️ Open

---

### Issue #51 — MEDIUM — `/health` endpoint existence unverified

**File:** `railway.toml` → `healthcheckPath = "/health"`  
**Symptom:** Railway is configured to call `GET /health` to verify deploy
health. If this HTTP endpoint does not exist in `app/core/scanner.py` (or
a web layer it starts), **every deploy will time out at 30 seconds** and
be marked as failed, even if the scanner is running correctly.

**No HTTP framework is listed in `requirements.txt`**, which raises the
question of what is serving `/health`.

**Action required:**
1. Confirm `app/core/scanner.py` starts an HTTP server and registers `/health`
2. If it uses Python `http.server` stdlib, document this explicitly
3. Confirm the endpoint returns HTTP 200 within 30 seconds of process start
4. If `/health` is not implemented, either implement it or remove
   `healthcheckPath` from `railway.toml` to prevent false-failed deploys

**Status:** ⚠️ Open — needs investigation in `app/core/` audit (next batch)

---

## Key Architecture Facts for Root-Level Config

- **Single entry point:** The entire system boots from `python -m app.core.scanner`.
  Nothing else in the repo is a standalone server.
- **Railway is the only deployment target.** There is no `Dockerfile`,
  `docker-compose.yml`, or Heroku `Procfile`. The build is 100% Nixpacks.
- **Python 3.10 is locked** in `nixpacks.toml`. All code must be 3.10-compatible.
  No walrus operators in f-strings, no `match` statements beyond 3.10 support level.
- **ML models are ephemeral** on Railway unless a persistent volume is mounted.
  The weekly `ml-retrain` cron writes the model file, but if the deployment
  restarts or redeploys between Sundays, the model may be gone. This is a
  **persistence risk** not addressed by current configuration.
- **No staging environment** is defined in `railway.toml`. All deploys go
  directly to production. There is no `[environments.staging]` block.
- **Test suite is never run automatically on Railway** — `pytest.ini` exists
  only for local development. CI via GitHub Actions (`.github/`) is separate
  and not yet audited.
- **`backports.zoneinfo`** conditional dep is dead code on Python 3.10 — the
  `zoneinfo` module is built into 3.9+. Safe to remove from `requirements.txt`
  in a cleanup pass.

---

## Next Batch

`app/core/` — the scanner, scheduler, database connections, and the `/health`
endpoint that Issue #51 depends on.
