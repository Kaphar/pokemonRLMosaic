"""Milestone / event-flag tracking using events.json.

Unlike the curated :class:`~milestonetracker.MilestoneTracker`, this
tracker scans *every* event flag in ``events.json`` and awards a one-time
``effective_rewards["event"]`` reward when a new flag is set.

It reads ``events.json`` directly (no separate ``milestones.json``) and uses
``GameState.event_flag()`` for clean MSB-first bit access matching the
``"0xD74B-5"`` key convention.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skill_lab.config import EVENT_JSON_PATH
from skill_lab.ram_map import GameState


class EventTracker:
    """Track all event flags and give rewards when they are achieved.

    Parameters
    ----------
    effective_rewards
        Dict produced by :func:`skill_lab.rewards.check_baseline_rewards`.
        Uses ``"event"`` key for per-event rewards (falls back to 1.0).
    event_json_path
        Path to ``events.json`` (defaults to :data:`EVENT_JSON_PATH`).
    """

    def __init__(
        self,
        effective_rewards: dict[str, float] | None = None,
        event_json_path: str | Path | None = None,
    ) -> None:
        self.effective_rewards = effective_rewards or {}
        self.event_json_path = Path(event_json_path) if event_json_path else EVENT_JSON_PATH
        self.event_names: dict[str, str] = self._load_events()
        self.achieved: set[str] = set()
        self.achieved_steps: dict[str, int] = {}
        self.total_reward: float = 0.0

    def _load_events(self) -> dict[str, str]:
        """Load the events.json mapping. Returns ``{key: name}``."""
        path = self.event_json_path
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    @staticmethod
    def _parse_event_key(key: str) -> tuple[int, int] | None:
        """Parse ``"0xD74B-5"`` into ``(address, msb_index)``."""
        try:
            addr_str, bit_str = key.split("-", 1)
            addr = int(addr_str, 16)
            msb_index = int(bit_str)
            return addr, msb_index
        except (ValueError, AttributeError):
            return None

    def _reward_for_event(self) -> float:
        return float(self.effective_rewards.get("event", 1.0))

    def reset(self, env_or_state=None, env_label: str = "") -> None:
        """Clear progress.  If a memory source is provided, pre-mark any
        already-set event flags as achieved."""
        self.achieved.clear()
        self.achieved_steps.clear()
        self.total_reward = 0.0

        if env_or_state is None:
            return

        game_state = self._to_game_state(env_or_state)
        if game_state is None:
            return

        for key in self.event_names:
            parsed = self._parse_event_key(key)
            if parsed is None:
                continue
            addr, msb_index = parsed
            if game_state.event_flag(addr, msb_index):
                self.achieved.add(key)

        if self.achieved:
            print(f"{env_label}[Event] {len(self.achieved)} event flags already set in initial state (ignored)")

    @staticmethod
    def _to_game_state(env_or_state) -> GameState | None:
        """Accept a GameState, a PyBoy env, or a SkillLabWrapper env."""
        if isinstance(env_or_state, GameState):
            return env_or_state
        pyboy = getattr(env_or_state, "pyboy", None)
        if pyboy is not None:
            return GameState(pyboy)
        return None

    def check_and_reward(self, env_or_state, env_label: str = "") -> float:
        """Check all event flags and return reward for newly achieved ones."""
        game_state = self._to_game_state(env_or_state)
        if game_state is None:
            return 0.0

        total_reward = 0.0
        unwrapped = getattr(env_or_state, "unwrapped", env_or_state)

        for key, name in self.event_names.items():
            if key in self.achieved:
                continue

            parsed = self._parse_event_key(key)
            if parsed is None:
                continue
            addr, msb_index = parsed

            if game_state.event_flag(addr, msb_index):
                self.achieved.add(key)
                step_count = getattr(unwrapped, "step_count", 0)
                self.achieved_steps[key] = int(step_count)
                reward = self._reward_for_event()
                total_reward += reward
                self.total_reward += reward
                display_name = name if name else key
                print(f"{env_label}[Event] ACHIEVED: {display_name} ({key}) at step {step_count} (reward +{reward:.2f})")

        return total_reward

    def get_progress(self) -> dict[str, Any]:
        return {
            "total_milestones": len(self.event_names),
            "achieved": len(self.achieved),
            "achieved_names": list(self.achieved),
            "achieved_steps": dict(self.achieved_steps),
        }