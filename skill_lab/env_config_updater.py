"""Utility to recursively update settings.json files in environment subfolders.

This script helps manage environment configurations for Pokemon Red RL training.
It can update any field in settings.json files across all environments in a subfolder.

USAGE EXAMPLES:
    # Update init_state to a new state file (copies state to each env folder)
    python env_config_updater.py SquirtleTrainer init_state "path/to/new_init.state" --copy-state

    # Update nested field stage_config.init_state
    python env_config_updater.py Workers stage_config.init_state '"custom_init.state"'

    # Update profile.reward_scale
    python env_config_updater.py SquirtleTrainer profile.reward_scale 3.0

    # Update arrays/objects using JSON
    python env_config_updater.py Workers catch_directive '["Pikachu", "Eevee"]'

    # Dry run to preview changes
    python env_config_updater.py Workers init_state '"new.state"' --dry-run

    # List available subfolders
    python env_config_updater.py --list-subfolders

    # Apply a trainer's trainer_config.json to all of its Env subfolders
    # Reads <subfolder>/trainer_config.json and updates stage, init_state,
    # rom_path, and profile fields (incl. reward_scale/explore_weight) in
    # each Env*/settings.json. Use --dry-run to preview.
    python env_config_updater.py CharmanderTrainer --from-trainer-config
    python env_config_updater.py CharmanderTrainer --from-trainer-config --dry-run

FIELD PATHS (dot notation):
    init_state                    # Root level init_state
    stage_config.init_state       # Inside stage_config object
    stage_config.max_steps        # Inside stage_config object
    profile.reward_scale          # Inside profile object
    profile.explore_weight        # Inside profile object
    catch_directive               # Root level array
    train_directive               # Root level array
    rom_path                      # Root level path
    input_replay                  # Root level path to a recorded inputs JSON
"""

from pathlib import Path
import json
import argparse
import shutil
from typing import Any, Callable, Optional


ENVS_DIR = Path(__file__).resolve().parents[1] / "skill_lab" / "envs"

TRAINER_NAMES = ["CharmanderTrainer", "SquirtleTrainer", "BulbasaurTrainer"]

PROFILES = {
    "trainer": {
        "name": "trainer",
        "reward_scale": 2.0,
        "explore_weight": 0.5,
        "catch_directive": ["Nidoran\u2642", "Pidgey", "Rattata", "Spearow", "Pikachu"],
        "train_directive": ["Nidoran\u2642", "Pikachu"],
        "save_on_catch": True,
        "save_on_catch_enabled": True,
        "save_on_catch_min_dv": 11,
    },
    "explorer": {
        "name": "explorer",
        "reward_scale": 0.5,
        "explore_weight": 3.0,
        "catch_directive": [],
        "train_directive": [],
        "save_on_catch": False,
        "save_on_catch_enabled": False,
        "save_on_catch_min_dv": 11,
    },
}


def list_subfolders() -> list[str]:
    """List all subfolders in envs/ that contain settings.json files."""
    subfolders = []
    for item in ENVS_DIR.iterdir():
        if item.is_dir() and list(item.rglob("settings.json")):
            subfolders.append(item.name)
    return sorted(subfolders)


def find_settings_files(env_subfolder: str) -> list[Path]:
    """Find all settings.json files in the given env subfolder recursively."""
    subfolder_path = ENVS_DIR / env_subfolder
    if not subfolder_path.exists():
        raise ValueError(f"Subfolder not found: {subfolder_path}")
    return list(subfolder_path.rglob("settings.json"))


