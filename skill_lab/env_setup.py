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

import copy
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
    SAVE_ON_CATCH,
    SAVE_ON_CATCH_ENABLED,
    SAVE_ON_CATCH_MIN_DV,
    GRID_COLS,
    GRID_ROWS,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]

# Default ROM paths
DEFAULT_ROM_RED = PROJECT_ROOT / "PokemonRed.gb"
DEFAULT_ROM_BLUE = PROJECT_ROOT / "PokemonBlue.gb"

# Profile definitions
PROFILES = {
    "trainer": {
        "name": "trainer",
        "reward_scale": 1.0,
        "explore_weight": 1.0,
        "category_multipliers": {
            "milestone": 1.0, "event": 1.0, "exploration": 1.0,
            "combat": 2.0, "healing": 1.0, "training": 1.0, "breadcrumb": 1.0,
        },
        "catch_directive": ["Nidoran♂", "Pidgey", "Rattata", "Spearow", "Pikachu"],
        "train_directive": ["Nidoran♂", "Pikachu"],
    },
    "speedrunner": {
        "name": "speedrunner",
        "reward_scale": 3.0,
        "explore_weight": 0.1,
        "category_multipliers": {
            "milestone": 3.0, "event": 3.0, "exploration": 1.0,
            "combat": 1.0, "healing": 0.5, "training": 1.0, "breadcrumb": 3.0,
        },
        "catch_directive": [],
        "train_directive": [],
    },
    "explorer": {
        "name": "explorer",
        "reward_scale": 1.0,
        "explore_weight": 3.0,
        "category_multipliers": {
            "milestone": 1.0, "event": 1.0, "exploration": 3.0,
            "combat": 0.5, "healing": 1.0, "training": 1.0, "breadcrumb": 1.0,
        },
        "catch_directive": [],
        "train_directive": [],
    },
}


def load_profile_config(profile_name: str) -> dict[str, Any]:
    """Load profile data from the JSON file when available, else fallback.

    This keeps the runtime config aligned with the actual JSON characteristics in
    skill_lab/profiles/ while preserving the legacy in-memory defaults.
    """
    profile_name = profile_name.lower()
    profile_path = PROFILES_DIR / f"{profile_name}.json"
    if profile_path.exists():
        with open(profile_path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict) and loaded.get("settings"):
            profile = dict(loaded.get("settings", {}))
            profile.setdefault("name", profile_name)
            profile["__source__"] = str(profile_path)
            return profile
        loaded["__source__"] = str(profile_path)
        return loaded
    fallback = PROFILES.get(profile_name, {}).copy()
    fallback["__source__"] = "default profile fallback in skill_lab/env_setup.py"
    return fallback


