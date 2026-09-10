"""Launch Pokemon Red in player mode with a live debug inspector."""

from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from datetime import datetime
from typing import Any

import cv2
import numpy as np
import tkinter as tk
import sdl2
from pyboy import PyBoy
from pyboy.utils import WindowEvent

PROJECT_ROOT = Path(__file__).resolve().parents[1]
V2_DIR = PROJECT_ROOT / "v2"
if str(V2_DIR) not in sys.path:
    sys.path.insert(0, str(V2_DIR))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skill_lab.panel_data import (
    MemoryWatchTracker,
    MemoryWatchWindow,
    address_range,
    draw_bag_panel,
    draw_memory_watch_panel,
    draw_menu_handler_info,
    draw_party_panel,
    get_screen_size,
    positioned_windows,
    draw_stats_panel,
    draw_trainer_panel,
    draw_world_info,
    read_panel_data,
)
from v2.global_map import local_to_global, GLOBAL_MAP_SHAPE

DEFAULT_ROM = PROJECT_ROOT / "PokemonRed.gb"
DEFAULT_INIT_STATE = PROJECT_ROOT / "init.state"
DEFAULT_MAP_IMAGE = PROJECT_ROOT / "visualization" / "poke_map" / "pokemap_full_calibrated_CROPPED_1.png"
ACTION_FREQ = 24
CONTROLS_PATH = PROJECT_ROOT / "skill_lab" / "controls.json"
# Set to False after diagnosing controller input.
DEBUG_INPUT = False
ACTION_NAMES = ["Down", "Left", "Right", "Up", "A", "B", "Start", "Select", "SpeedUp", "SpeedDown", "Pause"]
DEFAULT_CONTROLS = {
    "keyboard": {
        "Down": "down", "Left": "left", "Right": "right", "Up": "up",
        "A": "z", "B": "x", "Start": "return", "Select": "tab",
        "SpeedUp": "pageup", "SpeedDown": "pagedown", "Pause": "p",
    },
    "gamepad": {},
}


def initialize_sdl_input() -> None:
    flags = sdl2.SDL_INIT_VIDEO | sdl2.SDL_INIT_JOYSTICK | sdl2.SDL_INIT_GAMECONTROLLER
    result = sdl2.SDL_InitSubSystem(flags)
    if result != 0:
        print(f"SDL input initialization warning: {sdl2.SDL_GetError().decode('utf-8')}")
    sdl2.SDL_JoystickEventState(sdl2.SDL_ENABLE)
    sdl2.SDL_GameControllerEventState(sdl2.SDL_ENABLE)


def list_gamepads() -> list[str]:
    devices = []
    for index in range(max(0, sdl2.SDL_NumJoysticks())):
        name = sdl2.SDL_JoystickNameForIndex(index)
        if name:
            devices.append(name.decode("utf-8", errors="replace"))
    return devices


def debug_input(message: str) -> None:
    if DEBUG_INPUT:
        print(f"[INPUT] {message}", flush=True)


def debug_sdl_event(event: sdl2.SDL_Event, source: str) -> None:
    if not DEBUG_INPUT:
        return
    event_type = int(event.type)
    if event_type == sdl2.SDL_KEYDOWN or event_type == sdl2.SDL_KEYUP:
        name = sdl2.SDL_GetKeyName(event.key.keysym.sym).decode("utf-8", errors="replace")
        debug_input(f"{source} {'KEYDOWN' if event_type == sdl2.SDL_KEYDOWN else 'KEYUP'} key={name}")
    elif event_type in (sdl2.SDL_JOYBUTTONDOWN, sdl2.SDL_JOYBUTTONUP):
        state = "DOWN" if event_type == sdl2.SDL_JOYBUTTONDOWN else "UP"
        debug_input(f"{source} JOYBUTTON{state} joystick={event.jbutton.which} button={event.jbutton.button} token=button:{event.jbutton.button}")
    elif event_type in (sdl2.SDL_CONTROLLERBUTTONDOWN, sdl2.SDL_CONTROLLERBUTTONUP):
        state = "DOWN" if event_type == sdl2.SDL_CONTROLLERBUTTONDOWN else "UP"
        debug_input(f"{source} CONTROLLERBUTTON{state} controller={event.cbutton.which} button={event.cbutton.button} token=controller:{event.cbutton.button}")
    elif event_type == sdl2.SDL_JOYHATMOTION:
        debug_input(f"{source} JOYHAT hat={event.jhat.hat} value={event.jhat.value} token=hat:{event.jhat.hat}:{event.jhat.value}")
    elif event_type == sdl2.SDL_JOYAXISMOTION:
        debug_input(f"{source} JOYAXIS axis={event.jaxis.axis} value={event.jaxis.value}")
    elif event_type == sdl2.SDL_CONTROLLERAXISMOTION:
        debug_input(f"{source} CONTROLLERAXIS axis={event.caxis.axis} value={event.caxis.value}")

DEFAULT_ACTION_PRESS_FRAMES = 8
DEFAULT_NOOP_ACTION = 8
REPLAY_SPEED_PRESETS = ("auto", "x1", "x2", "x3", "x4")

ACTION_EVENTS = {
    0: (WindowEvent.PRESS_ARROW_DOWN, WindowEvent.RELEASE_ARROW_DOWN),
    1: (WindowEvent.PRESS_ARROW_LEFT, WindowEvent.RELEASE_ARROW_LEFT),
    2: (WindowEvent.PRESS_ARROW_RIGHT, WindowEvent.RELEASE_ARROW_RIGHT),
    3: (WindowEvent.PRESS_ARROW_UP, WindowEvent.RELEASE_ARROW_UP),
    4: (WindowEvent.PRESS_BUTTON_A, WindowEvent.RELEASE_BUTTON_A),
    5: (WindowEvent.PRESS_BUTTON_B, WindowEvent.RELEASE_BUTTON_B),
    6: (WindowEvent.PRESS_BUTTON_START, WindowEvent.RELEASE_BUTTON_START),
    7: (WindowEvent.PRESS_BUTTON_SELECT, WindowEvent.RELEASE_BUTTON_SELECT),
}

# SELECT events are always masked during replay: pressing SELECT does nothing.
# This matches the ``disable_select`` directive used during training.
SELECT_EVENTS = frozenset({
    int(WindowEvent.PRESS_BUTTON_SELECT),
    int(WindowEvent.RELEASE_BUTTON_SELECT),
})


def resolve_replay_speed(mode: str) -> float:
    """Translate the UI speed label into the emulator speed multiplier."""
    if mode in ("", "auto", "normal"):
        return 1.0
    if mode.startswith("x"):
        try:
            return float(mode[1:])
        except ValueError:
            return 1.0
    try:
        return float(mode)
    except ValueError:
        return 1.0


def compute_action_timing(action_freq: int, press_frames: int = DEFAULT_ACTION_PRESS_FRAMES) -> tuple[int, int, int]:
    """Split an action cycle into press, idle, and final-render phases.

    Mirrors the hold-then-release-then-idle structure of
    ``RedGymEnv.run_action_on_emulator``: the button is pressed for
    ``press_frames`` (clamped to ``DEFAULT_ACTION_PRESS_FRAMES``), released,
    then left idle for the remainder of the cycle, finishing with a single
    rendered tick. The three returned values always sum to ``action_freq``.
    """
    if action_freq < 2:
        raise ValueError(f"Replay action frequency must be at least 2, got {action_freq}")

    press_length = max(1, min(int(press_frames), DEFAULT_ACTION_PRESS_FRAMES))
    idle_frames = max(0, action_freq - press_length - 1)
    return press_length, idle_frames, 1

# Memory addresses (see v2/red_gym_env_v2.py and baselines/memory_addresses.py)
MAP_N_ADDRESS = 0xD35E
X_POS_ADDRESS = 0xD362
Y_POS_ADDRESS = 0xD361
BADGE_COUNT_ADDRESS = 0xD356

