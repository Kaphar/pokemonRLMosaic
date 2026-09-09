"""Scripted Pokemon naming system.

Detects the naming screen via memory and executes a hardcoded
button sequence to spell out a name from a config file.

Usage:
    namer = Namer("skill_lab/names.json")
    action = namer.get_action(env, model_action)
    # If on naming screen: returns scripted action
    # If not: returns model_action unchanged
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pyboy.utils import WindowEvent


# Pokemon Red naming screen alphabet layout (uppercase)
# Cursor starts at A (row=0, col=0)
# Navigate with UP/DOWN/LEFT/RIGHT, confirm with A
ALPHABET_GRID = [
    list("ABCDEFGHIJ"),
    list("KLMNOPQRST"),
    list("UVWXYZ():"),
    list(";[]' "),
    list("-.!?!"),  # Row with special chars
    list("END"),     # Special row - END confirms the name
]

# Map each character to its (row, col) position
CHAR_POSITIONS = {}
for row_idx, row in enumerate(ALPHABET_GRID):
    for col_idx, char in enumerate(row):
        CHAR_POSITIONS[char] = (row_idx, col_idx)

# Add lowercase if you want (switch with SELECT)
LOWERCASE_GRID = [
    list("abcdefghij"),
    list("klmnopqrst"),
    list("uvwxyz"),
]


class Namer:
    """Scripted naming system for Pokemon."""

    def __init__(self, names_config_path: str | Path) -> None:
        self.names_config_path = Path(names_config_path)
        self.names: dict[str, str] = {}

        # Load names config
        if self.names_config_path.exists():
            with open(self.names_config_path, "r") as f:
                data = json.load(f)
            self.names = data.get("names", {})
            print(f"[Namer] Loaded {len(self.names)} names from {self.names_config_path}")
        else:
            print(f"[Namer] WARNING: {self.names_config_path} not found")

        # Per-environment state
        self.env_state: dict[int, dict[str, Any]] = {}

    def get_name_for_env(self, env_index: int, directive: str | None = None) -> str:
        """Get the name for a specific environment.

        Priority:
        1. env_index-specific name (e.g., "0": "ASH")
        2. directive-specific name (e.g., "Charmander": "EMBER")
        3. Default name (e.g., "default": "RED")
        """
        idx_str = str(env_index)
        if idx_str in self.names:
            return self.names[idx_str]
        if directive and directive in self.names:
            return self.names[directive]
        return self.names.get("default", "RED")

    def is_on_naming_screen(self, env) -> bool:
        """Check if the game is currently on the naming screen.

        You'll need to find the right memory address for this!
        Use your inspector to identify it.
        """
        # TODO: Replace with actual address from your inspector
        # Example: naming_screen_flag = env.pyboy.memory[0xCC35]
        # return naming_screen_flag != 0

        # Placeholder - you MUST implement this
        return False

    def get_cursor_position(self, env) -> tuple[int, int]:
        """Get the current cursor position (row, col) on the naming screen.

        You'll need to find the right memory address for this!
        """
        # TODO: Replace with actual address from your inspector
        # Example:
        # cursor_byte = env.pyboy.memory[0xCC39]
        # row = cursor_byte // 10  # Adjust based on actual layout
        # col = cursor_byte % 10
        # return (row, col)

        # Placeholder - you MUST implement this
        return (0, 0)

    def get_typed_length(self, env) -> int:
        """Get how many characters have been typed so far."""
        # TODO: Read the name buffer and count non-zero bytes
        # Example:
        # name_buffer_start = 0xC000
        # length = 0
        # for i in range(10):  # Max name length
        #     if env.pyboy.memory[name_buffer_start + i] == 0x50:  # END marker
        #         break
        #     length += 1
        # return length

        # Placeholder - you MUST implement this
        return 0

    def _navigate_to_char(self, current_pos: tuple[int, int], target_pos: tuple[int, int]) -> int:
        """Calculate the button to press to move from current to target position.

        Returns a WindowEvent for the button to press.
        """
        curr_row, curr_col = current_pos
        tgt_row, tgt_col = target_pos

        # Simple navigation: move horizontally first, then vertically
        if curr_col < tgt_col:
            return WindowEvent.PRESS_ARROW_RIGHT
        elif curr_col > tgt_col:
            return WindowEvent.PRESS_ARROW_LEFT
        elif curr_row < tgt_row:
            return WindowEvent.PRESS_ARROW_DOWN
        elif curr_row > tgt_row:
            return WindowEvent.PRESS_ARROW_UP
        else:
            # We're at the target - press A to confirm
            return WindowEvent.PRESS_BUTTON_A

    def get_action(self, env, env_index: int, model_action: int, directive: str | None = None) -> int:
        """Get the action to execute.

        If on naming screen: returns scripted action to type the name
        If not: returns model_action unchanged
        """
        if not self.is_on_naming_screen(env):
            return model_action  # Not on naming screen, use model's action

        # Initialize state for this env if needed
        if env_index not in self.env_state:
            target_name = self.get_name_for_env(env_index, directive)
            self.env_state[env_index] = {
                "target_name": target_name.upper(),
                "char_index": 0,  # Which character we're typing
                "navigating": True,  # Are we moving to the letter or confirming?
            }
            print(f"[Namer] Env {env_index} will type: {target_name}")

        state = self.env_state[env_index]
        target_name = state["target_name"]
        char_index = state["char_index"]

        # Check if we're done typing
        if char_index >= len(target_name):
            # Navigate to END and press A
            end_pos = CHAR_POSITIONS.get("END", (5, 0))
            cursor_pos = self.get_cursor_position(env)
            if cursor_pos == end_pos:
                # We're at END, press A to confirm
                print(f"[Namer] Env {env_index} finished typing: {target_name}")
                # Clean up state
                del self.env_state[env_index]
                return self._window_event_to_action_index(env, WindowEvent.PRESS_BUTTON_A)
            else:
                # Navigate to END
                btn = self._navigate_to_char(cursor_pos, end_pos)
                return self._window_event_to_action_index(env, btn)

        # Get the target character
        target_char = target_name[char_index]
        if target_char not in CHAR_POSITIONS:
            print(f"[Namer] WARNING: Character '{target_char}' not in alphabet grid")
            # Skip this character
            state["char_index"] += 1
            return self._window_event_to_action_index(env, WindowEvent.PRESS_BUTTON_NOTHING if hasattr(WindowEvent, 'PRESS_BUTTON_NOTHING') else 0)

        target_pos = CHAR_POSITIONS[target_char]
        cursor_pos = self.get_cursor_position(env)

        # Navigate to the character and press A
        btn = self._navigate_to_char(cursor_pos, target_pos)

        # If we just pressed A (confirmed the letter), advance to next character
        if btn == WindowEvent.PRESS_BUTTON_A and cursor_pos == target_pos:
            state["char_index"] += 1
            print(f"[Namer] Env {env_index} typed '{target_char}' ({char_index + 1}/{len(target_name)})")

        return self._window_event_to_action_index(env, btn)

    def _window_event_to_action_index(self, env, window_event) -> int:
        """Convert a WindowEvent to the action index used by the environment."""
        valid_actions = env.valid_actions
        for idx, action in enumerate(valid_actions):
            if action == window_event:
                return idx
        return env.noop_button_index  # Fallback to NOOP