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
        "milestone_reward": medium_reward,
        "init_state": str(DEFAULT_INIT_STATE),
        "button_masks": {
            "Start": True,
            "Select": True,
            "B": False,
            "A": False,
        },
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
    
    # Load trainer configs from saved files if they exist
    trainer_configs = {}
    trainer_names = ["CharmanderTrainer", "SquirtleTrainer", "BulbasaurTrainer"]
    for trainer_name in trainer_names:
        config_file = ENVS_DIR / trainer_name / "trainer_config.json"
        if config_file.exists():
            with open(config_file, "r") as f:
                trainer_configs[trainer_name] = json.load(f)
    
    # Load worker defaults from saved file if it exists
    worker_defaults = {}
    worker_config_file = ENVS_DIR / "worker_defaults.json"
    if worker_config_file.exists():
        with open(worker_config_file, "r") as f:
            worker_defaults = json.load(f)
    
    # Create trainer directories (always 3 fixed trainers)
    workers_dir = ENVS_DIR / "Workers"
    workers_dir.mkdir(exist_ok=True)
    
    env_configs = []
    
    # First 3 envs are the named trainers (use saved config or defaults)
    for i in range(min(3, num_envs)):
        trainer_name = trainer_names[i]
        trainer_dir = ENVS_DIR / trainer_name
        trainer_dir.mkdir(exist_ok=True)
        
        # Get trainer config or use defaults
        trainer_cfg = trainer_configs.get(trainer_name, {})
        
        # Use configured values or defaults
        cfg_rom_name = trainer_cfg.get("rom", rom_path.name)
        cfg_init_state_name = trainer_cfg.get("init_state", init_state.name)
        cfg_stage = trainer_cfg.get("stage", stage)
        cfg_reward_scale = trainer_cfg.get("reward_scale", None)
        cfg_explore_weight = trainer_cfg.get("explore_weight", None)
        cfg_profile_name = trainer_cfg.get("profile", "trainer" if i == 0 else random.choice(["trainer", "explorer"]))
        
        # Set up ROM and init state paths
        if cfg_rom_name == "PokemonBlue.gb":
            trainer_rom_path = rom_path.parent / cfg_rom_name
            trainer_init_state = rom_path.parent / cfg_init_state_name
        else:
            trainer_rom_path = rom_path
            trainer_init_state = init_state
        
        # Each trainer gets an Env# subfolder
        env_subdir = trainer_dir / f"Env{i+1:03d}"
        env_subdir.mkdir(exist_ok=True)
        (env_subdir / "checkpoints").mkdir(exist_ok=True)
        (env_subdir / "states").mkdir(exist_ok=True)
        (env_subdir / "inputs").mkdir(exist_ok=True)
        
        # Copy ROM to env folder
        rom_dest = env_subdir / trainer_rom_path.name
        if not rom_dest.exists() and trainer_rom_path.exists():
            shutil.copy2(trainer_rom_path, rom_dest)
        
        # Assign profile based on config
        profile = PROFILES.get(cfg_profile_name, PROFILES["trainer"]).copy()
        
        # Override reward scale and explore weight if configured
        if cfg_reward_scale is not None:
            profile["reward_scale"] = cfg_reward_scale
        if cfg_explore_weight is not None:
            profile["explore_weight"] = cfg_explore_weight
        
        # Create settings.json
        settings = {
            "env_index": i,
            "env_name": trainer_name,
            "env_dir": str(env_subdir),
            "stage": cfg_stage,  # Use configured stage
            "stage_config": stage_config,
            "rom_path": str(rom_dest),
            "init_state": str(trainer_init_state),  # Use configured init state
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
            "rom_file": trainer_rom_path.name,  # Use actual ROM name
            "init_state_file": trainer_init_state.name,  # Use actual init state name
        }
        env_configs.append(config)
    
    # Remaining envs go to Workers directory
    # Use worker_defaults config if available, otherwise 50/50 for Blue ROM
    blue_rom_chance = worker_defaults.get("blue_rom_chance", 0.5)
    profile_distribution = worker_defaults.get("profile_distribution", "50/50")
    worker_stage = worker_defaults.get("stage", stage)
    worker_reward_scale = worker_defaults.get("reward_scale", None)
    worker_explore_weight = worker_defaults.get("explore_weight", None)
    
    for i in range(3, num_envs):
        env_name = f"Env{i+1:03d}"
        env_dir = workers_dir / env_name
        env_dir.mkdir(exist_ok=True)
        (env_dir / "checkpoints").mkdir(exist_ok=True)
        (env_dir / "states").mkdir(exist_ok=True)
        (env_dir / "inputs").mkdir(exist_ok=True)
        
        # Blue ROM selection based on configured chance
        use_blue = random.random() < blue_rom_chance
        if use_blue:
            worker_rom_path = rom_path.parent / "PokemonBlue.gb"
            worker_init_state = rom_path.parent / "blue.init.state"
        else:
            worker_rom_path = rom_path
            worker_init_state = init_state
        
        # Copy ROM to env folder
        rom_dest = env_dir / worker_rom_path.name
        if not rom_dest.exists() and worker_rom_path.exists():
            shutil.copy2(worker_rom_path, rom_dest)
        
        # Profile distribution based on config
        if profile_distribution == "all_trainer":
            profile_name = "trainer"
        elif profile_distribution == "all_explorer":
            profile_name = "explorer"
        else:  # 50/50
            profile_name = random.choice(["trainer", "explorer"])
        
        profile = PROFILES[profile_name].copy()
        
        # Override reward scale and explore weight if configured
        if worker_reward_scale is not None:
            profile["reward_scale"] = worker_reward_scale
        if worker_explore_weight is not None:
            profile["explore_weight"] = worker_explore_weight
        
        # Create settings.json
        settings = {
            "env_index": i,
            "env_name": env_name,
            "env_dir": str(env_dir),
            "stage": worker_stage,  # Use configured worker stage
            "stage_config": stage_config,
            "rom_path": str(rom_dest),
            "init_state": str(worker_init_state),
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
            "rom_file": worker_rom_path.name,
            "init_state_file": worker_init_state.name,
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


def ensure_env_exists(
    env_index: int,
    rom_source_path: Path | None = None,
    default_state_path: str | None = None,
    launcher_stage: str | None = None,
) -> dict[str, Any]:
    """Ensure an environment folder exists, creating it if necessary.
    
    This function is called at runtime when the mosaic launches. It checks if
    the environment folder exists, and if not, creates it with proper settings.
    For Worker envs (index >= 3), uses 'autostage' which will load the stage
    specified by the launcher.
    
    Args:
        env_index: The environment index (0-based).
        rom_source_path: Path to source ROM file to copy.
        default_state_path: Default initial state path.
        launcher_stage: Stage name selected in launcher (for autostage workers).
    
    Returns:
        The environment settings dict.
    """
    env_path = get_env_path(env_index)
    settings_file = env_path / "settings.json"
    
    # Create directory structure if missing
    if not env_path.exists():
        env_path.mkdir(parents=True, exist_ok=True)
        (env_path / "checkpoints").mkdir(exist_ok=True)
        (env_path / "states").mkdir(exist_ok=True)
        (env_path / "inputs").mkdir(exist_ok=True)
        
        # Determine profile
        if env_index == 0:  # CharmanderTrainer = 100% trainer
            profile_type = "trainer"
        else:
            profile_type = random.choice(["trainer", "explorer"])
        
        profile = PROFILES[profile_type].copy()
        
        # Determine stage config
        if env_index < 3:
            # Named trainers use their specific stage (starter for now)
            stage_config_name = "starter"
        else:
            # Workers use autostage - they train whatever stage the launcher selects
            stage_config_name = "autostage"
        
        # Load stage config for storage in settings
        if stage_config_name == "autostage" and launcher_stage:
            actual_stage = launcher_stage
        else:
            actual_stage = stage_config_name
        
        stage_config = load_stage_config(actual_stage)
        
        settings = {
            "env_index": env_index,
            "stage_config": stage_config_name,
            "launcher_override_stage": launcher_stage,
            "rom_path": str(env_path / "pokemon.gb"),
            "initial_state_path": default_state_path or "",
            "profile": profile,
            "catch_directive": profile["catch_directive"],
            "train_directive": profile["train_directive"],
            "save_on_catch": profile["save_on_catch"],
            "reset_on_catch": profile["reset_on_catch"],
        }
        
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        
        print(f"[EnvSetup] Created new environment at {env_path}")
    
    # Copy ROM if source provided and target doesn't exist
    if rom_source_path and not (env_path / "pokemon.gb").exists():
        shutil.copy2(rom_source_path, env_path / "pokemon.gb")
        print(f"[EnvSetup] Copied ROM to {env_path}")
    
    return get_env_config(env_index)


def get_env_path(env_index: int) -> Path:
    """Get the path for an environment by index.
    
    Args:
        env_index: The environment index (0-based).
        
    Returns:
        Path to the environment folder.
    """
    env_name = f"Env{env_index + 1:03d}"
    
    if env_index < 3:
        trainer_names = ["CharmanderTrainer", "SquirtleTrainer", "BulbasaurTrainer"]
        return ENVS_DIR / trainer_names[env_index] / env_name
    else:
        return ENVS_DIR / "Workers" / env_name


def copy_file_to_all_envs(source_file_path: str, dest_filename: str = "pokemon.gb") -> int:
    """Copy a file to all existing environment folders.
    
    Useful for updating resources (ROM, states) without regenerating settings.
    
    Args:
        source_file_path: Path to the source file.
        dest_filename: Name to use in destination folders.
    
    Returns:
        Number of environments the file was copied to.
    """
    source = Path(source_file_path)
    if not source.exists():
        print(f"[EnvSetup] Source file not found: {source}")
        return 0
    
    count = 0
    
    # Scan trainer directories
    for trainer_name in ["CharmanderTrainer", "SquirtleTrainer", "BulbasaurTrainer"]:
        base = ENVS_DIR / trainer_name
        if base.exists():
            for env_folder in base.iterdir():
                if env_folder.is_dir() and env_folder.name.startswith("Env"):
                    shutil.copy2(source, env_folder / dest_filename)
                    count += 1
    
    # Scan Workers directory
    workers_base = ENVS_DIR / "Workers"
    if workers_base.exists():
        for env_folder in workers_base.iterdir():
            if env_folder.is_dir() and env_folder.name.startswith("Env"):
                shutil.copy2(source, env_folder / dest_filename)
                count += 1
    
    print(f"[EnvSetup] Copied {source.name} to {count} environments.")
    return count