# Inspector panel layout
INSPECTOR_W = 720
INSPECTOR_H = 560
LEFT_PANEL_W = 320
RIGHT_PANEL_W = 400
MAP_LABEL_H = 220
MAP_DISPLAY_W = 286
MAP_DISPLAY_H = int(MAP_DISPLAY_W * GLOBAL_MAP_SHAPE[0] / GLOBAL_MAP_SHAPE[1])
MAP_ORIGIN_X = 16
MAP_ORIGIN_Y = MAP_LABEL_H
DEV_STATES_DIR = PROJECT_ROOT / "skill_lab" / "envs" / "dev" / "states"


class DebugLauncher:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Pokemon Red Emulator")
        self.root.resizable(False, False)

        self.rom_var = tk.StringVar(value=str(DEFAULT_ROM))
        self.state_var = tk.StringVar(value="none")
        self.state_path_var = tk.StringVar(value="No state: start from the ROM")
        self.replay_path_var = tk.StringVar(value="No replay selected")
        self.replay_speed_var = tk.StringVar(value="auto")
        self.deterministic_var = tk.BooleanVar(value=False)
        self.plugin_replay_var = tk.BooleanVar(value=False)
        self.controls = load_controls()
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

        speed_frame = tk.Frame(frame)
        speed_frame.grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 8))
        tk.Label(speed_frame, text="Replay speed:").pack(side=tk.LEFT, padx=(0, 8))
        for speed_name in REPLAY_SPEED_PRESETS:
            tk.Radiobutton(
                speed_frame,
                text=speed_name,
                value=speed_name,
                variable=self.replay_speed_var,
                indicatoron=True,
            ).pack(side=tk.LEFT, padx=2)

        tk.Label(
            frame,
            text=(
                "The emulator opens in player mode at normal speed with sound, in a keyboard-"
                "or gamepad-controllable SDL2 window. After the replay finishes it keeps running so you can play "
                "from where it stopped. Close the emulator window (Escape) or press Q in the inspector "
                "to stop. The replay speed is only a display/visualization control; the deterministic frame timing"
                " of the input step still uses the real action cycle. "
                "Enable \"Deterministic headless replay\" to run PyBoy with window=null so SDL event"
                " processing never interferes with emulation — this guarantees identical RNG and DVs"
                " to the original training run."
            ),
            fg="gray",
            wraplength=600,
            justify=tk.LEFT,
        ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(0, 12))

        tk.Checkbutton(
            frame, text="Deterministic headless replay (no SDL events, exact frame timing)",
            variable=self.deterministic_var,
        ).grid(row=8, column=0, columnspan=3, sticky="w", pady=(0, 4))

        tk.Checkbutton(
            frame, text="Use plugin-style frame-exact replay (reads input_events from recording)",
            variable=self.plugin_replay_var,
        ).grid(row=9, column=0, columnspan=3, sticky="w", pady=(0, 4))

        button_row = tk.Frame(frame)
        button_row.grid(row=10, column=0, columnspan=3, pady=(4, 0))
        tk.Button(button_row, text="Configure controls...", command=self._configure_controls).pack(side=tk.LEFT, padx=4)
        tk.Button(button_row, text="Start", width=16, command=self._start).pack(side=tk.LEFT, padx=4)

    def _configure_controls(self) -> None:
        ControlsDialog(self.root, self.controls)

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
        run_player(
            rom_path, state_path, replay, self.controls,
            replay_speed=self.replay_speed_var.get(),
            deterministic=self.deterministic_var.get(),
            use_plugin_replay=self.plugin_replay_var.get(),
        )


class RuntimeMenu:
    """Native menu bar for actions that operate on the live emulator."""

    def __init__(
        self,
        pyboy: PyBoy,
        close_callback: callable | None = None,
        reset_callback: callable | None = None,
    ) -> None:
        self.pyboy = pyboy
        self.closed = False
        self.close_callback = close_callback
        self.reset_callback = reset_callback
        self.root = tk.Tk()
        self.root.title("Pokemon Red Debug Controls")
        self.root.resizable(False, False)
        self.root.geometry("+0+0")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        menu_bar = tk.Menu(self.root)
        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="Save State...", command=self.save_state)
        file_menu.add_command(label="Load State...", command=self.load_state)
        file_menu.add_separator()
        file_menu.add_command(label="Reset ROM", command=self.reset_rom)
        file_menu.add_separator()
        file_menu.add_command(label="Close Emulator", command=self.close)
        file_menu.add_command(label="Close Menu", command=self.close_menu)
        menu_bar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menu_bar)
        tk.Label(self.root, text="Use File to save or load the live emulator state.", padx=12, pady=8).pack()

    def close_menu(self) -> None:
        self.close()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.close_callback is not None:
            try:
                self.close_callback()
            except Exception:
                pass
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def save_state(self) -> None:
        DEV_STATES_DIR.mkdir(parents=True, exist_ok=True)
        default_name = datetime.now().strftime("state_%Y-%m-%d_%H-%M-%S")
        name = simpledialog.askstring("Save state", "State name:", initialvalue=default_name, parent=self.root)
        if not name:
            return
        filename = re.sub(r'[<>:"/\\|?*]', "-", Path(name).name).strip(" .")
        if not filename:
            filename = default_name
        if not filename.lower().endswith(".state"):
            filename += ".state"
        path = DEV_STATES_DIR / filename
        try:
            with path.open("wb") as state_file:
                self.pyboy.save_state(state_file)
            messagebox.showinfo("State saved", f"Saved state to:\n{path}", parent=self.root)
        except OSError as error:
            messagebox.showerror("Save failed", str(error), parent=self.root)

    def load_state(self) -> None:
        path = filedialog.askopenfilename(
            title="Load state", initialdir=str(DEV_STATES_DIR),
            filetypes=[("PyBoy state", "*.state"), ("All files", "*.*")], parent=self.root,
        )
        if not path:
            return
        try:
            with Path(path).open("rb") as state_file:
                self.pyboy.load_state(state_file)
            messagebox.showinfo("State loaded", f"Loaded state from:\n{path}", parent=self.root)
        except OSError as error:
            messagebox.showerror("Load failed", str(error), parent=self.root)

    def reset_rom(self) -> None:
        if self.reset_callback is not None:
            self.reset_callback()

    def update(self) -> None:
        if self.closed:
            return
        self.root.update_idletasks()
        self.root.update()


