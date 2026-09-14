"""Environment setup and directive assignment.

Creates the skill_lab/envs/ folder structure and assigns
directives to each environment.

Folder structure:
    skill_lab/envs/
    ├── CharmanderTrainer/     ← Named env (specific directive)
    │   ├── Env001/            ← Each trainer gets an Env# subfolder
    │   │   ├── settings.json  ← Stage, ROM, save state config
    │   │   ├── checkpoints/   ← Saved model checkpoints
    │   │   ├── states/        ← Save states
    │   │   └── inputs/        ← Recorded inputs
    ├── SquirtleTrainer/
    │   └── Env002/
    ├── BulbasaurTrainer/
    │   └── Env003/
    └── Workers/               ← All excess environments
        ├── Env004/
        │   ├── settings.json
        │   ├── checkpoints/
        │   ├── states/
        │   └── inputs/
        └── ...
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path
from typing import Any

from skill_lab.config import (
    CATCH_DIRECTIVES,
    DEFAULT_INIT_STATE,
    DEFAULT_ROM,
    ENVS_DIR,
    PROFILES_DIR,
    TRAIN_DIRECTIVES,
)
from skill_lab.rewards import big_reward, huge_reward, medium_reward

PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Profile definitions
PROFILES = {
    "trainer": {
        "name": "trainer",
        "reward_scale": 2.0,
        "explore_weight": 0.5,
        "catch_directive": ["Nidoran♂", "Pidgey", "Rattata", "Spearow", "Pikachu"],
        "train_directive": ["Nidoran♂", "Pikachu"],
        "save_on_catch": True,
        "reset_on_catch": False,
    },
    "explorer": {
        "name": "explorer",
        "reward_scale": 0.5,
        "explore_weight": 3.0,
        "catch_directive": [],
        "train_directive": [],
        "save_on_catch": False,
        "reset_on_catch": True,
    },
}


def load_stage_config(stage_name: str) -> dict[str, Any]:
    """Load stage configuration from JSON file."""
    stages_dir = PROJECT_ROOT / "skill_lab" / "stages"
    stage_path = stages_dir / f"{stage_name}.json"
    
    if stage_path.exists():
        with open(stage_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    # Default fallback for starter stage
    return {
        "name": stage_name,
        "description": f"Default {stage_name} stage",
        "max_steps": 7200,
        "disable_start": True,
        "disable_select": True,
        "milestone_reward": medium_reward,
        "init_state": str(DEFAULT_INIT_STATE),
    }


def setup_envs(
    num_envs: int,
    stage: str = "starter",
    rom_path: Path | None = None,
    init_state: Path | None = None,
) -> list[dict[str, Any]]:
    """Set up environment folders and assign directives.

    Args:
        num_envs: Total number of environments to create.
        stage: Which training stage we're in.
        rom_path: Path to the ROM file (defaults to DEFAULT_ROM).
        init_state: Path to initial save state (defaults to DEFAULT_INIT_STATE).

    Returns:
        List of env configs, one per environment.
    """
    if rom_path is None:
        rom_path = DEFAULT_ROM
    if init_state is None:
        init_state = DEFAULT_INIT_STATE
    
    ENVS_DIR.mkdir(parents=True, exist_ok=True)
    
    # Load stage configuration
    stage_config = load_stage_config(stage)
    
    # Create trainer directories (always 3 fixed trainers)
    trainer_names = ["CharmanderTrainer", "SquirtleTrainer", "BulbasaurTrainer"]
    workers_dir = ENVS_DIR / "Workers"
    workers_dir.mkdir(exist_ok=True)
    
    env_configs = []
    
    # First 3 envs are the named trainers
    for i in range(min(3, num_envs)):
        trainer_name = trainer_names[i]
        trainer_dir = ENVS_DIR / trainer_name
        trainer_dir.mkdir(exist_ok=True)
        
        # Each trainer gets an Env# subfolder
        env_subdir = trainer_dir / f"Env{i+1:03d}"
        env_subdir.mkdir(exist_ok=True)
        (env_subdir / "checkpoints").mkdir(exist_ok=True)
        (env_subdir / "states").mkdir(exist_ok=True)
        (env_subdir / "inputs").mkdir(exist_ok=True)
        
        # Copy ROM to env folder
        rom_dest = env_subdir / rom_path.name
        if not rom_dest.exists() and rom_path.exists():
            shutil.copy2(rom_path, rom_dest)
        
        # Assign profile: CharmanderTrainer = 100% trainer, others = 50/50 random
        if i == 0:  # CharmanderTrainer
            profile = PROFILES["trainer"].copy()
        else:
            profile_name = random.choice(["trainer", "explorer"])
            profile = PROFILES[profile_name].copy()
        
        # Create settings.json
        settings = {
            "env_index": i,
            "env_name": trainer_name,
            "env_dir": str(env_subdir),
            "stage": stage,
            "stage_config": stage_config,
            "rom_path": str(rom_dest),
            "init_state": str(init_state),
            "profile": profile,
            "catch_directive": profile["catch_directive"],
            "train_directive": profile["train_directive"],
            "save_on_catch": profile["save_on_catch"],
            "reset_on_catch": profile["reset_on_catch"],
        }
        
        settings_path = env_subdir / "settings.json"
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        
        config = {
            "env_index": i,
            "env_name": trainer_name,
            "env_dir": str(env_subdir),
            "settings_path": str(settings_path),
            "directive": trainer_name.replace("Trainer", ""),
            "target_starter": trainer_name.replace("Trainer", ""),
            "profile": profile["name"],
            "catch_directive": profile["catch_directive"],
            "train_directive": profile["train_directive"],
            "description": f"{trainer_name} - {profile['name']} profile",
        }
        env_configs.append(config)
    
    # Remaining envs go to Workers directory
    for i in range(3, num_envs):
        env_name = f"Env{i+1:03d}"
        env_dir = workers_dir / env_name
        env_dir.mkdir(exist_ok=True)
        (env_dir / "checkpoints").mkdir(exist_ok=True)
        (env_dir / "states").mkdir(exist_ok=True)
        (env_dir / "inputs").mkdir(exist_ok=True)
        
        # Copy ROM to env folder
        rom_dest = env_dir / rom_path.name
        if not rom_dest.exists() and rom_path.exists():
            shutil.copy2(rom_path, rom_dest)
        
        # 50/50 random profile distribution for workers
        profile_name = random.choice(["trainer", "explorer"])
        profile = PROFILES[profile_name].copy()
        
        # Create settings.json
        settings = {
            "env_index": i,
            "env_name": env_name,
            "env_dir": str(env_dir),
            "stage": stage,
            "stage_config": stage_config,
            "rom_path": str(rom_dest),
            "init_state": str(init_state),
            "profile": profile,
            "catch_directive": profile["catch_directive"],
            "train_directive": profile["train_directive"],
            "save_on_catch": profile["save_on_catch"],
            "reset_on_catch": profile["reset_on_catch"],
        }
        
        settings_path = env_dir / "settings.json"
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        
        config = {
            "env_index": i,
            "env_name": env_name,
            "env_dir": str(env_dir),
            "settings_path": str(settings_path),
            "directive": "worker",
            "target_starter": None,
            "profile": profile["name"],
            "catch_directive": profile["catch_directive"],
            "train_directive": profile["train_directive"],
            "description": f"Worker {env_name} - {profile['name']} profile",
        }
        env_configs.append(config)
    
    # Print assignment summary
    print(f"\n[EnvSetup] Created {num_envs} environments for stage '{stage}':")
    print(f"  Trainers (0-2): CharmanderTrainer, SquirtleTrainer, BulbasaurTrainer")
    print(f"  Workers (3-{num_envs-1}): {num_envs - 3} worker environments")
    print(f"  ROM copied to each env folder: {rom_path.name}")
    print()
    
    return env_configs


def expand_envs(
    current_num_envs: int,
    new_num_envs: int,
    stage: str = "starter",
    rom_path: Path | None = None,
    init_state: Path | None = None,
) -> list[dict[str, Any]]:
    """Expand the number of environments by creating new Worker envs.
    
    Args:
        current_num_envs: Current number of environments.
        new_num_envs: New total number of environments.
        stage: Which training stage we're in.
        rom_path: Path to the ROM file.
        init_state: Path to initial save state.
    
    Returns:
        List of new env configs that were created.
    """
    if rom_path is None:
        rom_path = DEFAULT_ROM
    if init_state is None:
        init_state = DEFAULT_INIT_STATE
    
    workers_dir = ENVS_DIR / "Workers"
    workers_dir.mkdir(exist_ok=True)
    
    # Load stage configuration
    stage_config = load_stage_config(stage)
    
    new_configs = []
    
    for i in range(current_num_envs, new_num_envs):
        env_name = f"Env{i+1:03d}"
        env_dir = workers_dir / env_name
        env_dir.mkdir(exist_ok=True)
        (env_dir / "checkpoints").mkdir(exist_ok=True)
        (env_dir / "states").mkdir(exist_ok=True)
        (env_dir / "inputs").mkdir(exist_ok=True)
        
        # Copy ROM to env folder
        rom_dest = env_dir / rom_path.name
        if not rom_dest.exists() and rom_path.exists():
            shutil.copy2(rom_path, rom_dest)
        
        # 50/50 random profile distribution for new workers
        profile_name = random.choice(["trainer", "explorer"])
        profile = PROFILES[profile_name].copy()
        
        # Create settings.json with default initial state
        settings = {
            "env_index": i,
            "env_name": env_name,
            "env_dir": str(env_dir),
            "stage": stage,
            "stage_config": stage_config,
            "rom_path": str(rom_dest),
            "init_state": str(init_state),
            "profile": profile,
            "catch_directive": profile["catch_directive"],
            "train_directive": profile["train_directive"],
            "save_on_catch": profile["save_on_catch"],
            "reset_on_catch": profile["reset_on_catch"],
        }
        
        settings_path = env_dir / "settings.json"
        with open(settings_path, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        
        config = {
            "env_index": i,
            "env_name": env_name,
            "env_dir": str(env_dir),
            "settings_path": str(settings_path),
            "directive": "worker",
            "target_starter": None,
            "profile": profile["name"],
            "catch_directive": profile["catch_directive"],
            "train_directive": profile["train_directive"],
            "description": f"Worker {env_name} - {profile['name']} profile (newly created)",
        }
        new_configs.append(config)
    
    print(f"\n[EnvSetup] Added {len(new_configs)} new worker environments.")
    return new_configs


def get_env_config(env_index: int) -> dict[str, Any]:
    """Load the config for a specific environment from settings.json."""
    # Check trainer directories first
    for trainer_name in ["CharmanderTrainer", "SquirtleTrainer", "BulbasaurTrainer"]:
        trainer_dir = ENVS_DIR / trainer_name
        if not trainer_dir.exists():
            continue
        for env_subdir in trainer_dir.iterdir():
            if env_subdir.is_dir() and env_subdir.name.startswith("Env"):
                settings_path = env_subdir / "settings.json"
                if settings_path.exists():
                    with open(settings_path, "r", encoding="utf-8") as f:
                        settings = json.load(f)
                    if settings.get("env_index") == env_index:
                        return settings
    
    # Check Workers directory
    workers_dir = ENVS_DIR / "Workers"
    if workers_dir.exists():
        for env_dir in workers_dir.iterdir():
            if env_dir.is_dir():
                settings_path = env_dir / "settings.json"
                if settings_path.exists():
                    with open(settings_path, "r", encoding="utf-8") as f:
                        settings = json.load(f)
                    if settings.get("env_index") == env_index:
                        return settings
    
    return {}