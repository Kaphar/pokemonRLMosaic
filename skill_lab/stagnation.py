"""Stagnation detection to discourage the agent from staying idle or
oscillating in a small area for extended periods.

Two complementary signals are monitored:

1. **Position stagnation**: over a sliding window of the last *N* steps,
   if the agent's projected tile displacement is below a threshold (and
   the agent was not in battle for most of the window), a small per-step
   penalty is applied.

2. **A-button spam**: if the agent presses A many times without making
   meaningful positional progress (e.g., interacting with the same empty
   tile or NPC repeatedly), an additional penalty is applied.

Both penalties are intentionally small — they act as a gentle nudge, not
a wall — so the agent can still perform legitimate actions like standing
still during dialogue or mashing A to advance text.
"""
from __future__ import annotations

import math
from typing import Any

try:
    from v2.map_projection import project_position
    _HAS_PROJECTION = True
except ImportError:
    _HAS_PROJECTION = False
    project_position = None


class StagnationTracker:
    """Detect and penalise unproductive agent behaviour.

    Parameters
    ----------
    window:
        Number of steps in the evaluation window.  Each time the window
        fills up the tracker checks for stagnation and then shifts the
        window forward by half its length (50 % overlap) to keep the
        signal responsive.
    displacement_threshold:
        Minimum Manhattan tile displacement required over the window to
        avoid a stagnation penalty.
    max_battle_ratio:
        Maximum fraction of the window that may be spent in battle before
        the stagnation check is skipped (battle legitimately limits
        movement).
    a_spam_threshold:
        Number of A-button presses above which a spam penalty starts
        accruing (only counted outside of battle).
    position_penalty_per_step:
        Penalty applied per step when position stagnation is detected.
    a_spam_penalty_per_press:
        Penalty per A press above ``a_spam_threshold``.
    """

    PIXELS_PER_TILE = 16

    def __init__(
        self,
        window: int = 50,
        displacement_threshold: int = 5,
        max_battle_ratio: float = 0.5,
        a_spam_threshold: int = 10,
        position_penalty_per_step: float = -0.005,
        a_spam_penalty_per_press: float = -0.001,
    ) -> None:
        self.window = window
        self.displacement_threshold = displacement_threshold
        self.max_battle_ratio = max_battle_ratio
        self.a_spam_threshold = a_spam_threshold
        self.position_penalty_per_step = position_penalty_per_step
        self.a_spam_penalty_per_press = a_spam_penalty_per_press
        self.reset()

    def reset(self) -> None:
        self._steps: list[dict[str, Any]] = []
        self._total_penalty: float = 0.0
        self.total_position_penalties: int = 0
        self.total_a_spam_penalties: int = 0

    # ------------------------------------------------------------------ #
    # Core API
    # ------------------------------------------------------------------ #

    def _project_to_tile(self, x: int, y: int, map_id: int) -> tuple[int, int]:
        if _HAS_PROJECTION:
            result = project_position(x, y, map_id)
            return (result.pixel_x // self.PIXELS_PER_TILE, result.pixel_y // self.PIXELS_PER_TILE)
        return (x, y)

    def step(
        self,
        x: int,
        y: int,
        map_id: int,
        in_battle: bool,
        pressed_a: bool,
        current_step: int = 0,
    ) -> float:
        """Record one step of agent state.

        Returns the per-step penalty (0.0 if no penalty, a negative float
        if stagnation is detected).  The penalty is returned every step
        once the window fills and stagnation is confirmed, until the agent
        resumes making progress.
        """
        self._steps.append({
            "step": current_step,
            "x": x,
            "y": y,
            "map_id": map_id,
            "in_battle": in_battle,
            "pressed_a": pressed_a,
        })

        if len(self._steps) < self.window:
            return 0.0

        return self._evaluate_window()

    def _evaluate_window(self) -> float:
        window = self._steps[-self.window:]

        # --- Count non-battle steps ---
        non_battle_steps = [s for s in window if not s["in_battle"]]
        if len(non_battle_steps) < self.window * (1.0 - self.max_battle_ratio):
            # Too much battle time — skip stagnation evaluation.
            # Shift window forward by half.
            self._steps = self._steps[len(self._steps) // 2:]
            return 0.0

        # --- Position displacement check (projected tile space) ---
        first = non_battle_steps[0]
        last = non_battle_steps[-1]
        fx, fy = self._project_to_tile(first["x"], first["y"], first["map_id"])
        lx, ly = self._project_to_tile(last["x"], last["y"], last["map_id"])
        displacement = abs(lx - fx) + abs(ly - fy)

        penalty = 0.0
        current_step = window[-1]["step"]
        label = ""  # filled by caller

        if displacement < self.displacement_threshold:
            # Position stagnation: penalise every step in the window
            # proportional to how little was covered.
            severity = (self.displacement_threshold - displacement) / max(1, self.displacement_threshold)
            penalty += self.position_penalty_per_step * self.window * severity
            self.total_position_penalties += 1

        # --- A-button spam check (outside battle) ---
        a_presses = sum(1 for s in non_battle_steps if s["pressed_a"])
        if a_presses > self.a_spam_threshold and displacement < self.displacement_threshold * 2:
            excess = a_presses - self.a_spam_threshold
            a_penalty = self.a_spam_penalty_per_press * excess
            penalty += a_penalty
            self.total_a_spam_penalties += 1

        self._total_penalty += penalty

        # Log the penalty
        if penalty < 0:
            details = []
            details.append(f"disp={displacement}t")
            details.append(f"a_presses={a_presses}")
            details.append(f"window={self.window}")
            if displacement < self.displacement_threshold:
                pos_penalty = self.position_penalty_per_step * self.window * severity
                details.append(f"pos_stag={pos_penalty:.2f}")
            if a_presses > self.a_spam_threshold and displacement < self.displacement_threshold * 2:
                details.append(f"a_spam={a_penalty:.2f}")
            print(f"stag [{current_step}] Penalty: {penalty:.2f} | {' '.join(details)}",
                  flush=True)

        # Shift window forward by half to keep detection responsive
        self._steps = self._steps[len(self._steps) // 2:]

        return penalty

    def get_stats(self) -> dict[str, Any]:
        return {
            "total_penalty": round(self._total_penalty, 4),
            "position_penalty_count": self.total_position_penalties,
            "a_spam_penalty_count": self.total_a_spam_penalties,
            "window": self.window,
            "displacement_threshold": self.displacement_threshold,
            "a_spam_threshold": self.a_spam_threshold,
        }