class WatchControlPanel(tk.Toplevel):
    """Persistent control window with editable text fields for the memory watch.

    Provides direct address-range entry (no shortcut needed), a Reset ROM button,
    and Prev/Next page navigation for :class:`MemoryWatchWindow`.
    """

    def __init__(
        self,
        parent: tk.Tk,
        watch_window: MemoryWatchWindow,
        reset_callback: callable | None = None,
    ) -> None:
        super().__init__(parent)
        self.watch_window = watch_window
        self.reset_callback = reset_callback
        self.transient(parent)
        self.title("Watch Controls")
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._closed = False

        tk.Label(self, text="Address Range", font=("Arial", 9, "bold")).grid(
            row=0, column=0, columnspan=4, pady=(4, 2),
        )

        tk.Label(self, text="Start:").grid(row=1, column=0, sticky="e", padx=(8, 2))
        self._start_var = tk.StringVar(value=f"{watch_window.start_address:04X}")
        self._start_entry = tk.Entry(self, textvariable=self._start_var, width=10)
        self._start_entry.grid(row=1, column=1, padx=2)
        tk.Button(self, text="Apply", command=self._apply_start).grid(
            row=1, column=2, columnspan=2, padx=(4, 8), sticky="w",
        )

        tk.Label(self, text="End:").grid(row=2, column=0, sticky="e", padx=(8, 2))
        self._end_var = tk.StringVar(value=f"{watch_window.end_address:04X}")
        self._end_entry = tk.Entry(self, textvariable=self._end_var, width=10)
        self._end_entry.grid(row=2, column=1, padx=2)
        tk.Button(self, text="Apply", command=self._apply_end).grid(
            row=2, column=2, columnspan=2, padx=(4, 8), sticky="w",
        )

        tk.Button(self, text="Reset ROM", command=self._on_reset).grid(
            row=3, column=0, columnspan=4, pady=(6, 2), padx=8, sticky="ew",
        )

        tk.Label(self, text="Navigation", font=("Arial", 8)).grid(
            row=4, column=0, columnspan=4, pady=(8, 2),
        )
        btn_prev = tk.Button(self, text="Prev", command=self._prev_page, width=8)
        btn_prev.grid(row=5, column=0, columnspan=2, padx=4, pady=2, sticky="ew")
        btn_next = tk.Button(self, text="Next", command=self._next_page, width=8)
        btn_next.grid(row=5, column=2, columnspan=2, padx=4, pady=2, sticky="ew")

        screen_w, screen_h = get_screen_size()
        panel_w = 200
        panel_x = max(0, screen_w - panel_w - 20)
        self.geometry(f"+{panel_x}+{min(screen_h - 200, 200)}")

        self._start_entry.bind("<Return>", lambda e: self._apply_start())
        self._end_entry.bind("<Return>", lambda e: self._apply_end())

    def _apply_start(self) -> None:
        raw = self._start_var.get().strip()
        try:
            start = int(raw, 16)
        except ValueError:
            messagebox.showerror("Invalid address", f"'{raw}' is not valid hex.", parent=self)
            return
        self.watch_window.set_range(start, self.watch_window.end_address)

    def _apply_end(self) -> None:
        raw = self._end_var.get().strip()
        try:
            end = int(raw, 16)
        except ValueError:
            messagebox.showerror("Invalid address", f"'{raw}' is not valid hex.", parent=self)
            return
        self.watch_window.set_range(self.watch_window.start_address, end)

    def _on_reset(self) -> None:
        if self.reset_callback is not None:
            self.reset_callback()
        if self.watch_window.visible:
            self.watch_window._page = 0

    def _prev_page(self) -> None:
        if self.watch_window.visible:
            self.watch_window._page = max(0, self.watch_window._page - 1)

    def _next_page(self) -> None:
        if self.watch_window.visible:
            self.watch_window._page += 1

    def _on_close(self) -> None:
        self._closed = True
        try:
            self.destroy()
        except tk.TclError:
            pass

    @property
    def closed(self) -> bool:
        return self._closed

    def update_entries(self, start: int, end: int) -> None:
        self._start_var.set(f"{start:04X}")
        self._end_var.set(f"{end:04X}")

    def update(self) -> None:
        if self._closed:
            return
        self.update_idletasks()
        super().update()

def load_controls() -> dict[str, dict[str, str]]:
    controls = json.loads(json.dumps(DEFAULT_CONTROLS))
    if CONTROLS_PATH.is_file():
        try:
            saved = json.loads(CONTROLS_PATH.read_text(encoding="utf-8"))
            controls["keyboard"].update(saved.get("keyboard", {}))
            controls["gamepad"].update(saved.get("gamepad", {}))
        except (OSError, ValueError):
            pass
    return controls


class ControlsDialog:
    def __init__(self, parent: tk.Tk, controls: dict[str, dict[str, str]]) -> None:
        self.controls = controls
        self.window = tk.Toplevel(parent)
        self.window.title("Configure controls")
        self.window.resizable(False, False)
        self.pending_action: str | None = None
        self.keyboard_labels: dict[str, tk.StringVar] = {}
        self.gamepad_labels: dict[str, tk.StringVar] = {}
        self.joysticks = self._open_joysticks()
        self.controllers = self._open_controllers()
        self.gamepad_status = tk.StringVar()

        tk.Label(self.window, text="Configure controls", font=("Segoe UI", 14, "bold")).grid(
            row=0, column=0, columnspan=4, padx=14, pady=(14, 10), sticky="w"
        )
        tk.Label(self.window, text="Keyboard", font=("Segoe UI", 10, "bold")).grid(row=1, column=1, sticky="w")
        tk.Label(self.window, text="Gamepad", font=("Segoe UI", 10, "bold")).grid(row=1, column=3, sticky="w")
        for row, action in enumerate(ACTION_NAMES, start=2):
            tk.Label(self.window, text=action, width=9, anchor="w").grid(row=row, column=0, padx=(14, 4), pady=3)
            keyboard = tk.StringVar(value=self.controls["keyboard"].get(action, ""))
            self.keyboard_labels[action] = keyboard
            tk.Label(self.window, textvariable=keyboard, width=12, relief=tk.SUNKEN, anchor="w").grid(row=row, column=1, pady=3)
            tk.Button(self.window, text="Set key", command=lambda name=action: self._capture_key(name)).grid(row=row, column=2, padx=4)
            gamepad = tk.StringVar(value=self.controls["gamepad"].get(action, ""))
            self.gamepad_labels[action] = gamepad
            tk.Label(self.window, textvariable=gamepad, width=12, relief=tk.SUNKEN, anchor="w").grid(row=row, column=3, pady=3)
            tk.Button(self.window, text="Detect", command=lambda name=action: self._capture_gamepad(name)).grid(row=row, column=4, padx=(4, 14))

        devices = list_gamepads()
        device_text = "Detected: " + (", ".join(devices) if devices else "no SDL gamepad found")
        self.gamepad_status.set(device_text)
        tk.Label(self.window, textvariable=self.gamepad_status, fg="gray", wraplength=600, justify=tk.LEFT).grid(
            row=10, column=0, columnspan=5, padx=14, pady=(8, 4), sticky="w"
        )
        tk.Button(self.window, text="Save", width=12, command=self._save).grid(row=11, column=0, columnspan=5, pady=(4, 14))

    @staticmethod
    def _open_joysticks() -> list[object]:
        joysticks = []
        for index in range(max(0, sdl2.SDL_NumJoysticks())):
            joystick = sdl2.SDL_JoystickOpen(index)
            if joystick:
                joysticks.append(joystick)
        return joysticks

    @staticmethod
    def _open_controllers() -> list[object]:
        controllers = []
        for index in range(max(0, sdl2.SDL_NumJoysticks())):
            if sdl2.SDL_IsGameController(index):
                controller = sdl2.SDL_GameControllerOpen(index)
                if controller:
                    controllers.append(controller)
        return controllers

    def _capture_key(self, action: str) -> None:
        self.pending_action = action
        self.window.title(f"Press a key for {action}...")
        self.window.bind("<KeyPress>", self._on_key)
        self.window.focus_force()

    def _on_key(self, event: tk.Event) -> str:
        if self.pending_action is not None:
            debug_input(f"CAPTURE TK KEY action={self.pending_action} key={event.keysym.lower()}")
            self.keyboard_labels[self.pending_action].set(event.keysym.lower())
            self.pending_action = None
            self.window.title("Configure controls")
            self.window.unbind("<KeyPress>")
        return "break"

    def _capture_gamepad(self, action: str) -> None:
        initialize_sdl_input()
        devices = list_gamepads()
        if not devices:
            self.gamepad_status.set("No SDL gamepad detected. Reconnect it and press Detect again.")
            debug_input(f"NO GAMEPAD FOUND while trying to bind {action}")
            return
        sdl2.SDL_FlushEvents(sdl2.SDL_FIRSTEVENT, sdl2.SDL_LASTEVENT)
        self.pending_action = action
        debug_input(f"LISTENING FOR KEY TO BIND {action.upper()} : {', '.join(devices)}")
        self.window.title(f"Press a gamepad button for {action}...")
        self.window.after(20, self._poll_gamepad_capture)

    def _finish_gamepad_capture(self, action: str, token: str, event_name: str) -> None:
        self.gamepad_labels[action].set(token)
        debug_input(f"GAMEPAD#{action} HAS BEEN PRESSED, SETTING THE KEY: {event_name} -> {token}")
        self.pending_action = None
        self.window.title("Configure controls")

    def _poll_gamepad_capture(self) -> None:
        if self.pending_action is None:
            return
        event = sdl2.SDL_Event()
        while sdl2.SDL_PollEvent(event):
            debug_sdl_event(event, "CAPTURE")
            if event.type == sdl2.SDL_JOYBUTTONDOWN:
                action = self.pending_action
                self._finish_gamepad_capture(action, f"button:{event.jbutton.button}", "JOYBUTTONDOWN")
                return
            if event.type == sdl2.SDL_JOYHATMOTION:
                value = int(event.jhat.value)
                if value:
                    action = self.pending_action
                    self._finish_gamepad_capture(action, f"hat:{event.jhat.hat}:{value}", "JOYHATMOTION")
                    return
            if event.type == sdl2.SDL_CONTROLLERBUTTONDOWN:
                action = self.pending_action
                self._finish_gamepad_capture(action, f"controller:{event.cbutton.button}", "CONTROLLERBUTTONDOWN")
                return
            if event.type == sdl2.SDL_CONTROLLERAXISMOTION and abs(int(event.caxis.value)) > 16000:
                direction = "positive" if event.caxis.value > 0 else "negative"
                action = self.pending_action
                self._finish_gamepad_capture(action, f"controller_axis:{event.caxis.axis}:{direction}", "CONTROLLERAXISMOTION")
                return
            if event.type == sdl2.SDL_JOYAXISMOTION and abs(int(event.jaxis.value)) > 16000:
                direction = "positive" if event.jaxis.value > 0 else "negative"
                action = self.pending_action
                self._finish_gamepad_capture(action, f"axis:{event.jaxis.axis}:{direction}", "JOYAXISMOTION")
                return
        self.window.after(20, self._poll_gamepad_capture)

    def _save(self) -> None:
        self.controls["keyboard"] = {action: value.get() for action, value in self.keyboard_labels.items()}
        self.controls["gamepad"] = {action: value.get() for action, value in self.gamepad_labels.items() if value.get()}
        CONTROLS_PATH.write_text(json.dumps(self.controls, indent=2) + "\n", encoding="utf-8")
        for controller in self.controllers:
            sdl2.SDL_GameControllerClose(controller)
        for joystick in self.joysticks:
            sdl2.SDL_JoystickClose(joystick)
        self.window.destroy()


