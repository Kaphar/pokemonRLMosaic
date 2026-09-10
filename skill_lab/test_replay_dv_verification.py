"""Replay verification script: checks DV consistency between recorded inputs and party state.

Finds the N most recently created JSON input recordings in the envs folder,
replays each one using both the old-style step replay and the plugin-style
frame-exact replay, then uses the Gen1PartyReader to read the first Pokemon's
DVs from memory and compares them to the DVs encoded in the filename.

Also cross-references the saved .state file to isolate replay-timing issues
from state file issues.

Usage:
    python -m skill_lab.test_replay_dv_verification --count 100
    python -m skill_lab.test_replay_dv_verification --count 50 --method old
    python -m skill_lab.test_replay_dv_verification --count 100 --method plugin
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyboy import PyBoy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skill_lab.emulator_with_debug import (
    ACTION_FREQ,
    DEFAULT_ROM,
    replay_action,
    replay_frame_by_frame,
    load_replay,
    resolve_recording_path,
    generate_input_events,
)
from skill_lab.party_reader import Gen1PartyReader, PyBoyMemoryReader

ENVS_DIR = PROJECT_ROOT / "skill_lab" / "envs"
INPUT_JSON_RE = re.compile(
    r"^(?P<pokemon>.+?)\s+-\s+(?P<dvs>PERFECT|\d+(?:-\d+){3})\.json$",
    re.IGNORECASE,
)

PARTY_ADDRESSES = {
    "partyAddr": Gen1PartyReader.PARTY_ADDRESS,
    "partySlotsCounterAddr": Gen1PartyReader.PARTY_SIZE_ADDRESS,
    "partySpeciesAddr": Gen1PartyReader.PARTY_SPECIES_ADDRESS,
    "partyNicknamesAddr": Gen1PartyReader.PARTY_NICKNAMES_ADDRESS,
}


def parse_dvs_from_filename(filename: str) -> tuple[str, tuple[int, int, int, int]] | None:
    """Extract (pokemon_name, (atk, def, spd, spc)) from an input JSON filename."""
    match = INPUT_JSON_RE.match(filename)
    if match is None:
        return None
    pokemon = match.group("pokemon").strip()
    dv_text = match.group("dvs").upper()
    if dv_text == "PERFECT":
        return pokemon, (15, 15, 15, 15)
    values = tuple(int(v) for v in dv_text.split("-"))
    return pokemon, values


def read_first_pokemon_dvs(pyboy: PyBoy) -> tuple[int, int, int, int] | None:
    """Use the Gen1PartyReader to read the first Pokemon's stored DVs."""
    reader = Gen1PartyReader(PyBoyMemoryReader(pyboy.memory))
    party = reader.read_party(PARTY_ADDRESSES)
    if not party:
        return None
    pokemon = party[0]
    return (
        int(pokemon.get("ivAttack", 0)),
        int(pokemon.get("ivDefense", 0)),
        int(pokemon.get("ivSpeed", 0)),
        int(pokemon.get("ivSpAttack", 0)),
    )


def load_init_state_into_pyboy(pyboy: PyBoy, state_path: Path | None) -> bool:
    """Load the init state into a fresh PyBoy instance."""
    try:
        with state_path.open("rb") as state_file:
            pyboy.load_state(state_file)
        return True
    except Exception as error:
        print(f"  [ERROR] Failed to load state {state_path}: {error}")
        return False


def replay_old_way(pyboy: PyBoy, actions: list[int], action_freq: int) -> None:
    """Replay using the old-style step-by-step replay_action."""
    for action in actions:
        replay_action(pyboy, action, action_freq, verbose=False, render=False)


def replay_plugin_way(pyboy: PyBoy, json_path: Path, actions: list[int], action_freq: int) -> None:
    """Replay using the plugin-style frame-exact frame-by-frame replay."""
    _, replay_data = load_replay(json_path)
    input_events = replay_data.get("input_events", [])
    if not input_events:
        noop_action = int(replay_data.get("noop_action", 7))
        input_events = generate_input_events(actions, action_freq, noop_action)
    total_frames = len(actions) * action_freq
    replay_frame_by_frame(pyboy, input_events, total_frames, verbose=False, render=False)


