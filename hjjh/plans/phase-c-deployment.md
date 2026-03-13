# Phase C: Browser Terminal + Deployment

## Context

Phases A and B delivered backend abstractions and Fly.io backend code (FlyMachinesClient, FlyConfig, FlyHunterController, FlyWorktreeManager). All the Python logic for managing remote Hunter machines exists and is tested (84 tests, 2984 total passing). But there are **no deployment artifacts** — no Dockerfiles, no fly.toml, no entrypoint scripts, no deploy automation.

Phase C creates the infrastructure to actually run the two-machine system on Fly.io:
- **Overseer (Machine A)** — always-on, browser terminal via ttyd on :8080, OverseerLoop in background
- **Hunter (Machine B)** — ephemeral, created/destroyed by Overseer via Machines API

---

## Design Decisions

### Process supervisor: shell entrypoint, not Python

The original plan proposed `hunter/supervisor.py`. The job is trivial: start ttyd foreground + OverseerLoop background + signal trap. A shell script (`deploy/overseer-entrypoint.sh`) is simpler and more debuggable. No Python supervisor module needed.

### Machine config template (C8): not needed

`FlyConfig.to_machine_config()` already builds the complete Fly Machines API config dict from env vars and method arguments. No separate JSON template file required.

### Auth (C6): handled inline

The entrypoint script checks `AUTH_PASSWORD` env var and passes it to ttyd's `--credential` flag. No separate file or module needed.

### Persistent volume strategy

Set `HERMES_HOME=/data/hermes` in the Overseer Dockerfile. `get_hermes_home()` (`hermes_cli/config.py:34`) already respects this env var. All state (budget, spend ledger, logs, injections, session DB) lands on the persistent volume automatically. The hunter-repo clone path `/data/hunter-repo` is already hardcoded in the factory (`hunter/backends/__init__.py`).

### Health check

ttyd serves its web UI at `GET /` on :8080. Fly's default HTTP health check hits this — no custom health endpoint needed.

### Hunter boot: clone at runtime, not baked into image

The Hunter Docker image does NOT include the hermes-prime source. The entrypoint clones the hunter-live repo at boot using `HUNTER_REPO` + `GITHUB_PAT` env vars, then `pip install`s it. This means every Hunter machine gets the latest Overseer-written code without rebuilding the image.

---

## Bugs Found During Planning

1. **`hunter.backends` missing from pyproject.toml packaging.** Line 82 includes `"hunter"` and `"hunter.tools"` but not `"hunter.backends"`. `pip install` would skip all Fly backend code.

2. **`GITHUB_PAT` not passed to Hunter machine.** `FlyConfig.to_machine_config()` (`fly_config.py:98-108`) sets `HUNTER_REPO` but not `GITHUB_PAT`. The Hunter entrypoint needs it to clone the repo.

---

## Implementation Tasks

### C0: Packaging Fix

**Goal:** Ensure `pip install` includes the backends subpackage.

**Modify:** `pyproject.toml` line 82 — add `"hunter.backends"` and `"hunter.prompts"` to `include`.

**Verify:** `pip install -e . && python -c "from hunter.backends.fly_config import FlyConfig"`

---

### C1: Fix GITHUB_PAT in Machine Config

**Goal:** Hunter machines can clone the repo at boot.

**Modify:** `hunter/backends/fly_config.py` — add `"GITHUB_PAT": self.github_pat` to the env dict in `to_machine_config()` (after line 103).

**Modify:** `tests/test_fly_config.py` — update `test_to_machine_config_*` assertions to verify `GITHUB_PAT` is present.

---

### C2: Overseer Entrypoint Script

**Goal:** Single script that runs both ttyd and OverseerLoop with graceful shutdown.

**Create:** `deploy/overseer-entrypoint.sh`

Responsibilities:
- Create state directories on the persistent volume (`/data/hermes/hunter/{logs,injections}`, `/data/hunter-repo`)
- Set git config (`user.name`, `user.email`) for commit operations
- Start `hermes hunter overseer --interval $OVERSEER_INTERVAL` in background
- Trap SIGTERM/SIGINT, forward to background process
- Start ttyd in foreground on :8080 with optional `--credential hermes:$AUTH_PASSWORD`
- Use `exec` for ttyd so it becomes PID 1 (Fly signals propagate correctly)

---

### C3: Hunter Entrypoint Script

**Goal:** Boot sequence that clones repo, installs deps, runs the Hunter agent.

**Create:** `deploy/hunter-entrypoint.sh`

Responsibilities:
- Validate required env vars (`SESSION_ID`, `HUNTER_REPO`, `OPENROUTER_API_KEY`)
- Clone `https://$GITHUB_PAT@github.com/$HUNTER_REPO.git` into `/workspace/repo`
- `pip install -e ".[hunter]"` in the clone
- Translate env vars to CLI args (`HUNTER_MODEL` → `--model`, `SESSION_ID` → `--session-id`, etc.)
- `exec python -m hunter.runner $ARGS` for signal propagation
- Machine self-destructs on exit (`auto_destroy: True` in machine config)

---

### C4: Overseer Dockerfile

**Goal:** Production container image for the Overseer machine.

**Create:** `deploy/Dockerfile.overseer`