def generate_input_events(
    actions: list[int],
    action_freq: int,
    noop_action: int = DEFAULT_NOOP_ACTION,
    press_length: int | None = None,
) -> list[dict[str, Any]]:
    """Compute absolute-frame offsets for every input event in an action sequence.

    Each button action is held for *press_length* frames (default
    :data:`DEFAULT_ACTION_PRESS_FRAMES`, matching the environment's
    ``press_step``) then released, and the full cycle spans *action_freq* frames.
    Noop actions (equal to *noop_action* or absent from :data:`ACTION_EVENTS`)
    produce no events.

    The result is a list of ``{"frame", "event", "action"}`` dicts suitable for
    JSON serialisation and consumption by :func:`replay_frame_by_frame`.
    """
    if press_length is None:
        press_length = DEFAULT_ACTION_PRESS_FRAMES
    press_length = max(1, min(press_length, action_freq - 1))

    events: list[dict[str, Any]] = []
    for step, action in enumerate(actions):
        if action == noop_action or action not in ACTION_EVENTS:
            continue
        frame_base = step * action_freq
        press_event, release_event = ACTION_EVENTS[action]
        events.append({"frame": frame_base, "event": int(press_event), "action": action})
        events.append({"frame": frame_base + press_length, "event": int(release_event), "action": action})
    return events


def load_replay(path: Path | None) -> tuple[list[int], dict[str, object]]:
    if path is None:
        return [], {}
    with path.open("r", encoding="utf-8") as input_file:
        data = json.load(input_file)
    noop_action = int(data.get("noop_action", DEFAULT_NOOP_ACTION))
    action_freq = int(data.get("action_freq", ACTION_FREQ))
    entries = data.get("actions", [])
    actions = []
    for entry in entries:
        if not isinstance(entry, dict):
            actions.append(int(entry))
            continue
        # Legacy recordings kept the requested button and a separate mask flag.
        # Masked entries were replaced with the noop action during recording;
        # respect the recording's noop_action so the replay stays in sync with
        # the environment's action set even when the index differs from the
        # default.
        if entry.get("masked", False):
            actions.append(noop_action)
        else:
            actions.append(int(entry["action"]))

    # Generate frame-level input events if the recording doesn't already
    # contain them (older format). This gives the replayer exact frame offsets
    # instead of reconstructing them from action indices + press_step.
    if "input_events" not in data:
        data["input_events"] = generate_input_events(actions, action_freq, noop_action)
    return actions, data


def load_actions(path: Path | None) -> list[int]:
    """Load effective actions, retained as a small compatibility helper."""
    return load_replay(path)[0]


_plugin_recording_registry: dict[int, dict[str, Any]] = {}


class _RecordingPyBoyProxy:
    """Proxy that records ``send_input`` calls while delegating everything else.

    PyBoy is a Cython ``cdef class`` whose instance attributes are read-only,
    so we cannot monkey-patch ``send_input`` on instances. Instead this proxy
    wraps the real PyBoy object, intercepts ``send_input`` calls to log
    frame-exact events, and forwards every other attribute access transparently.
    """

    def __init__(self, pyboy: PyBoy, entry: dict[str, Any]) -> None:
        object.__setattr__(self, "_pyboy", pyboy)
        object.__setattr__(self, "_entry", entry)

    def send_input(self, event: int, delay: int = 0) -> None:
        if delay == 0:
            frame = self._pyboy.frame_count
        else:
            frame = self._pyboy.frame_count + delay
        entry = self._entry
        entry["events"].append({
            "frame": int(frame - entry["frame_offset"]),
            "event": int(event),
        })
        self._pyboy.send_input(event, delay)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._pyboy, name)


def record_input_with_plugin(
    pyboy: PyBoy,
    recording_path: Path,
    action_freq: int = 24,
    noop_action: int = DEFAULT_NOOP_ACTION,
) -> PyBoy:
    """Wrap *pyboy* with a proxy that records exact frame-level input events.

    This mirrors the approach used by PyBoy's built-in ``RecordReplay`` plugin:
    every ``send_input`` call is associated with the ``pyboy.frame_count`` at
    the moment it is issued, producing a ``(frame, event)`` log that is
    **independent of any assumed press-step value**. This guarantees that the
    replay can reproduce the *exact* frame-by-frame input sequence that
    occurred during training, with no timing reconstruction needed.

    Because PyBoy is a Cython ``cdef class`` (read-only attributes), we cannot
    monkey-patch ``send_input`` on the instance. Instead a
    :class:`_RecordingPyBoyProxy` is returned; the caller should replace its
    ``pyboy`` reference with the returned proxy.

    The recording is stored in a module-level registry keyed by
    ``id(proxy)`` so no attributes are set on the PyBoy object itself.

    Args:
        pyboy: The PyBoy instance running the game.
        recording_path: Path to write/update the recording JSON.
        action_freq: Frames per action (from the environment config).
        noop_action: The action index used for no-ops.

    Returns:
        A proxy wrapping *pyboy* whose ``send_input`` calls are recorded.
    """
    entry: dict[str, Any] = {
        "events": [],
        "frame_offset": pyboy.frame_count,
        "recording_path": recording_path,
        "action_freq": action_freq,
        "noop_action": noop_action,
    }
    proxy = _RecordingPyBoyProxy(pyboy, entry)
    _plugin_recording_registry[id(proxy)] = entry
    return proxy


