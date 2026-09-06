"""Gymnasium Wrapper for the Pokemon Red environment.

Fixes:
1. Action masking for Start/Select (dynamically detects indices)
2. Milestone rewards (with proper initialization on reset)
3. Exposes wrapped attributes to fix gymnasium deprecation warnings
"""

from __future__ import annotations

from typing import Any

import gymnasium
import numpy as np
from pyboy.utils import WindowEvent

from skill_lab.milestones import MilestoneTracker


class SkillLabWrapper(gymnasium.Wrapper):
    """Wraps RedGymEnv with action masking and milestone tracking."""

    def __init__(self, env, config: dict[str, Any]) -> None:
        super().__init__(env)

        # --- Configuration ---
        self.disable_start_select = config.get("disable_start_select", True)
        self.milestone_reward = config.get("milestone_reward", 5.0)
        self.milestones_path = config.get("milestones_path", None)
        self.speed_bonus_enabled = config.get("speed_bonus", True)
        self.last_milestone_step = 0

        # --- Dynamically detect Start/Select action indices ---
        self.start_action_index = None
        self.select_action_index = None
        self.noop_action_index = env.noop_button_index  # Use the env's built-in NOOP index

        valid_actions = env.valid_actions
        for idx, action in enumerate(valid_actions):
            if action == WindowEvent.PRESS_BUTTON_START:
                self.start_action_index = idx
            elif action == WindowEvent.PRESS_BUTTON_SELECT:
                self.select_action_index = idx

        if self.disable_start_select:
            print(f"[SkillLab]   NOOP index:   {self.noop_action_index}")
            print(f"[SkillLab]   START index:  {self.start_action_index} (will be masked)")
            print(f"[SkillLab]   SELECT index: {self.select_action_index} (will be masked)")
        else:
            print(f"[SkillLab] Action masking DISABLED")

        # --- Milestone Tracker ---
        self.milestone_tracker: MilestoneTracker | None = None
        if self.milestones_path:
            self.milestone_tracker = MilestoneTracker(
                milestones_path=self.milestones_path,
                reward_per_milestone=self.milestone_reward,
            )

        # --- Stats ---
        self.masked_action_count = 0
        self.total_milestone_reward = 0.0

    def step(self, action: int):
        """Intercept the action, apply masking, then step the real env."""

        # ========================================
        # STEP 1: ACTION MASKING
        # ========================================
        original_action = action

        if self.disable_start_select:
            if action == self.start_action_index or action == self.select_action_index:
                action = self.noop_action_index
                self.masked_action_count += 1

                # Debug: print every time we mask (remove later for performance)
                if self.masked_action_count <= 5:
                    print(f"[SkillLab] MASKED action {original_action} -> NOOP ({self.masked_action_count} total masked)")

        # ========================================
        # STEP 2: EXECUTE IN THE REAL ENVIRONMENT
        # ========================================
        observation, reward, terminated, truncated, info = self.env.step(action)

        # ========================================
        # STEP 3: ADD MILESTONE REWARDS + SPEED BONUS
        # ========================================
        if self.milestone_tracker is not None:
            milestone_reward = self.milestone_tracker.check_and_reward(self.env)
            if milestone_reward > 0:
                # SPEED BONUS: fewer steps since last milestone = more reward
                steps_since_last = self.env.unwrapped.step_count - self.last_milestone_step
                if self.speed_bonus_enabled and steps_since_last > 0:
                    # Bonus decreases as steps increase (max 2x reward for very fast completion)
                    speed_multiplier = max(1.0, 3.0 - (steps_since_last / 100.0))
                    milestone_reward *= speed_multiplier
                    print(f"[Speed] Milestone in {steps_since_last} steps → x{speed_multiplier:.1f} bonus")

                reward += milestone_reward
                self.total_milestone_reward += milestone_reward
                self.last_milestone_step = self.env.unwrapped.step_count
                info["milestone_reward"] = milestone_reward

        # ========================================
        # STEP 4: ADD DEBUG INFO
        # ========================================
        info["masked_action"] = (original_action != action)
        info["original_action"] = original_action

        return observation, reward, terminated, truncated, info

    def reset(self, **kwargs):
        """Reset the environment and milestone tracker."""
        observation, info = self.env.reset(**kwargs)

        # KEY FIX: Pass env to milestone tracker so it can read
        # current memory state and mark already-set events as achieved
        if self.milestone_tracker is not None:
            self.milestone_tracker.reset(self.env)

        self.masked_action_count = 0
        self.total_milestone_reward = 0.0

        return observation, info

    # ========================================
    # Expose wrapped attributes to fix gymnasium warnings
    # ========================================
    @property
    def step_count(self):
        return self.env.unwrapped.step_count

    @property
    def current_map_id(self):
        return self.env.unwrapped.current_map_id

    @property
    def current_level_sum(self):
        return self.env.unwrapped.current_level_sum

    def read_hp_fraction(self):
        return self.env.unwrapped.read_hp_fraction()

    @property
    def noop_button_index(self):
        return self.env.unwrapped.noop_button_index

    @property
    def valid_actions(self):
        return self.env.unwrapped.valid_actions

    @property
    def pyboy(self):
        return self.env.unwrapped.pyboy

    def get_milestone_progress(self) -> dict[str, Any]:
        """Get current milestone progress (for UI display)."""
        if self.milestone_tracker:
            return self.milestone_tracker.get_progress()
        return {"total_milestones": 0, "achieved": 0, "achieved_names": []}