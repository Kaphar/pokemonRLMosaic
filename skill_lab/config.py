"""Central configuration for the Skill Lab."""

from pathlib import Path


# --- Paths ---
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROM = PROJECT_ROOT / "PokemonRed.gb"
DEFAULT_INIT_STATE = PROJECT_ROOT / "init.state"
V2_DIR = PROJECT_ROOT / "v2"
# ROM_PATH = PROJECT_ROOT / "roms" / "pokemon_red.gb"
INIT_STATE_PATH = V2_DIR / "state" / "init.state"
EVENT_JSON_PATH = V2_DIR / "events.json"

# --- Emulator Settings ---
ACTION_FREQ = 24          # Frames between actions
TILE_WIDTH = 160          # Game Boy screen width
TILE_HEIGHT = 144         # Game Boy screen height

# TILE_WIDTH = 280
# TILE_HEIGHT = 288
TOTAL_TILES = 12          # Number of environments in the mosaic
DEFAULT_MAX_STEPS = 7200  # Max steps per episode

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
MILESTONE_REWARD = 5.0       # Reward for hitting an event flag
EXPLORATION_REWARD = 0.1     # Small reward for visiting new coordinates

# --- Teacher/Human Guidance ---
REWARD_MODIFIER_PRAISE = 1.0
REWARD_MODIFIER_SLASH = -1.0

PANEL_WIDTH = 220
GRID_COLS = 4
GRID_ROWS = 3
TOTAL_TILES = GRID_COLS * GRID_ROWS


SPECIALIZATION_PRESETS = {
    "default": {"reward_scale": 1.0, "explore_weight": 1.0},
    "explorer": {"reward_scale": 0.5, "explore_weight": 3.0},
    "trainer": {"reward_scale": 2.0, "explore_weight": 0.5},
    "speedrunner": {"reward_scale": 3.0, "explore_weight": 0.1},
}
