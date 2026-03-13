# Phase C: Browser Terminal + Deployment — Completion Report

## Goal

Create all deployment infrastructure to run the two-machine Hermes Prime system on Fly.io: Overseer (Machine A) with browser terminal via ttyd, and Hunter (Machine B) as an ephemeral machine created/destroyed by the Overseer via the Machines API. Fix two bugs discovered during planning.

**Result:** 10 files created or modified across 9 tasks (C0–C8). Two bugs fixed (packaging, missing env var). Two Dockerfiles, two entrypoint scripts, two fly.toml configs, and one deploy script. All 415 hunter/fly tests pass (zero regressions). 13 pre-existing failures in `test_hunter_memory.py` are unrelated (elephantasm `EventType` import issue).

---

## Bugs Fixed

### C0: Packaging Fix

**Problem:** `hunter.backends` and `hunter.prompts` missing from `pyproject.toml` `[tool.setuptools.packages.find].include`. `pip install` would skip all Fly backend code and prompt files.

**Fix:** `pyproject.toml` line 82 — added `"hunter.backends"` and `"hunter.prompts"` to `include`.

**Before:**
```
include = ["tools", "hermes_cli", "gateway", "cron", "honcho_integration", "hunter", "hunter.tools"]
```

**After:**
```
include = ["tools", "hermes_cli", "gateway", "cron", "honcho_integration", "hunter", "hunter.tools", "hunter.backends", "hunter.prompts"]
```

**Verified:** `pip install -e ".[hunter]" && python -c "from hunter.backends.fly_control import FlyHunterController"` succeeds.

---

### C1: GITHUB_PAT Missing from Machine Config

**Problem:** `FlyConfig.to_machine_config()` set `HUNTER_REPO` in the Hunter machine's env but not `GITHUB_PAT`. The Hunter entrypoint needs it to clone the private repo at boot.

**Fix:** `hunter/backends/fly_config.py` line 104 — added `"GITHUB_PAT": self.github_pat` to the env dict.

**Test update:** `tests/test_fly_config.py` — `test_env_vars_set` now asserts both `GITHUB_PAT` and `HUNTER_REPO` are present in the machine config env.

---

## Deployment Artifacts

### C2: Overseer Entrypoint Script

**File created:** `deploy/overseer-entrypoint.sh` (37 lines)

Single shell script that runs both ttyd and OverseerLoop with graceful shutdown:

| Responsibility | Implementation |
|----------------|----------------|
| State directories | `mkdir -p /data/hermes/hunter/{logs,injections}` + `/data/hunter-repo` |
| Git config | Global `user.name` / `user.email` for commit operations |
| OverseerLoop | `hermes hunter overseer --interval $OVERSEER_INTERVAL` in background (default 300s) |
| Signal handling | `trap cleanup SIGTERM SIGINT` — kills background OverseerLoop, waits, exits clean |
| ttyd | Foreground on `:8080` via `exec` (becomes PID 1 for Fly signal propagation) |
| Auth | Optional `--credential hermes:$AUTH_PASSWORD` when `AUTH_PASSWORD` is set |

**Design decision:** Shell script, not Python supervisor. The job is trivial (start two processes, trap signals) and a shell script is simpler and more debuggable than a Python supervisor module.

---

### C3: Hunter Entrypoint Script

**File created:** `deploy/hunter-entrypoint.sh` (47 lines)

Boot sequence that clones the repo, installs deps, and runs the Hunter agent:

| Step | Detail |
|------|--------|
| Env validation | Fails fast if `SESSION_ID`, `HUNTER_REPO`, or `OPENROUTER_API_KEY` are missing |
| Clone | `git clone --depth 1` into `/workspace/repo` with authenticated URL when `GITHUB_PAT` is set |
| Install | `pip install -e ".[hunter]" --quiet` in the clone |
| CLI args | Translates env vars to CLI flags: `HUNTER_MODEL` → `--model`, `SESSION_ID` → `--session-id`, `HUNTER_INSTRUCTION` → `--instruction`, `HUNTER_RESUME=1` → `--resume` |
| Run | `exec python -m hunter.runner $ARGS` for signal propagation |
| Self-destruct | Machine has `auto_destroy: True` in its Fly config — exits on completion |

**Design decision:** Source is NOT baked into the image. Every Hunter machine gets the latest Overseer-written code without rebuilding the Docker image.

---

### C4: Overseer Dockerfile

**File created:** `deploy/Dockerfile.overseer` (35 lines)

Layers ordered for Docker cache efficiency:

