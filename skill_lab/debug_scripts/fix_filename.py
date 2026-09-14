"""Repair saved starter-state filenames by reading DVs from the loaded state."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from pyboy import PyBoy
from pyboy.utils import WindowEvent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skill_lab.party_reader import Gen1PartyReader, PyBoyMemoryReader


STATE_PATTERN = re.compile(r"^(?P<pokemon>.+?)\s+-\s+.*\.state$", re.IGNORECASE)


def read_first_pokemon(pyboy: PyBoy) -> dict | None:
    memory = pyboy.memory
    if int(memory[Gen1PartyReader.PARTY_SIZE_ADDRESS]) == 0:
        return None
    if int(memory[Gen1PartyReader.PARTY_ADDRESS]) == 0:
        return None

    party = Gen1PartyReader(PyBoyMemoryReader(memory)).read_party({
        "partyAddr": Gen1PartyReader.PARTY_ADDRESS,
        "partySlotsCounterAddr": Gen1PartyReader.PARTY_SIZE_ADDRESS,
        "partySpeciesAddr": Gen1PartyReader.PARTY_SPECIES_ADDRESS,
        "partyNicknamesAddr": Gen1PartyReader.PARTY_NICKNAMES_ADDRESS,
    })
    return party[0] if party else None


def advance_with_a(pyboy: PyBoy, frames: int, render: bool) -> None:
    pyboy.send_input(WindowEvent.PRESS_BUTTON_A)
    pyboy.tick(8, render)
    pyboy.send_input(WindowEvent.RELEASE_BUTTON_A)
    pyboy.tick(max(frames - 8, 1), render)


def repair_state(
    state_path: Path,
    rom_path: Path,
    attempts: int,
    frames: int,
    force: bool,
    visual: bool,
) -> bool:
    print(f"Checking: {state_path}")
    pyboy = PyBoy(str(rom_path), window="SDL2" if visual else "null")
    if visual:
        pyboy.set_emulation_speed(1)
    try:
        with state_path.open("rb") as state_file:
            pyboy.load_state(state_file)

        pokemon = read_first_pokemon(pyboy)
        for attempt in range(attempts):
            if pokemon is not None:
                break
            advance_with_a(pyboy, frames, visual)
            pokemon = read_first_pokemon(pyboy)
            if visual and (attempt + 1) % 10 == 0:
                print(f"  A-button attempts: {attempt + 1}/{attempts}")

        if pokemon is None:
            print("  Could not read a populated party record; leaving file unchanged.")
            return False

        dvs = (
            int(pokemon.get("ivAttack", 0)),
            int(pokemon.get("ivDefense", 0)),
            int(pokemon.get("ivSpeed", 0)),
            int(pokemon.get("ivSpAttack", 0)),
        )
        if any(dv < 0 or dv > 15 for dv in dvs) or all(dv == 0 for dv in dvs):
            print(f"  Invalid/unpopulated DVs {dvs}; leaving file unchanged.")
            return False

        pokemon_name = str(pokemon.get("speciesName", "Unknown"))
        suffix = "PERFECT" if all(dv == 15 for dv in dvs) else "-".join(map(str, dvs))
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", pokemon_name).strip("._")
        destination = state_path.with_name(f"{safe_name} - {suffix}.state")

        if destination != state_path and destination.exists() and not force:
            print(f"  Destination exists; use --force to replace: {destination}")
            return False

        old_input_path = state_path.with_suffix(".json")
        new_input_path = destination.with_suffix(".json")
        repaired_state_path = destination.with_suffix(".repairing.state")
        with repaired_state_path.open("wb") as repaired_state_file:
            pyboy.save_state(repaired_state_file)

        if destination != state_path:
            if destination.exists() and force:
                destination.unlink()
            if old_input_path.exists():
                if new_input_path.exists() and not force:
                    repaired_state_path.unlink()
                    print("  Matching input destination exists; use --force. State unchanged.")
                    return False
                else:
                    old_input_path.replace(new_input_path)
            state_path.unlink()
        elif destination.exists():
            destination.unlink()
        repaired_state_path.replace(destination)

        print(f"  DVs: {dvs}; renamed to: {destination.name}")
        return True
    finally:
        pyboy.stop()


def main() -> None:
    project_root = PROJECT_ROOT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path, nargs="?", help="One .state file to repair")
    parser.add_argument("--rom", type=Path, default=project_root / "PokemonRed.gb")
    parser.add_argument("--envs-dir", type=Path, default=Path(__file__).resolve().parent / "envs")
    parser.add_argument("--attempts", type=int, default=240, help="A-button advances per state")
    parser.add_argument("--frames", type=int, default=24, help="Frames per A-button advance")
    parser.add_argument("--visual", action="store_true", help="Show the PyBoy SDL2 window while repairing")
    parser.add_argument("--force", action="store_true", help="Replace an existing destination")
    args = parser.parse_args()

    if not args.rom.exists():
        raise FileNotFoundError(f"ROM not found: {args.rom}")
    if args.attempts < 1 or args.frames < 9:
        parser.error("--attempts must be positive and --frames must be at least 9")

    if args.state is not None:
        state_paths = [args.state.resolve()]
    else:
        state_paths = sorted(args.envs_dir.resolve().glob("*/states/*.state"))

    if not state_paths:
        print("No state files found.")
        return

    repaired = sum(
        repair_state(path, args.rom.resolve(), args.attempts, args.frames, args.force, args.visual)
        for path in state_paths
    )
    print(f"Repaired {repaired} of {len(state_paths)} state(s).")


if __name__ == "__main__":
    main()