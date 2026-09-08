"""Convert legacy input recordings to replay the environment's masked actions.
it should be useless now, need to check or save replay"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEFAULT_NOOP_ACTION = 7


def fix_recording(source: Path, destination: Path, noop_action: int = DEFAULT_NOOP_ACTION) -> int:
    """Write a corrected copy and return the number of masked entries fixed."""
    with source.open("r", encoding="utf-8") as input_file:
        data = json.load(input_file)

    fixed_count = 0

    def fix_actions(entries: list[object]) -> None:
        nonlocal fixed_count
        for entry in entries:
            if not isinstance(entry, dict) or not entry.get("masked", False):
                continue
            if "requested_action" not in entry:
                entry["requested_action"] = entry.get("action")
            entry["action"] = noop_action
            fixed_count += 1

    fix_actions(data.get("actions", []))
    for environment in data.get("envs", {}).values():
        fix_actions(environment.get("actions", []))

    data["masking_fixed"] = True
    data["noop_action"] = noop_action
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as output_file:
        json.dump(data, output_file, indent=2)
        output_file.write("\n")
    return fixed_count


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Existing inputs JSON file")
    parser.add_argument("output", type=Path, nargs="?", help="Corrected JSON path")
    parser.add_argument("--in-place", action="store_true", help="Replace the input file")
    parser.add_argument("--noop-action", type=int, default=DEFAULT_NOOP_ACTION)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.in_place and args.output is not None:
        raise SystemExit("Use either OUTPUT or --in-place, not both")
    if not args.in_place and args.output is None:
        raise SystemExit("Provide OUTPUT or use --in-place")
    destination = args.input if args.in_place else args.output
    fixed_count = fix_recording(args.input, destination, args.noop_action)
    print(f"Fixed {fixed_count} masked actions: {destination}")


if __name__ == "__main__":
    main()