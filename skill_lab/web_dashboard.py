"""Small browser dashboard for live map + stats in the skill lab."""

from __future__ import annotations

import base64
import json
import struct
import threading
from collections.abc import Callable
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
import webbrowser

INSPECTOR_WATCH_ADDRESSES = [
    0xD356,  # badges
    0xD35E,  # map
    0xD361,  # y pos
    0xD362,  # x pos
    0xD163,  # party count
    0xD31D,  # bag count
    0xD158,  # player name start
    0xD057,  # in battle
    0xCFE6,  # enemy HP (high byte)
    0xCFF4,  # enemy max HP (high byte)
]

_INSPECTOR_WATCH_DESCRIPTIONS = {
    0xD356: "Badges",
    0xD35E: "Map ID",
    0xD361: "Y Position",
    0xD362: "X Position",
    0xD163: "Party Count",
    0xD31D: "Bag Count",
    0xD158: "Player Name",
    0xD057: "In Battle",
    0xCFE6: "Enemy HP",
    0xCFF4: "Enemy Max HP",
}

try:
    import cv2
    _HAS_CV2 = True
except ImportError:
    _HAS_CV2 = False

try:
    from pyboy.utils import WindowEvent
    _HAS_PYBOY = True
except ImportError:
    _HAS_PYBOY = False

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAP_IMAGE_PATH = (
    PROJECT_ROOT
    / "visualization"
    / "poke_map"
    / "pokemap_full_calibrated_CROPPED_1.png"
)
LAVA_JSON_PATH = PROJECT_ROOT / "skill_lab" / "lava.json"
CONTROLS_PATH = PROJECT_ROOT / "skill_lab" / "controls.json"

ACTION_BUTTON_EVENTS: dict[str, tuple[Any, Any]] = {
    "Down": (WindowEvent.PRESS_ARROW_DOWN, WindowEvent.RELEASE_ARROW_DOWN) if _HAS_PYBOY else (None, None),
    "Left": (WindowEvent.PRESS_ARROW_LEFT, WindowEvent.RELEASE_ARROW_LEFT) if _HAS_PYBOY else (None, None),
    "Right": (WindowEvent.PRESS_ARROW_RIGHT, WindowEvent.RELEASE_ARROW_RIGHT) if _HAS_PYBOY else (None, None),
    "Up": (WindowEvent.PRESS_ARROW_UP, WindowEvent.RELEASE_ARROW_UP) if _HAS_PYBOY else (None, None),
    "A": (WindowEvent.PRESS_BUTTON_A, WindowEvent.RELEASE_BUTTON_A) if _HAS_PYBOY else (None, None),
    "B": (WindowEvent.PRESS_BUTTON_B, WindowEvent.RELEASE_BUTTON_B) if _HAS_PYBOY else (None, None),
    "Start": (WindowEvent.PRESS_BUTTON_START, WindowEvent.RELEASE_BUTTON_START) if _HAS_PYBOY else (None, None),
    "Select": (WindowEvent.PRESS_BUTTON_SELECT, WindowEvent.RELEASE_BUTTON_SELECT) if _HAS_PYBOY else (None, None),
}

try:
    from v2.global_map import GLOBAL_MAP_SHAPE
except Exception:
    GLOBAL_MAP_SHAPE = (464, 436)

try:
    from v2.map_projection import (
        project_position as _project_position_impl,
        unproject_position as _unproject_position_impl,
    )
except Exception:
    _project_position_impl = None
    _unproject_position_impl = None


