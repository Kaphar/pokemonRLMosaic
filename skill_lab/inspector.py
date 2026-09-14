"""Observation inspector for the skill lab."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from skill_lab.panel_data import (
    MemoryWatchTracker,
    MemoryWatchWindow,
    address_range,
    draw_bag_panel,
    draw_memory_watch_panel,
    draw_party_panel,
    draw_stats_panel,
    draw_trainer_panel,
    draw_world_info,
    read_panel_data,
)
from skill_lab.party_reader import Gen1PartyReader, PyBoyMemoryReader


class ObservationInspector:
    def __init__(self, title: str = "Observation Inspector") -> None:
        self.title = title
        self.visible = False
        self._window_created = False
        self._needs_initial_render = False
        self._button_rect: tuple[int, int, int, int] | None = None
        self._watch_window = MemoryWatchWindow()
        self.address_watch = MemoryWatchTracker(
            [
                *address_range(0xD356, 0xD35F),
                *address_range(0xD361, 0xD362),
                *address_range(0xC026, 0xCC2F),
            ]
        )

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
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        rect = self._button_rect
        if rect is None:
            return
        bx, by, bw, bh = rect
        if bx <= x <= bx + bw and by <= y <= by + bh:
            self._watch_window.show()

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

        mem = env.envs[env_index].pyboy.memory
        panel_info = read_panel_data(mem)
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
        right_panel_w = 520
        panel_h = 440
        panel = np.full((panel_h, left_panel_w + right_panel_w, 3), 30, dtype=np.uint8)

        y = 25
        cv2.putText(panel, f"Env {env_index + 1}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        y += 28
        hp_color = (0, 255, 0) if hp > 0.5 else ((0, 255, 255) if hp > 0.2 else (0, 0, 255))
        cv2.putText(panel, f"HP: {hp:.0%}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, hp_color, 1)
        y += 24
        cv2.putText(panel, f"Level sum: {level_sum}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)
        y += 20
        draw_world_info(panel, 15, y, panel_info)
        y += 42
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

        party_x = left_panel_w + 15
        party_y = 18
        party_width = right_panel_w - 30
        cv2.rectangle(panel, (left_panel_w, 0), (left_panel_w + right_panel_w - 1, panel_h - 1), (75, 75, 75), 1)

        party = Gen1PartyReader(PyBoyMemoryReader(mem)).read_party({
            "partyAddr": Gen1PartyReader.PARTY_ADDRESS,
            "partySlotsCounterAddr": Gen1PartyReader.PARTY_SIZE_ADDRESS,
            "partyNicknamesAddr": Gen1PartyReader.PARTY_NICKNAMES_ADDRESS,
        })
        draw_party_panel(panel, party_x, party_y, party_width, 180, party)
        draw_trainer_panel(panel, party_x, 210, party_width, panel_info.get("trainer"))
        draw_bag_panel(panel, party_x, 255, party_width, panel_info.get("bag"))
        draw_stats_panel(panel, party_x, 315, party_width, {
            "badges": badges,
            "events": str(events),
            "steps": str(steps),
            "hp": f"{hp:.0%}",
            "env": f"{env_index + 1}",
        })

        watch_snapshot = self.address_watch.record(mem)
        self._button_rect = draw_memory_watch_panel(panel, 15, 330, 250, watch_snapshot, title="Addr watch")
        if self._watch_window.visible:
            self._watch_window.render(mem)

        rx = left_panel_w + 15
        ry = 120
        cv2.putText(panel, "Recent actions", (rx, ry), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        ry += 16
        action_names = ["Down", "Left", "Right", "Up", "A", "B", "Start", "Select"]
        for action in recent_actions:
            name = action_names[action] if action < len(action_names) else f"#{action}"
            cv2.putText(panel, f"  {name}", (rx, ry), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
            ry += 16
            if ry > 160:
                break

        screen_canvas = np.full((panel_h, 320, 3), 30, dtype=np.uint8)
        screen_canvas[:screen.shape[0], :screen.shape[1]] = screen
        inspector = np.hstack([screen_canvas, panel])
        cv2.imshow(self.title, inspector)
        self._needs_initial_render = False
        return True

    def close(self) -> None:
        self.visible = False
        self._window_created = False
        self._needs_initial_render = False
        self._watch_window.close()
        try:
            cv2.destroyWindow(self.title)
        except cv2.error:
            pass
