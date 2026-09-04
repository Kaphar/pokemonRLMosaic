"""Milestone tracking using the converted milestones.json.

Key fix: On reset(), we read the current memory state and mark
already-set events as "achieved". This prevents the tracker from
giving rewards for events that were already set in the initial state.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class MilestoneTracker:
    """Tracks game milestones and gives rewards when they're achieved."""

    def __init__(
        self,
        milestones_path: str | Path,
        reward_per_milestone: float = 5.0,
    ) -> None:
        self.reward_per_milestone = reward_per_milestone
        self.milestones: list[dict[str, Any]] = []
        self.achieved: set[str] = set()

        # Load milestones.json (the converted file)
        path = Path(milestones_path)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.milestones = data.get("milestones", [])
            print(f"[Milestones] Loaded {len(self.milestones)} milestones from {path}")
        else:
            print(f"[Milestones] WARNING: {path} not found. Milestone rewards disabled.")

    def reset(self, env=None) -> None:
        """Reset tracker and initialize achieved set from current memory state.

        This is the KEY FIX: we read memory at reset time and mark
        already-set events as achieved, so they don't give rewards.
        """
        self.achieved.clear()

        if env is None:
            return

        # Read current memory state and mark already-set events as achieved
        for milestone in self.milestones:
            name = milestone["name"]
            address = milestone["address"]
            mask = milestone["mask"]

            try:
                memory_value = env.pyboy.memory[address]
                if (memory_value & mask) > 0:
                    self.achieved.add(name)
            except (IndexError, AttributeError):
                pass

        if self.achieved:
            print(f"[Milestones] {len(self.achieved)} events already set in initial state (ignored)")

    def check_and_reward(self, env) -> float:
        """Check all milestones and return reward for newly achieved ones."""
        total_reward = 0.0

        for milestone in self.milestones:
            name = milestone["name"]
            if name in self.achieved:
                continue

            address = milestone["address"]
            mask = milestone["mask"]

            try:
                memory_value = env.pyboy.memory[address]
            except (IndexError, AttributeError):
                continue

            if (memory_value & mask) > 0:
                self.achieved.add(name)
                total_reward += self.reward_per_milestone
                print(f"[Milestone] ACHIEVED: {name} (reward +{self.reward_per_milestone})")

        return total_reward

    def get_progress(self) -> dict[str, Any]:
        """Return current progress info (useful for UI)."""
        return {
            "total_milestones": len(self.milestones),
            "achieved": len(self.achieved),
            "achieved_names": list(self.achieved),
        }