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

FIELD PATHS (dot notation):
    init_state                    # Root level init_state
    stage_config.init_state       # Inside stage_config object
    stage_config.max_steps        # Inside stage_config object
    profile.reward_scale          # Inside profile object
    profile.explore_weight        # Inside profile object
    catch_directive               # Root level array
    train_directive               # Root level array
    rom_path                      # Root level path
"""

from pathlib import Path
import json
import argparse
import shutil
from typing import Any, Callable, Optional


ENVS_DIR = Path(__file__).resolve().parents[1] / "skill_lab" / "envs"


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
    
    args = parser.parse_args()
    
    if args.list_subfolders:
        subfolders = list_subfolders()
        print("Available env subfolders:")
        for sf in subfolders:
            count = len(find_settings_files(sf))
            print(f"  {sf} ({count} environments)")
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