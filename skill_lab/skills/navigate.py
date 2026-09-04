"""NavigateTo skill."""

from __future__ import annotations

from typing import Any

import numpy as np

from skill_lab.skills.base import Skill


class NavigateToSkill(Skill):
    def __init__(self, target_map_id: int, max_steps: int = 512) -> None:
        super().__init__(name="NavigateTo", description=f"Navigate to map {target_map_id:02X}")
        self.target_map_id = target_map_id
        self.max_steps = max_steps
        self.steps = 0
        self.active = False

    def reset(self) -> None:
        self.steps = 0
        self.active = False

    def update(self, observation: dict[str, np.ndarray], env) -> None:
        current_map_id = int(env.current_map_id)
        if current_map_id == self.target_map_id:
            self.active = False
        else:
            self.active = True
        self.steps += 1

    def get_action(self, observation: dict[str, np.ndarray], env, base_policy_action: int) -> int:
        if not self.active:
            return base_policy_action

        current_map_id = int(env.current_map_id)
        if current_map_id == self.target_map_id:
            self.active = False
            return base_policy_action

        if self.steps > self.max_steps:
            self.active = False
            return base_policy_action

        # Very naive: prefer actions that move us toward the target.
        # This is a placeholder for a real pathfinding/planning skill.
        action_names = ["Down", "Left", "Right", "Up", "A", "B", "Start", "Noop"]
        preferred = [0, 1, 2, 3]
        for action in preferred:
            if action < len(action_names):
                return action
        return base_policy_action
