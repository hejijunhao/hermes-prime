#!/usr/bin/env bash
set -euo pipefail

# Hunter entrypoint: clones repo, installs deps, runs the Hunter agent.
# The machine self-destructs on exit (auto_destroy: true in machine config).

# --- Validate required env vars ---
for var in SESSION_ID HUNTER_REPO OPENROUTER_API_KEY; do
    if [ -z "${!var:-}" ]; then
        echo "[hunter-entrypoint] ERROR: Missing required env var: $var" >&2
        exit 1
    fi
done

# --- Clone the repo ---
CLONE_DIR="/workspace/repo"
if [ -n "${GITHUB_PAT:-}" ]; then
    REPO_URL="https://${GITHUB_PAT}@github.com/${HUNTER_REPO}.git"
else
    REPO_URL="https://github.com/${HUNTER_REPO}.git"
fi

echo "[hunter-entrypoint] Cloning ${HUNTER_REPO}..."
git clone --depth 1 "$REPO_URL" "$CLONE_DIR"

if [ ! -d "$CLONE_DIR/.git" ]; then
    echo "[hunter-entrypoint] ERROR: Clone failed — $CLONE_DIR/.git not found" >&2
    exit 1
fi

cd "$CLONE_DIR"

# --- Install ---
echo "[hunter-entrypoint] Installing dependencies..."
pip install -e ".[hunter]" --quiet

# --- Build CLI args ---
ARGS=()
if [ -n "${HUNTER_MODEL:-}" ]; then
    ARGS+=("--model" "$HUNTER_MODEL")
fi
ARGS+=("--session-id" "$SESSION_ID")
if [ -n "${HUNTER_INSTRUCTION:-}" ]; then
    ARGS+=("--instruction" "$HUNTER_INSTRUCTION")
fi
if [ "${HUNTER_RESUME:-}" = "1" ]; then
    ARGS+=("--resume")
fi

# --- Run (exec for signal propagation) ---
echo "[hunter-entrypoint] Starting Hunter agent..."
exec python -m hunter.runner "${ARGS[@]}"