class BrowserMapDashboard:
    """Simple browser dashboard served locally with a live map and table."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8765) -> None:
        self.host = host
        self.port = port
        self.url = f"http://{host}:{port}"
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._browser_opened = False
        self.map_width, self.map_height = self._read_map_size()
        self._mosaic_frame: bytes | None = None
        
        self._fallback_ko_counts: dict[int, int] = {}
        self._item_counts: dict[int, int] = {}
        self._last_bag_signatures: dict[int, tuple[tuple[int, int], ...] | None] = {}
        self._last_party_alive: dict[int, bool] = {}
        self._last_steps: dict[int, int] = {}
        self._memory_watch_lock = threading.Lock()
        self._memory_watch_tracker = None
        self._env_provider = None
        self._env = None
        self._inspector_data: dict[str, Any] = {}
        self._config: dict[str, Any] = {}
        self._pending_saves: dict[str, Any] = {}
        self._control_active: bool = False
        self._control_env_index: int = 0
        self._gamepad_bindings: dict[str, str] = {}
        self._key_bindings: dict[str, str] = {}
        self._load_default_controls()

        self._individual_frames: dict[int, bytes] = {}  # env_index -> png bytes
        self._mosaic_stream_active = False
        self._individual_frames_active = False
        self.state: dict[str, Any] = {
            "title": "Skill Lab Dashboard",
            "envs": [],
            "lava_zones": [],
            "map_width": self.map_width,
            "map_height": self.map_height,
            "last_updated": 0.0,
        }
        self._load_lava_zones()

    def set_mosaic_frame(self, frame) -> None:
        """Store a mosaic frame (numpy array) as JPEG for browser streaming."""
        if not self._mosaic_stream_active:
            return
        if frame is None:
            print("[MOSAIC DEBUG] No frame to store", flush=True)
            return
        if not _HAS_CV2:
            print("[MOSAIC DEBUG] cv2 not available, skipping mosaic frame", flush=True)
            return
        try:
            ok, encoded = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70]
            )
            if not ok or encoded is None:
                print("[MOSAIC DEBUG] cv2 failed to encode mosaic frame", flush=True)
                return
            with self._lock:
                self._mosaic_frame = encoded.tobytes()
            #print(f"[MOSAIC DEBUG] Frame stored: {len(self._mosaic_frame)} bytes", flush=True)
        except Exception as e:
            print(f"[MOSAIC DEBUG] Error encoding frame: {e}", flush=True)

    def set_individual_frame(self, env_index: int, frame) -> None:
        """Store an individual emulator frame as PNG for dynamic mosaic streaming (lossless quality)."""
        if not self._individual_frames_active:
            return
        if frame is None:
            return
        if not _HAS_CV2:
            return
        try:
            # Use PNG for lossless quality instead of JPEG compression
            ok, encoded = cv2.imencode(".png", frame)
            if not ok or encoded is None:
                return
            with self._lock:
                self._individual_frames[env_index] = encoded.tobytes()
        except Exception as e:
            print(f"[INDIVIDUAL FRAME DEBUG] Error encoding frame for env {env_index}: {e}", flush=True)

    def clear_individual_frames(self) -> None:
        """Clear all individual frames."""
        with self._lock:
            self._individual_frames.clear()

    def _save_lava_zones(self) -> None:
        """Persist lava zones to lava.json so the env can read them."""
        with self._lock:
            zones = list(self.state["lava_zones"])
        with suppress(Exception):
            with LAVA_JSON_PATH.open("w", encoding="utf-8") as f:
                json.dump({"lava_zones": zones}, f, indent=2)

    def _load_lava_zones(self) -> None:
        """Load lava zones from lava.json if it exists."""
        with suppress(Exception):
            if LAVA_JSON_PATH.exists():
                with LAVA_JSON_PATH.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    with self._lock:
                        self.state["lava_zones"] = [
                            (int(z[0]), int(z[1])) for z in data.get("lava_zones", [])
                        ]

    def _read_map_size(self) -> tuple[int, int]:
        """Read PNG dimensions without requiring an image-processing package."""
        if MAP_IMAGE_PATH.exists():
            with MAP_IMAGE_PATH.open("rb") as image_file:
                header = image_file.read(24)
            if header[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", header[16:24])
        return GLOBAL_MAP_SHAPE[1], GLOBAL_MAP_SHAPE[0]

    def start(self) -> None:
        if self._server is not None:
            return
        handler = self._build_handler()
        self._server = ThreadingHTTPServer((self.host, self.port), handler)
        self._server.dashboard = self
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._server is None:
            return
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None

    def open_browser(self) -> None:
        if self._browser_opened:
            return
        self._browser_opened = True
        with suppress(Exception):
            webbrowser.open(self.url, new=2)

    def update_state(self, env, env_count: int, *, scores: list[float] | None = None) -> None:
        entries: list[dict[str, Any]] = []
        for idx in range(env_count):
            hp = 0.0
            pcount = 0
            trainer_wins = 0
            wild_wins = 0
            wall_collisions = 0
            steps = 0
            current_map_id = 0
            x_pos = 0
            y_pos = 0
            map_n = 0
            gx = 0
            gy = 0
            position_error: str | None = None
            try:
                hp = float(env.get_attr("read_hp_fraction")[idx]())
                pcount = int(env.get_attr("read_m")[idx](0xD163))
                trainer_wins = int(env.get_attr("trainer_wins")[idx])
                wild_wins = int(env.get_attr("wild_wins")[idx])
                wall_collisions = int(env.get_attr("wall_collisions")[idx])
                steps = int(env.get_attr("step_count")[idx])
                current_map_id = int(env.get_attr("current_map_id")[idx])
            except Exception as exc:
                position_error = f"stats: {type(exc).__name__}: {exc}"
            try:
                x_pos = int(env.envs[idx].pyboy.memory[0xD362])
                y_pos = int(env.envs[idx].pyboy.memory[0xD361])
                map_n = int(env.envs[idx].pyboy.memory[0xD35E])
                gx, gy = self._project_position(x_pos, y_pos, map_n)
            except Exception as exc:
                position_error = f"position: {type(exc).__name__}: {exc}"
            if position_error is not None:
                print(f"[MAP DEBUG] Env {idx}: {position_error}", flush=True)
            score = float(scores[idx]) if scores is not None and idx < len(scores) else 0.0
            no_living = self._has_no_living_pokemon(env, idx, hp)
            ko_count = self._read_telemetry_count(
                env,
                idx,
                ("ko_count", "death_count", "deaths", "died_count", "ko_deaths"),
            )
            item_won_count = self._read_telemetry_count(
                env,
                idx,
                (
                    "item_won_count",
                    "items_won_count",
                    "item_wins",
                    "items_won",
                    "item_receipts",
                    "received_item_count",
                ),
            )
            with self._lock:
                previous_alive = self._last_party_alive.get(idx)
                previous_steps = self._last_steps.get(idx)
                reset_detected = previous_steps is not None and steps < previous_steps
                if reset_detected:
                    self._fallback_ko_counts[idx] = 0
                    self._item_counts[idx] = 0
                    self._last_bag_signatures.pop(idx, None)
                if ko_count is None:
                    if no_living and previous_alive is not False:
                        self._fallback_ko_counts[idx] = self._fallback_ko_counts.get(idx, 0) + 1
                    ko_count = self._fallback_ko_counts.get(idx, 0)
                else:
                    self._fallback_ko_counts[idx] = int(ko_count)
                if item_won_count is None:
                    item_won_count = self._track_item_wins(env, idx, reset_detected)
                else:
                    self._item_counts[idx] = int(item_won_count)
                    self._last_bag_signatures.pop(idx, None)
                self._last_party_alive[idx] = no_living
                self._last_steps[idx] = steps
                ko_count = int(ko_count)
                item_won_count = int(item_won_count)
            entries.append(
                {
                    "env_index": idx,
                    "hp": hp,
                    "pkmn": pcount,
                    "trainer_wins": trainer_wins,
                    "wild_wins": wild_wins,
                    "deaths": ko_count,
                    "ko_count": ko_count,
                    "no_living_pokemon": no_living,
                    "item_won_count": item_won_count,
                    "items_won": item_won_count,
                    "walls": wall_collisions,
                    "steps": steps,
                    "map_id": current_map_id,
                    "score": score,
                    "x": gx,
                    "y": gy,
                    "raw_x": x_pos,
                    "raw_y": y_pos,
                    "map_n": map_n,
                    "position_error": position_error,
                    "in_bounds": 0 <= gx < self.map_width and 0 <= gy < self.map_height,
                }
            )
        with self._lock:
            self._env = env
            self.state["envs"] = entries
            self.state["last_updated"] = __import__("time").time()
            self._collect_inspector_data(env, env_count)

    def _collect_inspector_data(self, env: Any, env_count: int) -> None:
        """Collect live inspector data for the Observation Inspector tab."""
        try:
            if env is None:
                self._inspector_data = {"error": "no environment connected"}
                return
            env_obj = env
            if hasattr(env, "envs") and len(env.envs) > 0:
                env_obj = env.envs[0]
            base_env = getattr(env_obj, "env", env_obj)
            unwrapped = getattr(base_env, "unwrapped", base_env)
            pyboy = getattr(unwrapped, "pyboy", getattr(env_obj, "pyboy", None))
            memory = getattr(pyboy, "memory", None)
            if memory is None:
                self._inspector_data = {"error": "memory not available"}
                return
            watch = self._inspector_memory_watch(memory)
            self._inspector_data = {"inspector": watch}
        except Exception:
            self._inspector_data = {"error": "failed to collect inspector data"}

    def set_environment_provider(
        self,
        provider: Callable[[], Any] | None,
    ) -> None:
        """Set an optional environment accessor for inspector requests."""
        with self._lock:
            self._env_provider = provider

    def _current_env(self) -> Any | None:
        with self._lock:
            provider = self._env_provider
            env = self._env
        if provider is not None:
            with suppress(Exception):
                provided = provider()
                if provided is not None:
                    return provided
        return env

    def _load_default_controls(self) -> None:
        """Load default gamepad/keyboard bindings from controls.json."""
        with suppress(Exception):
            if CONTROLS_PATH.exists():
                saved = json.loads(CONTROLS_PATH.read_text(encoding="utf-8"))
                for action, token in saved.get("gamepad", {}).items():
                    if action in ACTION_BUTTON_EVENTS:
                        self._gamepad_bindings[action] = token
                for action, token in saved.get("keyboard", {}).items():
                    if action in ACTION_BUTTON_EVENTS:
                        self._key_bindings[action] = token

    def send_inspector_input(self, action: str, pressed: bool, env_index: int) -> bool:
        """Send a press/release input event to the emulator for the given env."""
        if not _HAS_PYBOY or action not in ACTION_BUTTON_EVENTS:
            return False
        env = self._current_env()
        if env is None:
            return False
        env_obj = self._env_object(env, env_index)
        if env_obj is None:
            return False
        base_env = getattr(env_obj, "env", env_obj)
        unwrapped = getattr(base_env, "unwrapped", base_env)
        pyboy = getattr(unwrapped, "pyboy", getattr(env_obj, "pyboy", None))
        if pyboy is None:
            return False
        press_event, release_event = ACTION_BUTTON_EVENTS[action]
        if press_event is None or release_event is None:
            return False
        event = press_event if pressed else release_event
        try:
            pyboy.send_input(event)
            return True
        except Exception:
            return False

    def get_control_state(self) -> dict[str, Any]:
        """Return current control state and bindings."""
        with self._lock:
            return {
                "control_active": self._control_active,
                "env_index": self._control_env_index,
                "gamepad_bindings": dict(self._gamepad_bindings),
                "key_bindings": dict(self._key_bindings),
            }

    def get_config_state(self) -> dict[str, Any]:
        """Return the current applied config snapshot (read-only)."""
        with self._lock:
            return {
                "max_steps": self._config.get("max_steps"),
                "extra_steps": self._config.get("extra_steps", 0),
                "save_on_catch": self._config.get("save_on_catch"),
                "gamepad_bindings": dict(self._gamepad_bindings),
                "key_bindings": dict(self._key_bindings),
            }

    def take_pending_config(self) -> dict[str, Any] | None:
        """Atomically pop the pending config payload (if any).

        Returns a copy of the payload that was applied via the /api/config
        POST, or ``None`` if no new config has arrived since the last call.
        """
        with self._lock:
            if not self._pending_saves:
                return None
            pending = dict(self._pending_saves)
            self._pending_saves.clear()
            return pending

    def handle_control_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Handle control toggle, input events, and binding updates."""
        with self._lock:
            if "toggle" in payload:
                self._control_active = bool(payload["toggle"])
                if "env" in payload:
                    self._control_env_index = int(payload["env"])
            if "bindings" in payload:
                bindings = payload["bindings"]
                if "gamepad" in bindings:
                    self._gamepad_bindings.update(bindings["gamepad"])
                if "keyboard" in bindings:
                    self._key_bindings.update(bindings["keyboard"])
            control_active = self._control_active
            env_index = self._control_env_index
            gamepad_bindings = dict(self._gamepad_bindings)
            key_bindings = dict(self._key_bindings)
        input_ok = None
        if "action" in payload and "pressed" in payload:
            action = payload["action"]
            pressed = bool(payload["pressed"])
            target_env = int(payload.get("env", env_index))
            input_ok = self.send_inspector_input(action, pressed, target_env)
        result: dict[str, Any] = {
            "ok": True,
            "control_active": control_active,
            "env_index": env_index,
            "gamepad_bindings": gamepad_bindings,
            "key_bindings": key_bindings,
        }
        if input_ok is not None:
            result["input_sent"] = input_ok
        return result

    @staticmethod
    def _indexed_value(values: Any, index: int, default: Any = None) -> Any:
        if isinstance(values, dict):
            return values.get(index, values.get(str(index), default))
        try:
            return values[index]
        except (KeyError, IndexError, TypeError):
            return default

    def _read_env_value(
        self,
        env: Any,
        index: int,
        names: tuple[str, ...],
        default: Any = None,
    ) -> Any:
        for name in names:
            try:
                values = env.get_attr(name)
                value = self._indexed_value(values, index, default)
                if callable(value):
                    value = value()
                if value is not default:
                    return value
            except Exception:
                pass
        env_obj = self._env_object(env, index)
        for name in names:
            try:
                value = getattr(env_obj, name)
                if callable(value):
                    value = value()
                if value is not None:
                    return value
            except Exception:
                pass
        return default

    @staticmethod
    def _env_object(env: Any, index: int) -> Any | None:
        with suppress(Exception):
            return env.envs[index]
        return None

    @staticmethod
    def _as_int(value: Any, default: int | None = None) -> int | None:
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _read_telemetry_count(
        self,
        env: Any,
        index: int,
        names: tuple[str, ...],
    ) -> int | None:
        value = self._read_env_value(env, index, names)
        if value is not None:
            count = self._as_int(value)
            if count is not None:
                return max(0, count)
        stats = self._read_env_value(env, index, ("agent_stats",))
        if isinstance(stats, list) and stats:
            latest = stats[-1] if isinstance(stats[-1], dict) else {}
            for name in names:
                count = self._as_int(latest.get(name))
                if count is not None:
                    return max(0, count)
        return None

    @staticmethod
    def _memory_byte(memory: Any, address: int) -> int | None:
        try:
            return int(memory[address])
        except Exception:
            return None

    def _has_no_living_pokemon(self, env: Any, index: int, hp: float = 0.0) -> bool:
        explicit = self._read_env_value(
            env,
            index,
            ("no_living_pokemon", "all_pokemon_fainted", "party_ko"),
        )
        if explicit is not None:
            return bool(explicit)
        env_obj = self._env_object(env, index)
        try:
            memory = env_obj.pyboy.memory
            party_size = min(max(int(memory[0xD163]), 0), 6)
            if party_size == 0:
                return False
            for slot in range(party_size):
                base = 0xD16B + slot * 0x2C
                high = self._memory_byte(memory, base + 1)
                low = self._memory_byte(memory, base + 2)
                if high is not None and low is not None and ((high << 8) | low) > 0:
                    return False
            return True
        except Exception:
            return hp <= 0.0 and self._as_int(
                self._read_env_value(env, index, ("read_m",), None),
                0,
            ) is not None and False

    def _bag_signature(self, env: Any, index: int) -> tuple[tuple[int, int], ...] | None:
        env_obj = self._env_object(env, index)
        try:
            memory = env_obj.pyboy.memory
            count = min(max(int(memory[0xD31D]), 0), 40)
            items: list[tuple[int, int]] = []
            for slot in range(count):
                address = 0xD31E + slot * 2
                item_id = int(memory[address])
                quantity = int(memory[address + 1])
                if item_id:
                    items.append((item_id, quantity))
            return tuple(items)
        except Exception:
            return None

    def _track_item_wins(self, env: Any, index: int, reset_detected: bool) -> int:
        """Track bag signature changes to count items won.

        Must be called while holding ``self._lock``.
        """
        signature = self._bag_signature(env, index)
        if reset_detected or signature is None:
            if reset_detected:
                self._last_bag_signatures.pop(index, None)
            return self._item_counts.get(index, 0)
        previous = self._last_bag_signatures.get(index)
        self._last_bag_signatures[index] = signature
        if previous is None:
            return self._item_counts.get(index, 0)
        previous_by_id = dict(previous)
        wins = sum(
            1
            for item_id, quantity in signature
            if quantity > previous_by_id.get(item_id, 0)
        )
        if wins:
            self._item_counts[index] = self._item_counts.get(index, 0) + wins
        return self._item_counts.get(index, 0)

    def get_inspector_data(self, env_index: int) -> dict[str, Any]:
        """Return a JSON-safe snapshot of the data shown by ObservationInspector."""
        index = int(env_index)
        env = self._current_env()
        if env is None:
            return {"error": "environment provider is not connected"}
        env_obj = self._env_object(env, index)
        if env_obj is None:
            return {"error": f"environment {index} is not available"}
        base_env = getattr(env_obj, "env", env_obj)
        unwrapped = getattr(base_env, "unwrapped", base_env)
        pyboy = getattr(unwrapped, "pyboy", getattr(env_obj, "pyboy", None))
        memory = getattr(pyboy, "memory", None)
        screen_url = f"/api/inspector-screen?env={index}"
        directives = self._inspector_directives(env_obj, index)
        panel_data: dict[str, Any] = {}
        if memory is not None:
            with suppress(Exception):
                from skill_lab.panel_data import read_panel_data

                panel_data = read_panel_data(memory) or {}
        party = panel_data.get("party") or self._read_party(memory)
        opponent = self._safe_call(lambda: self._read_opponent_party(memory), [])
        trainer = panel_data.get("trainer") or {}
        bag = panel_data.get("bag") or self._read_bag(memory)
        hp = self._safe_call(lambda: float(env_obj.read_hp_fraction()), 0.0)
        level_sum = self._as_int(getattr(unwrapped, "current_level_sum", 0), 0) or 0
        map_id = self._as_int(getattr(unwrapped, "current_map_id", 0), 0) or 0
        badges = self._as_int(self._memory_byte(memory, 0xD356), 0) or 0
        badge_count = badges.bit_count()
        events = self._safe_call(lambda: list(unwrapped.read_event_bits()), [])
        steps = self._as_int(getattr(unwrapped, "step_count", 0), 0) or 0
        trainer_wins = self._as_int(getattr(unwrapped, "trainer_wins", 0), 0) or 0
        wild_wins = self._as_int(getattr(unwrapped, "wild_wins", 0), 0) or 0
        fled_battle = self._as_int(getattr(unwrapped, "fled_battle", 0), 0) or 0
        walls = self._as_int(getattr(unwrapped, "wall_collisions", 0), 0) or 0
        recent_actions = self._safe_call(lambda: list(getattr(unwrapped, "recent_actions", [])), [])
        action_names = ["Down", "Left", "Right", "Up", "A", "B", "Start", "Select"]
        recent_action_names = [
            action_names[action] if isinstance(action, int) and 0 <= action < len(action_names) else f"#{action}"
            for action in recent_actions
        ]
        milestones = self._safe_call(
            lambda: self._inspector_milestones(env_obj),
            {"available": False},
        )
        memory_watch = self._safe_call(
            lambda: self._inspector_memory_watch(memory),
            [],
        )
        screen_shape = self._safe_call(
            lambda: [int(value) for value in pyboy.screen.ndarray.shape],
            [],
        )
        return self._json_safe(
            {
                "env_index": index,
                "env_name": directives.get("env_name", f"Env {index + 1}"),
                "screen_url": screen_url,
                "screen_width": screen_shape[1] if len(screen_shape) > 1 else 0,
                "screen_height": screen_shape[0] if screen_shape else 0,
                "directives": directives,
                "party": party,
                "opponent": opponent,
                "trainer": trainer,
                "bag": bag,
                "stats": {
                    "hp": hp,
                    "level_sum": level_sum,
                    "map_id": map_id,
                    "badges": badge_count,
                    "events": len(events) if isinstance(events, list) else events,
                    "steps": steps,
                    "trainer_wins": trainer_wins,
                    "wild_wins": wild_wins,
                    "fled_battle": fled_battle,
                    "walls": walls,
                },
                "milestones": milestones,
                "checkpoints": self._safe_call(
                    lambda: self._inspector_checkpoints(env_obj),
                    {"available": False},
                ),
                "memory_watch": memory_watch,
                "recent_actions": recent_action_names,
                "raw_recent_actions": recent_actions,
                "panel_data": panel_data,
                "reward_history": {
                    "events": self._safe_call(
                        lambda: list(getattr(env_obj, "reward_events", [])[-50:]),
                        [],
                    ),
                    "counts": self._safe_call(
                        lambda: dict(getattr(env_obj, "reward_counts", {})),
                        {},
                    ),
                    "fled_battle": self._as_int(getattr(env_obj, "fled_battle", 0), 0) or 0,
                },
            }
        )

    @staticmethod
    def _safe_call(callback: Callable[[], Any], default: Any) -> Any:
        try:
            return callback()
        except Exception:
            return default

    def _inspector_directives(self, env_obj: Any, index: int) -> dict[str, Any]:
        wrapper = getattr(env_obj, "env", env_obj)
        values = {}
        for name in (
            "env_name",
            "target_starter",
            "rom_path",
            "catch_directive",
            "train_directive",
            "save_on_catch",
            "save_on_catch_enabled",
            "save_on_catch_min_dv",
            "reset_on_catch",
        ):
            values[name] = getattr(wrapper, name, None)
        rom_path = str(values.get("rom_path") or "")
        values["rom_label"] = "Blue" if "blue" in rom_path.lower() else "Red"
        values.setdefault("env_name", f"Env {index + 1}")
        return values

    def _inspector_milestones(self, env_obj: Any) -> dict[str, Any]:
        tracker = getattr(env_obj, "event_tracker", None)
        if tracker is None:
            return {"available": False}
        event_names = getattr(tracker, "event_names", {}) or {}
        milestone_keys = list(event_names.keys()) if isinstance(event_names, dict) else []
        achieved_raw = getattr(tracker, "achieved", set()) or set()
        try:
            achieved = set(achieved_raw)
        except TypeError:
            achieved = set()
        achieved_steps = dict(getattr(tracker, "achieved_steps", {}) or {})
        def _find_current():
            for name in milestone_keys:
                if name not in achieved:
                    return name
            return milestone_keys[-1] if milestone_keys else None
        current_target = self._safe_call(_find_current, None)
        return {
            "available": True,
            "milestones": milestone_keys,
            "achieved": self._safe_call(lambda: sorted(achieved), list(achieved_raw)),
            "achieved_steps": achieved_steps,
            "current_target": current_target,
        }

    def _inspector_checkpoints(self, env_obj: Any) -> dict[str, Any]:
        """Collect checkpoint progress from the SkillLabWrapper's checkpoint_tracker."""
        tracker = getattr(env_obj, "checkpoint_tracker", None)
        if tracker is None:
            return {"available": False}
        return self._safe_call(lambda: tracker.get_progress(), {"available": False})

    def _inspector_memory_watch(self, memory: Any) -> list[dict[str, Any]]:
        if memory is None:
            return []
        with self._memory_watch_lock:
            if self._memory_watch_tracker is None:
                with suppress(Exception):
                    from skill_lab.panel_data import MemoryWatchTracker

                    self._memory_watch_tracker = MemoryWatchTracker(INSPECTOR_WATCH_ADDRESSES)
            if self._memory_watch_tracker is None:
                return [
                    {
                        "address": address,
                        "value": self._memory_byte(memory, address),
                        "changed": False,
                        "description": _INSPECTOR_WATCH_DESCRIPTIONS.get(address, ""),
                    }
                    for address in INSPECTOR_WATCH_ADDRESSES
                ]
            snapshot = self._memory_watch_tracker.record(memory)
        return [
            {
                "address": address,
                "value": entry.get("value"),
                "previous": entry.get("previous"),
                "changed": entry.get("changed", False),
                "flash": entry.get("flash", False),
                "description": _INSPECTOR_WATCH_DESCRIPTIONS.get(address, ""),
            }
            for address, entry in snapshot.items()
        ]

    def _read_party(self, memory: Any) -> list[dict[str, Any]]:
        if memory is None:
            return []
        with suppress(Exception):
            from skill_lab.party_reader import Gen1PartyReader, PyBoyMemoryReader

            return Gen1PartyReader(PyBoyMemoryReader(memory)).read_party({
                "partyAddr": Gen1PartyReader.PARTY_ADDRESS,
                "partySlotsCounterAddr": Gen1PartyReader.PARTY_SIZE_ADDRESS,
                "partyNicknamesAddr": Gen1PartyReader.PARTY_NICKNAMES_ADDRESS,
            })
        return []

    def _read_opponent_party(self, memory: Any) -> list[dict[str, Any]]:
        """Read the current enemy Pokemon in battle (single slot)."""
        if memory is None:
            return []
        with suppress(Exception):
            from skill_lab.party_reader import Gen1PartyReader

            in_battle = int(memory[0xD057]) != 0
            if not in_battle:
                return []
            species_id = int(memory[0xCFE5])
            level = int(memory[0xCFF3])
            cur_hp = int(memory[0xCFE6]) | (int(memory[0xCFE7]) << 8)
            max_hp = int(memory[0xCFF4]) | (int(memory[0xCFF5]) << 8)
            names = getattr(Gen1PartyReader, "SPECIES_NAMES", [])
            species_name = names[species_id - 1] if 1 <= species_id <= len(names) else str(species_id)
            return [{
                "slot": 0,
                "speciesID": species_id,
                "speciesName": species_name,
                "level": level,
                "curHP": cur_hp,
                "maxHP": max_hp,
                "nickname": species_name,
            }]
        return []

    def _read_bag(self, memory: Any) -> list[dict[str, Any]]:
        if memory is None:
            return []
        with suppress(Exception):
            from skill_lab.bag_reader import BAG_COUNT_ADDRESS, BAG_ITEMS_ADDRESS, PokemonData

            count = min(int(memory[BAG_COUNT_ADDRESS]), 40)
            items: list[dict[str, Any]] = []
            for slot in range(count):
                address = BAG_ITEMS_ADDRESS + slot * 2
                item_id = int(memory[address])
                if item_id == 0:
                    break
                quantity = int(memory[address + 1])
                items.append({
                    "id": item_id,
                    "quantity": quantity,
                    "name": PokemonData.get_item_name(item_id),
                })
            return items
        return []

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, bytes):
            return base64.b64encode(value).decode("ascii")
        if hasattr(value, "tolist"):
            return cls._json_safe(value.tolist())
        return str(value)

    @staticmethod
    def _project_position(x_pos: int, y_pos: int, map_n: int) -> tuple[int, int]:
        """Convert game coordinates to the stitched map's pixel coordinates.

        Delegates to the single source of truth in
        :mod:`v2.map_projection` so that the env and the dashboard always
        agree on where each map offset lands in the 4000 × 4000 image.
        """
        if _project_position_impl is not None:
            result = _project_position_impl(x_pos, y_pos, map_n)
            return (result.pixel_x, result.pixel_y)
        # Fallback — should not happen in normal operation.
        offset_x, offset_y = {
            0: (0, 0), 1: (-10, 72), 2: (-10, 180),
            12: (0, 36), 13: (0, 144), 14: (30, 172),
            15: (80, 190), 33: (-50, 64), 37: (-9, 2),
            38: (-9, -7), 39: (21, 2), 40: (21, -6),
            41: (30, 47), 42: (30, 55), 43: (30, 72),
            44: (30, 64), 47: (21, 136), 49: (21, 108),
            50: (21, 108), 51: (-35, 137), 52: (-10, 189),
            53: (-10, 198), 54: (-21, 169), 55: (-19, 177),
            56: (-30, 163), 57: (-19, 177), 58: (-25, 154),
            59: (83, 227), 60: (123, 227), 61: (152, 227),
            68: (65, 190),
        }.get(map_n, (0, 0))
        pixel_x = 864 + 16 * (offset_x + x_pos)
        pixel_y = 4000 - (331 + 16 * (offset_y - y_pos))
        return int(pixel_x), int(pixel_y)

    def unproject_position(self, pixel_x: int, pixel_y: int) -> dict[str, Any]:
        """Convert stitched-map PNG pixel coordinates back to in-game coordinates.

        Returns a dict with ``map_id``, ``map_name``, ``x``, ``y`` and an
        ``in_bounds`` flag.  Delegates to :func:`v2.map_projection.unproject_position`.
        """
        if _unproject_position_impl is not None:
            result = _unproject_position_impl(pixel_x, pixel_y)
            return {
                "map_id": result.map_id,
                "map_name": result.map_name,
                "x": result.x,
                "y": result.y,
                "in_bounds": result.in_bounds,
            }
        return {
            "map_id": 0,
            "map_name": "Unknown",
            "x": 0,
            "y": 0,
            "in_bounds": False,
        }

    def add_lava_zone(self, x: int, y: int) -> None:
        with self._lock:
            zone = (int(x), int(y))
            existing = self.state["lava_zones"]
            if zone not in existing:
                existing.append(zone)

    def remove_lava_zone(self, x: int, y: int) -> None:
        with self._lock:
            zone = (int(x), int(y))
            self.state["lava_zones"] = [z for z in self.state["lava_zones"] if z != zone]

    def toggle_lava_zone(self, x: int, y: int) -> None:
        with self._lock:
            zone = (int(x), int(y))
            current = self.state["lava_zones"]
            if zone in current:
                self.state["lava_zones"] = [z for z in current if z != zone]
                print(f"[LAVA DEBUG] Removed zone {zone}, count={len(self.state['lava_zones'])}", flush=True)
            else:
                current.append(zone)
                print(f"[LAVA DEBUG] Added zone {zone}, count={len(self.state['lava_zones'])}", flush=True)
        self._save_lava_zones()

    def _build_handler(self):
        dashboard = self

        class DashboardHandler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._send_html()
                    return
                if parsed.path == "/style.css":
                    self._send_css()
                    return
                if parsed.path.startswith("/js/"):
                    self._send_js_module(parsed.path)
                    return
                if parsed.path == "/api/state":
                    with dashboard._lock:
                        data = json.dumps(dashboard.state).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if parsed.path == "/map.png":
                    self._send_map_image()
                    return
                if parsed.path == "/api/mosaic":
                    self._send_mosaic_frame()
                    return
                if parsed.path.startswith("/api/individual/"):
                    # Extract env_index from path: /api/individual/<index>
                    try:
                        env_index = int(parsed.path.split("/")[-1])
                        self._send_individual_frame(env_index)
                    except (ValueError, IndexError):
                        self.send_error(400, "invalid env index")
                    return
                if parsed.path == "/api/inspector-screen":
                    query = parse_qs(parsed.query)
                    env_index = int(query.get("env", [0])[0])
                    self._send_inspector_screen(env_index)
                    return
                if parsed.path == "/api/inspector":
                    query = parse_qs(parsed.query)
                    env_index = int(query.get("env", [0])[0])
                    data = json.dumps(dashboard.get_inspector_data(env_index)).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if parsed.path == "/api/control":
                    result = dashboard.get_control_state()
                    data = json.dumps(result).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if parsed.path == "/api/config":
                    result = dashboard.get_config_state()
                    data = json.dumps(result).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                if parsed.path == "/api/map-coords":
                    query = parse_qs(parsed.query)
                    try:
                        px = int(query.get("x", [0])[0])
                        py = int(query.get("y", [0])[0])
                    except (ValueError, IndexError):
                        self.send_error(400, "x and y query parameters must be integers")
                        return
                    result = dashboard.unproject_position(px, py)
                    data = json.dumps(result).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self.send_error(404)

            def do_POST(self) -> None:
                parsed = urlparse(self.path)
                if parsed.path == "/api/config":
                    content_length = int(self.headers.get("Content-Length", "0"))
                    body = self.rfile.read(content_length)
                    try:
                        payload = json.loads(body.decode("utf-8"))
                    except json.JSONDecodeError:
                        self.send_error(400, "invalid json")
                        return
                    with dashboard._lock:
                        dashboard._config.update(payload)
                        dashboard._pending_saves["config"] = payload.copy()
                        if "gamepad_bindings" in payload:
                            dashboard._gamepad_bindings.update(payload["gamepad_bindings"])
                        if "key_bindings" in payload:
                            dashboard._key_bindings.update(payload["key_bindings"])
                    config_data = json.dumps({"ok": True, "status": "saved"}).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(config_data)))
                    self.end_headers()
                    self.wfile.write(config_data)
                    return
                if parsed.path == "/api/control":
                    content_length = int(self.headers.get("Content-Length", "0"))
                    body = self.rfile.read(content_length)
                    try:
                        payload = json.loads(body.decode("utf-8"))
                    except json.JSONDecodeError:
                        self.send_error(400, "invalid json")
                        return
                    result = dashboard.handle_control_request(payload)
                    ctrl_data = json.dumps(result).encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(ctrl_data)))
                    self.end_headers()
                    self.wfile.write(ctrl_data)
                    return
                if parsed.path == "/api/streaming":
                    content_length = int(self.headers.get("Content-Length", "0"))
                    body = self.rfile.read(content_length)
                    try:
                        payload = json.loads(body.decode("utf-8"))
                    except json.JSONDecodeError:
                        self.send_error(400, "invalid json")
                        return
                    with dashboard._lock:
                        if "mosaic" in payload:
                            dashboard._mosaic_stream_active = bool(payload["mosaic"])
                        if "individual_frames" in payload:
                            dashboard._individual_frames_active = bool(payload["individual_frames"])
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
                    return
                if parsed.path == "/api/log":
                    content_length = int(self.headers.get("Content-Length", "0"))
                    body = self.rfile.read(content_length)
                    try:
                        payload = json.loads(body.decode("utf-8"))
                    except json.JSONDecodeError:
                        self.send_error(400, "invalid json")
                        return
                    message = payload.get("message", "")
                    print(f"[MAP COORD] {message}", flush=True)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
                    return
                if parsed.path != "/api/lava":
                    self.send_error(404)
                    return
                content_length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(content_length)
                try:
                    payload = json.loads(body.decode("utf-8"))
                except json.JSONDecodeError:
                    self.send_error(400, "invalid json")
                    return
                if "zones" in payload:
                    zones = payload["zones"]
                    for zone in zones:
                        dashboard.toggle_lava_zone(int(zone["x"]), int(zone["y"]))
                    print(f"[LAVA DEBUG] Batch toggle: {len(zones)} zones, first={zones[0] if zones else 'none'}", flush=True)
                    print(f"[LAVA DEBUG] After batch: zones={dashboard.state['lava_zones']}", flush=True)
                else:
                    x = int(payload.get("x", 0))
                    y = int(payload.get("y", 0))
                    print(f"[LAVA DEBUG] Toggle request received: x={x}, y={y}", flush=True)
                    dashboard.toggle_lava_zone(x, y)
                    print(f"[LAVA DEBUG] After toggle: zones={dashboard.state['lava_zones']}", flush=True)
                with dashboard._lock:
                    lava_zones = list(dashboard.state["lava_zones"])
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": True, "lava_zones": lava_zones}).encode("utf-8"))

            def _send_map_image(self) -> None:
                if not MAP_IMAGE_PATH.exists():
                    self.send_error(404, "map image not found")
                    return
                content = MAP_IMAGE_PATH.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def _send_mosaic_frame(self) -> None:
                with dashboard._lock:
                    frame = dashboard._mosaic_frame
                if frame is None:
                    self.send_response(204)
                    self.end_headers()
                    return
                # print(f"[MOSAIC DEBUG] Serving frame: {len(frame)} bytes", flush=True) 
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(frame)))
                self.end_headers()
                with suppress(ConnectionAbortedError, BrokenPipeError):
                    self.wfile.write(frame)

            def _send_individual_frame(self, env_index: int) -> None:
                with dashboard._lock:
                    frame = dashboard._individual_frames.get(env_index)
                if frame is None:
                    self.send_response(204)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(frame)))
                self.end_headers()
                with suppress(ConnectionAbortedError, BrokenPipeError):
                    self.wfile.write(frame)

            def _send_inspector_screen(self, env_index: int) -> None:
                """Send the high-quality 320x288 screen image for the Environment Inspector."""
                env = dashboard._current_env()
                if env is None:
                    self.send_response(204)
                    self.end_headers()
                    return
                try:
                    env_obj = dashboard._env_object(env, env_index)
                    if env_obj is None:
                        self.send_response(204)
                        self.end_headers()
                        return
                    base_env = getattr(env_obj, "env", env_obj)
                    unwrapped = getattr(base_env, "unwrapped", base_env)
                    pyboy = getattr(unwrapped, "pyboy", getattr(env_obj, "pyboy", None))
                    if pyboy is None:
                        self.send_response(204)
                        self.end_headers()
                        return
                    screen = pyboy.screen.ndarray
                    if screen is None:
                        self.send_response(204)
                        self.end_headers()
                        return
                    if screen.shape[-1] == 4:
                        screen = screen[:, :, :3]
                    # Resize to 320x288 (2x Game Boy resolution) like ObservationInspector
                    screen = cv2.resize(screen, (320, 288), interpolation=cv2.INTER_NEAREST)
                    # Encode as PNG for lossless quality
                    ok, encoded = cv2.imencode(".png", screen)
                    if not ok or encoded is None:
                        self.send_response(204)
                        self.end_headers()
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(encoded.tobytes())))
                    self.end_headers()
                    with suppress(ConnectionAbortedError, BrokenPipeError):
                        self.wfile.write(encoded.tobytes())
                except Exception as e:
                    print(f"[INSPECTOR SCREEN DEBUG] Error: {e}", flush=True)
                    self.send_response(204)
                    self.end_headers()

            def _send_html(self) -> None:
                svg_w, svg_h = dashboard.map_width, dashboard.map_height
                html_path = (
                    PROJECT_ROOT / "skill_lab" / "static" / "index.html"
                )
                html = html_path.read_text(encoding="utf-8")
                html = html.replace("__SVG_W__", str(svg_w))
                html = html.replace("__SVG_H__", str(svg_h))
                encoded = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def _send_css(self) -> None:
                css_path = PROJECT_ROOT / "skill_lab" / "static" / "style.css"
                if not css_path.exists():
                    self.send_error(404, "style.css not found")
                    return
                content = css_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/css")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def _send_js_module(self, path: str) -> None:
                js_dir = PROJECT_ROOT / "skill_lab" / "static" / "js"
                relative = path[len("/js/"):]
                module_path = (js_dir / relative).resolve()
                try:
                    module_path.relative_to(js_dir.resolve())
                except ValueError:
                    self.send_error(403)
                    return
                if not module_path.exists():
                    self.send_error(404, f"module {relative} not found")
                    return
                content = module_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/javascript")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

            def log_message(self, format: str, *args: Any) -> None:
                return

        return DashboardHandler


def main() -> None:
    dashboard = BrowserMapDashboard()
    dashboard.start()
    print(f"[Dashboard] Live map + stats: {dashboard.url}")
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        dashboard.stop()


if __name__ == "__main__":
    main()
