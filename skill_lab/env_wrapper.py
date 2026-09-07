"""Gymnasium Wrapper with early termination and per-env directives."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import gymnasium
import numpy as np
from pyboy.utils import WindowEvent

from skill_lab.milestones import MilestoneTracker
from skill_lab.party_reader import Gen1PartyReader, PyBoyMemoryReader


class SkillLabWrapper(gymnasium.Wrapper):
    """Wraps RedGymEnv with action masking, milestones, and early termination."""

    STARTER_SPECIES_IDS = {
        0x99: "Bulbasaur",
        0xB0: "Charmander",
        0xB1: "Squirtle",
    }

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
        self.env_dir = config.get("env_dir")
        self.init_state = config.get("init_state", "")
        self.save_objective_states = config.get("save_objective_states", True)
        self.perfect_sound_enabled = config.get("perfect_sound", True)

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
        self._debug_printed = False  # For one-time debug output
        self._episode_actions: list[dict[str, Any]] = []
        self.party_reader = Gen1PartyReader(
            PyBoyMemoryReader(self.env.unwrapped.pyboy.memory)
        )

    def _save_objective_state(self) -> bool:
        """Save state and inputs before DummyVecEnv automatically resets us."""
        if not self.save_objective_states or not self.env_dir:
            return True

        memory = self.env.unwrapped.pyboy.memory
        party_address = Gen1PartyReader.PARTY_ADDRESS
        party_size = int(memory[Gen1PartyReader.PARTY_SIZE_ADDRESS])
        # The species list is updated before the full party record during the
        # starter dialogue. Wait for the record to be copied before reading DVs.
        if party_size == 0 or int(memory[party_address]) == 0:
            return False

        party = self.party_reader.read_party({
            "partyAddr": Gen1PartyReader.PARTY_ADDRESS,
            "partySlotsCounterAddr": Gen1PartyReader.PARTY_SIZE_ADDRESS,
            "partySpeciesAddr": Gen1PartyReader.PARTY_SPECIES_ADDRESS,
            "partyNicknamesAddr": Gen1PartyReader.PARTY_NICKNAMES_ADDRESS,
        })
        if not party:
            return False

        pokemon = party[0]
        pokemon_name = self.STARTER_SPECIES_IDS.get(
            int(pokemon.get("speciesID", 0)), pokemon.get("speciesName", "Unknown")
        )
        dvs = (
            int(pokemon.get("ivAttack", 0)),
            int(pokemon.get("ivDefense", 0)),
            int(pokemon.get("ivSpeed", 0)),
            int(pokemon.get("ivSpAttack", 0)),
        )
        suffix = "PERFECT" if all(dv == 15 for dv in dvs) else "-".join(map(str, dvs))
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(pokemon_name)).strip("._")
        base_name = f"{safe_name} - {suffix}"

        env_dir = Path(self.env_dir)
        states_dir = env_dir / "states"
        inputs_dir = env_dir / "inputs"
        states_dir.mkdir(parents=True, exist_ok=True)
        inputs_dir.mkdir(parents=True, exist_ok=True)

        state_path = states_dir / f"{base_name}.state"
        with state_path.open("wb") as state_file:
            self.env.unwrapped.pyboy.save_state(state_file)

        inputs_path = inputs_dir / f"{base_name}.json"
        with inputs_path.open("w", encoding="utf-8") as inputs_file:
            json.dump({
                "env_index": self.env_index,
                "init_state": self.init_state,
                "total_actions": len(self._episode_actions),
                "actions": self._episode_actions,
            }, inputs_file, indent=2)

        print(
            f"[{self.env_name}] Saved objective state: {state_path} "
            f"and inputs: {inputs_path}"
        )
        if suffix == "PERFECT" and self.perfect_sound_enabled:
            try:
                sound_path = (
                    Path(__file__).resolve().parent / "assets" / "sound" / "mario_coin.mp3"
                )
                os.startfile(str(sound_path))
            except Exception as error:
                # Audio is optional; never let it affect saved perfect states.
                print(f"[{self.env_name}] Warning: could not play perfect-DV sound: {error}")
        return True

    def _should_mask(self, action: int) -> bool:
        if self.disable_start and action == self.start_action_index:
            return True
        if self.disable_select and action == self.select_action_index:
            return True
        return False

    def _check_starter_status(self) -> tuple[str, int]:
        """Check if a starter has been picked and whether it matches the target.
        
        Returns:
            (status, species_id) where status is:
            - "none": No pokemon picked yet
            - "correct": Picked the target starter
            - "wrong": Picked a starter, but not the target
            - "any": Picked any starter (for "default" directive)
        """
        party_size_address = Gen1PartyReader.PARTY_SIZE_ADDRESS
        party_address = Gen1PartyReader.PARTY_ADDRESS
        party_species_address = Gen1PartyReader.PARTY_SPECIES_ADDRESS
        memory = self.env.unwrapped.pyboy.memory
        party_size = int(memory[party_size_address])

        if party_size == 0:
            return "none", 0

        party = self.party_reader.read_party({
            "partyAddr": party_address,
            "partySlotsCounterAddr": party_size_address,
            "partySpeciesAddr": party_species_address,
            "partyNicknamesAddr": Gen1PartyReader.PARTY_NICKNAMES_ADDRESS,
        })
        # The first party record is the authoritative species source for the
        # starter. The auxiliary species list can be stale while the party is
        # being updated, which incorrectly labels Squirtle as a wrong pick.
        species = int(memory[party_address])
        species_name = self.STARTER_SPECIES_IDS.get(
            species,
            party[0].get("speciesName", "Unknown") if party else "Unknown",
        )

        # Keep the raw bytes visible when the party reader disagrees with the
        # party count. This catches stale or incorrect RAM addresses quickly.
        if not self._debug_printed:
            raw_species = int(memory[party_address])
            party_species = int(memory[party_species_address])
            next_species = int(memory[party_address + 0x2C])
            print(
                f"[{self.env_name}] DEBUG: party count @0x{party_size_address:04X}="
                f"{party_size}; species list @0x{party_species_address:04X}="
                f"0x{party_species:02X}; party mon @0x{party_address:04X}="
                f"0x{raw_species:02X}; next mon @0x{party_address + 0x2C:04X}="
                f"0x{next_species:02X}; reader species=0x{species:02X} "
                f"({species_name})"
            )
            self._debug_printed = True

        starter_name = species_name

        if self.target_starter is None:
            # "Pick any" directive: any starter is fine
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

        self._episode_actions.append({
            "step": int(self.env.unwrapped.step_count + 1),
            "action": int(original_action),
            "masked": bool(original_action != action),
        })

        # Execute in real environment
        observation, reward, terminated, truncated, info = self.env.step(action)

        # Add milestone rewards with speed bonus
        if self.milestone_tracker is not None:
            milestone_reward = self.milestone_tracker.check_and_reward(self.env)
            if milestone_reward > 0:
                steps_since_last = self.env.unwrapped.step_count - self.last_milestone_step
                
                # SPEED BONUS: fewer steps = higher multiplier
                if self.speed_bonus_enabled and steps_since_last > 0:
                    speed_multiplier = max(1.0, 3.0 - (steps_since_last / 100.0))
                    milestone_reward *= speed_multiplier
                    print(f"[{self.env_name}] 🚀 Speed bonus! Milestone in {steps_since_last} steps → x{speed_multiplier:.1f}")

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
                if self._save_objective_state():
                    self.objective_met = True
                    reward += 100.0  # Big positive reward for correct pick
                    terminated = True
                    print(f"[{self.env_name}] ✅ CORRECT starter (species=0x{species:02X}) at step {self.env.unwrapped.step_count}")
                    info["objective_success"] = True
                    info["objective_steps"] = self.env.unwrapped.step_count
                    info["objective_directive"] = self.target_starter or "any"
                    info["objective_env_name"] = self.env_name

            elif status == "wrong":
                if self._save_objective_state():
                    self.objective_met = True
                    reward -= 5.0  # Penalty for wrong pick
                    terminated = True
                    print(f"[{self.env_name}] ❌ WRONG starter (species=0x{species:02X}) at step {self.env.unwrapped.step_count} → continuing for inspection")
                    info["objective_success"] = False
                    info["objective_steps"] = self.env.unwrapped.step_count
                    info["objective_directive"] = self.target_starter or "any"
                    info["objective_env_name"] = self.env_name

            elif status == "any":
                if self._save_objective_state():
                    self.objective_met = True
                    reward += 5.0  # Moderate reward for any pick
                    terminated = True
                    print(f"[{self.env_name}] ✅ Picked a starter (species=0x{species:02X}) at step {self.env.unwrapped.step_count}")
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
        self.objective_met = False
        self._debug_printed = False  # Reset debug flag
        self._episode_actions = []

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