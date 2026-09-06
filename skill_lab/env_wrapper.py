"""Gymnasium Wrapper with early termination and per-env directives."""

from __future__ import annotations

from typing import Any

import gymnasium
import numpy as np
from pyboy.utils import WindowEvent

from skill_lab.milestones import MilestoneTracker


class SkillLabWrapper(gymnasium.Wrapper):
    """Wraps RedGymEnv with action masking, milestones, and early termination."""

    def __init__(self, env, config: dict[str, Any]) -> None:
        super().__init__(env)

        # --- Configuration ---
        self.disable_start = config.get("disable_start", True)
        self.disable_select = config.get("disable_select", True)
        self.milestone_reward = config.get("milestone_reward", 5.0)
        self.milestones_path = config.get("milestones_path", None)
        self.speed_bonus_enabled = config.get("speed_bonus", True)
        self.training_mode = config.get("training_mode", "segment")
        self.target_starter = config.get("target_starter", None)
        self.env_index = config.get("env_index", 0)
        self.env_name = config.get("env_name", f"Env{self.env_index}")

        # --- Detect action indices ---
        self.start_action_index = None
        self.select_action_index = None
        self.noop_action_index = env.noop_button_index

        valid_actions = env.valid_actions
        for idx, action in enumerate(valid_actions):
            if action == WindowEvent.PRESS_BUTTON_START:
                self.start_action_index = idx
            elif action == WindowEvent.PRESS_BUTTON_SELECT:
                self.select_action_index = idx

        # Print directive confirmation
        if self.target_starter:
            print(f"[{self.env_name}] Directive: Pick {self.target_starter}")
        else:
            print(f"[{self.env_name}] Directive: Pick any starter")

        masked = []
        if self.disable_start and self.start_action_index is not None:
            masked.append("START")
        if self.disable_select and self.select_action_index is not None:
            masked.append("SELECT")
        if masked:
            print(f"[{self.env_name}] Masking: {', '.join(masked)}")

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
        self.last_milestone_step = 0
        self.objective_met = False

    def _should_mask(self, action: int) -> bool:
        if self.disable_start and action == self.start_action_index:
            return True
        if self.disable_select and action == self.select_action_index:
            return True
        return False

    def _check_starter_status(self) -> tuple[str, int]:
        """Check if a starter has been picked and whether it matches the target."""
        # Read party size
        party_size = self.env.unwrapped.pyboy.memory[0xD163]

        if party_size == 0:
            return "none", 0

        # Read first pokemon's species (INTERNAL ID, not Pokédex number!)
        species = self.env.unwrapped.pyboy.memory[0xD16B]

        # Internal species IDs in Pokemon Red memory
        starter_ids = {
            0x99: "Bulbasaur",   # 153 decimal
            0xB0: "Charmander",  # 176 decimal
            0xB1: "Squirtle",    # 177 decimal
        }
        starter_name = starter_ids.get(species, f"Unknown(0x{species:02X})")

        if self.target_starter is None:
            return "any", species
        elif starter_name == self.target_starter:
            return "correct", species
        else:
            return "wrong", species

    def step(self, action: int):
        """Intercept action, apply masking, check for early termination."""

        original_action = action
        if self._should_mask(action):
            action = self.noop_action_index
            self.masked_action_count += 1

        # Execute in real environment
        observation, reward, terminated, truncated, info = self.env.step(action)

        # Add milestone rewards with speed bonus
        if self.milestone_tracker is not None:
            milestone_reward = self.milestone_tracker.check_and_reward(self.env)
            if milestone_reward > 0:
                steps_since_last = self.env.unwrapped.step_count - self.last_milestone_step
                if self.speed_bonus_enabled and steps_since_last > 0:
                    speed_multiplier = max(1.0, 3.0 - (steps_since_last / 100.0))
                    milestone_reward *= speed_multiplier

                reward += milestone_reward
                self.total_milestone_reward += milestone_reward
                self.last_milestone_step = self.env.unwrapped.step_count
                info["milestone_reward"] = milestone_reward

        # ========================================
        # EARLY TERMINATION: Check starter status
        # ========================================
        if not self.objective_met:
            status, species = self._check_starter_status()
            
            if status == "correct":
                self.objective_met = True
                reward += 10.0
                terminated = True
                info["objective_success"] = True
                info["objective_steps"] = self.env.unwrapped.step_count
                info["objective_directive"] = self.target_starter or "any"
                info["objective_env_name"] = self.env_name

            elif status == "wrong":
                self.objective_met = True
                reward -= 5.0
                terminated = True
                info["objective_success"] = False
                info["objective_steps"] = self.env.unwrapped.step_count
                info["objective_directive"] = self.target_starter or "any"
                info["objective_env_name"] = self.env_name

            elif status == "any":
                self.objective_met = True
                reward += 5.0
                terminated = True
                info["objective_success"] = True
                info["objective_steps"] = self.env.unwrapped.step_count
                info["objective_directive"] = "any"
                info["objective_env_name"] = self.env_name

        info["masked_action"] = (original_action != action)
        info["objective_met"] = self.objective_met

        return observation, reward, terminated, truncated, info


    def reset(self, **kwargs):
        """Reset environment and milestone tracker."""
        observation, info = self.env.reset(**kwargs)

        if self.milestone_tracker is not None:
            self.milestone_tracker.reset(self.env)

        self.masked_action_count = 0
        self.total_milestone_reward = 0.0
        self.last_milestone_step = 0
        self.objective_met = False  # Reset objective flag

        return observation, info

    # Expose wrapped attributes
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