def load_stage_config(stage_name: str) -> dict[str, Any]:
    """Load stage configuration from JSON file."""
    stages_dir = PROJECT_ROOT / "skill_lab" / "stages"
    stage_path = stages_dir / f"{stage_name}.json"
    
    if stage_path.exists():
        with open(stage_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        alias_map = {
            "milestone_reward": "milestone_reward_multiplier",
            "exploration_reward": "exploration_reward_multiplier",
            "combat_reward": "combat_reward_multiplier",
            "capture_reward": "capture_reward_multiplier",
            "healing_reward": "healing_reward_multiplier",
        }
        for legacy_key, canonical_key in alias_map.items():
            if legacy_key not in config and canonical_key in config:
                config[legacy_key] = config[canonical_key]
            elif canonical_key not in config and legacy_key in config:
                config[canonical_key] = config[legacy_key]
        config["__source__"] = str(stage_path)
        return config
    
    # Default fallback for starter stage
    fallback = {
        "name": stage_name,
        "description": f"Default {stage_name} stage",
        "max_steps": 7200,
        "milestone_reward_multiplier": 1.0,
        "event_reward_multiplier": 1.0,
        "exploration_reward_multiplier": 1.0,
        "combat_reward_multiplier": 1.0,
        "capture_reward_multiplier": 1.0,
        "healing_reward_multiplier": 1.0,
        "training_reward_multiplier": 1.0,
        "breadcrumb_reward_multiplier": 1.0,
        "init_state": str(DEFAULT_INIT_STATE),
        "button_masks": {
            "Start": True,
            "Select": True,
            "B": False,
            "A": False,
        },
    }
    fallback["__source__"] = "default stage fallback in skill_lab/env_setup.py"
    return fallback


def _resolve_init_state(
    init_state_name: str, env_subdir: Path, rom_parent: Path
) -> Path:
    """Resolve an init_state filename to a concrete path.

    Searches in: the env's root dir, the env's states/ dir, rom_parent,
    then project root. Falls back to env_subdir / init_state_name if none found.
    """
    search_dirs = [env_subdir, env_subdir / "states", rom_parent, PROJECT_ROOT]
    for d in search_dirs:
        candidate = d / init_state_name
        if candidate.exists():
            return candidate
    return env_subdir / init_state_name


def setup_envs(
    num_envs: int,
    stage: str = "starter",
    rom_path: Path | None = None,
    init_state: Path | None = None,
    mosaic_rows: int = GRID_ROWS,
    mosaic_cols: int = GRID_COLS,
    override_trainer_stage: bool = False,
) -> list[dict[str, Any]]:
    """Set up environment folders and assign directives.

    Args:
        num_envs: Total number of environments to create.
        stage: Which training stage we're in.
        rom_path: Path to the ROM file (defaults to DEFAULT_ROM_RED).
        init_state: Path to initial save state (defaults to DEFAULT_INIT_STATE).
        mosaic_rows: Number of rows in the mosaic grid.
        mosaic_cols: Number of columns in the mosaic grid.
        override_trainer_stage: When True, trainers use the launcher-selected
            ``stage`` instead of their own saved stage. Workers always use the
            launcher-selected stage regardless of this flag.

    Returns:
        List of env configs, one per environment.
    """
    if rom_path is None:
        rom_path = DEFAULT_ROM_RED
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
    
    # Create trainer directories
    # total_trainers is (mosaic_tiles // 3) * 3, split evenly across 3 starter types
    mosaic_tiles = mosaic_rows * mosaic_cols
    total_trainers = (mosaic_tiles // 3) * 3
    trainers_per_type = total_trainers // 3
    workers_dir = ENVS_DIR / "Workers"
    workers_dir.mkdir(exist_ok=True)
    
    env_configs = []
    
    # First total_trainers envs are the named trainers (use saved config or defaults)
    for i in range(min(total_trainers, num_envs)):
        trainer_idx = i // trainers_per_type
        trainer_name = trainer_names[trainer_idx]
        trainer_dir = ENVS_DIR / trainer_name
        trainer_dir.mkdir(exist_ok=True)
        
        # Get trainer config or use defaults
        trainer_cfg = trainer_configs.get(trainer_name, {})
        
        # Use configured values or defaults
        cfg_rom_name = trainer_cfg.get("rom", rom_path.name)
        cfg_init_state_name = trainer_cfg.get("init_state", init_state.name)
        cfg_stage = stage if override_trainer_stage else trainer_cfg.get("stage", stage)
        cfg_reward_scale = trainer_cfg.get("reward_scale", None)
        cfg_explore_weight = trainer_cfg.get("explore_weight", None)
        cfg_profile_name = trainer_cfg.get("profile", "trainer" if i == 0 else random.choice(["trainer", "speedrunner"]))
        cfg_input_replay = trainer_cfg.get("input_replay", "")
        
        # Set up ROM and init state paths
        if cfg_rom_name == "PokemonBlue.gb":
            trainer_rom_path = rom_path.parent / cfg_rom_name
        else:
            trainer_rom_path = rom_path

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

        # Resolve the configured init_state file: search in the env's own
        # root dir, states/ dir, rom_path.parent, then project root.
        trainer_init_state = _resolve_init_state(
            cfg_init_state_name, env_subdir, rom_path.parent
        )
        # Copy the init state into the env folder root if it's not already there
        env_state_dest = env_subdir / trainer_init_state.name
        if (
            trainer_init_state.exists()
            and trainer_init_state.resolve() != env_state_dest.resolve()
            and not env_state_dest.exists()
        ):
            shutil.copy2(trainer_init_state, env_state_dest)
        
        # Assign profile based on config
        profile = PROFILES.get(cfg_profile_name, PROFILES["trainer"]).copy()
        
        # Override reward scale and explore weight if configured
        if cfg_reward_scale is not None:
            profile["reward_scale"] = cfg_reward_scale
        if cfg_explore_weight is not None:
            profile["explore_weight"] = cfg_explore_weight
        
        # Create per-env stage_config so init_state/rom_path point to env-local paths
        env_stage_config = copy.deepcopy(stage_config)
        env_stage_config["init_state"] = str(env_state_dest)
        env_stage_config["rom_path"] = str(rom_dest)
        
        # Create settings.json
        settings = {
            "env_index": i,
            "env_name": trainer_name,
            "env_dir": str(env_subdir),
            "stage": cfg_stage,
            "input_replay": cfg_input_replay,
            "stage_config": env_stage_config,
            "rom_path": str(rom_dest),
            "init_state": str(env_state_dest),
            "profile": profile,
            "catch_directive": profile["catch_directive"],
            "train_directive": profile["train_directive"],
            "save_on_catch": SAVE_ON_CATCH,
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
            "save_on_catch": SAVE_ON_CATCH,
            "reset_on_catch": stage_config.get("reset_on_catch", False),
            "description": f"{trainer_name} - {profile['name']} profile",
            "rom_file": trainer_rom_path.name,
            "init_state_file": env_state_dest.name,
            "input_replay": cfg_input_replay,
        }
        env_configs.append(config)
    
    # Remaining envs go to Workers directory
    # Use worker_defaults config if available, otherwise 50/50 for Blue ROM
    blue_rom_chance = worker_defaults.get("blue_rom_chance", 0.5)
    profile_distribution = worker_defaults.get("profile_distribution", "50/50")
    # Workers always take the current (launcher-selected) stage
    worker_stage = stage
    worker_reward_scale = worker_defaults.get("reward_scale", None)
    worker_explore_weight = worker_defaults.get("explore_weight", None)
    worker_input_replay = worker_defaults.get("input_replay", "")
    
    num_trainers = min(total_trainers, num_envs)
    
    for i in range(num_trainers, num_envs):
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

        # Copy the init state into the env folder root if it's not already there
        env_state_dest = env_dir / worker_init_state.name
        if (
            worker_init_state.exists()
            and worker_init_state.resolve() != env_state_dest.resolve()
            and not env_state_dest.exists()
        ):
            shutil.copy2(worker_init_state, env_state_dest)
        
        # Profile distribution based on config
        if profile_distribution == "all_trainer":
            profile_name = "trainer"
        elif profile_distribution == "all_speedrunner":
            profile_name = "speedrunner"
        else:  # 50/50
            profile_name = random.choice(["trainer", "speedrunner"])
        
        profile = PROFILES[profile_name].copy()
        
        # Override reward scale and explore weight if configured
        if worker_reward_scale is not None:
            profile["reward_scale"] = worker_reward_scale
        if worker_explore_weight is not None:
            profile["explore_weight"] = worker_explore_weight
        
        # Create per-env stage_config so init_state/rom_path point to env-local paths
        env_stage_config = copy.deepcopy(stage_config)
        env_stage_config["init_state"] = str(env_state_dest)
        env_stage_config["rom_path"] = str(rom_dest)
        # Create settings.json
        settings = {
            "env_index": i,
            "env_name": env_name,
            "env_dir": str(env_dir),
            "stage": worker_stage,
            "input_replay": worker_input_replay,
            "stage_config": env_stage_config,
            "rom_path": str(rom_dest),
            "init_state": str(env_state_dest),
            "profile": profile,
            "catch_directive": profile["catch_directive"],
            "train_directive": profile["train_directive"],
            "save_on_catch": SAVE_ON_CATCH,
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
            "save_on_catch": SAVE_ON_CATCH,
            "reset_on_catch": stage_config.get("reset_on_catch", False),
            "save_on_catch_enabled": SAVE_ON_CATCH_ENABLED,
            "save_on_catch_min_dv": SAVE_ON_CATCH_MIN_DV,
            "description": f"Worker {env_name} - {profile['name']} profile",
            "rom_file": worker_rom_path.name,
            "init_state_file": worker_init_state.name,
            "input_replay": worker_input_replay,
        }
        env_configs.append(config)
    
    # Print assignment summary
    num_workers = num_envs - num_trainers
    red_count = sum(1 for cfg in env_configs if cfg.get('rom_file', '') == 'PokemonRed.gb')
    blue_count = sum(1 for cfg in env_configs if cfg.get('rom_file', '') == 'PokemonBlue.gb')
    print(f"\n[EnvSetup] Created {num_envs} environments for stage '{stage}':")
    print(f"  Trainers: {num_trainers} ({trainers_per_type} per starter type: Charmander, Squirtle, Bulbasaur)")
    print(f"  Workers: {num_workers}")
    print(f"  ROM Distribution: {red_count} PokemonRed.gb, {blue_count} PokemonBlue.gb")
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
        rom_path = DEFAULT_ROM_RED
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
        
        # 50/50 ROM selection for new workers
        use_blue = random.choice([True, False])
        worker_rom = DEFAULT_ROM_BLUE if use_blue else DEFAULT_ROM_RED
        
        # Copy ROM to env folder
        rom_dest = env_dir / worker_rom.name
        if not rom_dest.exists() and worker_rom.exists():
            shutil.copy2(worker_rom, rom_dest)
        
        # 50/50 random profile distribution for new workers
        profile_name = random.choice(["trainer", "speedrunner"])
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
            "save_on_catch": SAVE_ON_CATCH,
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
            "save_on_catch": SAVE_ON_CATCH,
            "reset_on_catch": stage_config.get("reset_on_catch", False),
            "save_on_catch_enabled": SAVE_ON_CATCH_ENABLED,
            "save_on_catch_min_dv": SAVE_ON_CATCH_MIN_DV,
            "description": f"Worker {env_name} - {profile['name']} profile (newly created)",
            "rom_file": worker_rom.name,
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
    trainers_per_type: int = 14,
    mosaic_rows: int = GRID_ROWS,
    mosaic_cols: int = GRID_COLS,
) -> dict[str, Any]:
    """Ensure an environment folder exists, creating it if necessary.
    
    This function is called at runtime when the mosaic launches. It checks if
    the environment folder exists, and if not, creates it with proper settings.
    For Worker envs, uses 'autostage' which will load the stage
    specified by the launcher.
    
    Args:
        env_index: The environment index (0-based).
        rom_source_path: Path to source ROM file to copy.
        default_state_path: Default initial state path.
        launcher_stage: Stage name selected in launcher (for autostage workers).
        trainers_per_type: Number of trainers per starter type (default 14 for 42 total).
        mosaic_rows: Number of rows in the mosaic grid.
        mosaic_cols: Number of columns in the mosaic grid.

    Returns:
        The environment settings dict.
    """
    env_path = get_env_path(env_index, trainers_per_type=trainers_per_type, mosaic_rows=mosaic_rows, mosaic_cols=mosaic_cols)
    settings_file = env_path / "settings.json"
    
    mosaic_tiles = mosaic_rows * mosaic_cols
    total_trainers = trainers_per_type * 3
    is_trainer = env_index < total_trainers
    
    # Create directory structure if missing
    if not env_path.exists():
        env_path.mkdir(parents=True, exist_ok=True)
        (env_path / "checkpoints").mkdir(exist_ok=True)
        (env_path / "states").mkdir(exist_ok=True)
        (env_path / "inputs").mkdir(exist_ok=True)
        
        # Determine profile
        if is_trainer:
            # First trainer of each type = 100% trainer, others = 50/50 random
            trainer_idx = env_index // trainers_per_type
            trainer_offset = env_index % trainers_per_type
            if trainer_offset == 0:
                profile_type = "trainer"
            else:
                profile_type = random.choice(["trainer", "speedrunner"])
        else:
            # Workers = 50/50 random
            profile_type = random.choice(["trainer", "speedrunner"])
        
        profile = PROFILES[profile_type].copy()
        
        # Determine ROM - trainers always use Red, workers 50/50 Red/Blue
        if is_trainer:
            assigned_rom = DEFAULT_ROM_RED
        else:
            use_blue = random.choice([True, False])
            assigned_rom = DEFAULT_ROM_BLUE if use_blue else DEFAULT_ROM_RED
        
        # Determine stage config
        if is_trainer:
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
        
        # Resolve the init state: search in the env's own dir, states/ dir, rom_parent, project root
        init_state_name = Path(default_state_path).name if default_state_path else "init.state"
        env_init_state = _resolve_init_state(init_state_name, env_path, DEFAULT_ROM_RED.parent)
        
        # Copy the init state into the env folder root if it's not already there
        if default_state_path and Path(default_state_path).exists():
            env_state_dest = env_path / Path(default_state_path).name
            if (
                Path(default_state_path).resolve() != env_state_dest.resolve()
                and not env_state_dest.exists()
            ):
                shutil.copy2(default_state_path, env_state_dest)
            init_state_str = str(env_state_dest)
        else:
            init_state_str = str(env_init_state)
        
        # Set env-local paths in stage_config
        env_stage_config = copy.deepcopy(stage_config)
        env_stage_config["name"] = actual_stage
        env_stage_config["init_state"] = init_state_str
        env_stage_config["rom_path"] = str(env_path / rom_dest_name)
        
        settings = {
            "env_index": env_index,
            "env_name": env_path.name,
            "env_dir": str(env_path),
            "stage": actual_stage,
            "input_replay": "",
            "stage_config": env_stage_config,
            "rom_path": str(env_path / rom_dest_name),
            "init_state": init_state_str,
            "profile": profile,
            "catch_directive": profile["catch_directive"],
            "train_directive": profile["train_directive"],
            "save_on_catch": SAVE_ON_CATCH,
            "save_on_catch_enabled": SAVE_ON_CATCH_ENABLED,
            "save_on_catch_min_dv": SAVE_ON_CATCH_MIN_DV,
        }
        
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        
        print(f"[EnvSetup] Created new environment at {env_path} with ROM {rom_dest_name}")
    
    # Copy ROM if source provided and target doesn't exist
    if rom_source_path:
        target_rom_name = rom_source_path.name
        if not (env_path / target_rom_name).exists():
            shutil.copy2(rom_source_path, env_path / target_rom_name)
            print(f"[EnvSetup] Copied ROM to {env_path}")
    
    return get_env_config(env_index)


def get_env_path(env_index: int, trainers_per_type: int = 14, mosaic_rows: int = GRID_ROWS, mosaic_cols: int = GRID_COLS) -> Path:
    """Get the path for an environment by index.
    
    Args:
        env_index: The environment index (0-based).
        trainers_per_type: Number of trainers per starter type.
        mosaic_rows: Number of rows in the mosaic grid.
        mosaic_cols: Number of columns in the mosaic grid.
        
    Returns:
        Path to the environment folder.
    """
    env_name = f"Env{env_index + 1:03d}"
    
    mosaic_tiles = mosaic_rows * mosaic_cols
    total_trainers = trainers_per_type * 3
    
    trainer_names = ["CharmanderTrainer", "SquirtleTrainer", "BulbasaurTrainer"]
    
    if env_index < total_trainers:
        trainer_idx = env_index // trainers_per_type
        return ENVS_DIR / trainer_names[trainer_idx] / env_name
    else:
        return ENVS_DIR / "Workers" / env_name


def copy_file_to_all_envs(source_file_path: str, dest_filename: str | None = None) -> int:
    """Copy a file to all existing environment folders.
    
    Useful for updating resources (ROM, states) without regenerating settings.
    
    Args:
        source_file_path: Path to the source file.
        dest_filename: Name to use in destination folders (defaults to source filename).
        
    Returns:
        Number of environments the file was copied to.
    """
    source = Path(source_file_path)
    if not source.exists():
        print(f"[EnvSetup] Source file not found: {source}")
        return 0
    
    if dest_filename is None:
        dest_filename = source.name
    
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
    
    print(f"[EnvSetup] Copied {source.name} to {count} environments as {dest_filename}.")
    return count