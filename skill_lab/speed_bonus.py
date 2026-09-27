"""Speed-bonus tracking for milestones and events.

Provides a configurable ``speed_reward_multiplier`` and personal-best
step tracking so that the speed bonus scales with how quickly the agent
reaches each achievement relative to its own best.
"""
from __future__ import annotations

import json
import math
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

        improvement = (best_steps - segment_steps) / best_steps
        pb_bonus = 1.0 + (PB_MAX - 1.0) * improvement

    Otherwise (or if the personal-best bonus is lower), an exponential
    fallback is used:

        fallback_bonus = FALLBACK_MAX * exp(-segment_steps / FALLBACK_HALF_LIFE)

    The final multiplier is::

        base_bonus = max(pb_bonus, fallback_bonus)
        final_bonus = max(1.0, base_bonus) * speed_reward_multiplier

    capped at ``MAX_BONUS``.

    The exponential fallback ensures that even untrained agents (which have
    no personal best) receive a meaningful bonus for speed — the decay is
    slow enough that an agent taking 500-1000 steps between achievements
    still gets a non-trivial multiplier, providing a gradient signal from
    the very first episode.
    """

    MAX_BONUS: float = 3.0
    """Hard cap on the final speed multiplier."""

    FALLBACK_HALF_LIFE: int = 500
    """Steps at which the exponential fallback bonus decays to ~55% of max."""

    FALLBACK_MAX: float = 3.0
    """Fallback multiplier at zero steps since last achievement."""

    PB_MAX: float = 3.0
    """Maximum personal-best multiplier (achieved when segment is 0 vs. best)."""

    def __init__(
        self,
        speed_reward_multiplier: float = 1.0,
        persist_path: str | Path | None = None,
    ) -> None:
        self.speed_reward_multiplier = float(speed_reward_multiplier)
        self._best_steps: dict[str, int] = {}
        self._last_achievement_step: int = 0
        self._last_segment: int = 0
        self._last_multiplier: float = 1.0
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

    def record_achievement(
        self,
        name: str,
        current_step: int,
        segment_steps: int | None = None,
    ) -> float:
        """Record an achievement at ``current_step``.

        Returns the speed-bonus multiplier (>= 1.0) to apply on top of the
        base reward for this achievement.

        Parameters
        ----------
        name:
            Achievement name (used for personal-best tracking).
        current_step:
            Absolute step count when the achievement fired.
        segment_steps:
            Optional explicit segment (steps since last achievement).  If
            not provided, falls back to ``current_step - _last_achievement_step``.
            Pass this when multiple achievement types (milestones, events)
            share this tracker but have their own notion of segment — this
            avoids a zero-segment artifact when two achievements fire on the
            same step.
        """
        if segment_steps is None:
            segment_steps = max(0, current_step - self._last_achievement_step)
        segment_steps = max(1, segment_steps)

        # Exponential fallback: gives a meaningful bonus even on the first
        # achievement (no personal best yet).  At segment=1 this is ~3.0x;
        # at 500 steps it's still ~1.65x; at 1000 steps ~0.91x.
        fallback_bonus = self.FALLBACK_MAX * math.exp(
            -segment_steps / self.FALLBACK_HALF_LIFE
        )

        # Personal-best bonus: scales how much *better* this segment is
        # compared to the best known segment for this achievement.
        pb_bonus = 0.0
        if name in self._best_steps and self._best_steps[name] > 0:
            best = self._best_steps[name]
            improvement = (best - segment_steps) / best
            pb_bonus = 1.0 + (self.PB_MAX - 1.0) * improvement

        # Take the better of the two formulas.  This ensures the bonus
        # is always > 1.0x for reasonably fast segments, and only drops
        # below 1.0x (clamped) when the agent is *very* slow.
        base_bonus = max(pb_bonus, fallback_bonus)
        base_bonus = max(1.0, base_bonus)

        bonus = base_bonus * self.speed_reward_multiplier
        bonus = min(bonus, self.MAX_BONUS)

        # Update personal best.
        old_best = self._best_steps.get(name)
        is_new_best = old_best is None or segment_steps < old_best
        if is_new_best:
            self._best_steps[name] = segment_steps
            self._save_best()

        self._last_achievement_step = current_step
        self._last_segment = segment_steps
        self._last_multiplier = bonus
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
        self._last_segment = 0
        self._last_multiplier = 1.0
        self._achievement_log.clear()

    def get_stats(self) -> dict[str, Any]:
        """Return a serializable summary for the inspector / dashboard."""
        return {
            "best_steps": dict(self._best_steps),
            "current_run": list(self._achievement_log),
            "speed_reward_multiplier": self.speed_reward_multiplier,
            "last_segment": self._last_segment,
            "last_multiplier": self._last_multiplier,
            "fallback": {
                "FALLBACK_MAX": self.FALLBACK_MAX,
                "MAX_BONUS": self.MAX_BONUS,
                "FALLBACK_HALF_LIFE": self.FALLBACK_HALF_LIFE,
            },
        }
