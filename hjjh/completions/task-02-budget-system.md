# Task 2: Budget System — Completion Notes

**Status:** Complete
**Date:** 2026-03-11

---

## What Was Done

Implemented `hunter/budget.py` — the full budget management system with config loading, spend tracking, enforcement, and CLI parsing.

---

## File Modified

### `hunter/budget.py` (replaced stub)

**~300 lines.** Contains:

### Classes

| Class | Purpose |
|-------|---------|
| `BudgetManager` | Main class — loads config, tracks spend, enforces limits |
| `BudgetStatus` | Dataclass snapshot of current budget state |
| `SpendEntry` | Dataclass for a single spend ledger row |

### BudgetManager Methods

| Method | Purpose |
|--------|---------|
| `__init__(config_path, ledger_path)` | Loads config + replays ledger to rebuild totals |
| `reload() → bool` | Check mtime, re-parse YAML if changed. Safe to call every loop iteration |
| `record_spend(cost_usd, model, input_tokens, output_tokens, agent)` | Append to JSONL ledger + update in-memory totals |
| `check_budget() → BudgetStatus` | Main enforcement check — returns allowed/alert/hard_stop |
| `estimate_cost(model, input_tokens, output_tokens) → float` | Predict cost using configured model rates |
| `create_default_config() → bool` | Write default `budget.yaml` if missing |
| `update_config(**kwargs)` | Modify specific config values and persist to disk |
| `get_spend_history(limit) → List[dict]` | Recent ledger entries (most recent first) |
| `get_daily_summary() → Dict[str, float]` | Spend per day from the ledger |

### Standalone Function

| Function | Purpose |
|----------|---------|
| `parse_budget_string(value) → dict` | Parse CLI input like `"20/day"`, `"300/5days"`, `"15"` into config kwargs |

### BudgetStatus Fields

| Field | Type | Description |
|-------|------|-------------|
| `allowed` | bool | Can we keep spending? |
| `remaining_usd` | float | Budget left |
| `percent_used` | float | 0.0 - 100.0 |
| `alert` | bool | Past alert threshold (default 80%)? |
| `hard_stop` | bool | Past hard stop threshold (default 100%)? |
| `mode` | str | "daily" or "total" |
| `spend_today` | float | USD spent today (UTC) |
| `spend_total` | float | USD spent all-time |
| `daily_limit` | float? | Set in daily mode |
| `total_limit` | float? | Set in total mode |
| `daily_rate_limit` | float? | In total mode: max_total / min_days |

---

## How It Works

### Config Watching

The Overseer calls `mgr.reload()` each loop iteration. `reload()`:
1. Checks `budget.yaml` mtime — if unchanged, returns `False` (no I/O)
2. If changed, re-parses the YAML
3. Rebuilds spend totals (handles day rollover)

This means the human can `vim ~/.hermes/hunter/budget.yaml` at any time and the Overseer picks up changes within seconds.

### Spend Tracking

Spend is recorded in an **append-only JSONL file** (`~/.hermes/hunter/spend.jsonl`). Each line:
```json
{"timestamp": "2026-03-11T14:23:01+00:00", "model": "qwen/qwen3.5-32b", "input_tokens": 4500, "output_tokens": 800, "cost_usd": 0.003, "agent": "hunter"}
```

On startup, `BudgetManager` replays the ledger to rebuild `_spend_today` and `_spend_total`. Daily spend resets at UTC midnight (detected by comparing `_today_utc` date string).

### Budget Modes

**Daily mode** (`mode: "daily"`):
- Tracks spend per UTC calendar day against `max_per_day`
- Alert at `alert_at_percent` (default 80%), hard stop at `hard_stop_at_percent` (default 100%)

**Total mode** (`mode: "total"`):
- Tracks all-time spend against `max_total`
- Also enforces a daily rate limit: `max_total / min_days`
- Whichever limit is hit first triggers alert/hard_stop

### parse_budget_string

Parses CLI shorthand:
- `"20/day"` or `"20/d"` → `{"mode": "daily", "max_per_day": 20.0}`
- `"300/5days"` or `"300/5d"` → `{"mode": "total", "max_total": 300.0, "min_days": 5}`
- `"15"` → `{"mode": "daily", "max_per_day": 15.0}`

---

## Design Decisions

### Why JSONL ledger instead of SQLite?

1. **Append-only is crash-safe.** No transactions, no WAL, no corruption. If the process dies mid-write, worst case is one truncated line that's skipped on replay.
2. **Human-readable.** `cat spend.jsonl | jq .` works. SQLite requires tooling.
3. **Simple.** No schema migrations, no connection management.
4. **The ledger is small.** Even at one entry per API call, months of operation produce a file under 1MB.

### Why mtime-based config watching instead of inotify/fswatch?

Cross-platform simplicity. `stat().st_mtime` works on macOS, Linux, and Windows. `inotify` is Linux-only and adds a dependency. The Overseer checks every 30 seconds, so mtime polling has negligible overhead.

### Why UTC midnight for daily reset?

Deterministic regardless of timezone. The human can be in any timezone; the budget resets at the same absolute time. This avoids edge cases where a timezone change mid-day could double-count or miss spend.

---

## Tests Run (9/9 passed)

| # | Test | What It Verifies |
|---|------|-----------------|
| 1 | Default config creation | `create_default_config()` writes YAML, is idempotent |
| 2 | Daily budget enforcement | Correct percent_used, alert, hard_stop at various spend levels |
| 3 | Total budget mode | Total limit + daily rate limit enforcement |
| 4 | Config reload on change | `reload()` detects mtime change, picks up new values |
| 5 | Spend ledger persistence | New BudgetManager rebuilds totals from existing ledger |
| 6 | Spend history | `get_spend_history()` returns entries in reverse chronological order |
| 7 | Cost estimation | `estimate_cost()` uses model_costs config correctly |
| 8 | parse_budget_string | All formats parse correctly, invalid input raises ValueError |
| 9 | Daily summary | `get_daily_summary()` aggregates by date |

---

## What's Next

The budget system is consumed by:
- **Task 6** (process tools): `hunter_spawn` checks budget before spawning
- **Task 9** (budget tools): `budget_status` tool wraps `check_budget()`
- **Task 10** (Overseer loop): calls `reload()` + `check_budget()` each iteration
- **Task 12** (CLI): `hermes hunter budget set 20/day` uses `parse_budget_string()` + `update_config()`