def load_trainer_config(trainer_name: str) -> dict:
    """Load trainer_config.json for a named trainer folder."""
    config_path = ENVS_DIR / trainer_name / "trainer_config.json"
    if not config_path.exists():
        raise FileNotFoundError(
            f"trainer_config.json not found in {config_path.parent}"
        )
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def apply_trainer_config_to_env(
    settings_path: Path, trainer_config: dict
) -> bool:
    """Apply a trainer_config.json dict to a single env's settings.json.

    Mirrors the logic in env_setup.setup_envs: picks a profile, overrides
    reward_scale / explore_weight, then writes stage, init_state,
    rom_path, and profile fields into settings.json and the flattened top-level
    catch_directive / train_directive / save_on_catch. (reset_on_catch is a
    stage-level property, not a profile or root setting.)

    Returns True if the file was modified, False otherwise.
    """
    with open(settings_path, "r", encoding="utf-8") as f:
        settings = json.load(f)

    profile_name = trainer_config.get("profile", "trainer")
    if profile_name not in PROFILES:
        profile_name = "trainer"
    profile = PROFILES[profile_name].copy()

    reward_scale = trainer_config.get("reward_scale")
    explore_weight = trainer_config.get("explore_weight")
    if reward_scale is not None:
        profile["reward_scale"] = reward_scale
    if explore_weight is not None:
        profile["explore_weight"] = explore_weight

    modified = False

    stage = trainer_config.get("stage")
    if stage is not None and settings.get("stage") != stage:
        settings["stage"] = stage
        modified = True

    init_state_file = trainer_config.get("init_state")
    if init_state_file is not None:
        if settings.get("init_state") != init_state_file:
            settings["init_state"] = init_state_file
            modified = True
        # Also sync stage_config.init_state to point to the env-local copy
        env_dir = settings_path.parent
        stage_cfg = settings.get("stage_config")
        if isinstance(stage_cfg, dict):
            stage_init_state = str(env_dir / init_state_file)
            if stage_cfg.get("init_state") != stage_init_state:
                stage_cfg["init_state"] = stage_init_state
                modified = True
        # Copy the state file into the env folder root if it's missing
        env_state_dest = env_dir / init_state_file
        if not env_state_dest.exists():
            for search_dir in [env_dir, env_dir / "states", ENVS_DIR.parent, PROJECT_ROOT]:
                src = search_dir / init_state_file
                if src.exists():
                    shutil.copy2(src, env_state_dest)
                    break

    input_replay = trainer_config.get("input_replay")
    if input_replay is not None and settings.get("input_replay") != input_replay:
        settings["input_replay"] = input_replay
        modified = True

    rom_file = trainer_config.get("rom")
    if rom_file is not None:
        env_dir = settings_path.parent
        rom_dest = env_dir / rom_file
        rom_path_value = str(rom_dest)
        if settings.get("rom_path") != rom_path_value:
            settings["rom_path"] = rom_path_value
            modified = True
        if isinstance(stage_cfg, dict):
            if stage_cfg.get("rom_path") != rom_path_value:
                stage_cfg["rom_path"] = rom_path_value
                modified = True

    existing_profile = settings.get("profile", {})
    for key, value in profile.items():
        if existing_profile.get(key) != value:
            existing_profile[key] = value
            modified = True
    settings["profile"] = existing_profile

    for flat_key in ("catch_directive", "train_directive", "save_on_catch"):
        if existing_profile.get(flat_key, None) != profile.get(flat_key, None):
            if settings.get(flat_key) != profile.get(flat_key):
                settings[flat_key] = profile.get(flat_key)
                modified = True

    if not modified:
        return False

    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)

    return True


