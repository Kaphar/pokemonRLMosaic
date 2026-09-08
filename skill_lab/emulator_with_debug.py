"""Launch Pokemon Red in player mode with a live debug inspector."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from tkinter import filedialog, messagebox

import cv2
import numpy as np
import tkinter as tk
from pyboy import PyBoy
from pyboy.utils import WindowEvent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V2_DIR = PROJECT_ROOT / "v2"
if str(V2_DIR) not in sys.path:
    sys.path.insert(0, str(V2_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skill_lab.party_reader import Gen1PartyReader, PyBoyMemoryReader
from v2.global_map import local_to_global, GLOBAL_MAP_SHAPE

DEFAULT_ROM = PROJECT_ROOT / "PokemonRed.gb"
DEFAULT_INIT_STATE = PROJECT_ROOT / "init.state"
DEFAULT_MAP_IMAGE = PROJECT_ROOT / "visualization" / "poke_map" / "pokemap_full_calibrated_CROPPED_1.png"
ACTION_FREQ = 24

ACTION_EVENTS = {
    0: (WindowEvent.PRESS_ARROW_DOWN, WindowEvent.RELEASE_ARROW_DOWN),
    1: (WindowEvent.PRESS_ARROW_LEFT, WindowEvent.RELEASE_ARROW_LEFT),
    2: (WindowEvent.PRESS_ARROW_RIGHT, WindowEvent.RELEASE_ARROW_RIGHT),
    3: (WindowEvent.PRESS_ARROW_UP, WindowEvent.RELEASE_ARROW_UP),
    4: (WindowEvent.PRESS_BUTTON_A, WindowEvent.RELEASE_BUTTON_A),
    5: (WindowEvent.PRESS_BUTTON_B, WindowEvent.RELEASE_BUTTON_B),
    6: (WindowEvent.PRESS_BUTTON_START, WindowEvent.RELEASE_BUTTON_START),
}

# Memory addresses (see v2/red_gym_env_v2.py and baselines/memory_addresses.py)
MAP_N_ADDRESS = 0xD35E
X_POS_ADDRESS = 0xD362
Y_POS_ADDRESS = 0xD361
BADGE_COUNT_ADDRESS = 0xD356

# Inspector panel layout
INSPECTOR_W = 720
INSPECTOR_H = 520
LEFT_PANEL_W = 320
RIGHT_PANEL_W = 400
MAP_LABEL_H = 164
MAP_DISPLAY_W = 286
MAP_DISPLAY_H = int(MAP_DISPLAY_W * GLOBAL_MAP_SHAPE[0] / GLOBAL_MAP_SHAPE[1])
MAP_ORIGIN_X = 16
MAP_ORIGIN_Y = MAP_LABEL_H


class DebugLauncher:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Pokemon Red Emulator")
        self.root.resizable(False, False)

        self.rom_var = tk.StringVar(value=str(DEFAULT_ROM))
        self.state_var = tk.StringVar(value="none")
        self.state_path_var = tk.StringVar(value="No state: start from the ROM")
        self.replay_path_var = tk.StringVar(value="No replay selected")
        self._build_ui()

    def _build_ui(self) -> None:
        frame = tk.Frame(self.root, padx=16, pady=16)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        tk.Label(frame, text="Pokemon Red Emulator", font=("Segoe UI", 16, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 14)
        )

        tk.Label(frame, text="ROM:").grid(row=1, column=0, sticky="w", pady=4)
        tk.Entry(frame, textvariable=self.rom_var, width=64).grid(row=1, column=1, sticky="ew", pady=4)
        tk.Button(frame, text="Browse...", command=self._choose_rom).grid(row=1, column=2, padx=(8, 0))

        tk.Label(frame, text="Start from:").grid(row=2, column=0, sticky="nw", pady=8)
        state_frame = tk.Frame(frame)
        state_frame.grid(row=2, column=1, columnspan=2, sticky="w", pady=4)
        tk.Radiobutton(
            state_frame, text="No state", variable=self.state_var, value="none",
            command=self._update_state_label,
        ).pack(anchor="w")
        tk.Radiobutton(
            state_frame, text="Initial state", variable=self.state_var, value="initial",
            command=self._update_state_label,
        ).pack(anchor="w")
        custom_row = tk.Frame(state_frame)
        custom_row.pack(anchor="w")
        tk.Radiobutton(
            custom_row, text="Custom state", variable=self.state_var, value="custom",
            command=self._update_state_label,
        ).pack(side=tk.LEFT)
        tk.Button(custom_row, text="Choose...", command=self._choose_state).pack(side=tk.LEFT, padx=8)
        tk.Label(frame, textvariable=self.state_path_var, fg="gray", wraplength=530, justify=tk.LEFT).grid(
            row=3, column=1, columnspan=2, sticky="w", pady=(0, 8)
        )

        tk.Label(frame, text="Replay inputs:").grid(row=4, column=0, sticky="w", pady=4)
        tk.Button(frame, text="Choose JSON...", command=self._choose_replay).grid(row=4, column=1, sticky="w", pady=4)
        tk.Label(frame, textvariable=self.replay_path_var, fg="gray", wraplength=530, justify=tk.LEFT).grid(
            row=5, column=1, columnspan=2, sticky="w", pady=(0, 12)
        )

        tk.Label(
            frame,
            text=(
                "The emulator opens in player mode at normal speed with sound, in a keyboard-"
                "controllable SDL2 window. After the replay finishes it keeps running so you can play "
                "from where it stopped. Close the emulator window (Escape) or press Q in the inspector "
                "to stop."
            ),
            fg="gray",
            wraplength=600,
            justify=tk.LEFT,
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 12))
        tk.Button(frame, text="Start", width=16, command=self._start).grid(row=7, column=0, columnspan=3, pady=(4, 0))

    def _choose_rom(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose ROM", initialdir=str(PROJECT_ROOT),
            filetypes=[("Game Boy ROM", "*.gb *.gbc"), ("All files", "*.*")],
        )
        if path:
            self.rom_var.set(path)

    def _choose_state(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose state", initialdir=str(PROJECT_ROOT),
            filetypes=[("PyBoy state", "*.state"), ("All files", "*.*")],
        )
        if path:
            self.state_var.set("custom")
            self.state_path_var.set(path)

    def _choose_replay(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose replay inputs", initialdir=str(PROJECT_ROOT),
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.replay_path_var.set(path)

    def _update_state_label(self) -> None:
        if self.state_var.get() == "none":
            self.state_path_var.set("No state: start from the ROM")
        elif self.state_var.get() == "initial":
            self.state_path_var.set(str(DEFAULT_INIT_STATE))

    def _start(self) -> None:
        rom_path = Path(self.rom_var.get()).expanduser()
        if not rom_path.is_file():
            messagebox.showerror("ROM not found", f"Could not find:\n{rom_path}")
            return

        state_path: Path | None = None
        if self.state_var.get() == "initial":
            state_path = DEFAULT_INIT_STATE
        elif self.state_var.get() == "custom":
            state_path = Path(self.state_path_var.get())
        if state_path is not None and not state_path.is_file():
            messagebox.showerror("State not found", f"Could not find:\n{state_path}")
            return

        replay_path = self.replay_path_var.get()
        replay = None if replay_path == "No replay selected" else Path(replay_path)
        if replay is not None and not replay.is_file():
            messagebox.showerror("Replay not found", f"Could not find:\n{replay}")
            return

        self.root.destroy()
        run_player(rom_path, state_path, replay)


def load_replay(path: Path | None) -> tuple[list[int], dict[str, object]]:
    if path is None:
        return [], {}
    with path.open("r", encoding="utf-8") as input_file:
        data = json.load(input_file)
    entries = data.get("actions", [])
    actions = []
    for entry in entries:
        if not isinstance(entry, dict):
            actions.append(int(entry))
            continue
        # Legacy recordings kept the requested button and a separate mask flag.
        actions.append(7 if entry.get("masked", False) else int(entry["action"]))
    return actions, data


def load_actions(path: Path | None) -> list[int]:
    """Load effective actions, retained as a small compatibility helper."""
    return load_replay(path)[0]


def resolve_recording_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path if path.is_file() else None


def replay_action(pyboy: PyBoy, action: int, action_freq: int) -> None:
    """Advance one action exactly as RedGymEnv.run_action_on_emulator does."""
    events = ACTION_EVENTS.get(action)
    if events is not None:
        pyboy.send_input(events[0])
    pyboy.tick(8, True)
    if events is not None:
        pyboy.send_input(events[1])
    pyboy.tick(action_freq - 8 - 1, True)
    pyboy.tick(1, True)


def load_map_image(path: Path | None) -> np.ndarray | None:
    if path is None or not path.is_file():
        return None
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        return None
    if image.shape[-1] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def _prepare_map_base(map_image: np.ndarray | None) -> np.ndarray | None:
    if map_image is None:
        return None
    gh, gw = GLOBAL_MAP_SHAPE
    crop = map_image[:gh, :gw]
    return cv2.resize(crop, (MAP_DISPLAY_W, MAP_DISPLAY_H), interpolation=cv2.INTER_AREA)


def render_inspector(
    pyboy: PyBoy,
    frame_count: int,
    replay_index: int,
    replay_total: int,
    replay_finished: bool,
    map_base: np.ndarray | None,
) -> None:
    """Draw the info-only inspector (party + position/map). No game-screen image."""
    memory = pyboy.memory
    x_pos = int(memory[X_POS_ADDRESS])
    y_pos = int(memory[Y_POS_ADDRESS])
    map_n = int(memory[MAP_N_ADDRESS])
    badges = int(memory[BADGE_COUNT_ADDRESS])

    panel = np.full((INSPECTOR_H, INSPECTOR_W, 3), 26, dtype=np.uint8)

    # ---- Left panel: status, position, map ----
    y = 26
    cv2.putText(panel, "Pokemon Red Inspector", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    y += 28
    if replay_total:
        if replay_finished:
            status = "REPLAY FINISHED - play via the emulator window"
        else:
            status = f"Replaying {replay_index}/{replay_total}"
    else:
        status = "Replay: inactive"
    cv2.putText(panel, status, (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (190, 210, 220), 1)
    y += 22
    cv2.putText(panel, f"Frames: {frame_count}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (190, 210, 220), 1)
    y += 20
    cv2.putText(panel, f"Map ID: {map_n:02X} ({map_n})", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)
    y += 20
    cv2.putText(panel, f"Position: X={x_pos}  Y={y_pos}", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)
    y += 20
    cv2.putText(panel, f"Badges: {badges}/8", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)

    gh, gw = GLOBAL_MAP_SHAPE
    if map_base is not None:
        map_img = map_base.copy()
        gy, gx = local_to_global(y_pos, x_pos, map_n)
        gx = min(max(gx, 0), gw - 1)
        gy = min(max(gy, 0), gh - 1)
        mx = int(gx * MAP_DISPLAY_W / gw)
        my = int(gy * MAP_DISPLAY_H / gh)
        cv2.circle(map_img, (mx, my), 5, (0, 0, 0), -1)
        cv2.circle(map_img, (mx, my), 5, (0, 0, 255), 1)
        cv2.putText(map_img, "you", (mx + 7, my + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)
    else:
        map_img = np.full((MAP_DISPLAY_H, MAP_DISPLAY_W, 3), 26, dtype=np.uint8)
        cv2.putText(map_img, "map image missing", (8, MAP_DISPLAY_H // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)

    panel[MAP_ORIGIN_Y:MAP_ORIGIN_Y + MAP_DISPLAY_H, MAP_ORIGIN_X:MAP_ORIGIN_X + MAP_DISPLAY_W] = map_img

    # ---- Right panel: party ----
    rx = LEFT_PANEL_W + 16
    ry = 26
    cv2.putText(panel, "Party", (rx, ry), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    ry += 24
    party = Gen1PartyReader(PyBoyMemoryReader(memory)).read_party({
        "partyAddr": Gen1PartyReader.PARTY_ADDRESS,
        "partySlotsCounterAddr": Gen1PartyReader.PARTY_SIZE_ADDRESS,
        "partyNicknamesAddr": Gen1PartyReader.PARTY_NICKNAMES_ADDRESS,
    })
    if party:
        party_width = RIGHT_PANEL_W - 32
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
            cv2.putText(panel, header[:78], (rx, ry), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (255, 255, 255), 1)
            cv2.putText(panel, stats[:86], (rx, ry + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.33, (180, 220, 255), 1)
            cv2.putText(panel, dvs[:86], (rx, ry + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.33, (180, 255, 180), 1)
            cv2.line(panel, (rx, ry + 33), (rx + party_width, ry + 33), (65, 65, 65), 1)
            ry += 44
            if ry + 44 > INSPECTOR_H - 24:
                break
    else:
        cv2.putText(panel, "No Pokemon", (rx, ry + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)

    cv2.putText(
        panel,
        "Q/Esc: quit | Arrows/A/S/Start: move & buttons | +/-: speed | P: pause | Esc(emulator): quit",
        (15, INSPECTOR_H - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (120, 120, 120), 1,
    )

    cv2.imshow("Pokemon Red Inspector", panel)
    cv2.moveWindow("Pokemon Red Inspector", 820, 80)


def run_player(rom_path: Path, state_path: Path | None, replay_path: Path | None) -> None:
    actions, replay_data = load_replay(replay_path)
    replay_action_freq = int(replay_data.get("action_freq", ACTION_FREQ))
    if replay_action_freq < 9:
        raise ValueError(f"Replay action frequency must be at least 9, got {replay_action_freq}")
    if state_path is None:
        state_path = resolve_recording_path(replay_data.get("init_state"))
    pyboy = PyBoy(str(rom_path), window="SDL2", sound=True)
    try:
        if state_path is not None:
            with state_path.open("rb") as state_file:
                pyboy.load_state(state_file)

        pyboy.set_emulation_speed(1)  # normal real-time speed
        map_base = _prepare_map_base(load_map_image(DEFAULT_MAP_IMAGE))

        frame_count = 0
        replay_index = 0
        replay_finished = len(actions) == 0
        render_inspector(pyboy, frame_count, replay_index, len(actions), replay_finished, map_base)

        while True:
            # Play back the next queued action at normal speed, one frame at a time, so the
            # audio/video stay in sync and the player can start controlling as soon as it ends.
            if replay_index < len(actions):
                action = actions[replay_index]
                replay_index += 1
                replay_action(pyboy, action, replay_action_freq)
                frame_count += replay_action_freq
            else:
                if not pyboy.tick(1, True):
                    break
                frame_count += 1

            if replay_index >= len(actions):
                replay_finished = True

            render_inspector(pyboy, frame_count, replay_index, len(actions), replay_finished, map_base)
            key = cv2.waitKeyEx(1)
            if key in (ord("q"), 27):
                break
            time.sleep(0.001)
    finally:
        pyboy.stop()
        cv2.destroyAllWindows()


def main() -> None:
    launcher = DebugLauncher()
    launcher.root.mainloop()


if __name__ == "__main__":
    main()
