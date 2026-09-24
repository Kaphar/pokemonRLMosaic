"""Speed-bonus tracking for milestones and events.

Provides a configurable ``speed_reward_multiplier`` and personal-best
step tracking so that the speed bonus scales with how quickly the agent
reaches each achievement relative to its own best.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class SpeedBonusTracker:
    """Track step counts for achievements and compute speed bonuses.

    The speed bonus is a multiplier applied on top of milestone and event
    rewards.  It rewards the agent for reaching achievements quickly.

    Bonus formula
    -------------
    For each achievement ``name`` at ``current_step``:

        segment_steps = current_step - last_achievement_step

    If a personal best exists for ``name``:

        base_bonus = min(best_steps / segment_steps, 3.0)

    Otherwise a linear fallback is used:

        base_bonus = max(1.0, 3.0 - segment_steps / 100.0)

    The final multiplier is::

        final_bonus = max(1.0, base_bonus) * speed_reward_multiplier

    capped at ``MAX_BONUS`` (5.0).
    """

    MAX_BONUS: float = 5.0
    """Hard cap on the final speed multiplier."""

    FALLBACK_HALF_LIFE: int = 100
    """Steps at which the fallback bonus drops to 1.0x."""

    FALLBACK_MAX: float = 3.0
    """Fallback multiplier at zero steps since last achievement."""

    def __init__(
        self,
        speed_reward_multiplier: float = 1.0,
        persist_path: str | Path | None = None,
    ) -> None:
        self.speed_reward_multiplier = float(speed_reward_multiplier)
        self._best_steps: dict[str, int] = {}
        self._last_achievement_step: int = 0
        self._achievement_log: list[dict[str, Any]] = []
        self._persist_path: Path | None = (
            Path(persist_path) if persist_path else None
        )
        self._load_best()

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def _load_best(self) -> None:
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            with self._persist_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                self._best_steps = {k: int(v) for k, v in data.items()}
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            pass

    def _save_best(self) -> None:
        if self._persist_path is None:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            with self._persist_path.open("w", encoding="utf-8") as fh:
                json.dump(self._best_steps, fh, indent=2)
        except (OSError, TypeError):
            pass

    # ------------------------------------------------------------------ #
    # Core API
    # ------------------------------------------------------------------ #

    def record_achievement(self, name: str, current_step: int) -> float:
        """Record an achievement at ``current_step``.

        Returns the speed-bonus multiplier (>= 1.0) to apply on top of the
        base reward for this achievement.
        """
        segment_steps = max(1, current_step - self._last_achievement_step)

        if name in self._best_steps:
            # Personal best exists — reward beating it.
            ratio = self._best_steps[name] / segment_steps
            base_bonus = min(ratio, self.FALLBACK_MAX)
        else:
            # No prior data — use the linear fallback.
            base_bonus = max(
                1.0,
                self.FALLBACK_MAX
                - (segment_steps / self.FALLBACK_HALF_LIFE),
            )

        bonus = max(1.0, base_bonus) * self.speed_reward_multiplier
        bonus = min(bonus, self.MAX_BONUS)

        # Update personal best.
        old_best = self._best_steps.get(name)
        is_new_best = old_best is None or segment_steps < old_best
        if is_new_best:
            self._best_steps[name] = segment_steps
            self._save_best()

        self._last_achievement_step = current_step
        self._achievement_log.append({
            "name": name,
            "segment_steps": segment_steps,
            "bonus": round(bonus, 4),
            "is_new_best": is_new_best,
        })

        return bonus

    def reset(self, current_step: int = 0) -> None:
        """Reset per-episode state.  Persisted best steps are retained."""
        self._last_achievement_step = current_step
        self._achievement_log.clear()

    def get_stats(self) -> dict[str, Any]:
        """Return a serializable summary for the inspector / dashboard."""
        return {
            "best_steps": dict(self._best_steps),
            "current_run": list(self._achievement_log),
            "speed_reward_multiplier": self.speed_reward_multiplier,
        }
