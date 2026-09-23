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

    Awards a small one-time ``breadcrumb`` reward each time the agent gets
    measurably closer to its current destination, and a larger
    ``breadcrumb_arrival`` reward when within the arrival threshold.

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
        self._best_distance: float | None = None
        self._rewarded_improvements: set[int] = set()
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
        self._best_distance = None
        self._rewarded_improvements.clear()
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

    def update(self, x: int, y: int, map_id: int, env_label: str = "") -> float:
        """Process a new position and return any reward earned.

        Parameters
        ----------
        x, y, map_id
            Current player position (local tile coordinates + map id).
        env_label
            Optional colored label for terminal logging.
        """
        if not self.waypoints:
            return 0.0

        reward = 0.0

        # Clamp to valid waypoint range
        if self._current_waypoint_idx >= len(self.waypoints):
            return 0.0

        wp = self.waypoints[self._current_waypoint_idx]

        # If the waypoint specifies a target_map and we're on a totally
        # different map family, advance to the next waypoint.
        target_map = int(wp.get("target_map", -1))
        if target_map >= 0 and map_id != target_map and self._current_waypoint_idx == 0:
            # Still try to navigate; don't skip unless we're way off
            pass

        distance = self._distance(x, y, map_id, wp)
        label = env_label or ""

        # Check arrival
        if distance <= self.ARRIVAL_THRESHOLD:
            arrival_reward = self.effective_rewards.get("breadcrumb_arrival", 10.0)
            reward += arrival_reward
            self.total_reward += arrival_reward
            wp_label = wp.get("label", f"Waypoint {self._current_waypoint_idx + 1}")
            print(f"{label} 🏁 Arrived at breadcrumb: {wp_label} (+{arrival_reward:.2f})")
            self._current_waypoint_idx += 1
            self._best_distance = None  # Reset for next waypoint
            return reward

        # Check improvement toward current target
        if self._best_distance is None or distance < self._best_distance:
            improvement_key = self._current_waypoint_idx
            if improvement_key not in self._rewarded_improvements:
                breadcrumb_reward = self.effective_rewards.get("breadcrumb", 0.5)
                reward += breadcrumb_reward
                self.total_reward += breadcrumb_reward
                self._rewarded_improvements.add(improvement_key)
                wp_label = wp.get("label", f"Waypoint {self._current_waypoint_idx + 1}")
                print(f"{label} 🔍 Closer to '{wp_label}': dist={distance:.1f} (+{breadcrumb_reward:.2f})")
            self._best_distance = distance

        return reward

    def get_progress(self) -> dict[str, Any]:
        """Return a serializable progress summary."""
        return {
            "total_waypoints": len(self.waypoints),
            "current_target_index": self._current_waypoint_idx,
            "total_reward": self.total_reward,
            "waypoint_labels": [wp.get("label", f"wp_{i}") for i, wp in enumerate(self.waypoints)],
        }