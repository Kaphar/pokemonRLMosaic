"""Migration script: convert zones.json from pixel coordinates to game coordinates.

Zones were previously stored as stitched-map PNG pixel positions ``[px, py]``.
They are now stored as ``{"map_id": m, "x": tx, "y": ty}`` where ``map_id`` is
the in-game map ID (WRAM ``0xD35E``) and ``x`` / ``y`` are tile coordinates
within that map (WRAM ``0xD362`` / ``0xD361``).

This script reads the existing ``zones.json``, reverse-projects each pixel cell
to ``(map_id, x, y)`` using ``v2.map_projection.unproject_position``, and writes
the result back.  Any cell that cannot be reverse-projected (e.g. it falls
outside all maps in ``MAP_OFFSETS``) is assigned to map 0 (Pallet Town) with a
warning — these can be manually re-placed in the UI after migration.

Usage::

    python scripts/migrate_zones_to_game_coords.py [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ZONES_JSON_PATH = PROJECT_ROOT / "skill_lab" / "zones.json"


def _try_import_unproject():
    """Import the reverse projection function from the v2 package."""
    sys.path.insert(0, str(PROJECT_ROOT / "v2"))
    try:
        from map_projection import unproject_position

        return unproject_position
    except Exception as exc:
        print(f"Could not import unproject_position from v2.map_projection: {exc}")
        return None


def _try_unproject(unproject, px, py):
    """Try reverse-projecting ``(px, py)``.

    The old pixel coordinates may have been captured at either the raw pixel
    position or at the position where the cell was rendered (which had a +8
    Y offset).  We try several Y adjustments and return the first in-bounds
    result.
    """
    for y_offset in [0, -8, 8, -16, 16, -24, 24]:
        result = unproject(px, py + y_offset)
        if result.in_bounds:
            return result
    return result


def migrate_zones(zones_path: Path, dry_run: bool = False) -> None:
    """Convert every ``cells`` array in *zones_path* from pixel to game coords."""
    if not zones_path.exists():
        print(f"Zones file not found: {zones_path}")
        return

    unproject = _try_import_unproject()
    if unproject is None:
        print("Cannot migrate without map_projection.unproject_position.")
        sys.exit(1)

    raw = zones_path.read_text(encoding="utf-8")
    data = json.loads(raw)
    zones = data.get("zones", [])

    migrated_count = 0
    skipped_count = 0
    warnings = []
    for zone in zones:
        cells = zone.get("cells", [])
        if not cells:
            continue
        new_cells = []
        for cell in cells:
            if isinstance(cell, dict) and "map_id" in cell:
                new_cells.append(cell)
                skipped_count += 1
                continue
            if not isinstance(cell, (list, tuple)) or len(cell) < 2:
                skipped_count += 1
                continue
            px, py = int(cell[0]), int(cell[1])
            result = _try_unproject(unproject, px, py)
            if result.in_bounds:
                new_cells.append({
                    "map_id": result.map_id,
                    "x": result.x,
                    "y": result.y,
                })
                migrated_count += 1
            else:
                warnings.append(
                    f"  WARNING: cell ({px}, {py}) in zone '{zone.get('label', zone.get('id'))}' "
                    f"could not be reverse-projected — defaulting to map_id=0, x=0, y=0"
                )
                new_cells.append({"map_id": 0, "x": 0, "y": 0})
                migrated_count += 1
        zone["cells"] = new_cells

    if dry_run:
        print(f"[DRY RUN] Would migrate {migrated_count} cells, skip {skipped_count}.")
        for w in warnings:
            print(w)
        print(json.dumps(data, indent=2))
        return

    zones_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Migrated {migrated_count} cells, skipped {skipped_count} already-migrated cells.")
    for w in warnings:
        print(w)
    print(f"Written to {zones_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--zones-path", type=Path, default=ZONES_JSON_PATH,
        help="Path to zones.json (default: skill_lab/zones.json)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print result without writing.")
    args = parser.parse_args()
    migrate_zones(args.zones_path, dry_run=args.dry_run)
