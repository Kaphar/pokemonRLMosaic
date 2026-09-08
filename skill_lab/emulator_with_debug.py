"""Launch Pokemon Red in player mode with a live debug inspector."""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from datetime import datetime

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
    draw_menu_handler_info,
    draw_party_panel,
    draw_trainer_bag_panel,
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
DEBUG_INPUT = True
ACTION_NAMES = ["Down", "Left", "Right", "Up", "A", "B", "Start"]
DEFAULT_CONTROLS = {
    "keyboard": {
        "Down": "down", "Left": "left", "Right": "right", "Up": "up",
        "A": "z", "B": "x", "Start": "return",
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

        tk.Label(
            frame,
            text=(
                "The emulator opens in player mode at normal speed with sound, in a keyboard-"
                "or gamepad-controllable SDL2 window. After the replay finishes it keeps running so you can play "
                "from where it stopped. Close the emulator window (Escape) or press Q in the inspector "
                "to stop."
            ),
            fg="gray",
            wraplength=600,
            justify=tk.LEFT,
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 12))
        button_row = tk.Frame(frame)
        button_row.grid(row=7, column=0, columnspan=3, pady=(4, 0))
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
        run_player(rom_path, state_path, replay, self.controls)


class RuntimeMenu:
    """Native menu bar for actions that operate on the live emulator."""

    def __init__(self, pyboy: PyBoy) -> None:
        self.pyboy = pyboy
        self.closed = False
        self.root = tk.Tk()
        self.root.title("Pokemon Red Debug Controls")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        menu_bar = tk.Menu(self.root)
        file_menu = tk.Menu(menu_bar, tearoff=False)
        file_menu.add_command(label="Save State...", command=self.save_state)
        file_menu.add_command(label="Load State...", command=self.load_state)
        file_menu.add_separator()
        file_menu.add_command(label="Close Menu", command=self.close)
        menu_bar.add_cascade(label="File", menu=file_menu)
        self.root.config(menu=menu_bar)
        tk.Label(self.root, text="Use File to save or load the live emulator state.", padx=12, pady=8).pack()

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

    def update(self) -> None:
        if self.closed:
            return
        self.root.update_idletasks()
        self.root.update()

    def close(self) -> None:
        self.closed = True
        try:
            self.root.destroy()
        except tk.TclError:
            pass


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


class InputController:
    def __init__(self, pyboy: PyBoy, controls: dict[str, dict[str, str]]) -> None:
        self.pyboy = pyboy
        self.controls = controls
        self.active: set[str] = set()
        self.quit_requested = False
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

    def _set_token(self, token: str, pressed: bool) -> None:
        action = self._action_for_token(token)
        debug_input(f"MAP token={token} pressed={pressed} action={ACTION_NAMES[action] if action is not None else 'UNBOUND'}")
        if action is None:
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
) -> None:
    """Draw the info-only inspector (party + position/map). No game-screen image."""
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
    draw_world_info(panel, 15, y, panel_data)
    y += 36
    draw_menu_handler_info(panel, 15, y, memory)
    y += 36
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
    draw_party_panel(panel, rx, ry, RIGHT_PANEL_W - 32, 285, panel_data["party"])
    draw_trainer_bag_panel(panel, rx, 315, RIGHT_PANEL_W - 32, panel_data["trainer"], panel_data["bag"])

    cv2.putText(
        panel,
        "Q/Esc: quit | Arrows/A/S/Start: move & buttons | +/-: speed | P: pause | Esc(emulator): quit",
        (15, INSPECTOR_H - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (120, 120, 120), 1,
    )

    cv2.imshow("Pokemon Red Inspector", panel)
    cv2.moveWindow("Pokemon Red Inspector", 820, 80)


def run_player(
    rom_path: Path,
    state_path: Path | None,
    replay_path: Path | None,
    controls: dict[str, dict[str, str]] | None = None,
) -> None:
    actions, replay_data = load_replay(replay_path)
    replay_action_freq = int(replay_data.get("action_freq", ACTION_FREQ))
    if replay_action_freq < 9:
        raise ValueError(f"Replay action frequency must be at least 9, got {replay_action_freq}")
    if state_path is None:
        state_path = resolve_recording_path(replay_data.get("init_state"))
    pyboy = PyBoy(str(rom_path), window="SDL2", sound=True)
    input_controller = InputController(pyboy, controls or load_controls())
    runtime_menu = RuntimeMenu(pyboy)
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
            runtime_menu.update()
            # Play back the next queued action at normal speed, one frame at a time, so the
            # audio/video stay in sync and the player can start controlling as soon as it ends.
            if replay_index < len(actions):
                action = actions[replay_index]
                replay_index += 1
                replay_action(pyboy, action, replay_action_freq)
                frame_count += replay_action_freq
            else:
                input_controller.poll()
                if input_controller.quit_requested:
                    break
                if not pyboy.tick(1, True):
                    break
                frame_count += 1

            if replay_index >= len(actions):
                replay_finished = True

            render_inspector(pyboy, frame_count, replay_index, len(actions), replay_finished, map_base)
            runtime_menu.update()
            key = cv2.waitKeyEx(1)
            if key in (ord("q"), 27):
                break
            time.sleep(0.001)
    except OSError as error:
        print(f"PyBoy stopped while closing the SDL window: {error}")
    finally:
        runtime_menu.close()
        input_controller.close()
        try:
            pyboy.stop()
        except OSError as error:
            print(f"PyBoy cleanup warning: {error}")
        cv2.destroyAllWindows()


def main() -> None:
    initialize_sdl_input()
    launcher = DebugLauncher()
    launcher.root.mainloop()


if __name__ == "__main__":
    main()