Layers (ordered for cache efficiency):
1. `python:3.11-slim` base
2. System deps: `git`, `curl`, `ca-certificates` via apt
3. ttyd binary from GitHub releases (architecture-aware via `dpkg --print-architecture`)
4. Copy `pyproject.toml` first, install Python deps (cache layer)
5. Copy full source, `pip install -e ".[hunter]"`
6. `ENV HERMES_HOME=/data/hermes`
7. Global git config (`user.name "Hermes Overseer"`, `user.email "overseer@hermes-prime"`)
8. Copy entrypoint script
9. `EXPOSE 8080`, `CMD ["/usr/local/bin/entrypoint.sh"]`

---

### C5: Hunter Dockerfile

**Goal:** Pre-built base image for Hunter machines. Source comes from git clone at boot.

**Create:** `deploy/Dockerfile.hunter`

Layers:
1. `python:3.11-slim` base
2. System deps: `git`, `curl`, `ca-certificates` via apt
3. Node.js 20.x (for JS-based security tools/targets)
4. Semgrep via pip
5. Global git config
6. Copy entrypoint script only (no source code — cloned at boot)
7. `WORKDIR /workspace`, `CMD ["/usr/local/bin/entrypoint.sh"]`

---

### C6: Overseer fly.toml

**Goal:** Fly.io app config for the always-on Overseer.

**Create:** `deploy/fly.overseer.toml`

Key settings:
- `app = "hermes-prime-overseer"` (placeholder — user sets via `--app` or edits)
- HTTP service on internal port 8080, force HTTPS
- `auto_stop_machines = "off"`, `min_machines_running = 1` (always-on)
- Mount: `overseer_data` volume at `/data`
- VM: `shared-cpu-2x`, 1024MB

Secrets to set via `fly secrets set`:
- `FLY_API_TOKEN`, `HUNTER_FLY_APP`, `GITHUB_PAT`, `HUNTER_REPO`
- `HUNTER_FLY_IMAGE`, `ELEPHANTASM_API_KEY`, `OPENROUTER_API_KEY`
- `AUTH_PASSWORD`

---

### C7: Hunter fly.toml

**Goal:** Fly.io app config for the Hunter. Used only to build and push the Docker image to Fly's registry.

**Create:** `deploy/fly.hunter.toml`

Key settings:
- `app = "hermes-prime-hunter"` (placeholder)
- No `[http_service]` — Hunter has no public endpoints
- No `[mounts]` — Hunter is ephemeral
- VM: `shared-cpu-2x`, 2048MB
- Actual machine creation happens via Machines API (FlyHunterController), not `fly deploy`

---

### C8: Deploy Script

**Goal:** One-command Fly.io deployment.

**Create:** `scripts/deploy-overseer.sh`

Steps:
1. Check prerequisites (`fly` CLI installed and authenticated)
2. Create Fly apps (`hermes-prime-overseer`, `hermes-prime-hunter`) if they don't exist
3. Create persistent volume `overseer_data` for Overseer
4. Build and push Hunter image to Fly registry via `fly deploy --build-only --push`
5. Set `HUNTER_FLY_IMAGE` secret on Overseer to the registry URL
6. Deploy Overseer via `fly deploy`
7. Print the URL

---

## Task Dependencies

```
C0 (pyproject.toml fix)
 |
 +-- C1 (GITHUB_PAT fix + tests)
 |
 +-- C2 (overseer entrypoint) --+
 |                               +-- C4 (overseer Dockerfile) -- C6 (overseer fly.toml) --+
 +-- C3 (hunter entrypoint) --+  |                                                         |
 |                             +-- C5 (hunter Dockerfile) -- C7 (hunter fly.toml) ---------+
 |                                                                                          |
 +-------------------------------------------------------------------------------------- C8 (deploy script)
```

Parallel opportunities: C2+C3, C4+C5, C6+C7.

---

## Files Summary

| Task | File | Action | Purpose |
|------|------|--------|---------|
| C0 | `pyproject.toml` | Modify | Add `hunter.backends` to packages |
| C1 | `hunter/backends/fly_config.py` | Modify | Add GITHUB_PAT to machine env |
| C1 | `tests/test_fly_config.py` | Modify | Update assertions |
| C2 | `deploy/overseer-entrypoint.sh` | Create | ttyd + OverseerLoop supervisor |
| C3 | `deploy/hunter-entrypoint.sh` | Create | Clone + install + run |
| C4 | `deploy/Dockerfile.overseer` | Create | Overseer container image |
| C5 | `deploy/Dockerfile.hunter` | Create | Hunter container image |
| C6 | `deploy/fly.overseer.toml` | Create | Fly config for Overseer |
| C7 | `deploy/fly.hunter.toml` | Create | Fly config for Hunter |
| C8 | `scripts/deploy-overseer.sh` | Create | One-command deployment |

---

## Verification

1. **Unit tests pass:** `python -m pytest tests/test_fly_config.py -q` (C1 updates)
2. **All hunter tests pass:** `python -m pytest tests/test_hunter_*.py tests/test_fly_*.py -q`
3. **Packaging works:** `pip install -e ".[hunter]" && python -c "from hunter.backends.fly_control import FlyHunterController"`
4. **Docker builds:** `docker build -f deploy/Dockerfile.overseer .` and `docker build -f deploy/Dockerfile.hunter .`
5. **Script syntax:** `bash -n deploy/overseer-entrypoint.sh && bash -n deploy/hunter-entrypoint.sh && bash -n scripts/deploy-overseer.sh`