def find_recent_json_files(envs_dir: Path, count: int) -> list[Path]:
    """Find the N most recently created JSON files in envs/*/inputs/."""
    json_files: list[tuple[float, Path]] = []
    for json_path in envs_dir.rglob("*.json"):
        if json_path.parent.name == "inputs":
            try:
                mtime = json_path.stat().st_mtime
                json_files.append((mtime, json_path))
            except OSError:
                pass
    json_files.sort(key=lambda x: x[0], reverse=True)
    return [path for _, path in json_files[:count]]


@dataclass
class ReplayResult:
    method: str
    expected_dvs: tuple[int, int, int, int]
    actual_dvs: tuple[int, int, int, int] | None
    elapsed: float
    error: str | None = None
    total_actions: int = 0
    total_frames: int = 0

    @property
    def matched(self) -> bool:
        return self.actual_dvs is not None and self.actual_dvs == self.expected_dvs


@dataclass
class FileResult:
    json_path: Path
    pokemon_name: str
    expected_dvs: tuple[int, int, int, int]
    env_name: str
    results: dict[str, ReplayResult] = field(default_factory=dict)
    state_dvs: tuple[int, int, int, int] | None = None
    state_matches: bool | None = None

    @property
    def replay_matched(self) -> bool:
        return all(r.matched for r in self.results.values() if r.error is None)


def read_dvs_from_state_file(json_path: Path) -> tuple[int, int, int, int] | None:
    """Load the objective .state file and read DVs for cross-reference."""
    match = INPUT_JSON_RE.match(json_path.name)
    if match is None:
        return None
    state_filename = match.group(0).replace(".json", ".state")
    state_path = json_path.parent.parent / "states" / state_filename
    if not state_path.is_file():
        return None
    pyboy = PyBoy(str(DEFAULT_ROM), window="null", sound=False)
    try:
        with state_path.open("rb") as state_file:
            pyboy.load_state(state_file)
        return read_first_pokemon_dvs(pyboy)
    except Exception:
        return None
    finally:
        pyboy.stop()


