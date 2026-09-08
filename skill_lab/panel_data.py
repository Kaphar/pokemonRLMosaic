"""Shared data and rendering helpers for the Skill Lab debug panels."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from skill_lab.bag_reader import Gen1PlayerReader
from skill_lab.party_reader import Gen1PartyReader, PyBoyMemoryReader

MAP_N_ADDRESS = 0xD35E
X_POS_ADDRESS = 0xD362
Y_POS_ADDRESS = 0xD361
BADGE_COUNT_ADDRESS = 0xD356
MENU_HANDLER_START = 0xCC26
MENU_HANDLER_END = 0xCC2F

PARTY_ADDRESSES = {
    "partyAddr": Gen1PartyReader.PARTY_ADDRESS,
    "partySlotsCounterAddr": Gen1PartyReader.PARTY_SIZE_ADDRESS,
    "partySpeciesAddr": Gen1PartyReader.PARTY_SPECIES_ADDRESS,
    "partyNicknamesAddr": Gen1PartyReader.PARTY_NICKNAMES_ADDRESS,
}


def read_panel_data(memory: Any) -> dict[str, Any]:
    """Read the common live data displayed by both inspectors."""
    party_reader = Gen1PartyReader(PyBoyMemoryReader(memory))
    player_reader = Gen1PlayerReader(PyBoyMemoryReader(memory))
    trainer = player_reader.update_trainer_info()
    return {
        "map_id": int(memory[MAP_N_ADDRESS]),
        "map_address": MAP_N_ADDRESS,
        "x": int(memory[X_POS_ADDRESS]),
        "y": int(memory[Y_POS_ADDRESS]),
        "position_addresses": {"x": X_POS_ADDRESS, "y": Y_POS_ADDRESS},
        "badges": int(memory[BADGE_COUNT_ADDRESS]).bit_count(),
        "party": party_reader.read_party(PARTY_ADDRESSES),
        "trainer": trainer or {},
        "bag": player_reader.read_bag().get("items", []),
    }


def draw_party_panel(
    image: np.ndarray,
    x: int,
    y: int,
    width: int,
    height: int,
    party: list[dict[str, Any]],
) -> None:
    """Draw the shared party presentation into an existing image."""
    cv2.putText(image, "Party", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 1)
    row_y = y + 22
    for slot, pokemon in enumerate(party[:6]):
        if pokemon.get("speciesID", 0) == 0:
            continue
        type_names = pokemon.get("type1Name", "?")
        if pokemon.get("type2") != pokemon.get("type1"):
            type_names += f"/{pokemon.get('type2Name', '?')}"
        name = pokemon.get("nickname") or pokemon.get("speciesName", "Unknown")
        header = f"{slot + 1}. {name} ({pokemon.get('speciesName', '?')}) Lv{pokemon.get('level', 0)} {type_names}"
        stats = (
            f"HP {pokemon.get('curHP', 0)}/{pokemon.get('maxHP', 0)}  "
            f"Atk {pokemon.get('attack', 0)} Def {pokemon.get('defense', 0)} "
            f"Spe {pokemon.get('speed', 0)} Sp {pokemon.get('spAttack', 0)}"
        )
        dvs = (
            f"DV HP {pokemon.get('ivHP', 0)} Atk {pokemon.get('ivAttack', 0)} "
            f"Def {pokemon.get('ivDefense', 0)} Spe {pokemon.get('ivSpeed', 0)} "
            f"Sp {pokemon.get('ivSpAttack', 0)}"
        )
        cv2.putText(image, header[: max(1, width // 7)], (x, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (255, 255, 255), 1)
        cv2.putText(image, stats[: max(1, width // 6)], (x, row_y + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.31, (180, 220, 255), 1)
        cv2.putText(image, dvs[: max(1, width // 6)], (x, row_y + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.31, (180, 255, 180), 1)
        cv2.line(image, (x, row_y + 33), (x + width, row_y + 33), (65, 65, 65), 1)
        row_y += 44
        if row_y + 44 > y + height:
            break
    if not party:
        cv2.putText(image, "No Pokemon", (x, y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)


def draw_trainer_bag_panel(
    image: np.ndarray,
    x: int,
    y: int,
    width: int,
    trainer: dict[str, Any],
    bag: list[dict[str, Any]],
) -> None:
    """Draw trainer identity, economy, badges, and bag contents consistently."""
    cv2.putText(image, "Trainer", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    trainer_line = (
        f"{trainer.get('name', '?')}  ${trainer.get('money', 0)}  "
        f"Coins {trainer.get('coins', 0)}  Badges {trainer.get('badge_count', 0)}/8"
    )
    cv2.putText(image, trainer_line[: max(1, width // 7)], (x, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 230, 160), 1)
    cv2.putText(image, "Bag", (x, y + 38), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    bag_line = ", ".join(f"{item['name']} x{item['quantity']}" for item in bag) or "Empty"
    cv2.putText(image, bag_line[: max(1, width // 6)], (x, y + 56), cv2.FONT_HERSHEY_SIMPLEX, 0.31, (200, 220, 255), 1)


def draw_world_info(image: np.ndarray, x: int, y: int, data: dict[str, Any]) -> None:
    """Draw map identity and player coordinates using shared labels."""
    lines = (
        f"Map {data['map_id']:02X} ({data['map_id']}) @ 0x{data['map_address']:04X}",
        f"Position X={data['x']} Y={data['y']} @ 0x{data['position_addresses']['x']:04X}/0x{data['position_addresses']['y']:04X}",
    )
    for offset, line in enumerate(lines):
        cv2.putText(image, line, (x, y + offset * 18), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 0), 1)


def read_menu_handler_bytes(memory: Any) -> dict[int, int]:
    """Read the WRAM menu/text handler probe range for diagnostics."""
    return {
        address: int(memory[address])
        for address in range(MENU_HANDLER_START, MENU_HANDLER_END + 1)
    }


def draw_menu_handler_info(image: np.ndarray, x: int, y: int, memory: Any) -> None:
    """Draw raw CC26-CC2F values without assuming their exact meanings."""
    values = read_menu_handler_bytes(memory)
    cv2.putText(image, "WRAM menu/text probe (raw)", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (190, 220, 255), 1)
    row = " ".join(f"{address:04X}:{value:02X}" for address, value in values.items())
    cv2.putText(image, row, (x, y + 17), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (190, 220, 255), 1)