def finalize_input_recording(
    pyboy: PyBoy,
    recording_path: Path,
    actions: list[int],
    action_freq: int = 24,
    noop_action: int = DEFAULT_NOOP_ACTION,
    rom_path: Path | None = None,
    init_state_path: Path | None = None,
) -> None:
    """Stop recording and write the captured frame-level inputs to JSON.

    Must be called after :func:`record_input_with_plugin` has been active
    during training. Writes a recording JSON with both ``actions`` (step-level
    for compatibility) and ``input_events`` (frame-level, exact).
    """
    pid = id(pyboy)
    entry = _plugin_recording_registry.pop(pid, None)
    recorded: list[dict[str, Any]] = entry["events"] if entry else []

    # Derive step-level actions from frame-level events
    if not recorded:
        input_events: list[dict[str, Any]] = []
    else:
        last_frame = max(ev["frame"] for ev in recorded)
        total_frames = last_frame + 1
        num_steps = total_frames // action_freq
        if total_frames % action_freq:
            num_steps += 1

        # Map each frame to its events
        event_map: dict[int, list[int]] = {}
        for ev in recorded:
            frame = int(ev["frame"])
            event_map.setdefault(frame, []).append(int(ev["event"]))

        # Reconstruct actions: an action is determined by the press event at
        # the start of its cycle (frame = step * action_freq)
        action_events: dict[int, int] = {}
        release_events: dict[int, int] = {}
        for action_idx in range(8):
            press, release = ACTION_EVENTS[action_idx]
            action_events[int(press)] = action_idx
            release_events[int(release)] = action_idx

        actions: list[int] = []
        input_events = []
        for step in range(num_steps):
            step_start = step * action_freq
            cycle_events = event_map.get(step_start, [])
            action_found = False
            for ev_code in cycle_events:
                if ev_code in action_events:
                    actions.append(action_events[ev_code])
                    action_found = True
                    break
            if not action_found:
                actions.append(noop_action)

        input_events = [{"frame": ev["frame"], "event": ev["event"]} for ev in recorded]

    data: dict[str, Any] = {
        "action_freq": action_freq,
        "noop_action": noop_action,
        "total_actions": len(actions),
        "actions": actions,
        "input_events": input_events,
        "source": "plugin",
    }
    if rom_path:
        data["rom"] = str(rom_path)
    if init_state_path:
        data["init_state"] = str(init_state_path)

    recording_path.parent.mkdir(parents=True, exist_ok=True)
    with recording_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def play_input_with_plugin(
    pyboy: PyBoy,
    recording_path: Path,
    *,
    render: bool = True,
) -> int:
    """Replay a recording using exact frame-level input events.

    Unlike :func:`replay_action`, this does NOT assume a fixed press-step.
    Instead it reads the ``input_events`` from the recording JSON and sends
    each event at its exact absolute frame offset, calling ``tick(1)`` per
    frame. This is the closest analog to PyBoy's own ``RecordReplay`` plugin
    playback.

    Args:
        pyboy: The PyBoy instance (should be headless for best determinism).
        recording_path: Path to the recording JSON with ``input_events``.
        render: Whether to render each frame.

    Returns:
        Total number of frames replayed.
    """
    _, replay_data = load_replay(recording_path)
    input_events = replay_data.get("input_events", [])
    if not input_events:
        raise ValueError(f"Recording {recording_path} has no input_events")

    action_freq = int(replay_data.get("action_freq", ACTION_FREQ))
    total_frames = len(replay_data.get("actions", [])) * action_freq

    return replay_frame_by_frame(pyboy, input_events, total_frames, render=render)


def resolve_recording_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path if path.is_file() else None


def _prime_emulator(
    pyboy: PyBoy,
    state_path: Path,
    actions: list[int],
    action_freq: int,
    noop_action: int,
    *,
    num_actions: int = 8,
) -> None:
    """Initialize PyBoy internal state for deterministic replay.

    A freshly-created PyBoy instance does not fully reset its internal
    buffers (input queues, PPU caches, etc.) when ``load_state`` is called.
    Running a short replay first "warms up" these buffers so that
    subsequent frame-exact replays via :func:`replay_frame_by_frame`
    produce correct, deterministic results.
    """
    with state_path.open("rb") as state_file:
        pyboy.load_state(state_file)
    for pa in actions[:num_actions]:
        replay_action(pyboy, pa, action_freq, verbose=False, render=False, noop_action=noop_action)
    with state_path.open("rb") as state_file:
        pyboy.load_state(state_file)


def replay_action(
    pyboy: PyBoy,
    action: int,
    action_freq: int,
    *,
    verbose: bool = True,
    render: bool = True,
    noop_action: int = DEFAULT_NOOP_ACTION,
) -> None:
    """Advance one action with the same press/hold timing as RedGymEnv.run_action_on_emulator.

    The button is held for ``press_length`` frames, released, then idles for
    ``idle_frames`` before a final rendered tick, so the total number of ticks
    always equals *action_freq*. The next action is replayed after.

    Args:
        pyboy: The PyBoy emulator instance.
        action: The action index (matches ``ACTION_EVENTS`` and ``run_action_on_emulator``).
        action_freq: Frames per action (from the recording's ``action_freq``).
        verbose: When ``True``, print the action being replayed.
        render: Whether to render frames during the non-final ticks. The final
            tick always renders (``True``) to match ``run_action_on_emulator``
            which calls ``tick(1, True)`` as the last step regardless of mode.
            For deterministic headless replay, pass ``render=False`` so PyBoy
            skips SDL event processing and rendering overhead.
        noop_action: The action index used for no-ops in the recording. When
            *action* equals *noop_action*, no input events are sent and the
            frame timing is preserved, keeping the replay in sync. This is
            critical because SELECT (index 7) shares the old NOOP slot in
            legacy recordings where ``noop_action`` was 7; the noop check
            prevents SELECT events from being sent for what was actually a
            no-op during the original recording.

    Note:
        SELECT (action 7) is masked via the environment's ``_should_mask``
        during training. When ``disable_select`` is True, masked actions are
        replaced with the noop action before recording, so SELECT events never
        appear in the recording for masked stages. For unmasked stages (e.g.
        "menu"), SELECT events are recorded and replayed exactly.
    """
    events = ACTION_EVENTS.get(action)
    if action == noop_action:
        events = None
    press_length, idle_frames, release_tick = compute_action_timing(action_freq)

    if verbose:
        print(f"REPLAY ACTION {action} ({ACTION_NAMES[action]}) with freq={action_freq} events={events}")
    if events is not None:
        pyboy.send_input(events[0])
    pyboy.tick(press_length, render)
    if events is not None:
        pyboy.send_input(events[1])
    pyboy.tick(idle_frames, render)
    pyboy.tick(release_tick, True)


def replay_frame_by_frame(
    pyboy: PyBoy,
    input_events: list[dict[str, Any]],
    total_frames: int,
    *,
    verbose: bool = False,
    render: bool = True,
) -> int:
    """Replay frame-level input events with exact frame granularity.

    Iterates one frame at a time, sending every recorded input event at its
    absolute frame offset. This guarantees the same input timing as the
    original recording regardless of press-length assumptions, making the
    replay deterministic.

    Args:
        pyboy: The PyBoy emulator instance.
        input_events: List of ``{"frame", "event"}`` dicts with absolute frame offsets.
        total_frames: Total number of frames to advance.
        verbose: When ``True``, print each frame and event code.
        render: When ``False``, use ``tick(1, False)`` to skip SDL event
            processing for deterministic headless replay. The final frame
            still renders (``True``) to match ``run_action_on_emulator``.

    Returns:
        The total number of frames replayed.
    """
    event_map: dict[int, list[int]] = {}
    for ev in input_events:
        frame = int(ev["frame"])
        event_code = int(ev["event"])
        event_map.setdefault(frame, []).append(event_code)

    for frame in range(total_frames):
        for event_code in event_map.get(frame, []):
            if verbose:
                print(f"FRAME {frame}: input {event_code}")
            pyboy.send_input(event_code)
        pyboy.tick(1, render if frame < total_frames - 1 else True)
        if render and frame % 600 == 0 and frame > 0:
            print(f"  ... replayed {frame}/{total_frames} frames")
        if render:
            cv2.waitKey(1)

    return total_frames


