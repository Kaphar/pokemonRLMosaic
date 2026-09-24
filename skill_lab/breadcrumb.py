"""Breadcrumb navigation reward system."""
from __future__ import annotations

import math
from typing import Any

try:
    from v2.map_projection import project_position
    _HAS_PROJECTION = True
except ImportError:
    _HAS_PROJECTION = False
    project_position = None


class BreadcrumbTracker:
    """Track navigation progress toward a sequence of waypoint destinations.

    Awards a small proximity reward every time the agent gets strictly closer
    to its current destination (one reward per improvement, no diminishing
    return), and a larger ``breadcrumb_arrival`` reward when within
    :attr:`ARRIVAL_THRESHOLD` tiles.

    The tracker projects local game coordinates to global map coordinates
    (via ``v2.map_projection.project_position``) so that waypoints defined in
    stage JSON are compared consistently.
    """

    ARRIVAL_THRESHOLD = 3  # tiles

    def __init__(
        self,
        waypoints: list[dict[str, Any]] | None = None,
        effective_rewards: dict[str, float] | None = None,
    ) -> None:
        self.waypoints: list[dict[str, Any]] = list(waypoints or [])
        self.effective_rewards = effective_rewards or {}
        self._closest_reached: float | None = None
        self._current_waypoint_idx = 0
        self.total_reward: float = 0.0

    @classmethod
    def from_stage_config(
        cls,
        stage_config: dict[str, Any] | None,
        effective_rewards: dict[str, float] | None = None,
    ) -> "BreadcrumbTracker | None":
        """Build a tracker from a stage config's ``breadcrumbs`` array.
        Returns None if no breadcrumbs are defined."""
        stage_config = stage_config or {}
        breadcrumbs = stage_config.get("breadcrumbs", [])
        if not breadcrumbs:
            return None
        return cls(waypoints=breadcrumbs, effective_rewards=effective_rewards)

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

    def reset(self) -> None:
        """Reset tracker state for a new episode."""
        self._closest_reached = None
        self._current_waypoint_idx = 0
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
                print(f"[BreadcrumbTracker]   [{i+1}/{len(self.waypoints)}] "
                      f"{wp.get('label', f'wp_{i}')}  "
                      f"map={wp.get('target_map', '?')}  "
                      f"x={wp.get('target_x', '?')}  y={wp.get('target_y', '?')}",
                      flush=True)

    def update(self, x: int, y: int, map_id: int, env_label: str = "") -> float:
        """Process a new position and return any reward earned.

        Awards a small proximity reward **every time** the agent's distance
        to the current waypoint drops to a new integer-floor level (i.e. a
        decrease of at least one full tile in projected space), so that
        sub-tile jitter does not trigger repeated rewards.  A larger
        ``breadcrumb_arrival`` reward is given when within
        :attr:`ARRIVAL_THRESHOLD` tiles.
        """
        if not self.waypoints:
            return 0.0

        reward = 0.0

        # Clamp to valid waypoint range
        if self._current_waypoint_idx >= len(self.waypoints):
            return 0.0

        wp = self.waypoints[self._current_waypoint_idx]

        distance = self._distance(x, y, map_id, wp)
        label = env_label or ""
        base_reward = self.effective_rewards.get("breadcrumb", 0.5)

        # Check arrival
        if distance <= self.ARRIVAL_THRESHOLD:
            arrival_reward = self.effective_rewards.get("breadcrumb_arrival", 10.0)
            reward += arrival_reward
            self.total_reward += arrival_reward
            wp_label = wp.get("label", f"Waypoint {self._current_waypoint_idx + 1}")
            print(f"{label} >> Arrived at: {wp_label} (+{arrival_reward:.2f})", flush=True)
            self._current_waypoint_idx += 1
            self._closest_reached = None
            return reward

        # Proximity: fixed reward only when the integer-floor of the
        # distance strictly decreases — avoids rewarding sub-tile jitter
        # at the same or similar distance level.
        level = math.floor(distance)
        if self._closest_reached is None:
            self._closest_reached = level
        elif level < self._closest_reached:
            proximity_reward = base_reward
            reward += proximity_reward
            self.total_reward += proximity_reward
            self._closest_reached = level
            wp_label = wp.get("label", f"Waypoint {self._current_waypoint_idx + 1}")
            print(f"{label} >> Closer to '{wp_label}': dist={distance:.1f} "
                  f"(+{proximity_reward:.2f})", flush=True)

        return reward

    def get_progress(self) -> dict[str, Any]:
        """Return a serializable progress summary."""
        return {
            "total_waypoints": len(self.waypoints),
            "current_target_index": self._current_waypoint_idx,
            "closest_reached": self._closest_reached,
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

    Each call to :meth:`update` that shows the player has gotten **strictly
    closer** to the nearest center (in Manhattan projected distance) awards a
    small fixed ``health_proximity`` reward scaled by urgency
    (``1 - hp_fraction``).  There is no diminishing-return decay — once the
    closest distance is updated, a further improvement of even 1 pixel
    triggers another reward so the agent sees every step of progress.
    """

    ARRIVAL_THRESHOLD = 8
    """Pixel distance (in projected space) within which the agent is
    considered to have reached the Pokemon Center."""

    HEALTH_THRESHOLD = 0.5
    """HP fraction below which health-proximity rewards are enabled."""

    POKEMON_CENTERS: list[dict[str, Any]] = [
        {"map_id": 41, "x": 4, "y": 2, "label": "Viridian City"},
        {"map_id": 58, "x": 4, "y": 2, "label": "Pewter City"},
        {"map_id": 68, "x": 4, "y": 2, "label": "Route 4"},
    ]

    def __init__(
        self,
        effective_rewards: dict[str, float] | None = None,
    ) -> None:
        self.effective_rewards = effective_rewards or {}
        self._closest_reached: float | None = None
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
        and only fire on actual movement toward the target (not merely on
        an HP drop).

        Proximity rewards fire **every time** the player's Manhattan distance
        to the nearest Pokemon Center strictly decreases — one reward per
        improvement, no diminishing return.  The reward is a small fixed
        amount scaled by health urgency (``1 - hp_fraction``) so that lower
        HP makes each improvement worth more.
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
            self._last_position = None
            return reward, death_penalty

        center_idx, distance = self._nearest_center(px, py)

        # Track position to avoid rewarding HP-only changes.
        current_pos = (px, py, map_id)
        if self._last_position is not None and self._last_position == current_pos:
            return reward, death_penalty
        self._last_position = current_pos

        if center_idx != self._current_center_idx:
            self._closest_reached = None
            self._current_center_idx = center_idx

        # When the tracker first becomes active (HP just dropped below
        # threshold) or switches to a new nearest center, seed
        # _closest_reached without rewarding — the agent hasn't moved yet.
        if self._closest_reached is None:
            self._closest_reached = math.floor(distance)
            return reward, death_penalty

        center = self.POKEMON_CENTERS[center_idx]
        urgency = 1.0 - hp_fraction  # 0 at HEALTH_THRESHOLD, approaching 1 at 0 HP

        # Arrival reward (scaled by urgency)
        if distance <= self.ARRIVAL_THRESHOLD:
            arrival_reward = self.effective_rewards.get("health_arrival", 15.0) * urgency
            reward += arrival_reward
            self.total_reward += arrival_reward
            pc_label = center["label"]
            print(f"{label} [PC] Arrived at Pokemon Center ({pc_label}) "
                  f"HP={hp_fraction:.0%} urgency x{urgency:.2f} (+{arrival_reward:.2f})",
                  flush=True)
            self._closest_reached = None
            return reward, death_penalty

        # Proximity: fixed reward only when the integer-floor of the
        # distance strictly decreases — avoids rewarding sub-tile jitter
        # at the same or similar distance level.
        level = math.floor(distance)
        if level < self._closest_reached:
            base = self.effective_rewards.get("health_proximity", 0.5)
            proximity_reward = base * urgency
            reward += proximity_reward
            self.total_reward += proximity_reward
            self._closest_reached = level
            pc_label = center["label"]
            print(f"{label} [PC] Closer to {pc_label}: dist={distance:.0f} "
                  f"HP={hp_fraction:.0%} urgency x{urgency:.2f} "
                  f"(+{proximity_reward:.2f})", flush=True)

        return reward, death_penalty

    def get_progress(self) -> dict[str, Any]:
        return {
            "total_reward": self.total_reward,
            "death_count": self._death_count,
            "health_enabled": self._health_enabled,
            "closest_reached": self._closest_reached,
            "current_center": self.POKEMON_CENTERS[self._current_center_idx]["label"]
            if self._current_center_idx is not None
            and self._current_center_idx < len(self.POKEMON_CENTERS)
            else None,
        }