def update_envs_from_trainer_config(
    trainer_name: str, dry_run: bool = False
) -> dict:
    """Apply a trainer's trainer_config.json to all of its Env subfolders.

    Args:
        trainer_name: One of TRAINER_NAMES (e.g. "CharmanderTrainer").
        dry_run: If True, only preview changes without writing.

    Returns:
        Dict with results: {"updated": int, skipped", int, "errors": list, "details": list}.
    """
    trainer_config = load_trainer_config(trainer_name)
    settings_files = find_settings_files(trainer_name)

    results: dict = {
        "updated": 0,
        "skipped": 0,
        "errors": [],
        "details": [],
    }
    if not settings_files:
        results["errors"].append(
            f"No settings.json files found under {trainer_name}"
        )
        return results

    for settings_file in settings_files:
        try:
            if dry_run:
                with open(settings_file, "r", encoding="utf-8") as f:
                    before = json.load(f)

                profile_name = trainer_config.get("profile", "trainer")
                profile = PROFILES.get(profile_name, PROFILES["trainer"]).copy()
                if trainer_config.get("reward_scale") is not None:
                    profile["reward_scale"] = trainer_config["reward_scale"]
                if trainer_config.get("explore_weight") is not None:
                    profile["explore_weight"] = trainer_config["explore_weight"]

                changes = []
                if trainer_config.get("stage") and before.get("stage") != trainer_config["stage"]:
                    changes.append(
                        f"stage: {before.get('stage')} -> {trainer_config['stage']}"
                    )
                init_file = trainer_config.get("init_state")
                if init_file and before.get("init_state") != init_file:
                    changes.append(
                        f"init_state: {before.get('init_state')} -> {init_file}"
                    )
                    stage_cfg = before.get("stage_config", {})
                    stage_init_state = str(settings_file.parent / init_file)
                    if isinstance(stage_cfg, dict) and stage_cfg.get("init_state") != stage_init_state:
                        changes.append(
                            f"stage_config.init_state: {stage_cfg.get('init_state')} -> {stage_init_state}"
                        )
                rom_file = trainer_config.get("rom")
                if rom_file and before.get("rom_path") != str(settings_file.parent / rom_file):
                    changes.append(
                        f"rom_path: {before.get('rom_path')} -> {rom_file}"
                    )
                    stage_cfg = before.get("stage_config", {})
                    if isinstance(stage_cfg, dict):
                        stage_rom_path = str(settings_file.parent / rom_file)
                        if stage_cfg.get("rom_path") != stage_rom_path:
                            changes.append(
                                f"stage_config.rom_path: {stage_cfg.get('rom_path')} -> {stage_rom_path}"
                            )
                replay_path = trainer_config.get("input_replay")
                if replay_path is not None and before.get("input_replay") != replay_path:
                    changes.append(
                        f"input_replay: {before.get('input_replay')} -> {replay_path}"
                    )
                before_profile = before.get("profile", {})
                for key, value in profile.items():
                    if before_profile.get(key) != value:
                        changes.append(
                            f"profile.{key}: {before_profile.get(key)} -> {value}"
                        )
                    if key in ("catch_directive", "train_directive", "save_on_catch"):
                        if before.get(key) != value:
                            changes.append(
                                f"{key}: {before.get(key)} -> {value}"
                            )

                if changes:
                    results["updated"] += 1
                    preview = "; ".join(changes)
                    results["details"].append(
                        f"WOULD UPDATE: {settings_file.relative_to(ENVS_DIR)} ({preview})"
                    )
                else:
                    results["skipped"] += 1
                    results["details"].append(
                        f"SKIP (no changes): {settings_file.relative_to(ENVS_DIR)}"
                    )
            else:
                modified = apply_trainer_config_to_env(settings_file, trainer_config)
                if modified:
                    results["updated"] += 1
                    results["details"].append(
                        f"UPDATED: {settings_file.relative_to(ENVS_DIR)}"
                    )
                else:
                    results["skipped"] += 1
                    results["details"].append(
                        f"SKIP (no changes): {settings_file.relative_to(ENVS_DIR)}"
                    )
        except Exception as e:
            results["errors"].append(
                f"{settings_file.relative_to(ENVS_DIR)}: {e}"
            )
            results["details"].append(
                f"ERROR: {settings_file.relative_to(ENVS_DIR)} - {e}"
            )

    return results


