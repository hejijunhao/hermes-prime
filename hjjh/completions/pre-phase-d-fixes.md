# Pre-Phase-D Hardening Fixes

Post-Phase-C review identified four functional gaps in the Fly backend that should be addressed before moving to Phase D (Bootstrap Mode). All four are hardening issues — not architectural — and affect production reliability of the two-machine system.

**Result:** 4 fixes applied, 10 new tests added (438 total, zero regressions).

---

## Fix 1: Retry Logic in FlyMachinesClient

**Problem:** `_request()` failed immediately on transient errors (5xx, 429, timeouts). A single network hiccup during `create_machine()` or `wait_for_state()` would crash the spawn flow.

**File modified:** `hunter/backends/fly_api.py`

**Change:** Added exponential backoff retry loop to `_request()`:
- Retries up to 3 times on transient errors (502, 503, 504, 429, timeouts)
- Backoff delays: 1s, 2s, 4s (`2^attempt`)
- Non-retryable errors (4xx except 429) fail immediately — no wasted time
- New `_backoff()` static method handles sleep + warning log
- New module-level `_RETRYABLE_STATUS_CODES = {502, 503, 504, 429}`

**Why:** The Overseer loop runs indefinitely. Transient Fly API errors are expected over days/weeks. Without retries, the Overseer would need external logic to recover from a single 503.

**Tests added:** `tests/test_fly_api.py` — 5 new tests in `TestRetryLogic`:
- `test_retries_on_5xx` — 503 then success, verifies 2 attempts + 1s sleep
- `test_retries_on_timeout` — exhausts all retries, verifies 4 attempts + 3 sleeps
- `test_no_retry_on_4xx` — 404 fails immediately, no sleep
- `test_retries_on_429` — rate limit then success
- `test_exponential_backoff_delays` — verifies 1s, 2s delay sequence

---

## Fix 2: Bounded History in FlyHunterController

**Problem:** `_history` was an unbounded `List`. Every spawn/kill cycle appended an entry. Over days/weeks of continuous operation, this would grow indefinitely and consume memory.

**File modified:** `hunter/backends/fly_control.py`

**Change:** Replaced `List` with `collections.deque(maxlen=100)`:
- `_MAX_HISTORY = 100` module-level constant
- `self._history: deque[Dict[str, Any]] = deque(maxlen=_MAX_HISTORY)`
- `history` property returns `list(self._history)` (unchanged API — callers get a list copy)
- Oldest entries automatically evicted when capacity is reached

**Why:** The Overseer is always-on. With a 5-minute loop interval and occasional redeploys, 100 entries covers ~8+ hours of history — more than enough for debugging while preventing unbounded growth.

**Tests added:** `tests/test_fly_control.py` — 1 new test:
- `test_history_capped_at_max` — spawns `_MAX_HISTORY + 10` times, verifies `len(history) <= _MAX_HISTORY`

---

## Fix 3: TTL Cache for `is_running`

**Problem:** `is_running` queried the Fly API on every call. The Overseer loop checks this property frequently. At tight intervals, this would cause unnecessary API traffic and potential rate limiting.

**File modified:** `hunter/backends/fly_control.py`

**Change:** Added a 30-second TTL cache:
- `_IS_RUNNING_TTL = 30.0` class-level constant
- `_is_running_cache: Optional[bool]` and `_is_running_cache_ts: float` instance fields
- Cache check uses `time.monotonic()` (immune to clock adjustments)
- Cache invalidated on `spawn()` and `kill()` via `_invalidate_running_cache()`
- When `_current is None`, returns `False` immediately without touching cache

**Why:** The Overseer's default loop interval is 300s, so the cache mostly prevents redundant calls within a single iteration that checks `is_running` multiple times. The 30s TTL is short enough that state changes are detected quickly.

**Tests added:** `tests/test_fly_control.py` — 4 new tests in `TestIsRunningCache`:
- `test_cache_avoids_repeated_api_calls` — second call doesn't hit API
- `test_cache_expires_after_ttl` — backdated timestamp forces re-query
- `test_spawn_invalidates_cache` — new spawn clears cache
- `test_kill_invalidates_cache` — kill clears cache, returns False (no current)

---

## Fix 4: Clone Verification in Hunter Entrypoint

**Problem:** `hunter-entrypoint.sh` ran `git clone` then immediately proceeded to `pip install` without checking whether the clone succeeded. A partial clone failure (network interruption, wrong repo name, expired PAT) would produce a confusing pip error instead of a clear clone failure message.

**File modified:** `deploy/hunter-entrypoint.sh`

**Change:** Added a guard after `git clone`:
```bash
if [ ! -d "$CLONE_DIR/.git" ]; then
    echo "[hunter-entrypoint] ERROR: Clone failed — $CLONE_DIR/.git not found" >&2
    exit 1
fi
```

**Why:** The Hunter machine is ephemeral and auto-destroys on exit. A clear error message in the logs makes it immediately obvious why a machine failed to boot, instead of chasing a misleading pip traceback.

**Tests:** Validated via `bash -n` syntax check (no unit tests for entrypoint scripts).

---

## Files Changed Summary

| File | Action | Change |
|------|--------|--------|
| `hunter/backends/fly_api.py` | Modified | Retry loop + backoff in `_request()` |
| `hunter/backends/fly_control.py` | Modified | `deque` history, TTL cache on `is_running`, cache invalidation |
| `deploy/hunter-entrypoint.sh` | Modified | Clone verification guard |
| `tests/test_fly_api.py` | Modified | +5 retry tests |
| `tests/test_fly_control.py` | Modified | +5 tests (1 history cap, 4 cache) |

**Totals:** ~60 lines production code, ~100 lines tests. 438 total tests passing.
