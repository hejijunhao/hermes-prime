# Fly App Setup + GitHub App Auth — Completion Report

## Goal

Create the Fly.io apps for Hermes Prime, replace static GitHub PAT authentication with GitHub App token exchange (auto-rotating), and add environment variable support for Elephantasm anima IDs. Prepare all deployment secrets.

**Result:** 2 Fly apps created, 1 new module (`github_auth.py`), 6 files modified, all 131 affected tests pass (zero regressions). GitHub App tokens auto-rotate every ~55 minutes with no human intervention.

---

## Fly.io Apps Created

Both apps created under the **Crimson Sun Technologies** org (`crimson-sun-technologies`):

| App | Purpose |
|-----|---------|
| `hermes-prime` | Overseer — persistent, long-running meta-agent |
| `hermes-prime-hunter` | Hunter — ephemeral worker machines, spun up/destroyed by Overseer |

A deploy token was generated scoped to `hermes-prime-hunter` only.

---

## GitHub App Auth (replaces GITHUB_PAT)

### Why

A static Personal Access Token (PAT) has drawbacks for an autonomous agent:
- Expires (max 1 year), requires manual rotation
- Tied to a personal account
- If leaked, grants persistent access until manually revoked

A GitHub App generates short-lived tokens (1 hour) that auto-rotate. If the private key leaks, tokens can only access the repos where the app is installed.

### GitHub App Setup

- **App name:** `hermes-prime-overseer`
- **Owner:** `kaminocorp`
- **Permissions:** Contents (R/W), Metadata (R) — nothing else
- **Installed on:** `kaminocorp/hermes-prime-hunter` only
- **App ID:** `3095054`
- **Installation ID:** `116464228`

### New File: `hunter/backends/github_auth.py`

`GitHubAppAuth` class that handles the full token lifecycle:
1. Signs a JWT with the app's RSA private key (valid 10 min)
2. Exchanges JWT for an installation access token via GitHub API
3. Caches the token in memory, refreshes 5 minutes before expiry
4. Thread-safe for concurrent access

**Env vars:** `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY`, `GITHUB_APP_INSTALLATION_ID`

### Modified: `hunter/backends/fly_config.py`

- Replaced `github_pat: str` field with `github_auth: GitHubAppAuth`
- `from_env()` now calls `GitHubAppAuth.from_env()` instead of reading `GITHUB_PAT`
- `to_machine_config()` calls `github_auth.get_token()` to generate a fresh token for each Hunter machine (passed as `GITHUB_PAT` env var — the Hunter doesn't need to know it came from a GitHub App)
- Removed `GITHUB_PAT` from `_REQUIRED_VARS`

### Modified: `hunter/backends/fly_worktree.py`

- Constructor takes `github_auth: GitHubAppAuth` instead of `github_pat: str`
- `_authenticated_url()` generates a fresh HTTPS URL with `x-access-token:{token}@github.com` on each call
- `_update_remote_url()` updates the git remote before pull/push (handles token rotation mid-session)
- `_safe_url()` redacts credentials without needing to store the raw token
- `setup()` calls `_update_remote_url()` before pulling (existing clones get fresh tokens)
- `push()` calls `_update_remote_url()` before pushing

### Modified: `hunter/backends/__init__.py`

- Passes `github_auth=config.github_auth` to `FlyWorktreeManager` instead of `github_pat`

### Unchanged: `deploy/hunter-entrypoint.sh`

The Hunter entrypoint still reads `GITHUB_PAT` as an env var. The Overseer generates a fresh installation token and passes it as `GITHUB_PAT` to each ephemeral Hunter machine. Since Hunter machines are short-lived (< 1hr typically), the 1-hour token lifetime is sufficient.

---

## Elephantasm Anima ID Env Var Support

### Why

Anima IDs were previously only stored in a local JSON cache (`~/.hermes/hunter/animas.json`). While the cache lives on the persistent volume and survives redeployments, having env var support is cleaner for deployment configuration and allows pre-seeding a known anima ID.

### Modified: `hunter/config.py`

Added env var constants and a name-to-env mapping:
- `OVERSEER_ANIMA_ID_ENV = "OVERSEER_ANIMA_ID"`
- `HUNTER_ANIMA_ID_ENV = "HUNTER_ANIMA_ID"`
- `_ANIMA_ENV_MAP` maps anima names to env var names

### Modified: `hunter/memory.py`

- `get_anima_id()` resolution order: env var -> local JSON cache
- `ensure_animas()` merges env var overrides into the cached map before checking if all animas are resolved

---

## Secrets Summary

All secrets are configured in `.env` for local development and will be set as Fly secrets for deployment:

| Secret | Purpose | Source |
|--------|---------|--------|
| `FLY_API_TOKEN` | Fly Machines API (Hunter app only) | `fly tokens create deploy` |
| `HUNTER_FLY_APP` | Hunter app name | `hermes-prime-hunter` |
| `HUNTER_REPO` | GitHub repo for Hunter code | `kaminocorp/hermes-prime-hunter` |
| `GITHUB_APP_ID` | GitHub App numeric ID | GitHub App settings |
| `GITHUB_APP_PRIVATE_KEY` | PEM-encoded RSA key | GitHub App settings |
| `GITHUB_APP_INSTALLATION_ID` | Installation ID | GitHub App installation URL |
| `ELEPHANTASM_API_KEY` | Elephantasm API key | Elephantasm dashboard |
| `OVERSEER_ANIMA_ID` | Pre-seeded anima ID | `5473d419-2c06-4f48-b4bb-104cb97bf5cb` |
| `OPENROUTER_API_KEY` | LLM API access | OpenRouter dashboard |
| `AUTH_PASSWORD` | ttyd browser terminal login | Generated via `openssl rand` |

---

## Test Changes

All 4 test files updated to use mock `GitHubAppAuth` instead of string PAT:

- `tests/test_fly_config.py` — mock `GitHubAppAuth.from_env()` in env-loading tests, use `_mock_github_auth()` helper for direct construction
- `tests/test_fly_worktree.py` — pass mock auth to constructor, updated URL assertions
- `tests/test_fly_control.py` — replaced `github_pat="ghp_test"` with `MagicMock` auth
- `tests/test_hunter_backends.py` — same pattern for factory tests
- `tests/test_hunter_memory.py` — added `_clean_anima_env` autouse fixture to prevent env var leakage from `.env` loading during full suite runs

**Result:** 131/131 tests pass across all modified files.

---

## Next Steps

1. Set Fly secrets (`fly secrets set --app hermes-prime ...`)
2. Run `./scripts/deploy-overseer.sh` to deploy
3. Connect at `https://hermes-prime.fly.dev`