def copy_state_to_envs(state_path: Path, env_subfolder: str) -> dict:
    """
    Copy a state file to each environment folder (at root level).
    
    Args:
        state_path: Path to the source state file
        env_subfolder: Name of the subfolder under envs/
        
    Returns:
        Dict with results: {"copied": int, "skipped": int, "errors": list, "details": list}
    """
    if not state_path.exists():
        raise ValueError(f"State file not found: {state_path}")
    
    settings_files = find_settings_files(env_subfolder)
    
    results = {"copied": 0, "skipped": 0, "errors": [], "details": []}
    
    for settings_file in settings_files:
        env_dir = settings_file.parent
        dest_path = env_dir / state_path.name
        
        try:
            if dest_path.exists():
                results["skipped"] += 1
                results["details"].append(f"SKIP (exists): {dest_path.relative_to(ENVS_DIR)}")
            else:
                shutil.copy2(state_path, dest_path)
                results["copied"] += 1
                results["details"].append(f"COPIED: {dest_path.relative_to(ENVS_DIR)}")
        except Exception as e:
            results["errors"].append(f"{env_dir.relative_to(ENVS_DIR)}: {e}")
            results["details"].append(f"ERROR: {env_dir.relative_to(ENVS_DIR)} - {e}")
    
    return results


def update_json_field(
    file_path: Path,
    field_path: str,
    new_value: Any,
    transform: Optional[Callable[[Any], Any]] = None,
) -> bool:
    """
    Update a nested field in a JSON file.
    
    Args:
        file_path: Path to the JSON file
        field_path: Dot-separated path to the field (e.g., "init_state" or "stage_config.init_state")
        new_value: The new value to set
        transform: Optional function to transform the value before setting
        
    Returns:
        True if the file was modified, False otherwise
    """
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    keys = field_path.split(".")
    current = data
    for key in keys[:-1]:
        if key not in current:
            return False
        current = current[key]
    
    final_key = keys[-1]
    if final_key not in current:
        return False
    
    old_value = current[final_key]
    value_to_set = transform(new_value) if transform else new_value
    
    if old_value == value_to_set:
        return False
    
    current[final_key] = value_to_set
    
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    
    return True


