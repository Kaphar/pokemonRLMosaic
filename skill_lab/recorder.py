"""Input recorder for replaying emulator sessions.

Records every action taken by each environment so you can:
1. Replay inputs to see what caused a glitch
2. Save the exact sequence that led to a specific state
3. Debug training issues visually

Usage:
    recorder = InputRecorder(session_path)
    recorder.record(env_index=0, step=42, action=3)
    recorder.save()  # Writes to session_path/inputs_env0.json
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class InputRecorder:
    """Records all inputs for each environment."""

    def __init__(self, session_path: Path, init_state: str = "") -> None:
        self.session_path = Path(session_path)
        self.session_path.mkdir(parents=True, exist_ok=True)
        self.init_state = init_state
        self.start_time = time.time()

        # Per-environment action logs: {env_index: [(step, action, timestamp), ...]}
        self.logs: dict[int, list[dict[str, Any]]] = {}

    def record(self, env_index: int, step: int, action: int, masked: bool = False) -> None:
        """Record a single action for an environment."""
        if env_index not in self.logs:
            self.logs[env_index] = []

        self.logs[env_index].append({
            "step": step,
            "action": action,
            "masked": masked,
            "time": time.time() - self.start_time,
        })

    def save(self, env_index: int | None = None) -> Path:
        """Save recorded inputs to a JSON file.

        Args:
            env_index: If provided, save only this env. Otherwise save all.

        Returns:
            Path to the saved file.
        """
        if env_index is not None:
            data = {
                "env_index": env_index,
                "init_state": self.init_state,
                "total_actions": len(self.logs.get(env_index, [])),
                "actions": self.logs.get(env_index, []),
            }
            path = self.session_path / f"inputs_env{env_index:03d}.json"
        else:
            data = {
                "init_state": self.init_state,
                "total_envs": len(self.logs),
                "envs": {
                    str(idx): {
                        "total_actions": len(actions),
                        "actions": actions,
                    }
                    for idx, actions in self.logs.items()
                },
            }
            path = self.session_path / "inputs_all.json"

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        return path

    def get_action_count(self, env_index: int) -> int:
        return len(self.logs.get(env_index, []))

    def reset(self, env_index: int) -> None:
        """Clear the log for a specific environment (after reset/kill)."""
        self.logs[env_index] = []


def replay_inputs(state_path: str, actions_path: str, speed: float = 1.0):
    """Replay a recorded input sequence.

    This is a standalone function you can call to visually replay
    what an emulator did. It loads the state and steps through
    the recorded actions.

    Args:
        state_path: Path to the .state file to load
        actions_path: Path to the inputs JSON file
        speed: Playback speed multiplier (1.0 = normal)
    """
    from pyboy import PyBoy
    import json

    with open(actions_path, "r") as f:
        data = json.load(f)

    actions = data.get("actions", [])
    if not actions:
        print("No actions to replay")
        return

    print(f"Replaying {len(actions)} actions from {actions_path}")
    print(f"Initial state: {state_path}")
    print("Press Ctrl+C to stop replay")

    # You would integrate this with PyBoy here
    # For now, this is a template showing the concept
    # pyboy = PyBoy("PokemonRed.gb")
    # pyboy.load_state(state_path)
    # for entry in actions:
    #     action = entry["action"]
    #     # Press the button corresponding to this action
    #     # Advance frames
    #     pass