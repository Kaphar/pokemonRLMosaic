"""Zone manager for lava zones and action-masking zones.

Zones are stored in ``zones.json`` as a list of zone objects.  Each zone has:

* ``id``        – unique identifier
* ``type``      – ``"lava"`` or ``"action_mask"``
* ``cells``     – list of ``[x, y]`` pixel positions in the stitched map
* ``label``     – human-readable name
* ``color``     – display color
* ``opacity``   – display opacity (0–1)
* ``action``     – (action_mask only) action name to mask, e.g. ``"Down"``
* ``activate_on``   – (action_mask only) checkpoint name that activates the zone
* ``deactivate_on`` – (action_mask only) checkpoint name that deactivates the zone

Backward compatibility: if ``zones.json`` does not exist the manager falls back
to reading the legacy ``lava.json`` flat list and converts it into a single
``"lava"`` zone.
"""

from __future__ import annotations

import json
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ZONES_JSON_PATH = PROJECT_ROOT / "skill_lab" / "zones.json"
LAVA_JSON_PATH = PROJECT_ROOT / "skill_lab" / "lava.json"

#: Canonical action-name ordering — matches ``valid_actions`` in RedGymEnv.
ACTION_NAMES = ["Down", "Left", "Right", "Up", "A", "B", "Start", "Select"]

#: Default display colours per zone type.
ZONE_TYPE_COLORS: dict[str, str] = {
    "lava": "#ff6b6b",
    "action_mask": "#4a9eff",
}

#: Default display opacity per zone type (lower so overlapping zones are visible).
ZONE_TYPE_OPACITIES: dict[str, float] = {
    "lava": 0.4,
    "action_mask": 0.25,
}

#: Checkpoint names known to the default milestone set — used to populate
#: the frontend dropdowns.  The actual list at runtime comes from the env's
#: checkpoint tracker but this provides a sane default.
KNOWN_CHECKPOINTS = [
    "Got Pokedex",
    "Party Has Starter",
    "Fought Rival",
    "Won Rival Battle",
    "Got Oak's Parcel",
    "ITEM: Oak Parcel",
    "Oak's Lab to give back parcel",
    "Oak Got Parcel",
]


def _default_color(zone_type: str) -> str:
    return ZONE_TYPE_COLORS.get(zone_type, "#ff6b6b")


def _default_opacity(zone_type: str) -> float:
    return ZONE_TYPE_OPACITIES.get(zone_type, 0.5)