def verify_recording(
    recording_path: Path,
    rom_path: Path | None = None,
    *,
    dump_states: bool = False,
) -> dict[str, Any]:
    """Replay a recording headlessly and return key state values for determinism checks.

    Loads the recording's ``init_state``, then replays every recorded action
    using the exact same timing as ``RedGymEnv.run_action_on_emulator`` (via
    :func:`replay_action`). The returned dictionary captures key memory values
    that can be compared across runs — if the same inputs produce different
    values, the timing or starting state is not in sync with the recorder.

    Args:
        recording_path: Path to the inputs JSON produced by the trainer.
        rom_path: Path to the ROM. If ``None``, resolved from the recording's
            ``rom`` field or :data:`DEFAULT_ROM`.
        dump_states: When ``True``, also return per-step snapshots of key
            memory addresses for fine-grained comparison.
    """
    actions, replay_data = load_replay(recording_path)
    action_freq = int(replay_data.get("action_freq", ACTION_FREQ))
    noop_action = int(replay_data.get("noop_action", DEFAULT_NOOP_ACTION))
    if action_freq < 9:
        raise ValueError(f"Replay action frequency must be at least 9, got {action_freq}")

    state_path = resolve_recording_path(replay_data.get("init_state"))
    if state_path is None:
        raise FileNotFoundError(
            f"Recording {recording_path} has no usable init_state"
        )

    if rom_path is None:
        rom_path = resolve_recording_path(replay_data.get("rom"))
        if rom_path is None:
            rom_path = DEFAULT_ROM

    pyboy = PyBoy(str(rom_path), window="null", sound=False)
    _prime_emulator(pyboy, state_path, actions, action_freq, noop_action)
    try:
        with state_path.open("rb") as state_file:
            pyboy.load_state(state_file)

        snapshots: list[dict[str, Any]] = []
        for index, action in enumerate(actions):
            replay_action(pyboy, action, action_freq, verbose=False, render=False, noop_action=noop_action)
            if dump_states:
                memory = pyboy.memory
                snapshots.append({
                    "step": index,
                    "x": int(memory[X_POS_ADDRESS]),
                    "y": int(memory[Y_POS_ADDRESS]),
                    "map": int(memory[MAP_N_ADDRESS]),
                    "badges": int(memory[BADGE_COUNT_ADDRESS]),
                    "party": int(memory[0xD163]),
                    "battle": int(memory[0xD057]),
                })

        memory = pyboy.memory
        result: dict[str, Any] = {
            "total_actions": len(actions),
            "action_freq": action_freq,
            "total_frames": len(actions) * action_freq,
            "final_state": {
                "x": int(memory[X_POS_ADDRESS]),
                "y": int(memory[Y_POS_ADDRESS]),
                "map": int(memory[MAP_N_ADDRESS]),
                "badges": int(memory[BADGE_COUNT_ADDRESS]),
                "party": int(memory[0xD163]),
                "battle": int(memory[0xD057]),
            },
        }
        if dump_states:
            result["snapshots"] = snapshots
        return result
    finally:
        pyboy.stop()


def verify_recording_frame_by_frame(
    recording_path: Path,
    rom_path: Path | None = None,
    *,
    dump_states: bool = False,
) -> dict[str, Any]:
    """Replay a recording in headless mode for deterministic verification.

    Uses :func:`replay_action` with ``render=False`` and ``window="null"`` —
    no SDL event processing at all. This eliminates any chance of SDL event
    interference and should produce identical results to the original training
    run that loaded the same ``init_state`` with ``headless=True``.

    Args:
        recording_path: Path to the inputs JSON produced by the trainer.
        rom_path: Optional path to the ROM. If ``None``, resolved from the
            recording's ``rom`` field or :data:`DEFAULT_ROM`.
        dump_states: When ``True``, return per-frame snapshots of key memory
            addresses for fine-grained comparison.
    """
    actions, replay_data = load_replay(recording_path)
    action_freq = int(replay_data.get("action_freq", ACTION_FREQ))
    noop_action = int(replay_data.get("noop_action", DEFAULT_NOOP_ACTION))
    total_frames = len(actions) * action_freq
    if action_freq < 9:
        raise ValueError(f"Replay action frequency must be at least 9, got {action_freq}")

    state_path = resolve_recording_path(replay_data.get("init_state"))
    if state_path is None:
        raise FileNotFoundError(f"Recording {recording_path} has no usable init_state")

    if rom_path is None:
        rom_path = resolve_recording_path(replay_data.get("rom"))
        if rom_path is None:
            rom_path = DEFAULT_ROM

    pyboy = PyBoy(str(rom_path), window="null", sound=False)
    pyboy.set_emulation_speed(1.0)
    _prime_emulator(pyboy, state_path, actions, action_freq, noop_action)
    try:
        with state_path.open("rb") as state_file:
            pyboy.load_state(state_file)

        if dump_states:
            snapshots: list[dict[str, Any]] = []
            for index, action in enumerate(actions):
                replay_action(pyboy, action, action_freq, verbose=False, render=False, noop_action=noop_action)
                memory = pyboy.memory
                snapshots.append({
                    "step": index,
                    "x": int(memory[X_POS_ADDRESS]),
                    "y": int(memory[Y_POS_ADDRESS]),
                    "map": int(memory[MAP_N_ADDRESS]),
                    "badges": int(memory[BADGE_COUNT_ADDRESS]),
                    "party": int(memory[0xD163]),
                    "battle": int(memory[0xD057]),
                })
        else:
            for action in actions:
                replay_action(pyboy, action, action_freq, verbose=False, render=False, noop_action=noop_action)
        memory = pyboy.memory
        result: dict[str, Any] = {
            "total_actions": len(actions),
            "action_freq": action_freq,
            "total_frames": total_frames,
            "final_state": {
                "x": int(memory[X_POS_ADDRESS]),
                "y": int(memory[Y_POS_ADDRESS]),
                "map": int(memory[MAP_N_ADDRESS]),
                "badges": int(memory[BADGE_COUNT_ADDRESS]),
                "party": int(memory[0xD163]),
                "battle": int(memory[0xD057]),
            },
        }
        if dump_states:
            result["snapshots"] = snapshots
        return result
    finally:
        pyboy.stop()


