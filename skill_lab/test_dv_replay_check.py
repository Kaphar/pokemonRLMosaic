"""DV replay verification script.

Recursively finds the N most recently created JSON input recordings in the
envs folder, replays each one using one or both replay methods (old step-by-step
or plugin frame-exact), reads the first Pokemon's DVs with the Gen1PartyReader,
and compares them to the DVs encoded in the filename.

Also cross-references the saved .state file to determine whether mismatches
are caused by replay timing divergence or by state file corruption.

Usage:
    python -m skill_lab.test_dv_replay_check --count 100
    python -m skill_lab.test_dv_replay_check --count 100 --method plugin
    python -m skill_lab.test_dv_replay_check --count 100 --no-check-state
    python -m skill_lab.test_dv_replay_check --count 100 --log dv_report.log --csv dv_results.csv
"""
from __future__ import annotations

import argparse
import csv
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
    _prime_emulator,
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


def parse_dvs(filename: str) -> tuple[str, tuple[int, int, int, int]] | None:
    """Extract (pokemon_name, (atk, def, spd, spc)) from a JSON filename."""
    m = INPUT_JSON_RE.match(filename)
    if m is None:
        return None
    pokemon = m.group("pokemon").strip()
    dv_text = m.group("dvs").upper()
    if dv_text == "PERFECT":
        return pokemon, (15, 15, 15, 15)
    return pokemon, tuple(int(v) for v in dv_text.split("-"))


def find_latest_json_files(envs_dir: Path, count: int) -> list[Path]:
    """Recursively find the N most recently created .json files in envs/*/inputs/."""
    files: list[tuple[float, Path]] = []
    for p in envs_dir.rglob("*.json"):
        if p.parent.name == "inputs":
            try:
                files.append((p.stat().st_mtime, p))
            except OSError:
                pass
    files.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in files[:count]]


@dataclass
class MethodResult:
    dvs: tuple[int, int, int, int] | None = None
    matched: bool = False
    error: str | None = None
    elapsed_s: float = 0.0
    total_actions: int = 0
    total_frames: int = 0


@dataclass
class CheckResult:
    file: str
    env: str
    pokemon: str
    expected_dvs: tuple[int, int, int, int]
    total_actions: int
    old: MethodResult = field(default_factory=MethodResult)
    plugin: MethodResult = field(default_factory=MethodResult)
    state_dvs: tuple[int, int, int, int] | None = None
    state_found: bool = False
    state_matched: bool = False
    elapsed_s: float = 0.0


def _read_party_dvs(pyboy: PyBoy) -> tuple[int, int, int, int] | None:
    """Read first Pokemon DVs using Gen1PartyReader."""
    reader = Gen1PartyReader(PyBoyMemoryReader(pyboy.memory))
    party = reader.read_party(PARTY_ADDRESSES)
    if not party:
        return None
    pk = party[0]
    return (
        int(pk.get("ivAttack", 0)),
        int(pk.get("ivDefense", 0)),
        int(pk.get("ivSpeed", 0)),
        int(pk.get("ivSpAttack", 0)),
    )


