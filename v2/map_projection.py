"""Readable coordinate projection between in-game tile positions and the
stitched Kanto map image used by the skill-lab browser dashboard.

Two coordinate systems are in play:

* **In-game tile coordinates** — ``x_pos`` and ``y_pos`` are single-byte
  values read from Game Boy WRAM (``0xD362`` / ``0xD361``) and are relative
  to the current map (``map_id`` / ``map_n`` at ``0xD35E``).

* **PNG pixel coordinates** — ``pixel_x`` / ``pixel_y`` are coordinates in
  the 4000 × 4000 pixel stitched map image
  (``poke_map/pokemap_full_calibrated_CROPPED_1.png``).

Every game tile is exactly ``PIXELS_PER_TILE`` (16) pixels wide/tall in the
stitched image.  The image origin is the top-left corner, with *x* increasing
to the right and *y* increasing downward.  Each map is drawn at a calibrated
pixel offset so that adjacent outdoor maps line up correctly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NamedTuple

# ---------------------------------------------------------------------------
# Projection constants
# ---------------------------------------------------------------------------

PIXELS_PER_TILE = 16
"""One game tile occupies this many pixels in the stitched map image."""

# The top-left corner of the Kanto world-map grid, in PNG pixel space.
# ``global_offset_x`` was derived as ``1056 - 16 * 12`` in the original
# BetterMapVis calibration and corresponds to Pallet-town's pixel origin
# when its tile offset is (0, 0).
GLOBAL_OFFSET_X = 864
GLOBAL_OFFSET_Y = 331

# Default image dimensions (the calibrated PNG is 4000 × 4000).
DEFAULT_MAP_WIDTH = 4000
DEFAULT_MAP_HEIGHT = 4000

# ---------------------------------------------------------------------------
# Map offset table
# ---------------------------------------------------------------------------
# Each entry maps a in-game ``map_id`` (the value stored at WRAM 0xD35E)
# to ``(offset_x, offset_y)``, a *tile* offset that positions the map within
# the global 4000 × 4000 pixel stitched image.
#
# The table below covers the outdoor maps and the indoor maps that the
# stitched image actually contains.  Maps not listed here fall back to an
# offset of (0, 0), i.e. they project to the Pallet-town region of the image.
#
# Source: original ``map_offsets`` dict in ``red_gym_env_v2.py`` and
#         ``web_dashboard.py``, calibrated from ``BetterMapVis_script_version.py``.

MAP_OFFSETS: dict[int, tuple[int, int]] = {
    # --- Kanto outdoor maps ---
    0: (0, 0),        # Pallet Town
    1: (-10, 72),     # Viridian City
    2: (-10, 180),    # Pewter City
    12: (0, 36),      # Route 1
    13: (0, 144),     # Route 2
    14: (30, 172),    # Route 3
    15: (80, 190),    # Route 4
    33: (-50, 64),    # Route 22
    51: (-35, 137),   # Viridian Forest

    # --- Pallet / Viridian indoor maps ---
    37: (-9, 2),      # Player's House — First Floor
    38: (-9, -7),     # Player's House — Second Floor
    39: (21, 2),      # Rival's House
    40: (21, -6),     # Oak's Lab
    41: (30, 47),     # Pokémon Center (Viridian City)
    42: (30, 55),     # Poké Mart (Viridian City)
    43: (30, 72),     # Pokémon Academy
    44: (30, 64),     # Nickname House (Viridian City)

    # --- Pewter indoor maps ---
    47: (21, 136),    # Gate (Viridian City ↔ Pewter City)
    49: (21, 108),    # Gate (Route 2 / Route 22)
    50: (21, 108),    # Gate (Route 2 / Viridian Forest)
    52: (-10, 189),   # Museum F1
    53: (-10, 198),   # Museum F2
    54: (-21, 169),   # Pewter Gym
    55: (-19, 177),   # House with Nidoran ♂ (Pewter City)
    56: (-30, 163),   # Poké Mart (Pewter City)
    57: (-19, 177),   # House with two Trainers (Pewter City)
    58: (-25, 154),   # Pokémon Center (Pewter City)

    # --- Mt. Moon ---
    59: (83, 227),    # Mt. Moon (Route 3 entrance)
    60: (123, 227),   # Mt. Moon B1F
    61: (152, 227),   # Mt. Moon B2F

    # --- Other ---
    68: (65, 190),    # Pokémon Center (Route 4)
}

# Human-readable names for every map that has a calibrated offset.
MAP_NAMES: dict[int, str] = {
    0: "Pallet Town",
    1: "Viridian City",
    2: "Pewter City",
    12: "Route 1",
    13: "Route 2",
    14: "Route 3",
    15: "Route 4",
    33: "Route 22",
    37: "Player's House — First Floor",
    38: "Player's House — Second Floor",
    39: "Rival's House",
    40: "Oak's Lab",
    41: "Pokémon Center (Viridian City)",
    42: "Poké Mart (Viridian City)",
    43: "Pokémon Academy",
    44: "Nickname House",
    47: "Gate (Viridian ↔ Pewter)",
    49: "Gate (Route 2)",
    50: "Gate (Route 2 ↔ Viridian Forest)",
    51: "Viridian Forest",
    52: "Pewter Museum F1",
    53: "Pewter Museum F2",
    54: "Pewter Gym",
    55: "Nidoran House (Pewter City)",
    56: "Poké Mart (Pewter City)",
    57: "House with Two Trainers (Pewter City)",
    58: "Pokémon Center (Pewter City)",
    59: "Mt. Moon (Route 3 Entrance)",
    60: "Mt. Moon B1F",
    61: "Mt. Moon B2F",
    68: "Pokémon Center (Route 4)",
    193: "Badge Check Gate (Route 22)",
}


def get_map_name(map_id: int) -> str:
    """Return a human-readable name for *map_id*, or ``'Unknown'``."""
    return MAP_NAMES.get(map_id, "Unknown")


# ---------------------------------------------------------------------------
# Map tile sizes (loaded from map_data.json — only needed for reverse lookup)
# ---------------------------------------------------------------------------

_MAP_DATA_PATH = Path(__file__).resolve().parent / "map_data.json"
_MAP_DATA: dict[int, dict] | None = None


def _load_map_data() -> dict[int, dict]:
    """Lazily load ``map_data.json`` and return a ``{map_id: region}`` dict."""
    global _MAP_DATA
    if _MAP_DATA is None:
        with _MAP_DATA_PATH.open("r", encoding="utf-8") as fh:
            regions = json.load(fh)["regions"]
        _MAP_DATA = {int(r["id"]): r for r in regions}
    return _MAP_DATA


def _get_map_tile_size(map_id: int) -> tuple[int, int] | None:
    """Return ``(tile_width, tile_height)`` for *map_id* from map_data.json."""
    data = _load_map_data()
    region = data.get(map_id)
    if region is None:
        return None
    tile = region.get("tileSize", [0, 0])
    return int(tile[0]), int(tile[1])


# ---------------------------------------------------------------------------
# Forward projection  —  in-game tile coords → PNG pixel coords
# ---------------------------------------------------------------------------


class MapPixelCoordinates(NamedTuple):
    """Coordinates in the stitched 4000 × 4000 map PNG image."""

    pixel_x: int
    pixel_y: int


def project_position(
    x_pos: int,
    y_pos: int,
    map_n: int,
    *,
    base_y: int = DEFAULT_MAP_HEIGHT,
) -> MapPixelCoordinates:
    """Convert in-game tile coordinates to stitched-map PNG pixel coordinates.

    Parameters
    ----------
    x_pos:
        In-game X tile coordinate (read from WRAM ``0xD362``).
    y_pos:
        In-game Y tile coordinate (read from WRAM ``0xD361``).
    map_n:
        In-game map id (read from WRAM ``0xD35E``).  Selects the calibrated
        offset for this map.
    base_y:
        Height of the stitched map PNG in pixels.  Defaults to 4000.
        The BetterMapVis visualisation script occasionally works with a
        cropped overlay whose height differs from 4000, so this is exposed
        as a keyword argument.

    Returns
    -------
    MapPixelCoordinates
        ``(pixel_x, pixel_y)`` in the stitched image.
    """
    offset_x, offset_y = MAP_OFFSETS.get(map_n, (0, 0))

    # X is straightforward: start at the global origin, add the map offset
    # and the in-game X position (all in tile units), then scale to pixels.
    pixel_x = GLOBAL_OFFSET_X + PIXELS_PER_TILE * (offset_x + x_pos)

    # Y is flipped because the game's Y-axis points "up" (smaller Y = further
    # north on the map) while image rows increase downward.
    pixel_y = base_y - (
        GLOBAL_OFFSET_Y + PIXELS_PER_TILE * (offset_y - y_pos)
    )

    return MapPixelCoordinates(int(pixel_x), int(pixel_y))


# ---------------------------------------------------------------------------
# Reverse projection  —  PNG pixel coords → in-game tile coords + map_id
# ---------------------------------------------------------------------------


class ReverseProjectionResult(NamedTuple):
    """Result of reverse-projecting a PNG pixel back to in-game coordinates."""

    map_id: int
    map_name: str
    x: int
    y: int
    in_bounds: bool


def unproject_position(pixel_x: int, pixel_y: int) -> ReverseProjectionResult:
    """Convert a stitched-map PNG pixel back to in-game tile coordinates.

    Iterates over every calibrated map offset and returns the first map whose
    bounding box contains the given pixel.  When no map matches, ``map_id``
    is ``0`` (Pallet Town) and ``in_bounds`` is ``False``.

    Parameters
    ----------
    pixel_x:
        X coordinate in the 4000 × 4000 stitched map image.
    pixel_y:
        Y coordinate in the 4000 × 4000 stitched map image.

    Returns
    -------
    ReverseProjectionResult
        ``(map_id, map_name, x, y, in_bounds)``.
    """
    # Pallet Town is the fallback when nothing is found.
    default_result = ReverseProjectionResult(
        map_id=0,
        map_name=MAP_NAMES[0],
        x=0,
        y=0,
        in_bounds=False,
    )

    for map_id, (offset_x, offset_y) in MAP_OFFSETS.items():
        tile_size = _get_map_tile_size(map_id)
        if tile_size is None:
            # Fall back to the "unknown" bounding box — treat the map as a
            # single tile so we at least still reverse-project the offset.
            tile_width = 1
            tile_height = 1
        else:
            tile_width, tile_height = tile_size

        origin_x = GLOBAL_OFFSET_X + PIXELS_PER_TILE * offset_x
        origin_y = DEFAULT_MAP_HEIGHT - (
            GLOBAL_OFFSET_Y + PIXELS_PER_TILE * offset_y
        )
        max_x = origin_x + PIXELS_PER_TILE * tile_width
        max_y = origin_y + PIXELS_PER_TILE * tile_height

        if origin_x <= pixel_x <= max_x and origin_y <= pixel_y <= max_y:
            game_x = int((pixel_x - GLOBAL_OFFSET_X) / PIXELS_PER_TILE - offset_x)
            game_y = int(
                offset_y - (DEFAULT_MAP_HEIGHT - pixel_y - GLOBAL_OFFSET_Y)
                / PIXELS_PER_TILE
            )
            return ReverseProjectionResult(
                map_id=map_id,
                map_name=get_map_name(map_id),
                x=game_x,
                y=game_y,
                in_bounds=True,
            )

    return default_result
