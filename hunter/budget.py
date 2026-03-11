"""Budget system — config loading, spend tracking, and enforcement.

The human sets budget constraints via ~/.hermes/hunter/budget.yaml.
The Overseer reads this file each loop iteration (watching for mtime changes)
and enforces limits by adjusting model selection or killing the Hunter.

Spend is tracked in an append-only JSONL ledger at ~/.hermes/hunter/spend.jsonl.
Daily spend resets at UTC midnight.

Config schema (budget.yaml):
    budget:
      mode: "daily"             # "daily" or "total"
      max_per_day: 15.00        # USD per calendar day (UTC)
      max_total: 300.00         # USD total (only used in "total" mode)
      min_days: 5               # Must last at least this many days ("total" mode)
      currency: "USD"
      alert_at_percent: 80      # Notify human when this % consumed
      hard_stop_at_percent: 100 # Kill Hunter when this % consumed
      model_costs:              # $/1M tokens — Overseer updates as it learns
        "qwen/qwen3.5-72b": 1.20
        "qwen/qwen3.5-32b": 0.60
        "qwen/qwen3.5-7b": 0.15
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from hunter.config import get_budget_config_path, get_spend_ledger_path, ensure_hunter_home

logger = logging.getLogger(__name__)


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class BudgetStatus:
    """Snapshot of current budget state, returned by BudgetManager.check_budget()."""

    allowed: bool               # Can we keep spending?
    remaining_usd: float        # How much budget is left
    percent_used: float         # 0.0 - 100.0
    alert: bool                 # Past alert threshold?
    hard_stop: bool             # Past hard stop threshold?
    mode: str                   # "daily" or "total"
    spend_today: float          # USD spent today (UTC)
    spend_total: float          # USD spent all-time
    daily_limit: Optional[float]    # Only set in "daily" mode
    total_limit: Optional[float]    # Only set in "total" mode
    daily_rate_limit: Optional[float]  # In "total" mode: max_total / min_days

    def to_dict(self) -> dict:
        return asdict(self)

    def summary(self) -> str:
        """Human-readable one-line summary."""
        if self.mode == "daily":
            return (
                f"${self.spend_today:.2f} / ${self.daily_limit:.2f} today "
                f"({self.percent_used:.0f}% used, ${self.remaining_usd:.2f} remaining)"
            )
        else:
            return (
                f"${self.spend_total:.2f} / ${self.total_limit:.2f} total "
                f"({self.percent_used:.0f}% used, ${self.remaining_usd:.2f} remaining)"
            )


@dataclass
class SpendEntry:
    """A single row in the spend ledger."""

    timestamp: str      # ISO 8601 UTC
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    agent: str          # "hunter" or "overseer"


# =============================================================================
# Default config
# =============================================================================

DEFAULT_BUDGET_CONFIG = {
    "budget": {
        "mode": "daily",
        "max_per_day": 15.00,
        "max_total": 300.00,
        "min_days": 5,
        "currency": "USD",
        "alert_at_percent": 80,
        "hard_stop_at_percent": 100,
        "model_costs": {
            "qwen/qwen3.5-72b": 1.20,
            "qwen/qwen3.5-32b": 0.60,
            "qwen/qwen3.5-7b": 0.15,
        },
    }
}


# =============================================================================
# BudgetManager
# =============================================================================

class BudgetManager:
    """Loads budget config, tracks spend, enforces limits.

    Usage:
        mgr = BudgetManager()
        mgr.reload()                        # Pick up config changes
        status = mgr.check_budget()         # Check limits
        mgr.record_spend(0.003, "qwen/qwen3.5-32b", 4500, 800, "hunter")
    """

    def __init__(self, config_path: Path = None, ledger_path: Path = None):
        self.config_path = config_path or get_budget_config_path()
        self.ledger_path = ledger_path or get_spend_ledger_path()
        self._config: dict = {}
        self._last_mtime: float = 0.0
        self._spend_today: float = 0.0
        self._spend_total: float = 0.0
        self._today_utc: str = ""  # "2026-03-11" — for daily reset detection
        self._loaded = False
        self.reload()

    # ── Config loading ──────────────────────────────────────────────────

    def reload(self) -> bool:
        """Reload config from disk if file changed. Returns True if reloaded.

        Safe to call frequently — checks mtime first to avoid unnecessary I/O.
        """
        if not self.config_path.exists():
            if not self._loaded:
                self._config = DEFAULT_BUDGET_CONFIG.get("budget", {})
                self._loaded = True
                self._rebuild_spend_totals()
                return True
            return False

        try:
            mtime = self.config_path.stat().st_mtime
        except OSError:
            return False

        if mtime == self._last_mtime and self._loaded:
            return False

        try:
            with open(self.config_path, "r") as f:
                raw = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError) as e:
            logger.warning("Failed to parse budget config: %s", e)
            return False

        self._config = raw.get("budget", raw)  # Accept both {"budget": {...}} and flat
        self._last_mtime = mtime
        self._loaded = True

        # Rebuild spend totals (in case day rolled over)
        self._rebuild_spend_totals()

        logger.info("Budget config reloaded: mode=%s", self._config.get("mode", "daily"))
        return True

    # ── Spend tracking ──────────────────────────────────────────────────

    def record_spend(
        self,
        cost_usd: float,
        model: str = "unknown",
        input_tokens: int = 0,
        output_tokens: int = 0,
        agent: str = "hunter",
    ) -> None:
        """Record LLM API spend. Appends to the JSONL ledger."""
        now = datetime.now(timezone.utc)
        entry = SpendEntry(
            timestamp=now.isoformat(),
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost_usd, 6),
            agent=agent,
        )

        # Append to ledger
        self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.ledger_path, "a") as f:
            f.write(json.dumps(asdict(entry)) + "\n")

        # Update in-memory totals
        today = now.strftime("%Y-%m-%d")
        if today != self._today_utc:
            self._today_utc = today
            self._spend_today = 0.0

        self._spend_today += cost_usd
        self._spend_total += cost_usd

    def _rebuild_spend_totals(self) -> None:
        """Replay the spend ledger to rebuild in-memory totals."""
        self._spend_today = 0.0
        self._spend_total = 0.0
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._today_utc = today

        if not self.ledger_path.exists():
            return

        try:
            with open(self.ledger_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        cost = entry.get("cost_usd", 0.0)
                        self._spend_total += cost
                        # Check if this entry is from today
                        ts = entry.get("timestamp", "")
                        if ts[:10] == today:
                            self._spend_today += cost
                    except (json.JSONDecodeError, KeyError):
                        continue
        except OSError as e:
            logger.warning("Failed to read spend ledger: %s", e)

    # ── Budget enforcement ──────────────────────────────────────────────

    def check_budget(self) -> BudgetStatus:
        """Check current budget status. Call each Overseer loop iteration."""
        mode = self._config.get("mode", "daily")
        alert_pct = self._config.get("alert_at_percent", 80)
        hard_stop_pct = self._config.get("hard_stop_at_percent", 100)

        # Check for day rollover
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if today != self._today_utc:
            self._rebuild_spend_totals()

        if mode == "daily":
            limit = self._config.get("max_per_day", 15.0)
            spent = self._spend_today
            remaining = max(0.0, limit - spent)
            pct = (spent / limit * 100) if limit > 0 else 100.0
            return BudgetStatus(
                allowed=pct < hard_stop_pct,
                remaining_usd=round(remaining, 4),
                percent_used=round(pct, 1),
                alert=pct >= alert_pct,
                hard_stop=pct >= hard_stop_pct,
                mode="daily",
                spend_today=round(self._spend_today, 4),
                spend_total=round(self._spend_total, 4),
                daily_limit=limit,
                total_limit=None,
                daily_rate_limit=None,
            )
        else:  # "total" mode
            total_limit = self._config.get("max_total", 300.0)
            min_days = self._config.get("min_days", 1)
            daily_rate_limit = total_limit / max(min_days, 1)
            spent = self._spend_total
            remaining = max(0.0, total_limit - spent)
            pct = (spent / total_limit * 100) if total_limit > 0 else 100.0

            # Also enforce daily rate limit in total mode
            daily_pct = (self._spend_today / daily_rate_limit * 100) if daily_rate_limit > 0 else 0.0
            effective_pct = max(pct, daily_pct)

            return BudgetStatus(
                allowed=effective_pct < hard_stop_pct,
                remaining_usd=round(remaining, 4),
                percent_used=round(pct, 1),
                alert=effective_pct >= alert_pct,
                hard_stop=effective_pct >= hard_stop_pct,
                mode="total",
                spend_today=round(self._spend_today, 4),
                spend_total=round(self._spend_total, 4),
                daily_limit=round(daily_rate_limit, 4),
                total_limit=total_limit,
                daily_rate_limit=round(daily_rate_limit, 4),
            )

    # ── Cost estimation ─────────────────────────────────────────────────

    def estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for a planned API call using configured model costs.

        Returns estimated cost in USD. Falls back to 0.0 if model not in config.
        Model costs are in $/1M tokens (combined input+output for simplicity).
        """
        costs = self._config.get("model_costs", {})
        per_million = costs.get(model, 0.0)
        total_tokens = input_tokens + output_tokens
        return round(per_million * total_tokens / 1_000_000, 6)

    # ── Config creation & modification ──────────────────────────────────

    def create_default_config(self) -> bool:
        """Write default budget.yaml if it doesn't exist. Returns True if created."""
        if self.config_path.exists():
            return False

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            yaml.dump(DEFAULT_BUDGET_CONFIG, f, default_flow_style=False, sort_keys=False)

        logger.info("Created default budget config at %s", self.config_path)
        self.reload()
        return True

    def update_config(self, **kwargs) -> None:
        """Update specific budget config values and write to disk.

        Example: update_config(mode="daily", max_per_day=20.0)
        """
        # Load current config (or default)
        if self.config_path.exists():
            with open(self.config_path, "r") as f:
                raw = yaml.safe_load(f) or {}
        else:
            raw = dict(DEFAULT_BUDGET_CONFIG)

        budget = raw.setdefault("budget", {})
        budget.update(kwargs)

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w") as f:
            yaml.dump(raw, f, default_flow_style=False, sort_keys=False)

        self.reload()

    # ── Spend history ───────────────────────────────────────────────────

    def get_spend_history(self, limit: int = 50) -> List[dict]:
        """Get recent spend entries from the ledger (most recent first)."""
        if not self.ledger_path.exists():
            return []

        entries = []
        try:
            with open(self.ledger_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except OSError:
            return []

        # Return most recent first
        return list(reversed(entries[-limit:]))

    def get_daily_summary(self) -> Dict[str, float]:
        """Get spend per day from the ledger. Returns {date_str: total_usd}."""
        if not self.ledger_path.exists():
            return {}

        daily: Dict[str, float] = {}
        try:
            with open(self.ledger_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        day = entry.get("timestamp", "")[:10]
                        if day:
                            daily[day] = daily.get(day, 0.0) + entry.get("cost_usd", 0.0)
                    except (json.JSONDecodeError, KeyError):
                        continue
        except OSError:
            pass

        return {k: round(v, 4) for k, v in sorted(daily.items())}

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def mode(self) -> str:
        return self._config.get("mode", "daily")

    @property
    def model_costs(self) -> Dict[str, float]:
        return self._config.get("model_costs", {})

    @property
    def config(self) -> dict:
        """Raw budget config dict (read-only view)."""
        return dict(self._config)

    def __repr__(self) -> str:
        status = self.check_budget()
        return f"BudgetManager(mode={status.mode}, {status.summary()})"


# =============================================================================
# CLI helpers
# =============================================================================

def parse_budget_string(value: str) -> dict:
    """Parse a CLI budget string into config kwargs.

    Formats:
        "20/day"        → {"mode": "daily", "max_per_day": 20.0}
        "300/5days"     → {"mode": "total", "max_total": 300.0, "min_days": 5}
        "15"            → {"mode": "daily", "max_per_day": 15.0}
    """
    value = value.strip().lower()

    # "300/5days" or "300/5d"
    match = re.match(r"^(\d+(?:\.\d+)?)\s*/\s*(\d+)\s*d(?:ays?)?$", value)
    if match:
        return {
            "mode": "total",
            "max_total": float(match.group(1)),
            "min_days": int(match.group(2)),
        }

    # "20/day" or "20/d"
    match = re.match(r"^(\d+(?:\.\d+)?)\s*/\s*d(?:ay)?$", value)
    if match:
        return {"mode": "daily", "max_per_day": float(match.group(1))}

    # Plain number → daily
    match = re.match(r"^(\d+(?:\.\d+)?)$", value)
    if match:
        return {"mode": "daily", "max_per_day": float(match.group(1))}

    raise ValueError(
        f"Invalid budget format: '{value}'. "
        "Expected: '20/day', '300/5days', or '15'"
    )
