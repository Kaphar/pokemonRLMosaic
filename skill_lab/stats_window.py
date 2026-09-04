"""Real-time stats window for all environments."""

from __future__ import annotations

import cv2
import numpy as np


class StatsWindow:
    def __init__(self, title: str = "Environment Stats") -> None:
        self.title = title
        self.visible = False
        self._window_created = False
        self._needs_initial_render = False
        self.row_height = 22
        self.header_height = 28
        self.col_widths = [60, 70, 60, 90, 70, 80, 80, 80, 70, 70, 80]
        self.col_labels = [
            "Env", "HP", "Pkmn", "Trainer W", "Wild W", "Walls", "Steps", "Mins", "Steps/m", "Map", "Score"
        ]

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

    def render(self, env, num_envs: int, action_freq: int = 24, scores: np.ndarray | None = None) -> bool:
        if not self.visible:
            self._needs_initial_render = False
            return True
        if not self._needs_initial_render and cv2.getWindowProperty(self.title, cv2.WND_PROP_VISIBLE) < 1:
            self.visible = False
            self._needs_initial_render = False
            return False

        header = self._render_header()
        rows = [header]
        for idx in range(num_envs):
            score = float(scores[idx]) if scores is not None and idx < len(scores) else 0.0
            row = self._render_env_row(env, idx, action_freq, score=score)
            rows.append(row)

        max_width = sum(self.col_widths) + 10
        total_height = self.header_height + num_envs * self.row_height + 10
        image = np.full((total_height, max_width, 3), 30, dtype=np.uint8)
        y_offset = 5
        for row in rows:
            image[y_offset:y_offset + row.shape[0], 5:5 + row.shape[1]] = row
            if row is header:
                y_offset += self.header_height
            else:
                y_offset += self.row_height

        cv2.imshow(self.title, image)
        cv2.setWindowProperty(self.title, cv2.WND_PROP_TOPMOST, 1)
        self._needs_initial_render = False
        return True

    def _render_header(self) -> np.ndarray:
        width = sum(self.col_widths)
        header = np.full((self.header_height, width, 3), 50, dtype=np.uint8)
        x = 0
        for label, col_w in zip(self.col_labels, self.col_widths):
            text_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)[0]
            text_x = x + (col_w - text_size[0]) // 2
            text_y = (self.header_height + text_size[1]) // 2
            cv2.putText(header, label, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
            x += col_w
        cv2.line(header, (0, self.header_height - 1), (width, self.header_height - 1), (100, 100, 100), 1)
        return header

    def _render_env_row(self, env, env_index: int, action_freq: int, score: float = 0.0) -> np.ndarray:
        width = sum(self.col_widths)
        row = np.full((self.row_height, width, 3), 30, dtype=np.uint8)

        try:
            hp = float(env.get_attr("read_hp_fraction")[env_index]())
            pcount = int(env.get_attr("read_m")[env_index](0xD163))
            trainer_wins = int(env.get_attr("trainer_wins")[env_index])
            wild_wins = int(env.get_attr("wild_wins")[env_index])
            wall_collisions = int(env.get_attr("wall_collisions")[env_index])
            steps = int(env.get_attr("step_count")[env_index])
            map_id = int(env.get_attr("current_map_id")[env_index])

            emulator_frames = steps * action_freq
            game_seconds = emulator_frames / 60.0
            game_minutes = game_seconds / 60.0
            steps_per_min = steps / max(game_minutes, 0.001)
        except Exception:
            hp = 0.0
            pcount = 0
            trainer_wins = 0
            wild_wins = 0
            wall_collisions = 0
            steps = 0
            game_minutes = 0.0
            steps_per_min = 0.0
            map_id = 0

        values = [
            str(env_index + 1),
            f"{hp:.0%}",
            str(pcount),
            str(trainer_wins),
            str(wild_wins),
            str(wall_collisions),
            str(steps),
            f"{game_minutes:.1f}",
            f"{steps_per_min:.0f}",
            f"{map_id:02X}",
            f"{score:+.1f}",
        ]

        x = 0
        for label, col_w in zip(values, self.col_widths):
            color = (220, 220, 220)
            if label == f"{hp:.0%}":
                if hp > 0.5:
                    color = (0, 255, 0)
                elif hp > 0.2:
                    color = (0, 255, 255)
                else:
                    color = (0, 0, 255)
            text_size = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)[0]
            text_x = x + (col_w - text_size[0]) // 2
            text_y = (self.row_height + text_size[1]) // 2
            cv2.putText(row, label, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
            x += col_w

        cv2.line(row, (0, self.row_height - 1), (width, self.row_height - 1), (60, 60, 60), 1)
        return row

    def close(self) -> None:
        self.visible = False
        self._window_created = False
        self._needs_initial_render = False
        try:
            cv2.destroyWindow(self.title)
        except cv2.error:
            pass