def update_env_configs(
    env_subfolder: str,
    field_path: str,
    new_value: Any,
    transform: Optional[Callable[[Any], Any]] = None,
    dry_run: bool = False,
) -> dict:
    """
    Update a field in all settings.json files within an env subfolder.
    
    Args:
        env_subfolder: Name of the subfolder under envs/ (e.g., "SquirtleTrainer", "Workers")
        field_path: Dot-separated path to the field (e.g., "init_state", "stage_config.init_state", "profile.reward_scale")
        new_value: The new value to set
        transform: Optional function to transform the value before setting
        dry_run: If True, only show what would be changed without modifying files
        
    Returns:
        Dict with results: {"updated": int, "skipped": int, "errors": list, "details": list}
    """
    settings_files = find_settings_files(env_subfolder)
    
    results = {"updated": 0, "skipped": 0, "errors": [], "details": []}
    
    for settings_file in settings_files:
        try:
            if dry_run:
                with open(settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                keys = field_path.split(".")
                current = data
                for key in keys[:-1]:
                    if key not in current:
                        current = None
                        break
                    current = current[key]
                
                if current is None or keys[-1] not in current:
                    results["skipped"] += 1
                    results["details"].append(f"SKIP (field not found): {settings_file.relative_to(ENVS_DIR)}")
                    continue
                
                old_value = current[keys[-1]]
                value_to_set = transform(new_value) if transform else new_value
                
                if old_value == value_to_set:
                    results["skipped"] += 1
                    results["details"].append(f"SKIP (same value): {settings_file.relative_to(ENVS_DIR)}")
                else:
                    results["updated"] += 1
                    results["details"].append(f"WOULD UPDATE: {settings_file.relative_to(ENVS_DIR)} ({old_value} -> {value_to_set})")
            else:
                modified = update_json_field(settings_file, field_path, new_value, transform)
                if modified:
                    results["updated"] += 1
                    results["details"].append(f"UPDATED: {settings_file.relative_to(ENVS_DIR)}")
                else:
                    results["skipped"] += 1
                    results["details"].append(f"SKIP: {settings_file.relative_to(ENVS_DIR)}")
        except Exception as e:
            results["errors"].append(f"{settings_file.relative_to(ENVS_DIR)}: {e}")
            results["details"].append(f"ERROR: {settings_file.relative_to(ENVS_DIR)} - {e}")
    
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Update settings.json files in env subfolders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument("subfolder", nargs="?", help="Env subfolder name (e.g., SquirtleTrainer, Workers)")
    parser.add_argument("field", nargs="?", help="Field path (e.g., init_state, stage_config.init_state, profile.reward_scale)")
    parser.add_argument("value", nargs="?", help="New value (JSON format)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be changed without modifying")
    parser.add_argument("--copy-state", action="store_true", help="Copy state file to each env folder (root) and update init_state")
    parser.add_argument("--list-subfolders", action="store_true", help="List available env subfolders and exit")
    parser.add_argument("--from-trainer-config", action="store_true",
                        help="Apply <subfolder>/trainer_config.json to all Env*/settings.json under that trainer. "
                             "Requires --subfolder to be one of the trainers (CharmanderTrainer, etc.)")
    
    args = parser.parse_args()
    
    if args.list_subfolders:
        subfolders = list_subfolders()
        print("Available env subfolders:")
        for sf in subfolders:
            count = len(find_settings_files(sf))
            print(f"  {sf} ({count} environments)")
        return
    
    if args.from_trainer_config:
        if not args.subfolder:
            parser.error("--from-trainer-config requires --subfolder")
        if args.subfolder not in TRAINER_NAMES:
            parser.error(
                f"--from-trainer-config requires a trainer subfolder "
                f"({', '.join(TRAINER_NAMES)}); got '{args.subfolder}'"
            )
        try:
            trainer_config = load_trainer_config(args.subfolder)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            print(f"[EnvConfigUpdater] Error loading trainer config: {e}")
            return

        print(
            f"Applying trainer_config.json from '{args.subfolder}' to all "
            f"Env*/settings.json (profile={trainer_config.get('profile', 'trainer')})..."
        )
        results = update_envs_from_trainer_config(
            args.subfolder, dry_run=args.dry_run
        )

        label = "WOULD UPDATE (dry run)" if args.dry_run else "Updated"
        print(f"\nResults:")
        print(f"  {label}: {results['updated']}")
        print(f"  Skipped: {results['skipped']}")
        print(f"  Errors:  {len(results['errors'])}")

        for detail in results["details"]:
            print(f"  {detail}")

        if results["errors"]:
            print("\nErrors:")
            for error in results["errors"]:
                print(f"  {error}")
        return
    
    if not args.subfolder or not args.field or args.value is None:
        parser.print_help()
        return
    
    try:
        new_value = json.loads(args.value)
    except json.JSONDecodeError:
        new_value = args.value
    
    if args.copy_state:
        state_path = Path(new_value)
        if not state_path.is_absolute():
            state_path = Path.cwd() / state_path
        
        print(f"Copying state file '{state_path}' to each environment in '{args.subfolder}'...")
        copy_results = copy_state_to_envs(state_path, args.subfolder)
        
        print(f"\nCopy Results:")
        print(f"  Copied:  {copy_results['copied']}")
        print(f"  Skipped: {copy_results['skipped']}")
        print(f"  Errors:  {len(copy_results['errors'])}")
        
        for detail in copy_results["details"]:
            print(f"  {detail}")
        
        if copy_results["errors"]:
            print("\nErrors:")
            for error in copy_results["errors"]:
                print(f"  {error}")
        
        # Update init_state to just the filename (since it's now in the env root)
        state_filename = state_path.name
        print(f"\nUpdating init_state to '{state_filename}'...")
        new_value = state_filename
    
    print(f"Updating field '{args.field}' to '{new_value}' in '{args.subfolder}'...")
    
    results = update_env_configs(args.subfolder, args.field, new_value, dry_run=args.dry_run)
    
    print(f"\nResults:")
    print(f"  Updated: {results['updated']}")
    print(f"  Skipped: {results['skipped']}")
    print(f"  Errors:  {len(results['errors'])}")
    
    for detail in results["details"]:
        print(f"  {detail}")
    
    if results["errors"]:
        print("\nErrors:")
        for error in results["errors"]:
            print(f"  {error}")


if __name__ == "__main__":
    main()