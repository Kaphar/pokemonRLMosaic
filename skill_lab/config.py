"""Central configuration for the Skill Lab."""

import json
from pathlib import Path
from typing import Any

from skill_lab.rewards import medium_reward, reward_penalty, small_reward


# --- Paths ---
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = PROJECT_ROOT / "PokemonRed.gb"
DEFAULT_INIT_STATE = PROJECT_ROOT / "init.state"
V2_DIR = PROJECT_ROOT / "v2"
# ROM_PATH = PROJECT_ROOT / "roms" / "pokemon_red.gb"
INIT_STATE_PATH = V2_DIR / "state" / "init.state"
EVENT_JSON_PATH = V2_DIR / "events.json"
PROFILES_DIR = PROJECT_ROOT / "skill_lab" / "profiles"
ENVS_DIR = PROJECT_ROOT / "skill_lab" / "envs"

# --- Emulator Settings ---
ACTION_FREQ = 24          # Frames between actions
TILE_WIDTH = 160          # Game Boy screen width
TILE_HEIGHT = 144         # Game Boy screen height

# TILE_WIDTH = 280
# TILE_HEIGHT = 288

GRID_COLS = 7
GRID_ROWS = 6
DEFAULT_TOTAL_ENV = 56

DEFAULT_MAX_STEPS = 7200  # Max steps per episode
DEFAULT_EMULATOR_SPEED = 0  # 0=auto/turbo, 1=normal, 2=double, etc.

# --- Action Indices (must match v2/red_gym_env_v2.py valid_actions) ---
# These are the standard indices used in PWhiddy's v2:
ACTION_NOOP = 0
ACTION_UP = 1
ACTION_DOWN = 2
ACTION_LEFT = 3
ACTION_RIGHT = 4
ACTION_A = 5
ACTION_B = 6
ACTION_SELECT = 7
ACTION_START = 8

# --- Milestone Rewards ---
MILESTONE_REWARD = medium_reward       # Reward for hitting an event flag
EXPLORATION_REWARD = small_reward       # Small reward for visiting new coordinates

# --- Teacher/Human Guidance ---
REWARD_MODIFIER_PRAISE = medium_reward
REWARD_MODIFIER_SLASH = reward_penalty

PANEL_WIDTH = 220


# --- Catch/Train Directives ---
# Pokemon to prioritize catching/training by species name or ID
CATCH_DIRECTIVES = {
    "charmander_trainer": ["Nidoran♂", "Pidgey", "Pikachu"],
    "squirtle_trainer": [],  # Free exploration
    "bulbasaur_trainer": [],  # Free exploration
    "default": [],
}

TRAIN_DIRECTIVES = {
    "charmander_trainer": ["Nidoran♂", "Pikachu"],
    "squirtle_trainer": [],
    "bulbasaur_trainer": [],
    "default": [],
}


SPECIALIZATION_PRESETS = {
    "default": {"reward_scale": 1.0, "explore_weight": 1.0},
    "trainer": {"reward_scale": 2.0, "explore_weight": 0.5},
    "speedrunner": {"reward_scale": 3.0, "explore_weight": 0.1},
}

# --- Settings Loader ---
SETTINGS_FILE = PROJECT_ROOT / "skill_lab" / "settings.json"


def _load_settings_json() -> dict[str, Any]:
    """Load settings.json if it exists, returning an empty dict on failure."""
    try:
        if SETTINGS_FILE.exists():
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_settings_json(settings: dict[str, Any]) -> None:
    """Save settings to settings.json."""
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError:
        pass


_APP_SETTINGS = _load_settings_json()

# --- Save on Catch Settings ---
SAVE_ON_CATCH = _APP_SETTINGS.get("catch", {}).get("save_on_catch", True)
SAVE_ON_CATCH_MIN_DV = _APP_SETTINGS.get("catch", {}).get("save_on_catch_min_dv", 11)
SAVE_ON_CATCH_ENABLED = _APP_SETTINGS.get("catch", {}).get("save_on_catch_enabled", True)

# --- Episode Settings ---
MAX_STEPS = _APP_SETTINGS.get("episode", {}).get("max_steps", 7200)
PERFECT_SOUND = _APP_SETTINGS.get("episode", {}).get("perfect_sound", True)

# --- Launcher Defaults (from settings.json) ---
SETTINGS_LAUNCHER = _APP_SETTINGS.get("launcher", {})
COLS = SETTINGS_LAUNCHER.get("cols", GRID_COLS)
ROWS = SETTINGS_LAUNCHER.get("rows", GRID_ROWS)
DEFAULT_ENV_AMOUNT = SETTINGS_LAUNCHER.get("default_env_amount", GRID_COLS * GRID_ROWS)