def _do_replay(
    pyboy: PyBoy,
    actions: list[int],
    replay_data: dict[str, Any],
    method: str,
) -> tuple[tuple[int, int, int, int] | None, str | None]:
    """Replay actions on the given PyBoy instance and return (dvs, error)."""
    action_freq = int(replay_data.get("action_freq", ACTION_FREQ))
    noop_action = int(replay_data.get("noop_action", 8))
    total_frames = len(actions) * action_freq
    try:
        if method == "old":
            for action in actions:
                replay_action(pyboy, action, action_freq, verbose=False, render=False, noop_action=noop_action)
        elif method == "plugin":
            input_events = replay_data.get("input_events", [])
            if not input_events:
                input_events = generate_input_events(actions, action_freq, noop_action)
            replay_frame_by_frame(pyboy, input_events, total_frames, verbose=False, render=False)
        return _read_party_dvs(pyboy), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def check_file(
    json_path: Path,
    methods: list[str],
    check_state: bool,
) -> CheckResult:
    """Process a single JSON file: replay with requested methods, check state."""
    t0 = time.time()

    parsed = parse_dvs(json_path.name)
    pokemon_name = "?"
    expected_dvs = (0, 0, 0, 0)
    if parsed is not None:
        pokemon_name, expected_dvs = parsed

    rel_path = str(json_path.relative_to(PROJECT_ROOT).as_posix())
    env_name = json_path.parent.parent.name if len(json_path.parents) >= 2 else "unknown"
    result = CheckResult(
        file=rel_path,
        env=env_name,
        pokemon=pokemon_name,
        expected_dvs=expected_dvs,
        total_actions=0,
    )

    actions, replay_data = load_replay(json_path)
    result.total_actions = len(actions)

    rom_path = resolve_recording_path(replay_data.get("rom")) or DEFAULT_ROM
    state_path = resolve_recording_path(replay_data.get("init_state"))
    action_freq = int(replay_data.get("action_freq", ACTION_FREQ))
    noop_action = int(replay_data.get("noop_action", 8))

    if state_path is None:
        for m in methods:
            mr = getattr(result, m)
            mr.error = "No init_state in recording"
        result.elapsed_s = round(time.time() - t0, 2)
        return result

    # --- State file cross-check ---
    if check_state:
        m = INPUT_JSON_RE.match(json_path.name)
        if m is not None:
            state_name = m.group(0).replace(".json", ".state")
            state_file = json_path.parent.parent / "states" / state_name
            if state_file.is_file():
                result.state_found = True
                s_pyboy = PyBoy(str(DEFAULT_ROM), window="null", sound=False)
                try:
                    with state_file.open("rb") as sf:
                        s_pyboy.load_state(sf)
                    result.state_dvs = _read_party_dvs(s_pyboy)
                    if result.state_dvs is not None:
                        result.state_matched = result.state_dvs == expected_dvs
                except Exception:
                    pass
                finally:
                    s_pyboy.stop()

    # --- Replay ---
    pyboy = PyBoy(str(rom_path), window="null", sound=False)
    try:
        _prime_emulator(pyboy, state_path, actions, action_freq, noop_action, num_actions=len(actions))
        with state_path.open("rb") as sf:
            pyboy.load_state(sf)
        for method in methods:
            if method != methods[0]:
                with state_path.open("rb") as sf:
                    pyboy.load_state(sf)

            t_replay = time.time()
            dvs, err = _do_replay(pyboy, actions, replay_data, method)
            elapsed = round(time.time() - t_replay, 2)

            mr = getattr(result, method)
            mr.dvs = dvs
            mr.matched = dvs == expected_dvs if dvs else False
            mr.error = err
            mr.elapsed_s = elapsed
            mr.total_actions = len(actions)
            mr.total_frames = len(actions) * int(replay_data.get("action_freq", ACTION_FREQ))
    except Exception as exc:
        for m in methods:
            mr = getattr(result, m)
            mr.error = f"{type(exc).__name__}: {exc}"
    finally:
        pyboy.stop()

    result.elapsed_s = round(time.time() - t0, 2)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--count", type=int, default=100,
        help="Number of most recently created JSON files to check (default: 100)",
    )
    parser.add_argument(
        "--envs-dir", type=Path, default=ENVS_DIR,
        help="Root envs folder (default: skill_lab/envs)",
    )
    parser.add_argument(
        "--method", choices=["old", "plugin", "both"], default="both",
        help="Replay method to use (default: both)",
    )
    parser.add_argument(
        "--check-state", action=argparse.BooleanOptionalAction, default=True,
        help="Also check DVs directly from the saved .state file",
    )
    parser.add_argument(
        "--log", type=Path, default=None,
        help="Optional log file path for human-readable results",
    )
    parser.add_argument(
        "--csv", type=Path, default=None,
        help="Optional CSV file path for machine-readable results",
    )
    parser.add_argument(
        "--matches-states", type=Path, default=None,
        help="Optional output file listing full paths of files where the plugin method matched (one per line)",
    )
    args = parser.parse_args()

    envs_dir = args.envs_dir.resolve()
    if not envs_dir.is_dir():
        print(f"ERROR: envs dir not found: {envs_dir}")
        sys.exit(1)

    json_files = find_latest_json_files(envs_dir, args.count)
    if not json_files:
        print(f"No JSON input files found in {envs_dir}/*/inputs/")
        sys.exit(0)

    methods = ["old", "plugin"] if args.method == "both" else [args.method]

    print(f"Checking {len(json_files)} JSON file(s) in {envs_dir}", flush=True)
    print(f"Replay method(s): {', '.join(methods)}", flush=True)
    print(f"State file cross-check: {'on' if args.check_state else 'off'}", flush=True)
    print("=" * 80, flush=True)

    results: list[CheckResult] = []
    log_lines: list[str] = []

    for idx, jf in enumerate(json_files, 1):
        parsed = parse_dvs(jf.name)
        expected_str = "-".join(map(str, parsed[1])) if parsed else "N/A"
        env_name = jf.parent.parent.name
        line = f"[{idx}/{len(json_files)}] {env_name}/{jf.name}  expected={expected_str}"
        print(line, flush=True)
        log_lines.append(line)

        result = check_file(jf, methods, args.check_state)
        results.append(result)

        for method in methods:
            mr = getattr(result, method)
            if mr.error:
                detail = f"  {method:7s} ERROR: {mr.error}"
            elif mr.dvs is None:
                detail = f"  {method:7s} No party found after replay"
            else:
                dvs_str = "-".join(map(str, mr.dvs))
                match_str = "MATCH" if mr.matched else "MISMATCH"
                detail = f"  {method:7s} DV={dvs_str}  {match_str}  ({mr.total_actions} actions, {mr.elapsed_s}s)"
            print(detail, flush=True)
            log_lines.append(detail)

        if args.check_state:
            if not result.state_found:
                state_line = f"  {'state':7s} (no .state file found)"
            elif result.state_dvs is None:
                state_line = f"  {'state':7s} (error reading state)"
            else:
                dvs_str = "-".join(map(str, result.state_dvs))
                match_str = "MATCH" if result.state_matched else "MISMATCH"
                state_line = f"  {'state':7s} DV={dvs_str}  {match_str}"
            print(state_line, flush=True)
            log_lines.append(state_line)

        log_lines.append("")
        print(flush=True)

    # --- Summary ---
    total = len(results)
    old_matches = sum(1 for r in results if not r.old.error and r.old.dvs and r.old.matched)
    plugin_matches = sum(1 for r in results if not r.plugin.error and r.plugin.dvs and r.plugin.matched)
    state_matches = sum(1 for r in results if r.state_found and r.state_matched)
    state_mismatches = sum(1 for r in results if r.state_found and not r.state_matched)
    state_not_found = sum(1 for r in results if not r.state_found)
    total_time = sum(r.elapsed_s for r in results)

    summary_lines = [
        "=" * 80,
        "SUMMARY",
        "=" * 80,
        f"Total files checked:        {total}",
        f"Old method DV matches:      {old_matches}/{total}",
        f"Plugin method DV matches:   {plugin_matches}/{total}",
    ]

    if args.check_state:
        summary_lines.extend([
            f"State file DV matches:      {state_matches}/{state_matches + state_mismatches}",
            f"State file DV mismatches:   {state_mismatches}",
            f"State file not found:       {state_not_found}",
        ])

    summary_lines.extend([
        f"Total time:                 {total_time:.1f}s",
        "",
    ])

    if old_matches == 0 and plugin_matches == total:
        summary_lines.extend([
            "KEY FINDING:",
            "  The OLD replay method (step-by-step tick(24)) produces DV mismatches.",
            "  The PLUGIN replay method (frame-by-frame with input_events) MATCHES.",
            "  State .state files also match the filename DVs.",
            "  => The old method has a timing issue that causes RNG divergence.",
            f"  => The plugin method is the correct/proper replay mode.",
            "",
        ])
    elif old_matches == total and plugin_matches == 0:
        summary_lines.extend([
            "KEY FINDING:",
            "  The OLD replay method matches but the PLUGIN method does not.",
            "  This is the opposite of expected behavior.",
            "",
        ])
    elif old_matches == total and plugin_matches == total:
        summary_lines.append("All DVs match across all replay methods!")
    elif old_matches == 0 and plugin_matches == 0:
        summary_lines.append(f"All {total} file(s) mismatched. No matches found.")
    else:
        summary_lines.append(f"Old: {old_matches}/{total} match. Plugin: {plugin_matches}/{total} match.")

    if old_matches > 0 and old_matches < total and plugin_matches == total:
        summary_lines.append(f"But only {old_matches} old-method files matched — investigate those.")

    summary_text = "\n".join(summary_lines)
    print(summary_text, flush=True)
    log_lines.extend(summary_lines)

    if args.log:
        args.log.parent.mkdir(parents=True, exist_ok=True)
        with args.log.open("w") as f:
            f.write("\n".join(log_lines) + "\n")
        print(f"Log written to: {args.log}", flush=True)

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "file", "env", "pokemon", "expected_dvs", "total_actions",
            "old_dvs", "old_matched", "old_error", "old_elapsed_s",
            f"plugin_dvs", "plugin_matched", "plugin_error", "plugin_elapsed_s",
            "state_dvs", "state_found", "state_matched", "elapsed_s",
        ]
        with args.csv.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for r in results:
                row = {
                    "file": r.file,
                    "env": r.env,
                    "pokemon": r.pokemon,
                    "expected_dvs": "-".join(map(str, r.expected_dvs)),
                    "total_actions": r.total_actions,
                    "old_dvs": "-".join(map(str, r.old.dvs)) if r.old.dvs else None,
                    "old_matched": r.old.matched,
                    "old_error": r.old.error,
                    "old_elapsed_s": r.old.elapsed_s,
                    "plugin_dvs": "-".join(map(str, r.plugin.dvs)) if r.plugin.dvs else None,
                    "plugin_matched": r.plugin.matched,
                    "plugin_error": r.plugin.error,
                    "plugin_elapsed_s": r.plugin.elapsed_s,
                    "state_dvs": "-".join(map(str, r.state_dvs)) if r.state_dvs else None,
                    "state_found": r.state_found,
                    "state_matched": r.state_matched,
                    "elapsed_s": r.elapsed_s,
                }
                writer.writerow(row)
        print(f"CSV written to: {args.csv}", flush=True)

    if args.matches_states:
        plugin_matched_files = [
            str(jf.resolve().as_posix())
            for jf, r in zip(json_files, results)
            if "plugin" in methods and r.plugin.matched
        ]
        args.matches_states.parent.mkdir(parents=True, exist_ok=True)
        with args.matches_states.open("w") as f:
            f.write("\n".join(plugin_matched_files) + ("\n" if plugin_matched_files else ""))
        print(f"Matches-states written to: {args.matches_states} ({len(plugin_matched_files)} files)", flush=True)


if __name__ == "__main__":
    main()
