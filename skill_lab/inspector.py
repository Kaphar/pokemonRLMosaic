"""Observation inspector for the skill lab."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np

from skill_lab.party_reader import Gen1PartyReader, PyBoyMemoryReader


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
        right_panel_w = 520
        panel_h = 420
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

        party_x = left_panel_w + 15
        party_y = 22
        party_width = right_panel_w - 30
        cv2.rectangle(panel, (left_panel_w, 0), (left_panel_w + right_panel_w - 1, panel_h - 1), (75, 75, 75), 1)
        cv2.putText(panel, "Party", (party_x, party_y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
        party = Gen1PartyReader(
            PyBoyMemoryReader(env.envs[env_index].pyboy.memory)
        ).read_party({
            "partyAddr": Gen1PartyReader.PARTY_ADDRESS,
            "partySlotsCounterAddr": Gen1PartyReader.PARTY_SIZE_ADDRESS,
            "partyNicknamesAddr": Gen1PartyReader.PARTY_NICKNAMES_ADDRESS,
        })
        if party:
            row_y = party_y + 20
            for slot, pokemon in enumerate(party[:6]):
                if pokemon.get("speciesID", 0) == 0:
                    continue
                type_names = pokemon["type1Name"]
                if pokemon["type2"] != pokemon["type1"]:
                    type_names += f"/{pokemon['type2Name']}"
                name = pokemon.get("nickname") or pokemon.get("speciesName", "Unknown")
                header = f"{slot + 1}. {name} ({pokemon['speciesName']}) Lv{pokemon['level']} {type_names}"
                stats = (
                    f"HP {pokemon['curHP']}/{pokemon['maxHP']}  "
                    f"Atk {pokemon['attack']} Def {pokemon['defense']} "
                    f"Spe {pokemon['speed']} Sp {pokemon['spAttack']}"
                )
                dvs = (
                    f"DV HP {pokemon['ivHP']} Atk {pokemon['ivAttack']} "
                    f"Def {pokemon['ivDefense']} Spe {pokemon['ivSpeed']} "
                    f"Sp {pokemon['ivSpAttack']}"
                )
                cv2.putText(panel, header[:74], (party_x, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)
                cv2.putText(panel, stats[:82], (party_x, row_y + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (180, 220, 255), 1)
                cv2.putText(panel, dvs[:82], (party_x, row_y + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (180, 255, 180), 1)
                cv2.line(panel, (party_x, row_y + 32), (party_x + party_width, row_y + 32), (65, 65, 65), 1)
                row_y += 44
        else:
            cv2.putText(panel, "No Pokemon", (party_x, party_y + 24), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)

        rx = left_panel_w + 15
        ry = 320
        cv2.putText(panel, "Recent actions", (rx, ry), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        ry += 16
        action_names = ["Down", "Left", "Right", "Up", "A", "B", "Start"]
        for action in recent_actions:
            name = action_names[action] if action < len(action_names) else f"#{action}"
            cv2.putText(panel, f"  {name}", (rx, ry), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
            ry += 16
            if ry > 365:
                break

        ry = 390
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

        screen_canvas = np.full((panel_h, 320, 3), 30, dtype=np.uint8)
        screen_canvas[:screen.shape[0], :screen.shape[1]] = screen
        inspector = np.hstack([screen_canvas, panel])
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
