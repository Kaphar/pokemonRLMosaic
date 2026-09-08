"""Environment setup and directive assignment.

Creates the skill_lab/envs/ folder structure and assigns
directives to each environment.

Folder structure:
    skill_lab/envs/
    ├── CharmanderTrainer/     ← Named env (specific directive)
    │   ├── config.json        ← Directive, rewards, state path
    │   ├── checkpoints/       ← Saved model checkpoints
    │   ├── states/            ← Save states
    │   └── inputs/            ← Recorded inputs
    ├── SquirtleTrainer/
    ├── BulbasaurTrainer/
    ├── Env001/                ← Auto-generated env
    │   ├── config.json
    │   ├── checkpoints/
    │   ├── states/
    │   └── inputs/
    └── ...
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from skill_lab.rewards import big_reward, huge_reward, medium_reward

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENVS_DIR = PROJECT_ROOT / "skill_lab" / "envs"

# Directive presets
DIRECTIVE_PRESETS = {
    "charmander": {
        "name": "CharmanderTrainer",
        "target_starter": "Charmander",
        "milestone_reward": huge_reward,
        "speed_bonus": True,
        "description": "Navigate to pick Charmander (right ball)",
    },
    "squirtle": {
        "name": "SquirtleTrainer",
        "target_starter": "Squirtle",
        "milestone_reward": huge_reward,
        "speed_bonus": True,
        "description": "Navigate to pick Squirtle (middle ball)",
    },
    "bulbasaur": {
        "name": "BulbasaurTrainer",
        "target_starter": "Bulbasaur",
        "milestone_reward": huge_reward,
        "speed_bonus": True,
        "description": "Navigate to pick Bulbasaur (left ball)",
    },
    "default": {
        "name": "AnyStarter",
        "target_starter": None,  # Any starter is fine
        "milestone_reward": big_reward,
        "speed_bonus": True,
        "description": "Pick any starter, focus on speed",
    },
    "explorer": {
        "name": "Explorer",
        "target_starter": None,
        "milestone_reward": medium_reward,
        "speed_bonus": False,  # Explorers don't care about speed
        "description": "Explore freely, discover new areas",
    },
}


def setup_envs(num_envs: int, stage: str = "starter") -> list[dict[str, Any]]:
    """Set up environment folders and assign directives.

    Args:
        num_envs: Total number of environments to create.
        stage: Which training stage we're in.

    Returns:
        List of env configs, one per environment.
    """
    ENVS_DIR.mkdir(parents=True, exist_ok=True)

    env_configs = []
    quarter = num_envs // 4

    for i in range(num_envs):
        # Assign directive based on position
        if stage == "starter":
            if i < quarter:
                directive = DIRECTIVE_PRESETS["charmander"]
            elif i < quarter * 2:
                directive = DIRECTIVE_PRESETS["squirtle"]
            elif i < quarter * 3:
                directive = DIRECTIVE_PRESETS["bulbasaur"]
            else:
                directive = DIRECTIVE_PRESETS["default"]
        elif stage == "explore":
            directive = DIRECTIVE_PRESETS["explorer"]
        else:
            directive = DIRECTIVE_PRESETS["default"]

        # Create folder
        env_name = directive["name"] if i < quarter * 3 else f"Env{i+1:03d}"
        env_dir = ENVS_DIR / env_name
        env_dir.mkdir(exist_ok=True)
        (env_dir / "checkpoints").mkdir(exist_ok=True)
        (env_dir / "states").mkdir(exist_ok=True)
        (env_dir / "inputs").mkdir(exist_ok=True)

        # Build config
        config = {
            "env_index": i,
            "env_name": env_name,
            "env_dir": str(env_dir),
            "directive": directive["name"],
            "target_starter": directive["target_starter"],
            "milestone_reward": directive["milestone_reward"],
            "speed_bonus": directive["speed_bonus"],
            "description": directive["description"],
        }

        # Save config to folder
        config_path = env_dir / "config.json"
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        env_configs.append(config)

    # Print assignment summary
    print(f"\n[EnvSetup] Created {num_envs} environments for stage '{stage}':")
    print(f"  Quarter 1 (0-{quarter-1}): Charmander")
    print(f"  Quarter 2 ({quarter}-{quarter*2-1}): Squirtle")
    print(f"  Quarter 3 ({quarter*2}-{quarter*3-1}): Bulbasaur")
    print(f"  Quarter 4 ({quarter*3}-{num_envs-1}): Any/Default")
    print()

    return env_configs


def get_env_config(env_index: int) -> dict[str, Any]:
    """Load the config for a specific environment."""
    for env_dir in ENVS_DIR.iterdir():
        config_path = env_dir / "config.json"
        if config_path.exists():
            with open(config_path, "r") as f:
                config = json.load(f)
            if config.get("env_index") == env_index:
                return config
    return {}