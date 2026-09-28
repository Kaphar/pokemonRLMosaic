"""Breadcrumb navigation reward system."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from v2.map_projection import project_position
    _HAS_PROJECTION = True
except ImportError:
    _HAS_PROJECTION = False
    project_position = None


class BreadcrumbTracker:
    """Track navigation progress toward a sequence of waypoint destinations.

    Awards a **proportional** proximity reward every step the agent closes
    the tile-distance gap to its current destination (``base * delta_tiles``),
    so that the reward scales with how many tiles were traversed toward the
    target.  A larger ``breadcrumb_arrival`` reward fires when within
    :attr:`ARRIVAL_THRESHOLD` tiles.

    The tracker projects local game coordinates to global map coordinates
    (via ``v2.map_projection.project_position``) so that waypoints defined in
    stage JSON are compared consistently in a shared pixel/tile space.

    Breadcrumbs may declare ``activate_on`` and/or ``deactivate_on`` fields whose
    values are the **names** of milestones.  A waypoint only awards rewards
    after its ``activate_on`` milestone has been achieved, and stops rewarding
    (if ``deactivate_on`` is set) once that milestone is achieved too.  This
    lets the breadcrumb navigation path shift as story progression unfolds.

    Waypoints without ``activate_on``/``deactivate_on`` are always active (unless
    a deactivation milestone has been reached).
    """

    ARRIVAL_THRESHOLD = 3  # tiles

    PIXELS_PER_TILE = 16
    """Conversion factor from projected pixel distance to tile distance."""

    DEFAULT_BREADCRUMBS_PATH = (
        Path(__file__).resolve().parent / "stages" / "default_breadcrumbs.json"
    )

    def __init__(
        self,
        waypoints: list[dict[str, Any]] | None = None,
        effective_rewards: dict[str, float] | None = None,
        reward_logger=None,
    ) -> None:
        self.waypoints: list[dict[str, Any]] = list(waypoints or [])
        self.effective_rewards = effective_rewards or {}
        self._reward_logger = reward_logger
        self._closest_reached: float | None = None
        self._prev_distance: float | None = None
        self._current_waypoint_idx = 0
        self.total_reward: float = 0.0

    @classmethod
    def from_stage_config(
        cls,
        stage_config: dict[str, Any] | None,
        effective_rewards: dict[str, float] | None = None,
        reward_logger=None,
    ) -> "BreadcrumbTracker | None":
        """Build a tracker from a stage config's ``breadcrumbs`` array.

        Returns a tracker using the stage's breadcrumbs if defined.  If the
        stage provides no ``breadcrumbs`` array, falls back to
        ``stages/default_breadcrumbs.json`` so full-playthrough stages get
        sensible waypoint progression automatically.  Returns ``None`` only if
        neither source provides any breadcrumbs.
        """
        stage_config = stage_config or {}
        breadcrumbs = stage_config.get("breadcrumbs", [])

        if not breadcrumbs:
            default_path = cls.DEFAULT_BREADCRUMBS_PATH
            if default_path.exists():
                try:
                    with open(default_path, "r", encoding="utf-8") as f:
                        default_data = json.load(f)
                    breadcrumbs = default_data.get("breadcrumbs", [])
                    if breadcrumbs:
                        print(f"[BreadcrumbTracker] Loaded {len(breadcrumbs)} default breadcrumbs from {default_path.name}", flush=True)
                except Exception as e:
                    print(f"[BreadcrumbTracker] Failed to load default breadcrumbs: {e}", flush=True)

        if not breadcrumbs:
            return None
        return cls(waypoints=breadcrumbs, effective_rewards=effective_rewards, reward_logger=reward_logger)

    def _project(self, x: int, y: int, map_id: int) -> tuple[int, int]:
        """Project local game coords to global coords for distance comparison."""
        if _HAS_PROJECTION:
            result = project_position(x, y, map_id)
            return (result.pixel_x, result.pixel_y)
        return (x, y)

    def _distance(self, x: int, y: int, map_id: int, wp: dict[str, Any]) -> float:
        """Manhattan distance from player position to a waypoint."""
        gx, gy = self._project(x, y, map_id)
        wpx = int(wp.get("target_x", 0))
        wpy = int(wp.get("target_y", 0))
        wmap = int(wp.get("target_map", 0))
        if _HAS_PROJECTION:
            wg = self._project(wpx, wpy, wmap)
        else:
            wg = (wpx, wpy)
        return abs(gx - wg[0]) + abs(gy - wg[1])

    def _is_waypoint_active(self, wp: dict[str, Any], achieved: set[str] | None) -> bool:
        """Check if a waypoint is currently active based on milestone progress.

        A waypoint is active if:
        - ``activate_on`` is None (or the milestone is in ``achieved``), AND
        - ``deactivate_on`` is None (or the milestone is NOT in ``achieved``).
        """
        achieved = achieved or set()
        activate_on = wp.get("activate_on")
        if activate_on is not None and activate_on not in achieved:
            return False
        deactivate_on = wp.get("deactivate_on")
        if deactivate_on is not None and deactivate_on in achieved:
            return False
        return True

    def _next_active_waypoint(self, achieved: set[str] | None, start_idx: int | None = None) -> int | None:
        """Find the index of the next active waypoint at or after ``start_idx``.

        Skips over waypoints that are not yet active.  Returns None if no
        active waypoint remains.
        """
        achieved = achieved or set()
        idx = start_idx if start_idx is not None else 0
        while idx < len(self.waypoints):
            if self._is_waypoint_active(self.waypoints[idx], achieved):
                return idx
            idx += 1
        return None

    def reset(self, achieved: set[str] | None = None) -> None:
        """Reset tracker state for a new episode.

        Optionally accepts the current set of achieved milestone names so
        that the active waypointer starts at the correct position in the
        progression.
        """
        self._closest_reached = None
        self._prev_distance = None
        self._current_waypoint_idx = self._next_active_waypoint(achieved) or 0
        self.total_reward = 0.0

    def set_waypoints(self, waypoints: list[dict[str, Any]]) -> None:
        """Replace the current waypoint list and reset progress.

        Used when the milestone progression shifts the navigation goal
        (e.g. after obtaining Oak's Parcel the agent must return to
        Oak's Lab instead of continuing toward the original destination).
        """
        self.waypoints = list(waypoints or [])
        self.reset()
        if self.waypoints:
            wp_labels = [wp.get("label", f"wp{i+1}") for i, wp in enumerate(self.waypoints)]
            print(f"[BreadcrumbTracker] Waypoints set ({len(self.waypoints)}): "
                  f"{', '.join(wp_labels)}", flush=True)
            for i, wp in enumerate(self.waypoints):
                wp_label = wp.get('label', f'wp_{i}')
                activate = wp.get('activate_on', 'always')
                deactivate = wp.get('deactivate_on', 'never')
                print(f"[BreadcrumbTracker]   [{i+1}/{len(self.waypoints)}] "
                      f"{wp_label}  "
                      f"map={wp.get('target_map', '?')}  "
                      f"x={wp.get('target_x', '?')}  y={wp.get('target_y', '?')}  "
                      f"activate_on={activate}  deactivate_on={deactivate}",
                      flush=True)

    def _log_reward(self, reward_type: str, amount: float, description: str) -> None:
        """Log a breadcrumb reward event via the reward logger if available.

        Mirrors the logging pattern used by :class:`PokemonCenterTracker`
        in ``env_wrapper.py._log_reward``.
        """
        if self._reward_logger is not None:
            try:
                self._reward_logger(reward_type, amount, description)
            except Exception:
                pass

    def update(self, x: int, y: int, map_id: int, env_label: str = "",
               achieved: set[str] | None = None) -> float:
        """Process a new position and return any reward earned.

        Awards a **proportional** proximity reward every step that the agent
        closes the tile-distance gap to the current waypoint:
        ``reward = base * delta_tiles``.  This gives a continuous gradient
        signal — every step toward the target yields a commensurate reward.
        A larger ``breadcrumb_arrival`` reward is given when within
        :attr:`ARRIVAL_THRESHOLD` tiles.

        Breadcrumbs with ``activate_on``/``deactivate_on`` fields are only
        active when the corresponding milestones have/haven't been reached.
        The ``achieved`` set (from the milestone tracker) drives this logic.
        """
        if not self.waypoints:
            return 0.0

        # Skip to the next active waypoint if the current one is no longer active.
        if not self._is_waypoint_active(self.waypoints[self._current_waypoint_idx], achieved):
            next_idx = self._next_active_waypoint(achieved, start_idx=self._current_waypoint_idx)
            if next_idx is None:
                return 0.0
            self._current_waypoint_idx = next_idx
            self._prev_distance = None
            self._closest_reached = None
            wp = self.waypoints[self._current_waypoint_idx]
            wp_map = int(wp.get("target_map", 0))
            wp_x = int(wp.get("target_x", 0))
            wp_y = int(wp.get("target_y", 0))
            wp_label = wp.get("label", f"Waypoint {self._current_waypoint_idx + 1}")
            print(f"{env_label} >> Breadcrumb activated: {wp_label} "
                  f"(map=0x{wp_map:02X}/x={wp_x}/y={wp_y})", flush=True)

        reward = 0.0

        # Clamp to valid waypoint range
        if self._current_waypoint_idx >= len(self.waypoints):
            return 0.0

        wp = self.waypoints[self._current_waypoint_idx]

        # If the current waypoint became inactive mid-progress, advance
        if not self._is_waypoint_active(wp, achieved):
            next_idx = self._next_active_waypoint(achieved, start_idx=self._current_waypoint_idx + 1)
            if next_idx is None:
                return 0.0
            self._current_waypoint_idx = next_idx
            self._prev_distance = None
            self._closest_reached = None
            wp = self.waypoints[self._current_waypoint_idx]

        distance_px = self._distance(x, y, map_id, wp)
        distance_tiles = distance_px / self.PIXELS_PER_TILE
        label = env_label or ""
        base_reward = self.effective_rewards.get("breadcrumb", 0.5)

        wp_label = wp.get("label", f"Waypoint {self._current_waypoint_idx + 1}")
        wp_map = int(wp.get("target_map", 0))
        wp_x = int(wp.get("target_x", 0))
        wp_y = int(wp.get("target_y", 0))

        # Check arrival
        if distance_tiles <= self.ARRIVAL_THRESHOLD:
            arrival_reward = self.effective_rewards.get("breadcrumb_arrival", 10.0)
            reward += arrival_reward
            self.total_reward += arrival_reward
            print(f"{label} >> Arrived at: {wp_label} "
                  f"(wp=map:0x{wp_map:02X}/x={wp_x}/y={wp_y} "
                  f"player=map:0x{map_id:02X}/x={x}/y={y} "
                  f"dist={distance_tiles:.1f}t) (+{arrival_reward:.2f})",
                  flush=True)
            self._log_reward("breadcrumb_arrival", arrival_reward, f"Arrived at waypoint: {wp_label}")
            self._current_waypoint_idx += 1
            self._prev_distance = None
            self._closest_reached = None
            return reward

        # Proportional proximity: reward every step that reduces distance,
        # scaled by the number of tiles closed.
        if self._prev_distance is not None:
            delta = self._prev_distance - distance_tiles
            if delta > 0:
                proximity_reward = base_reward * delta
                reward += proximity_reward
                self.total_reward += proximity_reward
                self._closest_reached = distance_tiles
                print(f"{label} >> Closer to '{wp_label}': "
                      f"wp=map:0x{wp_map:02X}/x={wp_x}/y={wp_y} "
                      f"player=map:0x{map_id:02X}/x={x}/y={y} "
                      f"dist={distance_tiles:.1f}t (was {self._prev_distance:.1f}t) "
                      f"(+{proximity_reward:.2f})", flush=True)
                self._log_reward("breadcrumb", proximity_reward,
                                 f"Navigated toward waypoint: {wp_label}")

        self._prev_distance = distance_tiles
        return reward

    def get_progress(self, achieved: set[str] | None = None) -> dict[str, Any]:
        """Return a serializable progress summary."""
        achieved = achieved or set()
        return {
            "total_waypoints": len(self.waypoints),
            "active_waypoints": [
                i for i, wp in enumerate(self.waypoints)
                if self._is_waypoint_active(wp, achieved)
            ],
            "current_target_index": self._current_waypoint_idx,
            "closest_reached": self._closest_reached,
            "prev_distance": self._prev_distance,
            "total_reward": self.total_reward,
            "waypoint_labels": [wp.get("label", f"wp_{i}") for i, wp in enumerate(self.waypoints)],
        }


class PokemonCenterTracker:
    """Track navigation toward the nearest Pokemon Center, with rewards
    that scale with health urgency.

    Unlike the ordered :class:`BreadcrumbTracker`, this tracker dynamically
    selects the globally-nearest Pokemon Center from a registry and rewards
    the agent for making progress toward it.  The reward magnitude scales
    with health urgency: the lower the party's HP fraction, the higher the
    reward for closing distance.

    Proximity rewards are only active when ``hp_fraction`` falls below
    :attr:`HEALTH_THRESHOLD` (and the party is non-empty), so the tracker
    does not interfere with normal exploration when health is healthy.

    Rewards are **proportional** to the distance reduction in tile units
    (not a flat per-step amount), so every step toward the center generates
    a commensurate reward.  A larger ``health_arrival`` reward fires when
    the agent reaches the center.
    """

    ARRIVAL_THRESHOLD = 3
    """Distance in *tiles* (projected space) within which the agent is
    considered to have reached the Pokemon Center."""

    HEALTH_THRESHOLD = 0.7
    """HP fraction below which health-proximity rewards are enabled."""

    PIXELS_PER_TILE = 16
    """Conversion factor from projected pixel distance to tile distance."""

    POKEMON_CENTERS: list[dict[str, Any]] = [
        {"map_id": 41, "x": 23, "y": 26, "label": "Viridian City"},
        {"map_id": 58, "x": 4, "y": 2, "label": "Pewter City"},
        {"map_id": 68, "x": 4, "y": 2, "label": "Route 4"},
    ]
    # map=0x02 (Pewter City), x=13, y=26 # this is the location of the tile under the door of the pkmn center in pewter city.
    # careful : they are also in the starter.json.


    def __init__(
        self,
        effective_rewards: dict[str, float] | None = None,
    ) -> None:
        self.effective_rewards = effective_rewards or {}
        self._closest_reached: float | None = None
        self._prev_distance: float | None = None
        self._current_center_idx: int | None = None
        self._health_enabled: bool = False
        self._death_count: int = 0
        self._prior_all_fainted: bool = False
        self._last_position: tuple[int, int, int] | None = None
        self.total_reward: float = 0.0

    def _project(self, x: int, y: int, map_id: int) -> tuple[int, int]:
        if _HAS_PROJECTION:
            result = project_position(x, y, map_id)
            return (result.pixel_x, result.pixel_y)
        return (x, y)

    def _nearest_center(self, px: int, py: int) -> tuple[int, float]:
        best_dist: float = float("inf")
        best_idx: int = 0
        for i, center in enumerate(self.POKEMON_CENTERS):
            cx, cy = self._project(center["x"], center["y"], center["map_id"])
            dist = abs(px - cx) + abs(py - cy)
            if dist < best_dist:
                best_dist = dist
                best_idx = i
        return best_idx, best_dist

    def reset(self) -> None:
        self._closest_reached = None
        self._prev_distance = None
        self._current_center_idx = None
        self._health_enabled = False
        self._death_count = 0
        self._prior_all_fainted = False
        self._last_position = None
        self.total_reward = 0.0

    def update(
        self,
        x: int,
        y: int,
        map_id: int,
        hp_fraction: float,
        all_fainted: bool,
        in_battle: bool = False,
        env_label: str = "",
    ) -> tuple[float, float]:
        """Process position + health state.

        Returns ``(proximity_reward, death_penalty)``.
        ``death_penalty`` is non-zero only on the step where the blackout
        is first detected.  Proximity rewards are suppressed while in battle
        (the player cannot move toward a center and HP changes come from
        combat — the death penalty still fires).

        Proximity reward is **proportional** to the tile-distance reduction
        toward the nearest center: ``reward = k * delta_tiles * urgency``
        where ``urgency = 1 - hp_fraction``.  Every step that reduces
        distance yields a proportional reward, providing continuous gradient
        signal rather than a sparse binary improvement flag.
        """
        reward = 0.0
        death_penalty = 0.0
        label = env_label or ""

        # ---- Death / blackout penalty (fires regardless of battle) ----
        if all_fainted and not self._prior_all_fainted:
            self._death_count += 1
            death_penalty = self.effective_rewards.get("death_penalty", -5.0)
            self.total_reward += death_penalty
            print(f"{label} [DEATH] Blackout penalty: {death_penalty:.2f} "
                  f"(total deaths: {self._death_count})", flush=True)
        self._prior_all_fainted = all_fainted

        # Skip proximity navigation rewards while in battle — the player
        # can't move toward a center and HP changes come from combat.
        if in_battle:
            return reward, death_penalty

        px, py = self._project(x, y, map_id)

        # ---- Health-scaled proximity rewards ----
        self._health_enabled = (
            0.0 < hp_fraction < self.HEALTH_THRESHOLD
        )
        if not self._health_enabled:
            self._prev_distance: float | None = None
            return reward, death_penalty

        center_idx, distance_px = self._nearest_center(px, py)

        # Track position to avoid rewarding HP-only changes.
        current_pos = (px, py, map_id)
        if self._last_position is not None and self._last_position == current_pos:
            return reward, death_penalty
        self._last_position = current_pos

        if center_idx != self._current_center_idx:
            self._prev_distance = None
            self._closest_reached = None
            self._current_center_idx = center_idx

        center = self.POKEMON_CENTERS[center_idx]
        urgency = 1.0 - hp_fraction  # 0 at HEALTH_THRESHOLD, approaching 1 at 0 HP
        distance_tiles = distance_px / self.PIXELS_PER_TILE

        # Arrival reward (scaled by urgency)
        if distance_tiles <= self.ARRIVAL_THRESHOLD:
            arrival_reward = self.effective_rewards.get("health_arrival", 15.0) * urgency
            reward += arrival_reward
            self.total_reward += arrival_reward
            pc_label = center["label"]
            print(f"{label} [PC] Arrived at Pokemon Center ({pc_label}) "
                  f"map=0x{center['map_id']:02X} x={center['x']} y={center['y']} "
                  f"player_map=0x{map_id:02X} player_x={x} player_y={y} "
                  f"dist={distance_tiles:.1f}t HP={hp_fraction:.0%} "
                  f"urgency x{urgency:.2f} (+{arrival_reward:.2f})",
                  flush=True)
            self._prev_distance = None
            return reward, death_penalty

        # Proportional proximity reward:
        # Scale by tile-distance reduction * urgency so every step that
        # closes the gap yields a proportional reward.
        if self._prev_distance is not None:
            delta = self._prev_distance - distance_tiles
            if delta > 0:
                base = self.effective_rewards.get("health_proximity", 0.5)
                proximity_reward = base * delta * urgency
                reward += proximity_reward
                self.total_reward += proximity_reward
                self._closest_reached = distance_tiles
                pc_label = center["label"]
                print(f"{label} [PC] Closer to {pc_label} ({center['x']},{center['y']}): map=0x{map_id:02X} "
                      f"{x}/{y}"
                      f"dist={self._prev_distance:.1f}t > {distance_tiles:.1f}t"
                      f"HP={hp_fraction:.0%} urgency x{urgency:.2f} "
                      f"(+{proximity_reward:.2f})", flush=True)

        self._prev_distance = distance_tiles
        return reward, death_penalty

    def get_progress(self) -> dict[str, Any]:
        return {
            "total_reward": self.total_reward,
            "death_count": self._death_count,
            "health_enabled": self._health_enabled,
            "closest_reached": self._closest_reached,
            "prev_distance": self._prev_distance,
            "current_center": self.POKEMON_CENTERS[self._current_center_idx]["label"]
            if self._current_center_idx is not None
            and self._current_center_idx < len(self.POKEMON_CENTERS)
            else None,
        }