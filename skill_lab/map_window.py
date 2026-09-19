"""Overall map window for the skill lab."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

PROJECT_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
V2_DIR = PROJECT_ROOT / "v2"
if str(V2_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(V2_DIR))

from global_map import local_to_global, GLOBAL_MAP_SHAPE


class MapWindow:
    def __init__(self, title: str = "Overall Map", map_image_path: str | None = None) -> None:
        self.title = title
        if map_image_path is None:
            map_image_path = str(PROJECT_ROOT / "visualization" / "poke_map" / "pokemap_full_calibrated_CROPPED_1.png")
        self.map_image = cv2.imread(map_image_path, cv2.IMREAD_UNCHANGED)
        if self.map_image is None:
            self.map_image = np.zeros((GLOBAL_MAP_SHAPE[0], GLOBAL_MAP_SHAPE[1], 3), dtype=np.uint8)
        self.canvas = self.map_image.copy()
        self.canvas_h, self.canvas_w = self.canvas.shape[:2]
        self.tracked_env: int | None = None
        self.history: list[tuple[int, int]] = []
        self.max_history = 200
        self.lava_zones: set[tuple[int, int]] = set()
        self.visible = False
        self._window_created = False
        self._needs_initial_render = False
        self._last_click = None
        self._last_display_scale = 1.0
        self.zoom = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.dragging = False
        self.drag_start = (0, 0)
        self.drag_origin = (0, 0)

    def show(self) -> None:
        if self.visible and self._window_created:
            return
        self.visible = True
        if not self._window_created:
            cv2.namedWindow(self.title)
            cv2.setMouseCallback(self.title, self._on_mouse)
            self._window_created = True
        self._needs_initial_render = True

    def hide(self) -> None:
        self.visible = False
        self._needs_initial_render = False

    def _on_mouse(self, event: int, x: int, y: int, flags: int, param: Any) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            self.dragging = True
            self.drag_start = (x, y)
            self.drag_origin = (self.pan_x, self.pan_y)
            self._last_click = (x, y)
            self._toggle_lava_under_click(x, y)
            self.tracked_env = None
            self.history.clear()
        elif event == cv2.EVENT_MOUSEMOVE and self.dragging:
            dx = x - self.drag_start[0]
            dy = y - self.drag_start[1]
            self.pan_x = self.drag_origin[0] - dx / max(self.zoom, 0.1)
            self.pan_y = self.drag_origin[1] - dy / max(self.zoom, 0.1)
        elif event == cv2.EVENT_LBUTTONUP:
            self.dragging = False

    def _toggle_lava_under_click(self, x: int, y: int) -> None:
        """Toggle a lava zone on the current map image at the clicked coordinate."""
        if not self.canvas.size:
            return
        if x < 0 or y < 0:
            return
        world_x = int((x - self.pan_x) / max(self.zoom, 0.1))
        world_y = int((y - self.pan_y) / max(self.zoom, 0.1))
        cell = (world_x, world_y)
        if cell in self.lava_zones:
            self.lava_zones.remove(cell)
        else:
            self.lava_zones.add(cell)

    def add_lava_zone(self, gx: int, gy: int) -> None:
        self.lava_zones.add((gx, gy))

    def set_tracked_env(self, env_index: int | None) -> None:
        self.tracked_env = env_index
        self.history.clear()

    def render(self, env, env_index: int) -> bool:
        if not self.visible or env_index != self.tracked_env:
            return True
        if not self._needs_initial_render and cv2.getWindowProperty(self.title, cv2.WND_PROP_VISIBLE) < 1:
            self.visible = False
            self._needs_initial_render = False
            return False

        e = env.envs[env_index]
        x_pos = e.pyboy.memory[0xD362]
        y_pos = e.pyboy.memory[0xD361]
        map_n = e.pyboy.memory[0xD35E]
        gy, gx = local_to_global(y_pos, x_pos, map_n)
        self.history.append((gx, gy))
        if len(self.history) > self.max_history:
            self.history = self.history[-self.max_history:]

        canvas = self.map_image.copy()
        for gx, gy in self.lava_zones:
            cv2.rectangle(canvas, (gx, gy), (gx + 3, gy + 3), (0, 0, 255), -1)
        if len(self.history) > 1:
            for i in range(1, len(self.history)):
                cv2.line(canvas, self.history[i - 1], self.history[i], (0, 255, 0), 1)
        if self.history:
            cv2.circle(canvas, self.history[-1], 4, (0, 0, 255), -1)
        cv2.putText(canvas, f"Env {env_index + 1} | Map {map_n:02X} | ({x_pos}, {y_pos})", (10, 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(canvas, f"Lava cells: {len(self.lava_zones)} | click to toggle | wheel zoom / drag pan", (10, 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 100, 100), 1)

        scale = 1.0
        if canvas.shape[0] > 600 or canvas.shape[1] > 800:
            scale = min(600.0 / canvas.shape[0], 800.0 / canvas.shape[1])
        self._last_display_scale = scale

        # Zoomed display on a larger, scrollable-style canvas to keep the map readable.
        display_size = (max(1, int(canvas.shape[1] * self.zoom * scale)), max(1, int(canvas.shape[0] * self.zoom * scale)))
        display = cv2.resize(canvas, display_size, interpolation=cv2.INTER_NEAREST)
        cv2.imshow(self.title, display)
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
