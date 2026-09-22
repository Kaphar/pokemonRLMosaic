"""Curated checkpoint tracker for the Skill Lab.

Unlike the event-flag ``MilestoneTracker`` (which scans every event bit),
``CheckpointTracker`` tracks a curated, ordered list of *story checkpoints*
for a stage.  Each checkpoint maps to an ``events.json`` key (e.g.
``"0xD74B-5"``) and awards a one-time milestone reward when that event fires.

Checkpoints are loaded from the stage config's ``"checkpoints"`` array, so
different stages can define their own ordered progression.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skill_lab.ram_map import GameState


class CheckpointTracker:
    """Track a curated, ordered list of story checkpoints.

    Parameters
    ----------
    checkpoints
        List of dicts, each with keys: ``name``, ``event_key``,
        ``reward_baseline`` (optional, defaults to 1.0), ``description``
        (optional).
    effective_rewards
        Dict produced by :func:`skill_lab.rewards.check_baseline_rewards`.
        Must contain ``"milestone"`` key for the default reward value.
    """

    def __init__(
        self,
        checkpoints: list[dict[str, Any]] | None = None,
        effective_rewards: dict[str, float] | None = None,
    ) -> None:
        self.checkpoints: list[dict[str, Any]] = list(checkpoints or [])
        self.effective_rewards = effective_rewards or {}
        self.achieved: set[str] = set()
        self.achieved_steps: dict[str, int] = {}
        self.total_reward: float = 0.0

    @classmethod
    def from_stage_config(
        cls,
        stage_config: dict[str, Any] | None,
        effective_rewards: dict[str, float] | None = None,
    ) -> "CheckpointTracker":
        """Build a tracker from a stage config's ``checkpoints`` array."""
        stage_config = stage_config or {}
        checkpoints = stage_config.get("checkpoints", [])
        return cls(checkpoints=checkpoints, effective_rewards=effective_rewards)

    @property
    def current_target_index(self) -> int:
        """Index of the first not-yet-achieved checkpoint, or len if all done."""
        for idx, cp in enumerate(self.checkpoints):
            if cp["name"] not in self.achieved:
                return idx
        return len(self.checkpoints)

    @property
    def all_completed(self) -> bool:
        return len(self.achieved) >= len(self.checkpoints)

    def _parse_event_key(self, key: str) -> tuple[int, int] | None:
        """Parse ``"0xD74B-5"`` style keys into ``(address, msb_index)``."""
        try:
            addr_str, bit_str = key.split("-", 1)
            addr = int(addr_str, 16)
            msb_index = int(bit_str)
            return addr, msb_index
        except (ValueError, AttributeError):
            return None

    def _event_is_set(self, game_state: GameState, key: str) -> bool:
        parsed = self._parse_event_key(key)
        if parsed is None:
            return False
        addr, msb_index = parsed
        return game_state.event_flag(addr, msb_index)

    def _reward_for(self, checkpoint: dict[str, Any]) -> float:
        """Return the reward for a checkpoint, using a per-checkpoint override
        if present, falling back to ``effective_rewards["milestone"]``."""
        override = checkpoint.get("reward_baseline")
        if override is not None:
            return float(override)
        return float(self.effective_rewards.get("milestone", 1.0))

    def reset(self, game_state: GameState | None = None, env_label: str = "") -> None:
        """Clear progress.  If a GameState is provided, pre-mark any
        already-set checkpoints as achieved (so we don't reward past events)."""
        self.achieved.clear()
        self.achieved_steps.clear()
        self.total_reward = 0.0

        if game_state is None:
            return

        for cp in self.checkpoints:
            key = cp.get("event_key")
            if key and self._event_is_set(game_state, key):
                self.achieved.add(cp["name"])

        if self.achieved:
            print(f"{env_label}[Checkpoint] {len(self.achieved)} checkpoints already completed in initial state")

    def check_and_reward(self, game_state_or_env, env_label: str = "") -> float:
        """Return reward for any newly completed checkpoints.

        Accepts either a :class:`~skill_lab.ram_map.GameState` or an env
        that exposes ``pyboy`` / ``unwrapped``.
        """
        reward = 0.0
        game_state = self._to_game_state(game_state_or_env)
        if game_state is None:
            return 0.0

        unwrapped = getattr(game_state_or_env, "unwrapped", game_state_or_env)
        step_count = getattr(unwrapped, "step_count", 0)
        if hasattr(step_count, "step_count"):
            step_count = step_count.step_count

        for cp in self.checkpoints:
            name = cp["name"]
            if name in self.achieved:
                continue

            key = cp.get("event_key")
            if not key:
                continue

            if self._event_is_set(game_state, key):
                self.achieved.add(name)
                self.achieved_steps[name] = int(step_count)
                cp_reward = self._reward_for(cp)
                reward += cp_reward
                self.total_reward += cp_reward
                print(f"{env_label}[Checkpoint] ACHIEVED: {name} at step {step_count} (reward +{cp_reward:.2f})")

        return reward

    @staticmethod
    def _to_game_state(env_or_state) -> GameState | None:
        """Accept a GameState, a PyBoy env, or any object with pyboy."""
        if isinstance(env_or_state, GameState):
            return env_or_state
        pyboy = getattr(env_or_state, "pyboy", None)
        if pyboy is not None:
            return GameState(pyboy)
        return None

    def get_progress(self) -> dict[str, Any]:
        """Return a serializable progress summary for the UI / dashboard."""
        total = len(self.checkpoints)
        names = [cp.get("name", f"checkpoint_{i}") for i, cp in enumerate(self.checkpoints)]
        return {
            "total": total,
            "achieved": len(self.achieved),
            "achieved_names": list(self.achieved),
            "achieved_steps": dict(self.achieved_steps),
            "checkpoint_names": names,
            "current_target_index": self.current_target_index,
            "total_reward": self.total_reward,
        }