1. `python:3.11-slim` base
2. System deps: `git`, `curl`, `ca-certificates`
3. ttyd 1.7.7 binary from GitHub releases (architecture-aware via `dpkg --print-architecture`)
4. `pyproject.toml` copy → `pip install -e ".[hunter]"` (deps-only cache layer, allowed to fail since source isn't present yet)
5. Full source copy → `pip install -e ".[hunter]"` (final install with source)
6. `ENV HERMES_HOME=/data/hermes` — all state lands on the persistent volume via `get_hermes_home()`
7. Global git config (`Hermes Overseer` / `overseer@hermes-prime`)
8. Entrypoint script copy + `chmod +x`
9. `EXPOSE 8080`, `CMD ["/usr/local/bin/entrypoint.sh"]`

---

### C5: Hunter Dockerfile

**File created:** `deploy/Dockerfile.hunter` (25 lines)

Pre-built base image — source comes from git clone at boot:

1. `python:3.11-slim` base
2. System deps: `git`, `curl`, `ca-certificates`
3. Node.js 20.x via NodeSource (for JS-based security tools/targets)
4. Semgrep via pip
5. Global git config (`Hermes Hunter` / `hunter@hermes-prime`)
6. Entrypoint script copy only (no source code)
7. `WORKDIR /workspace`, `CMD ["/usr/local/bin/entrypoint.sh"]`

---

### C6: Overseer fly.toml

**File created:** `deploy/fly.overseer.toml` (20 lines)

| Setting | Value | Rationale |
|---------|-------|-----------|
| `app` | `hermes-prime-overseer` | Placeholder — user edits or uses `--app` |
| `primary_region` | `sjc` | Default; user can change |
| HTTP service | Internal port 8080, force HTTPS | ttyd web UI |
| `auto_stop_machines` | `"off"` | Overseer must be always-on |
| `min_machines_running` | `1` | Always-on |
| Mount | `overseer_data` → `/data` | Persistent volume for all state |
| VM | `shared-cpu-2x`, 1024MB | Sufficient for Overseer + ttyd |

Secrets to set via `fly secrets set`: `FLY_API_TOKEN`, `HUNTER_FLY_APP`, `GITHUB_PAT`, `HUNTER_REPO`, `HUNTER_FLY_IMAGE`, `ELEPHANTASM_API_KEY`, `OPENROUTER_API_KEY`, `AUTH_PASSWORD`.

---

### C7: Hunter fly.toml

**File created:** `deploy/fly.hunter.toml` (14 lines)

| Setting | Value | Rationale |
|---------|-------|-----------|
| `app` | `hermes-prime-hunter` | Placeholder |
| `primary_region` | `sjc` | Default |
| No `[http_service]` | — | Hunter has no public endpoints |
| No `[mounts]` | — | Hunter is ephemeral |
| VM | `shared-cpu-2x`, 2048MB | Needs more RAM for security tools + LLM calls |

This config is used **only** to build and push the Docker image to Fly's registry. Actual machine creation happens via the Machines API (`FlyHunterController`), not `fly deploy`.

---

### C8: Deploy Script

**File created:** `scripts/deploy-overseer.sh` (90 lines)

One-command Fly.io deployment:

| Step | Command |
|------|---------|
| Prerequisites | Checks `fly` CLI installed and authenticated |
| Create apps | `fly apps create` for both Overseer and Hunter (idempotent) |
| Create volume | `fly volumes create overseer_data` — 10GB, `sjc` region (idempotent) |
| Build Hunter | `fly deploy --build-only --push` using `deploy/fly.hunter.toml` |
| Set image secret | `fly secrets set HUNTER_FLY_IMAGE=registry.fly.io/hermes-prime-hunter:latest` on Overseer |
| Deploy Overseer | `fly deploy` using `deploy/fly.overseer.toml` |
| Print URL | Shows Overseer URL + reminder of secrets to set |

---

## Design Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Process supervisor | Shell entrypoint, not Python | Trivial job (two processes + signal trap); simpler and more debuggable |
| Machine config template (C8 from plan) | Not needed | `FlyConfig.to_machine_config()` already builds the complete config dict |
| Auth | Inline in entrypoint | `AUTH_PASSWORD` env var → ttyd `--credential` flag; no separate module |
| Persistent volume | `HERMES_HOME=/data/hermes` | `get_hermes_home()` already respects this env var; all state lands on volume |
| Health check | Default HTTP | ttyd serves web UI at `GET /` on :8080; Fly's default HTTP check hits this |
| Hunter boot | Clone at runtime | Latest Overseer-written code without image rebuilds |

---

## Files Summary

| Task | File | Action | Lines | Purpose |
|------|------|--------|-------|---------|
| C0 | `pyproject.toml` | Modified | 1 line | Added `hunter.backends`, `hunter.prompts` to packages |
| C1 | `hunter/backends/fly_config.py` | Modified | +1 line | Added `GITHUB_PAT` to machine env |
| C1 | `tests/test_fly_config.py` | Modified | +2 lines | Assert `GITHUB_PAT` and `HUNTER_REPO` in env |
| C2 | `deploy/overseer-entrypoint.sh` | **Created** | 37 | ttyd + OverseerLoop + signal handling |
| C3 | `deploy/hunter-entrypoint.sh` | **Created** | 47 | Clone + install + run |
| C4 | `deploy/Dockerfile.overseer` | **Created** | 35 | Overseer container image |
| C5 | `deploy/Dockerfile.hunter` | **Created** | 25 | Hunter container image |
| C6 | `deploy/fly.overseer.toml` | **Created** | 20 | Fly config for always-on Overseer |
| C7 | `deploy/fly.hunter.toml` | **Created** | 14 | Fly config for Hunter image builds |
| C8 | `scripts/deploy-overseer.sh` | **Created** | 90 | One-command deployment |

---

## Verification

1. **All hunter/fly tests pass:** `python -m pytest tests/test_hunter_*.py tests/test_fly_*.py -q` → 415 passed, zero regressions
2. **Packaging works:** `pip install -e ".[hunter]" && python -c "from hunter.backends.fly_control import FlyHunterController"` → success
3. **Script syntax valid:** `bash -n deploy/overseer-entrypoint.sh && bash -n deploy/hunter-entrypoint.sh && bash -n scripts/deploy-overseer.sh` → all pass
4. **Docker builds:** Deferred until deployment — requires Docker daemon and network access
5. **Live deployment:** Deferred until Fly.io apps are provisioned and secrets are set

## Pre-existing Issues (Not Phase C)

13 test failures in `tests/test_hunter_memory.py` — `AttributeError: 'NoneType' object has no attribute 'SYSTEM'` / `'TOOL_CALL'`. The `elephantasm` package's `EventType` enum is returning `None`. These failures reproduce identically on the pre-Phase-C `main` branch and are unrelated to this phase's changes.
