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
from skill_lab.milestones import MilestoneTracker
from skill_lab.party_reader import Gen1PartyReader, PyBoyMemoryReader
from skill_lab.ram_map import GameState


def get_env_directives(env, env_index: int) -> dict[str, Any]:
    """Extract directive information from the environment."""
    env_obj = env.envs[env_index]
    wrapper = getattr(env_obj, 'env', None)
    if wrapper is None:
        wrapper = env_obj
    
    # Get attributes from the wrapper
    target_starter = getattr(wrapper, 'target_starter', None)
    rom_path = getattr(wrapper, 'rom_path', '')
    catch_directive = getattr(wrapper, 'catch_directive', [])
    train_directive = getattr(wrapper, 'train_directive', [])
    env_name = getattr(wrapper, 'env_name', f'Env{env_index+1}')
    
    # Determine ROM color (Red = red, Blue = blue)
    rom_color = (0, 0, 255)  # Default red (BGR)
    rom_label = "Red"
    if 'Blue' in rom_path or 'blue' in rom_path:
        rom_color = (255, 0, 0)  # Blue in BGR
        rom_label = "Blue"
    
    return {
        'env_name': env_name,
        'target_starter': target_starter,
        'rom_path': rom_path,
        'rom_label': rom_label,
        'rom_color': rom_color,
        'catch_directive': catch_directive,
        'train_directive': train_directive,
    }


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
        if self.visible and self._window_created and self._window_alive():
            return
        self.visible = True
        if not self._window_created or not self._window_alive():
            cv2.namedWindow(self.title, cv2.WINDOW_NORMAL)
            cv2.setMouseCallback(self.title, self._on_mouse)
            self._window_created = True
        self._needs_initial_render = True

    def _window_alive(self) -> bool:
        try:
            return cv2.getWindowProperty(self.title, cv2.WND_PROP_VISIBLE) >= 1
        except cv2.error:
            return False

    def hide(self) -> None:
        self.visible = False
        self._needs_initial_render = False

    def _on_mouse(self, event: int, x: int, y: int, flags: int, param: Any) -> None:
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        # Check "Show more" button for memory watch
        rect = self._button_rect
        if rect is not None:
            bx, by, bw, bh = rect
            if bx <= x <= bx + bw and by <= y <= by + bh:
                self._watch_window.show()
                return
        # Check memory watch window buttons if it's open
        if self._watch_window.visible:
            # The watch window has its own mouse callback
            pass

    def render(self, env, env_index: int, reward_history: list[float] | None = None) -> bool:
        if not self.visible:
            self._needs_initial_render = False
            return True
        if not self._needs_initial_render and not self._window_alive():
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

        # Get directive info
        directives = get_env_directives(env, env_index)

        # Larger panels (~20% increase)
        left_panel_w = 410  # Was 340
        right_panel_w = 700  # Was 580
        panel_h = 620  # Was 520
        panel = np.full((panel_h, left_panel_w + right_panel_w, 3), 30, dtype=np.uint8)

        y = 25
        # Env label with ROM color
        env_label = f"Env {env_index + 1} [{directives['env_name']}]"
        cv2.putText(panel, env_label, (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, directives["rom_color"], 2)
        y += 28
        
        # ROM indicator with color
        cv2.putText(panel, f"ROM: ", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 200), 1)
        rom_text_x = 15 + int(cv2.getTextSize("ROM: ", cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)[0][0])
        cv2.putText(panel, f"[{directives['rom_label']}]", (rom_text_x, y), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, directives['rom_color'], 2)
        y += 24
        
        # Target starter directive
        if directives['target_starter']:
            cv2.putText(panel, f"Target: {directives['target_starter']}", (15, y), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)
        else:
            cv2.putText(panel, "Target: Any starter", (15, y), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)
        y += 22
        
        # Catch directives
        if directives['catch_directive']:
            catch_str = ", ".join(directives['catch_directive'][:4])
            if len(directives['catch_directive']) > 4:
                catch_str += f" (+{len(directives['catch_directive'])-4} more)"
            cv2.putText(panel, f"Catch: {catch_str}", (15, y), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 255, 180), 1)
        else:
            cv2.putText(panel, "Catch: (none)", (15, y), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
        y += 20
        
        # Train directives
        if directives['train_directive']:
            train_str = ", ".join(directives['train_directive'][:3])
            if len(directives['train_directive']) > 3:
                train_str += f" (+{len(directives['train_directive'])-3} more)"
            cv2.putText(panel, f"Train: {train_str}", (15, y), 
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 180, 180), 1)
        y += 24

        event_tracker = getattr(env.envs[env_index], "event_tracker", None)
        if event_tracker is not None:
            cv2.putText(panel, "Milestones:", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            y += 18
            event_names = getattr(event_tracker, "event_names", {}) or {}
            milestone_items = list(event_names.items()) if isinstance(event_names, dict) else []
            achieved = getattr(event_tracker, "achieved", set()) or set()
            current_target_index = None
            for idx, (key, name) in enumerate(milestone_items):
                if key not in achieved:
                    current_target_index = idx
                    break
            if current_target_index is None:
                current_target_index = len(milestone_items) - 1
            start_index = max(0, current_target_index - 2)
            end_index = min(len(milestone_items), current_target_index + 4)
            for idx in range(start_index, end_index):
                key, name = milestone_items[idx]
                done = key in achieved
                is_target = idx == current_target_index
                if done:
                    color = (0, 255, 0)
                    label = "✓"
                    step_text = f" @ step {getattr(event_tracker, 'achieved_steps', {}).get(key, 0)}"
                elif is_target:
                    color = (0, 255, 255)
                    label = "▶"
                    step_text = " (current target)"
                else:
                    color = (110, 110, 110)
                    label = "○"
                    step_text = ""
                cv2.putText(panel, f"{label} {name}{step_text}", (20, y), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1)
                y += 15
            y += 8
        else:
            cv2.putText(panel, "Milestones: (not available)", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
            y += 18

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
        y += 20
        fled_battle = int(getattr(env.envs[env_index], "fled_battle", 0))
        flee_color = (0, 0, 255) if fled_battle > 0 else (110, 110, 110)
        cv2.putText(panel, f"Fled: {fled_battle}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, flee_color, 1)
        y += 20
        cv2.putText(panel, f"Walls: {env.envs[env_index].wall_collisions}", (15, y),
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

        # --- Checkpoint Tracker ---
        checkpoint_y = party_y + 180 + 10
        checkpoint_tracker = getattr(env.envs[env_index], "checkpoint_tracker", None)
        if checkpoint_tracker is not None:
            progress = checkpoint_tracker.get_progress()
            cv2.putText(panel, "Checkpoints:", (party_x, checkpoint_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            checkpoint_y += 18
            checkpoint_list = progress.get("checkpoints", [])
            current_target = progress.get("current_target_index", 0)
            start_idx = max(0, current_target - 2)
            end_idx = min(len(checkpoint_list), current_target + 4)
            for idx in range(start_idx, end_idx):
                if idx >= len(checkpoint_list):
                    break
                cp = checkpoint_list[idx]
                cp_name = cp.get("name", f"cp_{idx}")
                done = cp.get("achieved", False)
                is_target = idx == current_target
                cp_step = cp.get("achieved_step", None)
                if done:
                    color = (0, 255, 0)
                    label = "#"
                    step_text = f" @ step {cp_step}" if cp_step else ""
                elif is_target:
                    color = (0, 255, 255)
                    label = ">"
                    step_text = " (current target)"
                else:
                    color = (110, 110, 110)
                    label = "o"
                    step_text = ""
                cv2.putText(panel, f"{label} {cp_name}{step_text}", (party_x + 5, checkpoint_y), cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1)
                checkpoint_y += 15
            checkpoint_y += 8

        # --- Opponent / Battle info ---
        opp_y = checkpoint_y + 10
        enemy_species_name = None
        enemy_level = None
        enemy_hp = None
        in_battle = False
        try:
            in_battle = int(mem[0xD057]) != 0
            if in_battle:
                enemy_species = int(mem[0xCFE5])
                enemy_level = int(mem[0xCFF3])
                enemy_species_name = Gen1PartyReader.SPECIES_NAMES[enemy_species - 1] \
                    if 1 <= enemy_species <= len(Gen1PartyReader.SPECIES_NAMES) else f"#{enemy_species:03d}"
                enemy_cur_hp = (int(mem[0xCFE6]) | (int(mem[0xCFE7]) << 8))
                enemy_max_hp = (int(mem[0xCFF4]) | (int(mem[0xCFF5]) << 8))
                enemy_hp = (enemy_cur_hp, enemy_max_hp)
        except Exception:
            in_battle = False

        if in_battle and enemy_species_name:
            cv2.putText(panel, f"Opponent: {enemy_species_name} Lv.{enemy_level}", (party_x, opp_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 200, 200), 1)
            opp_y += 16
            if enemy_hp:
                cv2.putText(panel, f"  HP: {enemy_hp[0]}/{enemy_hp[1]}", (party_x, opp_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 200, 200), 1)
            opp_y += 20
        else:
            cv2.putText(panel, "Opponent: (none)", (party_x, opp_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (110, 110, 110), 1)
            opp_y += 20

        draw_trainer_panel(panel, party_x, opp_y, party_width, panel_info.get("trainer"))
        draw_bag_panel(panel, party_x, opp_y + 140, party_width, panel_info.get("bag"))
        draw_stats_panel(panel, party_x, opp_y + 185, party_width, {
            "badges": badges,
            "events": str(events),
            "steps": str(steps),
            "hp": f"{hp:.0%}",
            "trainer_wins": str(trainer_wins),
            "wild_wins": str(wild_wins),
            "fled_battle": str(fled_battle),
            "env": f"{env_index + 1}",
        })

        # --- Reward History ---
        reward_y = opp_y + 235
        cv2.putText(panel, "Reward History", (party_x, reward_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        reward_y += 18
        reward_counts = getattr(env.envs[env_index], "reward_counts", {})
        if reward_counts:
            for rtype, rlabel in [
                ("fled_battle", "Fled:"),
                ("combat_trainer", "Trainer:"),
                ("combat_wild", "Wild:"),
                ("milestone", "Milestones:"),
                ("event", "Events:"),
            ]:
                cv2.putText(panel, f"{rlabel} {reward_counts.get(rtype, 0)}", (party_x, reward_y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1)
                reward_y += 14
        else:
            cv2.putText(panel, "  (no rewards yet)", (party_x, reward_y), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (110, 110, 110), 1)

        watch_snapshot = self.address_watch.record(mem)
        self._button_rect = draw_memory_watch_panel(panel, 15, 360, left_panel_w - 30, watch_snapshot, title="Addr watch", max_rows=12)
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
        inspector_frame = np.hstack([screen_canvas, panel])
        try:
            cv2.imshow(self.title, inspector_frame)
        except cv2.error:
            self.visible = False
            self._needs_initial_render = False
            return False
        
        # Resize window to fit content
        if self._window_created and self._window_alive():
            total_w = 320 + left_panel_w + right_panel_w
            total_h = panel_h
            try:
                cv2.resizeWindow(self.title, total_w, total_h)
            except cv2.error:
                pass
        
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
