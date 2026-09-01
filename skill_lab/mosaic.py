"""Mosaic display for the skill lab."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from skill_lab.config import GRID_COLS, GRID_ROWS, PANEL_WIDTH, TILE_HEIGHT, TILE_WIDTH


class Mosaic:
    def __init__(self, num_tiles: int, title: str = "Pokemon Red V2 Mosaic", foreground: bool = False) -> None:
        self.num_tiles = num_tiles
        self.title = title
        self.foreground = foreground
        self.selected_index: int | None = None
        self.pending_human_action: int | None = None

        self.panel_x = GRID_COLS * TILE_WIDTH
        self.panel_y = 0
        self.panel_w = PANEL_WIDTH
        self.panel_h = GRID_ROWS * TILE_HEIGHT

        button_margin = 20
        button_w = self.panel_w - button_margin * 2
        button_h = 60
        button_gap = 20
        start_y = 80
        self.buttons = {
            "Control": {
                "rect": (button_margin, start_y, button_w, button_h),
                "color": (0, 180, 255),
                "hover": (0, 220, 255),
            },
            "Slash": {
                "rect": (button_margin, start_y + button_h + button_gap, button_w, button_h),
                "color": (0, 0, 180),
                "hover": (0, 0, 255),
            },
            "Praise": {
                "rect": (button_margin, start_y + (button_h + button_gap) * 2, button_w, button_h),
                "color": (0, 180, 0),
                "hover": (0, 255, 0),
            },
        }
        self.hovered_button: str | None = None
        self.last_action: str | None = None
        self.last_action_target: int | None = None

        cv2.namedWindow(self.title)
        cv2.setMouseCallback(self.title, self._on_mouse)

    def _button_at(self, x: int, y: int) -> str | None:
        for name, info in self.buttons.items():
            bx, by, bw, bh = info["rect"]
            if bx <= x < bx + bw and by <= y < by + bh:
                return name
        return None

    def _on_mouse(self, event: int, x: int, y: int, flags: int, param: Any) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            if x >= self.panel_x:
                button = self._button_at(x, y)
                if button == "Control":
                    if self.selected_index is not None:
                        self.last_action = "Control"
                        self.last_action_target = self.selected_index
                        self.pending_human_action = None
                elif button == "Slash":
                    if self.selected_index is not None:
                        self.last_action = "Slash"
                        self.last_action_target = self.selected_index
                elif button == "Praise":
                    if self.selected_index is not None:
                        self.last_action = "Praise"
                        self.last_action_target = self.selected_index
            else:
                column = x // TILE_WIDTH
                row = y // TILE_HEIGHT
                clicked = row * GRID_COLS + column
                if 0 <= clicked < self.num_tiles:
                    self.selected_index = None if self.selected_index == clicked else clicked
                    self.pending_human_action = None
        elif event == cv2.EVENT_MOUSEMOVE:
            if x >= self.panel_x:
                self.hovered_button = self._button_at(x, y)
            else:
                self.hovered_button = None

    def render(self, tiles: list[np.ndarray], reward_modifiers: list[float] | None = None) -> None:
        cols = min(GRID_COLS, len(tiles))
        rows = (len(tiles) + cols - 1) // cols
        rows_list = []
        for row in range(rows):
            start = row * cols
            end = min(start + cols, len(tiles))
            row_tiles = tiles[start:end]
            while len(row_tiles) < cols:
                row_tiles.append(np.zeros((TILE_HEIGHT, TILE_WIDTH, 3), dtype=np.uint8))
            rows_list.append(np.hstack(row_tiles))
        grid = np.vstack(rows_list)

        panel = np.full((self.panel_h, self.panel_w, 3), 40, dtype=np.uint8)
        cv2.rectangle(panel, (0, 0), (self.panel_w - 1, self.panel_h - 1), (80, 80, 80), thickness=2)

        cv2.putText(panel, "Supervisor", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        if self.selected_index is not None:
            cv2.putText(panel, f"Selected: {self.selected_index + 1}", (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 255), 1)
        else:
            cv2.putText(panel, "No selection", (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (150, 150, 150), 1)

        for name, info in self.buttons.items():
            bx, by, bw, bh = info["rect"]
            color = info["hover"] if self.hovered_button == name else info["color"]
            cv2.rectangle(panel, (bx, by), (bx + bw, by + bh), color, thickness=-1)
            cv2.rectangle(panel, (bx, by), (bx + bw, by + bh), (255, 255, 255), thickness=2)
            text_size = cv2.getTextSize(name, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
            text_x = bx + (bw - text_size[0]) // 2
            text_y = by + (bh + text_size[1]) // 2
            cv2.putText(panel, name, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

        if self.last_action is not None and self.last_action_target is not None:
            action_text = f"{self.last_action} #{self.last_action_target + 1}"
            cv2.putText(panel, action_text, (20, self.panel_h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)

        if reward_modifiers is not None and self.selected_index is not None:
            mod = reward_modifiers[self.selected_index]
            mod_text = f"Reward mod: {mod:+.1f}"
            cv2.putText(panel, mod_text, (20, self.panel_h - 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

        mosaic = np.hstack([grid, panel])
        cv2.imshow(self.title, mosaic)
        if self.foreground:
            cv2.setWindowProperty(self.title, cv2.WND_PROP_TOPMOST, 1)

    def poll_key(self) -> int | None:
        key = cv2.waitKeyEx(1)
        if key in (ord("q"), 27):
            return key
        if key in (
            ord("1"), ord("2"), ord("3"), ord("4"), ord("5"),
            ord("6"), ord("7"), ord("8"), ord("9"),
        ):
            clicked_instance = key - ord("1")
            self.selected_index = None if self.selected_index == clicked_instance else clicked_instance
            self.pending_human_action = None
        elif key in (ord("0"), ord("a"), ord("b")):
            clicked_instance = {ord("0"): 9, ord("a"): 10, ord("b"): 11}[key]
            self.selected_index = None if self.selected_index == clicked_instance else clicked_instance
            self.pending_human_action = None
        elif self.selected_index is not None:
            self.pending_human_action = {
                2490368: 3,
                2621440: 0,
                2424832: 1,
                2555904: 2,
                ord("z"): 4,
                ord("x"): 5,
                ord("s"): 6,
            }.get(key)
        return key

    def close(self) -> None:
        cv2.destroyWindow(self.title)