class InputController:
    def __init__(self, pyboy: PyBoy, controls: dict[str, dict[str, str]]) -> None:
        self.pyboy = pyboy
        self.controls = controls
        self.active: set[str] = set()
        self.quit_requested = False
        self.paused = False
        self.emulation_speed = 1.0
        self.joysticks = []
        self.controllers = []
        initialize_sdl_input()
        for index in range(max(0, sdl2.SDL_NumJoysticks())):
            joystick = sdl2.SDL_JoystickOpen(index)
            if joystick:
                self.joysticks.append(joystick)
            if sdl2.SDL_IsGameController(index):
                controller = sdl2.SDL_GameControllerOpen(index)
                if controller:
                    self.controllers.append(controller)

    def _handle_special_action(self, action: int, pressed: bool) -> None:
        if action not in (8, 9, 10):
            return
        if not pressed:
            return

        name = ACTION_NAMES[action]
        if name == "Pause":
            self.paused = not self.paused
            self.pyboy.set_emulation_speed(0.0 if self.paused else self.emulation_speed)
            return

        if name == "SpeedUp":
            self.emulation_speed = min(8.0, max(0.5, self.emulation_speed * 2.0))
        elif name == "SpeedDown":
            self.emulation_speed = max(0.5, self.emulation_speed / 2.0)

        self.pyboy.set_emulation_speed(0.0 if self.paused else self.emulation_speed)

    @staticmethod
    def _normalize_token(token: str) -> str:
        token = token.lower()
        if token.startswith("controller:"):
            return "button:" + token.split(":", 1)[1]
        return token

    def _action_for_token(self, token: str) -> int | None:
        normalized_token = self._normalize_token(token)
        for index, action in enumerate(ACTION_NAMES):
            if self.controls["keyboard"].get(action, "").lower() == token:
                return index
            configured = self.controls["gamepad"].get(action, "")
            if self._normalize_token(configured) == normalized_token:
                return index
        return None

    def request_quit(self) -> None:
        self.quit_requested = True

    def _set_token(self, token: str, pressed: bool) -> None:
        action = self._action_for_token(token)
        debug_input(f"MAP token={token} pressed={pressed} action={ACTION_NAMES[action] if action is not None else 'UNBOUND'}")
        if action is None:
            return
        if action in (8, 9, 10):
            self._handle_special_action(action, pressed)
            return
        if pressed and token not in self.active:
            self.pyboy.send_input(ACTION_EVENTS[action][0])
            self.active.add(token)
        elif not pressed and token in self.active:
            self.pyboy.send_input(ACTION_EVENTS[action][1])
            self.active.remove(token)

    def poll(self) -> None:
        event = sdl2.SDL_Event()
        while sdl2.SDL_PollEvent(event):
            debug_sdl_event(event, "PLAY")
            if event.type == sdl2.SDL_QUIT:
                self.quit_requested = True
            elif event.type == sdl2.SDL_KEYDOWN and not event.key.repeat:
                name = sdl2.SDL_GetKeyName(event.key.keysym.sym).decode("utf-8").lower()
                self._set_token(name, True)
            elif event.type == sdl2.SDL_KEYUP:
                name = sdl2.SDL_GetKeyName(event.key.keysym.sym).decode("utf-8").lower()
                self._set_token(name, False)
            elif event.type == sdl2.SDL_JOYBUTTONDOWN:
                self._set_token(f"button:{event.jbutton.button}", True)
            elif event.type == sdl2.SDL_JOYBUTTONUP:
                self._set_token(f"button:{event.jbutton.button}", False)
            elif event.type == sdl2.SDL_CONTROLLERBUTTONDOWN:
                self._set_token(f"controller:{event.cbutton.button}", True)
            elif event.type == sdl2.SDL_CONTROLLERBUTTONUP:
                self._set_token(f"controller:{event.cbutton.button}", False)
            elif event.type == sdl2.SDL_CONTROLLERAXISMOTION:
                value = int(event.caxis.value)
                self._set_token(f"controller_axis:{event.caxis.axis}:positive", value > 16000)
                self._set_token(f"controller_axis:{event.caxis.axis}:negative", value < -16000)
            elif event.type == sdl2.SDL_JOYAXISMOTION:
                value = int(event.jaxis.value)
                self._set_token(f"axis:{event.jaxis.axis}:positive", value > 16000)
                self._set_token(f"axis:{event.jaxis.axis}:negative", value < -16000)
            elif event.type == sdl2.SDL_JOYHATMOTION:
                prefix = f"hat:{event.jhat.hat}:"
                for value in (1, 2, 4, 8):
                    self._set_token(prefix + str(value), int(event.jhat.value) & value != 0)

    def close(self) -> None:
        for joystick in self.joysticks:
            sdl2.SDL_JoystickClose(joystick)
        for controller in self.controllers:
            sdl2.SDL_GameControllerClose(controller)
        self.joysticks.clear()
        self.controllers.clear()


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
    watch_snapshot: dict[int, dict[str, Any]] | None = None,
) -> tuple[int, int, int, int] | None:
    """Draw the info-only inspector with split party, trainer, bag, stats, and memory-watch sections.

    Returns the (x, y, w, h) rectangle of the "Show more" button when present,
    or None when the button is not rendered.
    """
    memory = pyboy.memory
    panel_data = read_panel_data(memory)
    x_pos = panel_data["x"]
    y_pos = panel_data["y"]
    map_n = panel_data["map_id"]
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
    # Temporarily disabled until the map overlay can be toggled cleanly.
    # draw_world_info(panel, 15, y, panel_data)
    # y += 50
    cv2.putText(panel, f"Badges: {badges}/8", (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)
    y += 22

    # Temporarily disabled until the map overlay can be toggled cleanly.
    # gh, gw = GLOBAL_MAP_SHAPE
    # if map_base is not None:
    #     map_img = map_base.copy()
    #     gy, gx = local_to_global(y_pos, x_pos, map_n)
    #     gx = min(max(gx, 0), gw - 1)
    #     gy = min(max(gy, 0), gh - 1)
    #     mx = int(gx * MAP_DISPLAY_W / gw)
    #     my = int(gy * MAP_DISPLAY_H / gh)
    #     cv2.circle(map_img, (mx, my), 5, (0, 0, 0), -1)
    #     cv2.circle(map_img, (mx, my), 5, (0, 0, 255), 1)
    #     cv2.putText(map_img, "you", (mx + 7, my + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)
    # else:
    #     map_img = np.full((MAP_DISPLAY_H, MAP_DISPLAY_W, 3), 26, dtype=np.uint8)
    #     cv2.putText(map_img, "map image missing", (8, MAP_DISPLAY_H // 2),
    #                 cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)
    # panel[MAP_ORIGIN_Y:MAP_ORIGIN_Y + MAP_DISPLAY_H, MAP_ORIGIN_X:MAP_ORIGIN_X + MAP_DISPLAY_W] = map_img

    rx = LEFT_PANEL_W + 16
    ry = 24
    draw_party_panel(panel, rx, ry, RIGHT_PANEL_W - 32, 170, panel_data.get("party"))
    draw_trainer_panel(panel, rx, 200, RIGHT_PANEL_W - 32, panel_data.get("trainer"))
    draw_bag_panel(panel, rx, 240, RIGHT_PANEL_W - 32, panel_data.get("bag"))
    draw_stats_panel(panel, rx, 300, RIGHT_PANEL_W - 32, {
        "badges": panel_data.get("badges", badges),
        "events": "n/a",
        "steps": frame_count,
        "hp": "n/a",
        "env": "live",
    })
    button_rect: tuple[int, int, int, int] | None = None
    if watch_snapshot:
        button_rect = draw_memory_watch_panel(panel, 15, 280, 260, watch_snapshot, title="Addr watch")

    cv2.putText(
        panel,
        "Q/Esc: quit | M: toggle watch | R: set range | Reset: via control panel | Show more: full watch | Arrows/A/S/Start: move & buttons | +/-: speed | P: pause",
        (15, INSPECTOR_H - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (120, 120, 120), 1,
    )

    cv2.namedWindow("Pokemon Red Inspector", cv2.WINDOW_NORMAL)
    cv2.imshow("Pokemon Red Inspector", panel)
    if "Pokemon Red Inspector" not in positioned_windows:
        screen_w, _ = get_screen_size()
        win_x = max(0, screen_w - INSPECTOR_W - 20)
        cv2.moveWindow("Pokemon Red Inspector", win_x, 40)
        positioned_windows.add("Pokemon Red Inspector")

    return button_rect


def _set_watch_range(
    parent: tk.Tk,
    watch_window: MemoryWatchWindow,
    control_panel: WatchControlPanel | None = None,
) -> None:
    """Prompt the user for a new hex address range and apply it to *watch_window*."""
    start_hex = simpledialog.askstring(
        "Watch Range", "Start address (hex, e.g. CC06):",
        initialvalue=f"{watch_window.start_address:04X}", parent=parent,
    )
    if not start_hex:
        return
    end_hex = simpledialog.askstring(
        "Watch Range", "End address (hex, e.g. D362):",
        initialvalue=f"{watch_window.end_address:04X}", parent=parent,
    )
    if not end_hex:
        return
    try:
        start = int(start_hex, 16)
        end = int(end_hex, 16)
    except ValueError:
        messagebox.showerror("Invalid range", "Please enter valid hexadecimal addresses.", parent=parent)
        return
    watch_window.set_range(start, end)
    if control_panel is not None:
        control_panel.update_entries(start, end)
    if watch_window.visible:
        watch_window.show()


def run_player(
    rom_path: Path,
    state_path: Path | None,
    replay_path: Path | None,
    controls: dict[str, dict[str, str]] | None = None,
    replay_speed: str = "auto",
    *,
    deterministic: bool = False,
    use_plugin_replay: bool = False,
) -> None:
    actions, replay_data = load_replay(replay_path)
    replay_action_freq = int(replay_data.get("action_freq", ACTION_FREQ))
    replay_noop_action = int(replay_data.get("noop_action", DEFAULT_NOOP_ACTION))
    if replay_action_freq < 9:
        raise ValueError(f"Replay action frequency must be at least 9, got {replay_action_freq}")
    if state_path is None:
        state_path = resolve_recording_path(replay_data.get("init_state"))

    replay_speed_value = resolve_replay_speed(replay_speed)
    window_mode = "null" if deterministic else "SDL2"
    sound_enabled = not deterministic
    render_during_replay = not deterministic
    total_replay_frames = len(actions) * replay_action_freq

    os.environ.setdefault("SDL_VIDEO_WINDOW_POS", "0,0")
    pyboy = PyBoy(str(rom_path), window=window_mode, sound=sound_enabled)
    pyboy.set_emulation_speed(replay_speed_value)
    if not deterministic:
        input_controller = InputController(pyboy, controls or load_controls())
    else:
        input_controller = None

    def close_emulator() -> None:
        if input_controller is not None:
            input_controller.request_quit()
        try:
            pyboy.stop()
        except OSError:
            pass

    initial_state = io.BytesIO()
    pyboy.save_state(initial_state)
    initial_state.seek(0)

    def reset_rom() -> None:
        initial_state.seek(0)
        pyboy.load_state(initial_state)
        initial_state.seek(0)
        if watch_window.visible:
            watch_window._page = 0
        messagebox.showinfo("Reset ROM", "ROM has been reset to initial state.", parent=runtime_menu.root)

    runtime_menu = RuntimeMenu(pyboy, close_callback=close_emulator, reset_callback=reset_rom)
    watch_addresses = [
        *address_range(MAP_N_ADDRESS, MAP_N_ADDRESS),
        *address_range(X_POS_ADDRESS, Y_POS_ADDRESS),
        *address_range(BADGE_COUNT_ADDRESS, BADGE_COUNT_ADDRESS),
        *address_range(0xCC06, 0xCC2F),
    ]
    watcher = MemoryWatchTracker(watch_addresses)
    try:
        if state_path is not None:
            with state_path.open("rb") as state_file:
                pyboy.load_state(state_file)

        pyboy.set_emulation_speed(replay_speed_value)
        if input_controller is not None:
            input_controller.emulation_speed = replay_speed_value
        map_base = _prepare_map_base(load_map_image(DEFAULT_MAP_IMAGE))

        frame_count = 0
        replay_index = 0
        replay_finished = len(actions) == 0
        show_more_state: dict[str, tuple[int, int, int, int] | None] = {"rect": None}
        watch_window = MemoryWatchWindow()
        control_panel = WatchControlPanel(runtime_menu.root, watch_window, reset_callback=reset_rom)

        def _on_inspector_click(event: int, x: int, y: int, flags: int, param: Any) -> None:
            if event != cv2.EVENT_LBUTTONDOWN:
                return
            rect = show_more_state["rect"]
            if rect is None:
                return
            bx, by, bw, bh = rect
            if bx <= x <= bx + bw and by <= y <= by + bh:
                watch_window.show()

        initial_snapshot = watcher.record(pyboy.memory)
        initial_button_rect = render_inspector(pyboy, frame_count, replay_index, len(actions), replay_finished, map_base, watch_snapshot=initial_snapshot)
        show_more_state["rect"] = initial_button_rect
        cv2.setMouseCallback("Pokemon Red Inspector", _on_inspector_click)

        # If plugin-based replay is requested, do the full frame-by-frame replay
        # in one shot before entering the interactive loop.
        if use_plugin_replay and replay_path is not None:
            print(f"Playing {len(actions)} actions via plugin-style frame-exact replay...")
            frames_replayed = play_input_with_plugin(pyboy, replay_path, render=render_during_replay)
            frame_count += frames_replayed
            replay_index = len(actions)
            replay_finished = True

        while True:
            runtime_menu.update()
            # Play back the next queued action at normal speed, one frame at a time, so the
            # audio/video stay in sync and the player can start controlling as soon as it ends.
            if replay_index < len(actions):
                action = actions[replay_index]
                replay_index += 1
                print(f"REPLAYING ACTION {action} ({ACTION_NAMES[action]}) with freq={replay_action_freq}")
                replay_action(pyboy, action, replay_action_freq, render=render_during_replay, noop_action=replay_noop_action)
                frame_count += replay_action_freq
            else:
                if deterministic:
                    pyboy.tick(1, False)
                    frame_count += 1
                else:
                    input_controller.poll()
                    if input_controller.quit_requested:
                        break
                    if not pyboy.tick(1, True):
                        input_controller.request_quit()
                        break
                    frame_count += 1

            if replay_index >= len(actions):
                replay_finished = True

            watch_snapshot = watcher.record(pyboy.memory)
            button_rect = render_inspector(pyboy, frame_count, replay_index, len(actions), replay_finished, map_base, watch_snapshot=watch_snapshot)
            show_more_state["rect"] = button_rect
            if watch_window.visible:
                watch_window.render(pyboy.memory)
            runtime_menu.update()
            control_panel.update()

            if deterministic:
                screen = np.array(pyboy.screen.ndarray[:, :, ::-1])
                cv2.imshow("Pokemon Red (Deterministic)", screen)
                if replay_finished:
                    key = cv2.waitKey(1)
                    if key in (ord("q"), 27):
                        break
                else:
                    cv2.waitKey(1)
            else:
                try:
                    inspector_visible = cv2.getWindowProperty("Pokemon Red Inspector", cv2.WND_PROP_VISIBLE) >= 1
                except cv2.error:
                    inspector_visible = False
                if not inspector_visible:
                    input_controller.request_quit()
                    break

                key = cv2.waitKeyEx(1)
                if key in (ord("q"), 27):
                    input_controller.request_quit()
                    break
                if key == ord("m"):
                    if watch_window.visible:
                        watch_window.hide()
                    else:
                        watch_window.show()
                if key == ord("r"):
                    _set_watch_range(runtime_menu.root, watch_window, control_panel)
                time.sleep(0.001)
    except OSError as error:
        print(f"PyBoy stopped while closing the SDL window: {error}")
    finally:
        runtime_menu.close_menu()
        control_panel._on_close()
        if input_controller is not None:
            input_controller.close()
        watch_window.close()
        try:
            pyboy.stop()
        except OSError as error:
            print(f"PyBoy cleanup warning: {error}")
        cv2.destroyAllWindows()


def main() -> None:
    initialize_sdl_input()
    launcher = DebugLauncher()
    launcher.root.geometry("+0+0")
    launcher.root.mainloop()


if __name__ == "__main__":
    main()