class ZoneManager:
    """Manages lava and action-masking zones.

    Can be used by both the web dashboard (for editing / serving zones) and
    the env wrapper (for checking positions and applying masking).
    """

    def __init__(self, zones_path: str | Path | None = None) -> None:
        self.zones_path = Path(zones_path) if zones_path else ZONES_JSON_PATH
        self.zones: list[dict[str, Any]] = self._load_zones()
        self.steps_in_action_mask_zone: int = 0
        self._masked_actions: list[str] = []
        self._last_file_mtime: float | None = None
        self._zone_step_counts: dict[str, int] = {}

    # ------------------------------------------------------------------ #
    # Loading / saving
    # ------------------------------------------------------------------ #

    def _load_zones(self) -> list[dict[str, Any]]:
        """Load zones from ``zones.json``, falling back to legacy ``lava.json``."""
        # New format
        with suppress(Exception):
            if self.zones_path.exists():
                with open(self.zones_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                zones = data.get("zones", [])
                if zones:
                    return self._normalize_zones(zones)

        # Legacy lava.json format
        with suppress(Exception):
            if LAVA_JSON_PATH.exists():
                with open(LAVA_JSON_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cells = [(int(z[0]), int(z[1])) for z in data.get("lava_zones", [])]
                if cells:
                    return [self._create_zone("lava", cells, label="Lava Zone")]

        return []

    def _normalize_zones(self, zones: list[dict]) -> list[dict[str, Any]]:
        """Ensure every zone dict has all required keys with sane defaults."""
        normalized: list[dict[str, Any]] = []
        for zone in zones:
            zone_type = zone.get("type", "lava")
            normalized.append(
                {
                    "id": zone.get("id") or f"zone_{len(normalized)}",
                    "type": zone_type,
                    "cells": [[int(c[0]), int(c[1])] for c in zone.get("cells", [])],
                    "label": zone.get("label") or zone_type.capitalize(),
                    "color": zone.get("color") or _default_color(zone_type),
                    "opacity": zone.get("opacity", _default_opacity(zone_type)),
                    "action": zone.get("action"),
                    "activate_on": zone.get("activate_on"),
                    "deactivate_on": zone.get("deactivate_on"),
                    "mask_rules": zone.get("mask_rules", []),
                }
            )
        return normalized

    @staticmethod
    def _create_zone(
        zone_type: str, cells: list, label: str | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        """Build a fresh zone dict with defaults applied."""
        return {
            "id": f"zone_{uuid.uuid4().hex[:8]}",
            "type": zone_type,
            "cells": [[int(c[0]), int(c[1])] for c in cells],
            "label": label or zone_type.capitalize(),
            "color": kwargs.get("color") or _default_color(zone_type),
            "opacity": kwargs.get("opacity", _default_opacity(zone_type)),
            "action": kwargs.get("action"),
            "activate_on": kwargs.get("activate_on"),
            "deactivate_on": kwargs.get("deactivate_on"),
            "mask_rules": kwargs.get("mask_rules", []),
        }

    def _save_zones(self) -> None:
        """Persist zones to ``zones.json``."""
        try:
            self.zones_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.zones_path, "w", encoding="utf-8") as f:
                json.dump({"zones": self.zones}, f, indent=2)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #

    def get_zone(self, zone_id: str) -> dict[str, Any] | None:
        for z in self.zones:
            if z["id"] == zone_id:
                return z
        return None

    def list_zones(self) -> list[dict[str, Any]]:
        return list(self.zones)

    def create_zone(
        self, zone_type: str = "lava", label: str | None = None, **kwargs: Any
    ) -> str:
        """Create a new empty zone and return its id."""
        zone = self._create_zone(zone_type, cells=[], label=label, **kwargs)
        self.zones.append(zone)
        self._save_zones()
        return zone["id"]

    def delete_zone(self, zone_id: str) -> bool:
        before = len(self.zones)
        self.zones = [z for z in self.zones if z["id"] != zone_id]
        if len(self.zones) != before:
            self._save_zones()
            return True
        return False

    def update_zone_config(self, zone_id: str, **kwargs: Any) -> bool:
        zone = self.get_zone(zone_id)
        if zone is None:
            return False
        for key, value in kwargs.items():
            if value is not None:
                zone[key] = value
        self._save_zones()
        return True

    def batch_toggle_cells(self, cells: list[list[int]], zone_id: str) -> bool:
        """Toggle all *cells* in *zone_id* at once (add/remove), saving once.

        This replaces the old per-cell ``toggle_lava_zone`` which wrote to disk
        on every single cell — the cause of the "cells update one by one" issue.
        """
        zone = self.get_zone(zone_id)
        if zone is None:
            return False
        cell_set: set[tuple[int, int]] = {
            (int(c[0]), int(c[1])) for c in zone["cells"]
        }
        for cell in cells:
            key = (int(cell[0]), int(cell[1]))
            if key in cell_set:
                cell_set.discard(key)
            else:
                cell_set.add(key)
        zone["cells"] = [[x, y] for x, y in sorted(cell_set)]
        self._save_zones()
        return True

    def set_zone_cells(self, cells: list[list[int]], zone_id: str) -> bool:
        """Replace the cell list of *zone_id* entirely."""
        zone = self.get_zone(zone_id)
        if zone is None:
            return False
        zone["cells"] = [[int(c[0]), int(c[1])] for c in cells]
        self._save_zones()
        return True

    # ------------------------------------------------------------------ #
    # Position / activation queries
    # ------------------------------------------------------------------ #

    @staticmethod
    def _position_in_cells(px: int, py: int, cells: list[list[int]]) -> bool:
        """Return True when *(px, py)* is within 8 px of any cell."""
        for cell in cells:
            if abs(px - cell[0]) < 8 and abs(py - cell[1]) < 8:
                return True
        return False

    @staticmethod
    def _is_zone_active(
        zone: dict[str, Any], achieved_checkpoints: set[str]
    ) -> bool:
        """Decide whether *zone* is currently active.

        Zones with ``mask_rules`` are always considered active — individual
        rules carry their own ``activate_on`` checkpoint and are evaluated
        in :meth:`get_masked_actions`.  Zones without ``mask_rules`` use
        the legacy single ``activate_on`` / ``deactivate_on`` fields.
        """
        if zone.get("mask_rules"):
            return True
        activate_on = zone.get("activate_on")
        deactivate_on = zone.get("deactivate_on")
        if activate_on is not None and activate_on not in achieved_checkpoints:
            return False
        if deactivate_on is not None and deactivate_on in achieved_checkpoints:
            return False
        return True

    def get_active_zones(self, achieved_checkpoints: set[str] | None = None) -> list[dict[str, Any]]:
        """Return zones whose milestone gates (if any) are currently satisfied."""
        if achieved_checkpoints is None:
            achieved_checkpoints = set()
        return [z for z in self.zones if self._is_zone_active(z, achieved_checkpoints)]

    def get_masked_actions(
        self,
        px: int,
        py: int,
        achieved_checkpoints: set[str] | None = None,
    ) -> list[str]:
        """Return action names masked at *(px, py)* by active action_mask zones.

        Supports two zone configurations:

        * **mask_rules** (preferred) — a list of ``{"action": "Down",
          "activate_on": "Fought Rival"}`` rules.  Each rule independently
          checks its ``activate_on`` checkpoint, so a single zone can mask
          different actions at different milestones.  A rule is also gated by
          its ``deactivate_on`` checkpoint — once that milestone is achieved
          the rule no longer masks its action.
        * **action + activate_on** (legacy) — a single action string and a
          single activation checkpoint on the zone itself.
        """
        if achieved_checkpoints is None:
            achieved_checkpoints = set()
        masked: list[str] = []
        for zone in self.get_active_zones(achieved_checkpoints):
            if zone["type"] != "action_mask":
                continue
            if not self._position_in_cells(px, py, zone["cells"]):
                continue
            mask_rules = zone.get("mask_rules")
            if mask_rules:
                for rule in mask_rules:
                    action = rule.get("action")
                    if not action:
                        continue
                    activate_on = rule.get("activate_on")
                    if activate_on is not None and activate_on not in achieved_checkpoints:
                        continue
                    deactivate_on = rule.get("deactivate_on")
                    if deactivate_on is not None and deactivate_on in achieved_checkpoints:
                        continue
                    if action not in masked:
                        masked.append(action)
            elif zone.get("action"):
                masked.append(zone["action"])
        return masked

    @property
    def in_action_mask_zone(self) -> bool:
        """True when the agent was last seen inside an active action_mask zone."""
        return bool(self._masked_actions)

    def tick(
        self,
        px: int,
        py: int,
        achieved_checkpoints: set[str] | None = None,
        in_battle: bool = False,
    ) -> list[str]:
        """Called once per env step.

        Returns the list of masked action names (empty list if not in a zone).
        When non-empty, ``steps_in_action_mask_zone`` is incremented.

        When ``in_battle`` is *False*, per-zone step counts are accumulated
        so the inspector can display how much time the agent spent in each
        zone outside of combat.
        """
        masked = self.get_masked_actions(px, py, achieved_checkpoints)
        self._masked_actions = masked
        if masked:
            self.steps_in_action_mask_zone += 1
        if not in_battle:
            for zone in self.zones:
                if zone.get("cells") and self._position_in_cells(px, py, zone["cells"]):
                    zone_id = zone.get("id", "unknown")
                    self._zone_step_counts[zone_id] = self._zone_step_counts.get(zone_id, 0) + 1
        return masked

    # ------------------------------------------------------------------ #
    # Serialisation / stats
    # ------------------------------------------------------------------ #

    def get_state(self) -> dict[str, Any]:
        """Return a JSON-safe dict for the web dashboard ``/api/state``."""
        return {
            "zones": [dict(z) for z in self.zones],
        }

    def get_stats(self) -> dict[str, Any]:
        """Return stats for the inspector."""
        return {
            "steps_in_action_mask_zone": self.steps_in_action_mask_zone,
            "zone_count": len(self.zones),
            "zone_types": [z["type"] for z in self.zones],
            "zone_step_counts": dict(self._zone_step_counts),
        }

    def reset_stats(self) -> None:
        self.steps_in_action_mask_zone = 0
        self._zone_step_counts.clear()

    def reload(self) -> bool:
        """Reload zones from disk (picks up edits made via the web UI).

        Returns True if zones were reloaded (file changed or was missing).
        """
        try:
            mtime = self.zones_path.stat().st_mtime
        except OSError:
            mtime = None
        if mtime is None or mtime != self._last_file_mtime:
            try:
                self.zones = self._load_zones()
            except Exception:
                pass
            self._last_file_mtime = mtime
            return True
        return False
