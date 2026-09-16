"""Dynamic mosaic display for the Skill Lab."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from skill_lab.config import PANEL_WIDTH, TILE_HEIGHT, TILE_WIDTH


class Mosaic:
    def __init__(self, num_tiles: int, title: str = "Pokemon Red V2 Mosaic", foreground: bool = False,
                 rows: int = 6, cols: int = 7) -> None:
        self.num_tiles = num_tiles
        self.rows = max(1, rows)
        self.cols = max(1, cols)
        self.title = title
        self.foreground = foreground
        self.page = 0
        self.view_mode = "pages"
        self.display_paused = False
        self._visible_indices: list[int] = []
        self.selected_index: int | None = None
        self.pending_human_action: int | None = None
        self.panel_x = self.cols * TILE_WIDTH
        self.panel_w = PANEL_WIDTH
        self.hovered_button: str | None = None
        self.last_action: str | None = None
        self.last_action_target: int | None = None
        self.control_active = False
        self.stats_visible = False
        self.map_visible = False
        margin, width, height, gap = 12, self.panel_w - 24, 42, 5
        start = 35
        colors = {
            "Control": (0, 180, 255), "Slash": (0, 0, 180), "Praise": (0, 180, 0),
            "Stats": (180, 180, 0), "Map": (180, 0, 0),
            "RESET": (180, 180, 0), "KILL": (180, 0, 0),
        }
        self.buttons: dict[str, dict[str, Any]] = {}
        for index, (name, color) in enumerate(colors.items()):
            self.buttons[name] = {
                "rect": (margin, start + (height + gap) * index, width, height),
                "color": color,
                "hover": tuple(min(255, value + 75) for value in color),
            }
        for index, (name, action, color) in enumerate((
            ("Previous", "previous", (80, 80, 180)),
            ("Next", "next", (80, 180, 180)),
            ("Best", "best", (80, 160, 80)),
            ("Worst", "worst", (160, 80, 80)),
            ("Pause UI", "pause", (100, 100, 100)),
        ), start=8):
            self.buttons[name] = {
                "action": action,
                "rect": (margin, start + (height + gap) * index, width, height),
                "color": color,
                "hover": tuple(min(255, value + 75) for value in color),
            }
        cv2.namedWindow(self.title)
        cv2.setMouseCallback(self.title, self._on_mouse)

    def _button_at(self, x: int, y: int) -> str | None:
        for name, info in self.buttons.items():
            bx, by, bw, bh = info["rect"]
            if bx + self.panel_x <= x < bx + self.panel_x + bw and by <= y < by + bh:
                return name
        return None

    def _on_mouse(self, event: int, x: int, y: int, flags: int, param: Any) -> None:
        if event == cv2.EVENT_MOUSEMOVE:
            self.hovered_button = self._button_at(x, y) if x >= self.panel_x else None
            return
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        if x >= self.panel_x:
            button = self._button_at(x, y)
            if button == "Control" and self.selected_index is not None:
                self.control_active = not self.control_active
                self.last_action = "Control" if self.control_active else None
                self.last_action_target = self.selected_index if self.control_active else None
                self.pending_human_action = None
            elif button == "Slash" and self.selected_index is not None:
                self.last_action, self.last_action_target = "Slash", self.selected_index
            elif button == "Praise" and self.selected_index is not None:
                self.last_action, self.last_action_target = "Praise", self.selected_index
            elif button == "RESET" and self.selected_index is not None:
                self.last_action, self.last_action_target = "RESET", self.selected_index
            elif button == "KILL" and self.selected_index is not None:
                self.last_action, self.last_action_target = "KILL", self.selected_index
            elif button == "Stats":
                self.stats_visible = not self.stats_visible
            elif button == "Map":
                self.map_visible = not self.map_visible
            elif button in ("Previous", "Next", "Best", "Worst", "Pause UI"):
                self._handle_view_action(self.buttons[button]["action"])
            return
        slot = (y // TILE_HEIGHT) * self.cols + (x // TILE_WIDTH)
        if slot < len(self._visible_indices):
            clicked = self._visible_indices[slot]
            self.selected_index = None if self.selected_index == clicked else clicked
            self.pending_human_action = None

    def render(self, tiles: list[np.ndarray], reward_modifiers: list[float] | None = None,
               ppo_updates: int = 0, objective_info: list[tuple[str, str | None, float]] | None = None,
               step_count: int = 0, batch_number: int = 0, model_name: str | None = None,
               tile_indices: list[int] | None = None) -> None:
        tile_indices = tile_indices or list(range(len(tiles)))
        self._visible_indices = tile_indices
        rows_list = []
        for row in range(self.rows):
            row_tiles = tiles[row * self.cols:(row + 1) * self.cols]
            while len(row_tiles) < self.cols:
                row_tiles.append(np.zeros((TILE_HEIGHT, TILE_WIDTH, 3), dtype=np.uint8))
            rows_list.append(np.hstack(row_tiles))
        grid = np.vstack(rows_list)
        panel_h = grid.shape[0]
        panel = np.full((panel_h, self.panel_w, 3), 40, dtype=np.uint8)
        cv2.rectangle(panel, (0, 0), (self.panel_w - 1, panel_h - 1), (80, 80, 80), 2)
        cv2.putText(panel, f"Supervisor | {self.view_mode} | page {self.page + 1}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        selected_text = f"Selected: {self.selected_index + 1}" if self.selected_index is not None else "No selection"
        cv2.putText(panel, selected_text, (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 255), 1)
        cv2.putText(panel, f"PPO updates: {ppo_updates}", (20, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)
        cv2.putText(panel, f"Step: {step_count}", (20, 105), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(panel, f"Batch: {batch_number}", (20, 125), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        if model_name:
            cv2.putText(panel, f"Model: {model_name}", (20, 145), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        for name, info in self.buttons.items():
            bx, by, bw, bh = info["rect"]
            if name == "Pause UI":
                color = info["hover"] if self.display_paused else info["color"]
            elif name == "Stats":
                color = info["hover"] if self.stats_visible else info["color"]
            elif name == "Map":
                color = info["hover"] if self.map_visible else info["color"]
            else:
                color = info["hover"] if self.hovered_button == name else info["color"]
            cv2.rectangle(panel, (bx, by), (bx + bw, by + bh), color, -1)
            cv2.rectangle(panel, (bx, by), (bx + bw, by + bh), (255, 255, 255), 2)
            text_size = cv2.getTextSize(name, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)[0]
            cv2.putText(panel, name, (bx + (bw - text_size[0]) // 2, by + (bh + text_size[1]) // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        if self.control_active and self.selected_index is not None:
            cv2.putText(panel, "CONTROL ON", (20, panel_h - 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        mosaic = np.hstack([grid, panel])
        cv2.imshow(self.title, mosaic)
        if self.foreground:
            cv2.setWindowProperty(self.title, cv2.WND_PROP_TOPMOST, 1)

    def _handle_view_action(self, action: str) -> None:
        page_size = self.rows * self.cols
        pages = max(1, (self.num_tiles + page_size - 1) // page_size)
        if action == "next":
            self.view_mode, self.page = "pages", (self.page + 1) % pages
        elif action == "previous":
            self.view_mode, self.page = "pages", (self.page - 1) % pages
        elif action in ("best", "worst"):
            self.view_mode, self.page = action, 0
        elif action == "pause":
            self.display_paused = not self.display_paused

    def visible_indices(self, scores: np.ndarray | None = None) -> list[int]:
        size = self.rows * self.cols
        if self.view_mode == "best" and scores is not None:
            return np.argsort(scores)[::-1].tolist()[:size]
        if self.view_mode == "worst" and scores is not None:
            return np.argsort(scores).tolist()[:size]
        start = self.page * size
        return list(range(start, min(start + size, self.num_tiles)))

    def poll_key(self) -> int | None:
        key = cv2.waitKeyEx(1)
        if key in (ord("q"), 27):
            return key
        if key in (ord("n"), ord("]")):
            self._handle_view_action("next")
        elif key in (ord("p"), ord("[")):
            self._handle_view_action("previous")
        elif key == ord("v"):
            self._handle_view_action("best" if self.view_mode != "best" else "worst")
        elif key == ord(" "):
            self._handle_view_action("pause")
        elif ord("1") <= key <= ord("9"):
            slot = key - ord("1")
            if slot < len(self._visible_indices):
                clicked = self._visible_indices[slot]
                self.selected_index = None if self.selected_index == clicked else clicked
                self.pending_human_action = None
        elif self.selected_index is not None:
            self.pending_human_action = {2490368: 3, 2621440: 0, 2424832: 1, 2555904: 2, ord("z"): 4, ord("x"): 5, ord("s"): 6}.get(key)
        return key

    def close(self) -> None:
        cv2.destroyWindow(self.title)