def replay_and_check(
    json_path: Path,
    method: str,
    expected_dvs: tuple[int, int, int, int],
) -> ReplayResult:
    """Set up PyBoy, replay inputs with the given method, and read DVs."""
    start_time = time.time()
    actions, replay_data = load_replay(json_path)
    action_freq = int(replay_data.get("action_freq", ACTION_FREQ))
    total_frames = len(actions) * action_freq

    rom_path = resolve_recording_path(replay_data.get("rom")) or DEFAULT_ROM
    state_path = resolve_recording_path(replay_data.get("init_state"))

    if state_path is None:
        return ReplayResult(
            method=method,
            expected_dvs=expected_dvs,
            actual_dvs=None,
            elapsed=0.0,
            error="No usable init_state in recording",
            total_actions=len(actions),
            total_frames=total_frames,
        )

    pyboy = PyBoy(str(rom_path), window="null", sound=False)
    try:
        if not load_init_state_into_pyboy(pyboy, state_path):
            return ReplayResult(
                method=method,
                expected_dvs=expected_dvs,
                actual_dvs=None,
                elapsed=time.time() - start_time,
                error=f"Failed to load init state: {state_path}",
                total_actions=len(actions),
                total_frames=total_frames,
            )

        if method == "old":
            replay_old_way(pyboy, actions, action_freq)
        elif method == "plugin":
            replay_plugin_way(pyboy, json_path, actions, action_freq)
        else:
            replay_old_way(pyboy, actions, action_freq)

        actual_dvs = read_first_pokemon_dvs(pyboy)
        return ReplayResult(
            method=method,
            expected_dvs=expected_dvs,
            actual_dvs=actual_dvs,
            elapsed=time.time() - start_time,
            total_actions=len(actions),
            total_frames=total_frames,
        )
    except Exception as error:
        return ReplayResult(
            method=method,
            expected_dvs=expected_dvs,
            actual_dvs=None,
            elapsed=time.time() - start_time,
            error=f"{type(error).__name__}: {error}",
            total_actions=len(actions),
            total_frames=total_frames,
        )
    finally:
        pyboy.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Number of most recently created JSON files to check (default: 100)",
    )
    parser.add_argument(
        "--envs-dir",
        type=Path,
        default=ENVS_DIR,
        help="Folder containing environment subdirectories (default: skill_lab/envs)",
    )
    parser.add_argument(
        "--method",
        choices=["old", "plugin", "both"],
        default="both",
        help="Which replay method to use (default: both)",
    )
    parser.add_argument(
        "--check-state",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Also read DVs directly from the .state file for cross-reference",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional path to write a JSON summary of results",
    )
    args = parser.parse_args()

    envs_dir = args.envs_dir.resolve()
    if not envs_dir.is_dir():
        print(f"ERROR: envs dir not found: {envs_dir}")
        sys.exit(1)

    json_files = find_recent_json_files(envs_dir, args.count)
    if not json_files:
        print(f"No JSON input files found in {envs_dir}")
        sys.exit(0)

    print(f"Found {len(json_files)} JSON input file(s) to verify.", flush=True)
    print(f"Replay method: {args.method}")
    print(f"State cross-check: {'on' if args.check_state else 'off'}")
    print("-" * 80)

    results: list[FileResult] = []
    methods_to_run = ["old", "plugin"] if args.method == "both" else [args.method]

    for index, json_path in enumerate(json_files, 1):
        parsed = parse_dvs_from_filename(json_path.name)
        if parsed is None:
            print(f"[{index}/{len(json_files)}] SKIP {json_path.name}")
            continue

        pokemon_name, expected_dvs = parsed
        env_name = json_path.parent.parent.name if len(json_path.parents) >= 2 else "unknown"
        expected_str = "-".join(map(str, expected_dvs))

        print(f"[{index}/{len(json_files)}] {env_name}/{json_path.name}")
        print(f"  Expected DVs: {pokemon_name} {expected_str}")

        file_result = FileResult(
            json_path=json_path,
            pokemon_name=pokemon_name,
            expected_dvs=expected_dvs,
            env_name=env_name,
        )

        if args.check_state:
            state_dvs = read_dvs_from_state_file(json_path)
            if state_dvs is not None:
                state_match = state_dvs == expected_dvs
                file_result.state_dvs = state_dvs
                file_result.state_matches = state_match
                state_str = "-".join(map(str, state_dvs))
                print(f"  State file DVs:  {state_str}  {'OK' if state_match else 'MISMATCH!!!'}")
            else:
                print(f"  State file DVs:  (no matching .state file found)")

        for method in methods_to_run:
            result = replay_and_check(json_path, method, expected_dvs)
            file_result.results[method] = result
            if result.error:
                print(f"  [{method.upper()}] ERROR: {result.error}")
            elif result.actual_dvs is None:
                print(f"  [{method.upper()}] No party found after replay")
            else:
                actual_str = "-".join(map(str, result.actual_dvs))
                match_str = "OK" if result.matched else "MISMATCH!!!"
                print(f"  [{method.upper()}] {result.total_actions} actions "
                      f"({result.total_frames} frames) in {result.elapsed:.1f}s → "
                      f"DV={actual_str}  {match_str}")

        results.append(file_result)
        print()

    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)

    total = len(results)
    if total == 0:
        print("No matching JSON files to summarize.")
        return

    both_ok = sum(1 for fr in results if fr.replay_matched and fr.results)
    old_ok = sum(1 for fr in results if "old" in fr.results and fr.results["old"].matched)
    plugin_ok = sum(1 for fr in results if "plugin" in fr.results and fr.results["plugin"].matched)
    both_fail = sum(1 for fr in results if all(not r.matched and r.error is None for r in fr.results.values()))
    errored = sum(1 for fr in results if any(r.error for r in fr.results.values()))

    state_ok = 0
    state_mismatch = 0
    state_no_file = 0
    if args.check_state:
        for fr in results:
            if fr.state_dvs is not None:
                if fr.state_matches:
                    state_ok += 1
                else:
                    state_mismatch += 1
            else:
                state_no_file += 1

    print(f"Total files processed:           {total}")
    if args.check_state:
        print(f"State file DVs matched:          {state_ok}")
        print(f"State file DVs MISMATCH:         {state_mismatch}")
        print(f"State file not found:            {state_no_file}")
    print(f"Old replay DVs matched:          {old_ok}")
    print(f"Plugin replay DVs matched:       {plugin_ok}")
    print(f"Both replay methods matched:     {both_ok}")
    print(f"Both replay methods FAILED:      {both_fail}")
    print(f"Errors (skipped/exceptions):     {errored}")

    if both_fail > 0 and args.check_state and state_ok > 0:
        print()
        print("KEY FINDING: State files have correct DVs but replays do NOT.")
        print("This isolates the issue to replay timing/sequence divergence,")
        print("not to the saved state file itself.")

    mismatches = [
        fr for fr in results
        if ("old" in fr.results and fr.results["old"].error is None and not fr.results["old"].matched)
        or ("plugin" in fr.results and fr.results["plugin"].error is None and not fr.results["plugin"].matched)
    ]

    if mismatches:
        print()
        print("--- MISMATCH DETAILS ---")
        for fr in mismatches:
            expected = "-".join(map(str, fr.expected_dvs))
            parts = []
            for method in methods_to_run:
                r = fr.results.get(method)
                if r and r.error is None and r.actual_dvs is not None:
                    actual = "-".join(map(str, r.actual_dvs))
                    parts.append(f"{method}={actual}")
            state_str = ""
            if fr.state_dvs is not None:
                state_str = f" | state={'-'.join(map(str, fr.state_dvs))}"
            print(f"  {fr.json_path.relative_to(PROJECT_ROOT).as_posix()}: "
                  f"expected={expected} {' '.join(parts)}{state_str}")

    if args.output:
        summary = []
        for fr in results:
            entry: dict[str, Any] = {
                "file": str(fr.json_path.relative_to(PROJECT_ROOT).as_posix()),
                "pokemon": fr.pokemon_name,
                "env": fr.env_name,
                "expected_dvs": list(fr.expected_dvs),
            }
            if fr.state_dvs is not None:
                entry["state_dvs"] = list(fr.state_dvs)
                entry["state_matches"] = fr.state_matches
            for method, r in fr.results.items():
                entry[f"{method}_actual_dvs"] = list(r.actual_dvs) if r.actual_dvs else None
                entry[f"{method}_matched"] = r.matched
                if r.error:
                    entry[f"{method}_error"] = r.error
                entry[f"{method}_total_actions"] = r.total_actions
                entry[f"{method}_total_frames"] = r.total_frames
                entry[f"{method}_elapsed_s"] = round(r.elapsed, 2)
            summary.append(entry)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w") as f:
            json.dump({"timestamp": datetime.now(timezone.utc).isoformat(), "results": summary}, f, indent=2)
        print(f"\nDetailed results written to: {args.output}")

    if both_ok == total:
        print("\nAll DVs match across all replay methods. No discrepancies found.")
    elif both_ok == 0 and state_ok == total and args.check_state:
        print("\nAll replays mismatched but all state files verified correct.")
        print("The issue is in replay timing/sequence reproduction, not the saved state.")
    else:
        print(f"\n{both_ok}/{total} fully passed. See details above.")


if __name__ == "__main__":
    main()
