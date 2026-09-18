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

from skill_lab.config import (
    SAVE_ON_CATCH_ENABLED,
    SAVE_ON_CATCH_MIN_DV,
)
from skill_lab.milestones import MilestoneTracker
from skill_lab.party_reader import Gen1PartyReader, PyBoyMemoryReader
from skill_lab.rewards import calculate_starter_reward, medium_reward, wrong_choice_penalty


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
        self.milestone_reward = config.get("milestone_reward", medium_reward)
        self.milestones_path = config.get("milestones_path", None)
        self.speed_bonus_enabled = config.get("speed_bonus", True)
        self.training_mode = config.get("training_mode", "segment")
        self.target_starter = config.get("target_starter", None)
        self.env_index = config.get("env_index", 0)
        self.env_name = config.get("env_name", f"Env{self.env_index}")
        self.env_dir = config.get("env_dir")
        self.init_state = config.get("init_state", "")
        self.rom_path = config.get("rom_path", "")
        self.action_freq = int(config.get("action_freq", 24))
        self.save_objective_states = config.get("save_objective_states", True)
        self.perfect_sound_enabled = config.get("perfect_sound", True)
        
        # Action masking for B button (from stage config)
        self.disable_B = config.get("disable_B", False)
        self.B_action_index = None
        
        # Catch/train directives from profile
        self.catch_directive = config.get("catch_directive", [])
        self.train_directive = config.get("train_directive", [])
        self.save_on_catch = config.get("save_on_catch", False)
        self.reset_on_catch = config.get("reset_on_catch", False)

        # Save on catch settings
        self.save_on_catch_enabled = config.get("save_on_catch_enabled", SAVE_ON_CATCH_ENABLED)
        self.save_on_catch_min_dv = config.get("save_on_catch_min_dv", SAVE_ON_CATCH_MIN_DV)

        # Track party size to detect new catches
        self._previous_party_size = 0

        # --- Detect action indices ---
        self.start_action_index = None
        self.select_action_index = None
        self.noop_action_index = env.noop_button_index
        self.B_action_index = None

        valid_actions = env.valid_actions
        for idx, action in enumerate(valid_actions):
            if action == WindowEvent.PRESS_BUTTON_START:
                self.start_action_index = idx
            elif action == WindowEvent.PRESS_BUTTON_SELECT:
                self.select_action_index = idx
            elif action == WindowEvent.PRESS_BUTTON_B:
                self.B_action_index = idx

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
        if self.disable_B and self.B_action_index is not None:
            masked.append("B")
        if masked:
            print(f"[{self.env_name}] Masking: {', '.join(masked)}")
        
        # Print catch/train directives
        if self.catch_directive:
            print(f"[{self.env_name}] Catch directive: {self.catch_directive}")
        if self.train_directive:
            print(f"[{self.env_name}] Train directive: {self.train_directive}")

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

        # --- Input Replay ---
        # Optional recorded input sequence replayed from the init state. Once the
        # sequence is exhausted the model (or human) takes over automatically.
        self.input_replay_path = config.get("input_replay", "")
        self._replay_actions: list[int] = []
        self._replay_events: list[dict[str, Any]] = []
        self._replay_total_frames = 0
        self._replay_action_freq = self.action_freq
        self._replay_noop_action = self.noop_action_index
        self._replay_state_path: Path | None = None
        self._replay_frame = 0
        self._replay_index = 0
        self._original_run_action = None
        self._load_input_replay()

    # --- Input Replay ---

    def _load_input_replay(self) -> None:
        """Load a recorded input sequence from the path in this env's settings.

        Supports both the step-level ``actions`` list and the plugin/frame-exact
        ``input_events`` list produced by :mod:`skill_lab.emulator_with_debug`.
        When frame-exact events are available the replay drives the emulator with
        those exact events (matching the original recording deterministically);
        otherwise it falls back to replaying the step-level action indices through
        the normal action cycle.
        """
        if not self.input_replay_path:
            return
        replay_path = Path(self.input_replay_path)
        if not replay_path.is_absolute() and self.env_dir:
            replay_path = Path(self.env_dir) / replay_path
        if not replay_path.exists():
            print(f"[{self.env_name}] Input replay file not found: {replay_path}")
            return
        try:
            with open(replay_path, "r", encoding="utf-8") as replay_file:
                data = json.load(replay_file)
            self._replay_noop_action = int(
                data.get("noop_action", self.noop_action_index)
            )
            entries = data.get("actions", [])
            self._replay_actions = []
            for entry in entries:
                if isinstance(entry, dict):
                    if entry.get("masked", False):
                        self._replay_actions.append(self._replay_noop_action)
                    else:
                        self._replay_actions.append(
                            int(entry.get("action", entry.get("requested_action", 0)))
                        )
                else:
                    self._replay_actions.append(int(entry))
            self._replay_action_freq = int(data.get("action_freq", self.action_freq))
            if self._replay_action_freq < 1:
                raise ValueError("Replay action frequency must be positive")
            # Match emulator_with_debug.load_replay(): recordings without an
            # event list still take the plugin path with generated events.
            from skill_lab.emulator_with_debug import generate_input_events
            self._replay_events = data.get("input_events", []) or generate_input_events(
                self._replay_actions,
                self._replay_action_freq,
                self._replay_noop_action,
            )
            from skill_lab.emulator_with_debug import resolve_recording_path
            self._replay_state_path = resolve_recording_path(data.get("init_state"))
            self._replay_total_frames = len(self._replay_actions) * self._replay_action_freq
            if self._replay_events:
                print(
                    f"[{self.env_name}] Loaded input replay (frame-exact): "
                    f"{len(self._replay_actions)} actions / {len(self._replay_events)} events "
                    f"from {replay_path}"
                )
            else:
                print(
                    f"[{self.env_name}] Loaded input replay: "
                    f"{len(self._replay_actions)} actions from {replay_path}"
                )
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as error:
            print(f"[{self.env_name}] Failed to load input replay {replay_path}: {error}")
            self._replay_actions = []
            self._replay_events = []

    def _driven_pyboy(self):
        """Return the real PyBoy object (unwrap the plugin recording proxy)."""
        pyboy = self.env.unwrapped.pyboy
        return getattr(pyboy, "_pyboy", pyboy)

    def _install_frame_exact_replay(self) -> None:
        """Route the env's action cycle through frame-exact event replay."""
        if self._replay_events and self._original_run_action is None:
            self._original_run_action = self.env.run_action_on_emulator
            self.env.run_action_on_emulator = self._frame_exact_run_action

    def _restore_run_action(self) -> None:
        """Restore the env's native action cycle after replay finishes."""
        if self._original_run_action is not None:
            self.env.run_action_on_emulator = self._original_run_action
            self._original_run_action = None

    def _frame_exact_run_action(self, action) -> None:
        """Advance one action cycle using the recording's exact input events.

        Replaces the env's ``run_action_on_emulator`` while a frame-exact replay
        is in progress. Each call drives exactly ``action_freq`` frames, sending
        the recorded events at their absolute frame offsets so the emulator
        reaches the same state as the original run. When the events are
        exhausted this falls back to the native action cycle so the model can
        take over.
        """
        if not self._replay_events or self._replay_frame >= self._replay_total_frames:
            original_run_action = self._original_run_action
            self._restore_run_action()
            if original_run_action is None:
                raise RuntimeError("Frame-exact replay lost the native action cycle")
            return original_run_action(action)
        try:
            from skill_lab.emulator_with_debug import _prime_emulator, replay_frame_by_frame

            if self._replay_frame == 0 and self._replay_state_path is not None:
                _prime_emulator(
                    self._driven_pyboy(),
                    self._replay_state_path,
                    self._replay_actions,
                    self._replay_action_freq,
                    self._replay_noop_action,
                    # num_actions=len(self._replay_actions), # setting lower number to cut the cost of priming, but this may cause issues if the replay is longer than expected, 8 didn't work, but 24 did.
                    num_actions=20,
                )

            replay_frame_by_frame(
                self._driven_pyboy(),
                self._replay_events,
                self._replay_total_frames,
                render=True,
                start_frame=self._replay_frame,
                max_frames=self._replay_action_freq,
            )
            self._replay_frame += self._replay_action_freq
        except Exception as error:
            print(
                f"[{self.env_name}] Frame-exact replay failed, falling back to "
                f"native action cycle: {error}"
            )
            original_run_action = self._original_run_action
            self._restore_run_action()
            if original_run_action is None:
                raise RuntimeError("Frame-exact replay lost the native action cycle") from error
            return original_run_action(action)

    def has_replay(self) -> bool:
        """Return True while there are still replay actions to consume."""
        return self._replay_index < len(self._replay_actions)

    def consume_replay_action(self) -> int | None:
        """Return the next replayed action (and advance) or None when exhausted.

        During frame-exact replay the actual emulator input is driven by
        :meth:`_frame_exact_run_action`, but callers still need the action index
        for logging / rollout-buffer bookkeeping, so this still yields the
        recorded step action while a replay is in progress.
        """
        if self._replay_index < len(self._replay_actions):
            action = self._replay_actions[self._replay_index]
            self._replay_index += 1
            return action
        return None

    def _save_objective_state(self, check_dv_threshold: bool = True) -> bool:
        """Save state and inputs before DummyVecEnv automatically resets us.
        
        Args:
            check_dv_threshold: If True, only save if DVs meet minimum threshold.
        """
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

        # Check DV threshold if required (for starter picks that aren't the target)
        if check_dv_threshold and self.save_on_catch_enabled:
            if not all(dv >= self.save_on_catch_min_dv for dv in dvs):
                print(
                    f"[{self.env_name}] Skipped saving {pokemon_name} - DVs {dvs} below threshold {self.save_on_catch_min_dv}"
                )
                return False

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
                "rom": self.rom_path,
                "action_freq": self.action_freq,
                "noop_action": self.noop_action_index,
                "total_actions": len(self._episode_actions),
                "actions": self._episode_actions,
                "source": "input_recorder",
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

    def _save_caught_pokemon(self, pokemon: dict, slot: int) -> bool:
        """Save state and inputs when a Pokemon is caught, if DVs meet threshold."""
        if not self.save_on_catch_enabled or not self.env_dir:
            return False

        # Get DVs for the caught Pokemon
        dvs = (
            int(pokemon.get("ivAttack", 0)),
            int(pokemon.get("ivDefense", 0)),
            int(pokemon.get("ivSpeed", 0)),
            int(pokemon.get("ivSpAttack", 0)),
        )

        # Check if all DVs meet the minimum threshold
        if not all(dv >= self.save_on_catch_min_dv for dv in dvs):
            return False

        pokemon_name = pokemon.get("speciesName", "Unknown")
        suffix = "PERFECT" if all(dv == 15 for dv in dvs) else "-".join(map(str, dvs))
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(pokemon_name)).strip("._")
        base_name = f"{safe_name} - {suffix} (slot{slot+1})"

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
                "rom": self.rom_path,
                "action_freq": self.action_freq,
                "noop_action": self.noop_action_index,
                "total_actions": len(self._episode_actions),
                "actions": self._episode_actions,
                "source": "input_recorder",
                "caught_pokemon": {
                    "slot": slot,
                    "species": pokemon_name,
                    "species_id": int(pokemon.get("speciesID", 0)),
                    "dvs": dvs,
                    "level": int(pokemon.get("level", 0)),
                },
            }, inputs_file, indent=2)

        print(
            f"[{self.env_name}] 🎉 Saved caught Pokemon: {pokemon_name} "
            f"DVs={dvs} at slot {slot+1} -> {state_path}"
        )
        if suffix == "PERFECT" and self.perfect_sound_enabled:
            try:
                sound_path = (
                    Path(__file__).resolve().parent / "assets" / "sound" / "mario_coin.mp3"
                )
                os.startfile(str(sound_path))
            except Exception as error:
                print(f"[{self.env_name}] Warning: could not play perfect-DV sound: {error}")
        return True

    def _check_for_new_catches(self) -> None:
        """Check if any new Pokemon were caught and save if DVs meet threshold."""
        party = self.party_reader.read_party({
            "partyAddr": Gen1PartyReader.PARTY_ADDRESS,
            "partySlotsCounterAddr": Gen1PartyReader.PARTY_SIZE_ADDRESS,
            "partySpeciesAddr": Gen1PartyReader.PARTY_SPECIES_ADDRESS,
            "partyNicknamesAddr": Gen1PartyReader.PARTY_NICKNAMES_ADDRESS,
        })
        if not party:
            self._previous_party_size = 0
            return

        current_size = len(party)
        if current_size > self._previous_party_size:
            # New Pokemon caught! Check each new slot
            for slot in range(self._previous_party_size, current_size):
                if slot < len(party):
                    self._save_caught_pokemon(party[slot], slot)
        self._previous_party_size = current_size

    def _read_starter_dvs(self) -> tuple[int, int, int, int] | None:
        """Read the four stored DVs for the first party Pokemon."""
        party = self.party_reader.read_party({
            "partyAddr": Gen1PartyReader.PARTY_ADDRESS,
            "partySlotsCounterAddr": Gen1PartyReader.PARTY_SIZE_ADDRESS,
            "partySpeciesAddr": Gen1PartyReader.PARTY_SPECIES_ADDRESS,
            "partyNicknamesAddr": Gen1PartyReader.PARTY_NICKNAMES_ADDRESS,
        })
        if not party:
            return None

        pokemon = party[0]
        return (
            int(pokemon.get("ivAttack", 0)),
            int(pokemon.get("ivDefense", 0)),
            int(pokemon.get("ivSpeed", 0)),
            int(pokemon.get("ivSpAttack", 0)),
        )

    def _should_mask(self, action: int) -> bool:
        if self.disable_start and action == self.start_action_index:
            return True
        if self.disable_select and action == self.select_action_index:
            return True
        if self.disable_B and action == self.B_action_index:
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
            "action": int(action),
            "requested_action": int(original_action),
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
                dvs = self._read_starter_dvs()
                if dvs is not None and self._save_objective_state(check_dv_threshold=False):
                    self.objective_met = True
                    reward += calculate_starter_reward(*dvs)
                    # NOTE: Do NOT terminate on correct starter - continue playing!
                    print(f"[{self.env_name}] ✅ CORRECT starter (species=0x{species:02X}) at step {self.env.unwrapped.step_count}")
                    info["objective_success"] = True
                    info["objective_steps"] = self.env.unwrapped.step_count
                    info["objective_directive"] = self.target_starter or "any"
                    info["objective_env_name"] = self.env_name

            elif status == "wrong":
                # Wrong starter picked - check if we should save based on DVs
                dvs = self._read_starter_dvs()
                if dvs is not None:
                    self.objective_met = True
                    # Save if DVs meet threshold (for potential replay on correct profile)
                    saved = self._save_objective_state(check_dv_threshold=True)
                    # Apply wrong choice penalty but NOT the starter DV reward
                    reward += wrong_choice_penalty
                    terminated = True
                    if saved:
                        print(f"[{self.env_name}] ❌ WRONG starter (species=0x{species:02X}) at step {self.env.unwrapped.step_count} → saved (DVs meet threshold)")
                    else:
                        print(f"[{self.env_name}] ❌ WRONG starter (species=0x{species:02X}) at step {self.env.unwrapped.step_count} → not saved (DVs below threshold)")
                    info["objective_success"] = False
                    info["objective_steps"] = self.env.unwrapped.step_count
                    info["objective_directive"] = self.target_starter or "any"
                    info["objective_env_name"] = self.env_name

            elif status == "any":
                dvs = self._read_starter_dvs()
                if dvs is not None:
                    # Starter picked - objective met regardless of DV threshold
                    self.objective_met = True
                    # Only save if DVs meet threshold
                    saved = self._save_objective_state(check_dv_threshold=True)
                    if saved:
                        reward += calculate_starter_reward(*dvs)
                        # NOTE: Do NOT terminate on any starter - continue playing!
                        print(f"[{self.env_name}] ✅ Picked a starter (species=0x{species:02X}) at step {self.env.unwrapped.step_count}")
                        info["objective_success"] = True
                        info["objective_steps"] = self.env.unwrapped.step_count
                        info["objective_directive"] = "any"
                        info["objective_env_name"] = self.env_name
                    else:
                        # DVs below threshold - don't save, but objective is still met
                        print(f"[{self.env_name}] ✅ Picked a starter (species=0x{species:02X}) but DVs below threshold - not saved")
                        info["objective_success"] = True
                        info["objective_steps"] = self.env.unwrapped.step_count
                        info["objective_directive"] = "any"
                        info["objective_env_name"] = self.env_name

        info["masked_action"] = (original_action != action)
        info["objective_met"] = self.objective_met

        # Check for new Pokemon catches (after step to catch the updated party)
        self._check_for_new_catches()

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
        self._replay_index = 0
        self._replay_frame = 0
        self._previous_party_size = 0

        # The standalone plugin replay loads the recording's state before
        # priming. Do the same instead of relying on per-environment defaults.
        if self._replay_events and self._replay_state_path is not None:
            with self._replay_state_path.open("rb") as state_file:
                self._driven_pyboy().load_state(state_file)

        # Restore a native action cycle left over from a previous (possibly
        # interrupted) replay so step bookkeeping stays consistent.
        self._restore_run_action()

        # Install the frame-exact replay hook when the recording provides
        # absolute frame-level input events. The plugin recorder captures exact
        # frame offsets so no emulator priming/warming is needed — the events
        # alone drive deterministic replay from the init state.
        if self._replay_events:
            self._install_frame_exact_replay()

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

    def save_recording(self, actions, output_path):
        return self.env.unwrapped.save_recording(actions, output_path)