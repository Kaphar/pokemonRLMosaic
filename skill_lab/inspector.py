"""Observation inspector for the skill lab."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np


class ObservationInspector:
    def __init__(self, title: str = "Observation Inspector") -> None:
        self.title = title
        self.visible = False
        self._window_created = False
        self._needs_initial_render = False

    def show(self) -> None:
        if self.visible and self._window_created:
            return
        self.visible = True
        if not self._window_created:
            cv2.namedWindow(self.title)
            self._window_created = True
        self._needs_initial_render = True

    def hide(self) -> None:
        self.visible = False
        self._needs_initial_render = False

    def render(self, env, env_index: int, reward_history: list[float] | None = None) -> bool:
        if not self.visible:
            self._needs_initial_render = False
            return True
        if not self._needs_initial_render and cv2.getWindowProperty(self.title, cv2.WND_PROP_VISIBLE) < 1:
            self.visible = False
            self._needs_initial_render = False
            return False

        screen = env.envs[env_index].pyboy.screen.ndarray
        if screen is None:
            screen = np.zeros((144, 160, 3), dtype=np.uint8)
        if screen.shape[-1] == 4:
            screen = screen[:, :, :3]
        screen = cv2.resize(screen, (320, 288), interpolation=cv2.INTER_NEAREST)

        hp = float(env.envs[env_index].read_hp_fraction())
        level_sum = int(env.envs[env_index].current_level_sum)
        map_id = int(env.envs[env_index].current_map_id)
        badges = int(env.envs[env_index].read_m(0xD356))
        events = int(np.sum(env.envs[env_index].read_event_bits()))
        steps = int(env.envs[env_index].step_count)
        trainer_wins = int(env.envs[env_index].trainer_wins)
        wild_wins = int(env.envs[env_index].wild_wins)
        recent_actions = env.envs[env_index].recent_actions

        left_panel_w = 280
        right_panel_w = 240
        panel_h = 288
        panel = np.full((panel_h, left_panel_w + right_panel_w, 3), 30, dtype=np.uint8)

        y = 25
        cv2.putText(panel, f"Env {env_index + 1}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        y += 30
        hp_color = (0, 255, 0) if hp > 0.5 else ((0, 255, 255) if hp > 0.2 else (0, 0, 255))
        cv2.putText(panel, f"HP: {hp:.0%}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, hp_color, 1)
        y += 24
        cv2.putText(panel, f"Level sum: {level_sum}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)
        y += 20
        cv2.putText(panel, f"Map ID: {map_id:02X}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)
        y += 20
        cv2.putText(panel, f"Badges: {badges}/8", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)
        y += 20
        cv2.putText(panel, f"Events: {events}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)
        y += 20
        cv2.putText(panel, f"Steps: {steps}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)
        y += 20
        cv2.putText(panel, f"Trainer W: {trainer_wins}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)
        y += 20
        cv2.putText(panel, f"Wild W: {wild_wins}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)
        cv2.putText(panel, f"Walls: {env.envs[env_index].wall_collisions}", (15, y + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)

        rx = left_panel_w + 15
        ry = 55
        cv2.putText(panel, "Recent actions", (rx, ry), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        ry += 20
        action_names = ["Down", "Left", "Right", "Up", "A", "B", "Start"]
        for action in recent_actions:
            name = action_names[action] if action < len(action_names) else f"#{action}"
            cv2.putText(panel, f"  {name}", (rx, ry), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
            ry += 16
            if ry > panel_h - 20:
                break

        ry = panel_h // 2 + 10
        cv2.putText(panel, "Reward history", (rx, ry), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        ry += 20
        if reward_history is not None and reward_history:
            history = np.array(reward_history[-50:], dtype=np.float32)
            if history.size > 1:
                hmin, hmax = history.min(), history.max()
                if hmax > hmin:
                    normalized = (history - hmin) / (hmax - hmin)
                else:
                    normalized = np.zeros_like(history)
                rx_start = rx
                rx_end = rx + right_panel_w - 15
                plot_w = rx_end - rx_start
                plot_h = 38
                points = [
                    (rx_start + int(i * plot_w / max(len(normalized) - 1, 1)),
                     int((1.0 - v) * plot_h))
                    for i, v in enumerate(normalized)
                ]
                for i in range(len(points) - 1):
                    cv2.line(panel, (points[i][0], ry + points[i][1]),
                             (points[i + 1][0], ry + points[i + 1][1]), (0, 255, 0), 1)
            else:
                cv2.putText(panel, f"  {history[-1]:+.2f}", (rx, ry + 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
        else:
            cv2.putText(panel, "  no data", (rx, ry + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (150, 150, 150), 1)

        inspector = np.hstack([screen, panel])
        cv2.imshow(self.title, inspector)
        cv2.setWindowProperty(self.title, cv2.WND_PROP_TOPMOST, 1)
        self._needs_initial_render = False
        return True

    def close(self) -> None:
        self.visible = False
        self._window_created = False
        self._needs_initial_render = False
        try:
            cv2.destroyWindow(self.title)
        except cv2.error:
            pass
