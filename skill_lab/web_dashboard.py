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

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAP_IMAGE_PATH = (
    PROJECT_ROOT
    / "visualization"
    / "poke_map"
    / "pokemap_full_calibrated_CROPPED_1.png"
)
LAVA_JSON_PATH = PROJECT_ROOT / "skill_lab" / "lava.json"

try:
    from v2.global_map import GLOBAL_MAP_SHAPE
except Exception:
    GLOBAL_MAP_SHAPE = (464, 436)


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

        self._individual_frames: dict[int, bytes] = {}  # env_index -> jpeg bytes
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
        walls = self._as_int(getattr(unwrapped, "wall_collisions", 0), 0) or 0
        recent_actions = self._safe_call(lambda: list(getattr(unwrapped, "recent_actions", [])), [])
        action_names = ["Down", "Left", "Right", "Up", "A", "B", "Start", "Select"]
        recent_action_names = [
            action_names[action] if isinstance(action, int) and 0 <= action < len(action_names) else f"#{action}"
            for action in recent_actions
        ]
        milestones = self._inspector_milestones(env_obj)
        memory_watch = self._inspector_memory_watch(memory)
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
                    "walls": walls,
                },
                "milestones": milestones,
                "memory_watch": memory_watch,
                "recent_actions": recent_action_names,
                "raw_recent_actions": recent_actions,
                "panel_data": panel_data,
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
        tracker = getattr(env_obj, "milestone_tracker", None)
        if tracker is None:
            return {"available": False}
        milestones = list(getattr(tracker, "milestones", []) or [])
        achieved = set(getattr(tracker, "achieved", set()) or set())
        achieved_steps = dict(getattr(tracker, "achieved_steps", {}) or {})
        current_target = next(
            (name for name in milestones if name not in achieved),
            milestones[-1] if milestones else None,
        )
        return {
            "available": True,
            "milestones": milestones,
            "achieved": sorted(achieved),
            "achieved_steps": achieved_steps,
            "current_target": current_target,
        }

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
        """Convert game coordinates to the stitched map's pixel coordinates."""
        # These offsets match the original BetterMapVis calibration: each game
        # tile is 16 pixels and the map image's origin is at (864, 331).
        map_offsets = {
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
        }
        offset_x, offset_y = map_offsets.get(map_n, (0, 0))
        pixel_x = 864 + 16 * (offset_x + x_pos)
        pixel_y = 4000 - (331 + 16 * (offset_y - y_pos))
        return int(pixel_x), int(pixel_y)

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
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"ok": True, "status": "saved"}).encode("utf-8"))
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
                self.wfile.write(frame)

            def _send_html(self) -> None:
                svg_w, svg_h = dashboard.map_width, dashboard.map_height
                html = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Skill Lab Dashboard</title>
  <style>
    :root {{
      --bg: #0c1220;
      --panel: #141d2e;
      --muted: #8aa0c7;
      --accent: #6ee7ff;
      --good: #67f39b;
      --warning: #ffd166;
      --danger: #ff6b6b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: system-ui, sans-serif; background: var(--bg); color: #eef4ff;
      min-height: 100vh;
    }}
    .tab-bar {{
      display: flex; gap: 4px; padding: 4px 16px; background: rgba(15, 22, 34, 0.96); border-bottom: 1px solid rgba(255,255,255,0.08);
    }}
    .tab-bar .tab-btn {{
      padding: 10px 20px; border-radius: 8px 8px 0 0; border: 1px solid rgba(255,255,255,0.1);
      background: rgba(255,255,255,0.04); color: var(--muted); font-size: 0.9rem; font-weight: 600;
      cursor: pointer; transition: all 0.15s ease;
    }}
    .tab-bar .tab-btn:hover {{ background: rgba(255,255,255,0.08); }}
    .tab-bar .tab-btn.active {{ background: var(--panel); color: var(--accent); border-bottom: 2px solid var(--accent); }}
    .tab-content {{ padding: 18px; height: calc(100vh - 60px); }}
    .tab-pane {{ display: none; height: 100%; }}
    .tab-pane.active {{ display: block; }}
    .panel {{ background: rgba(20, 29, 46, 0.9); border: 1px solid rgba(255,255,255,0.08); border-radius: 12px; overflow: hidden; }}
    .map-panel {{ position: relative; display: flex; flex-direction: column; height: 100%; }}
    .map-wrap {{ flex: 1; padding: 12px; position: relative; border: 1px solid rgba(255,255,255,0.08); border-radius: 10px; }}
    .map-wrap svg {{ width: 100%; height: 100%; background: linear-gradient(180deg, #0d1728, #111c2e); border-radius: 10px; cursor: grab; touch-action: none; }}
    .map-wrap svg.grabbing {{ cursor: grabbing; }}
    .map-controls {{ position: absolute; right: 14px; top: 12px; display: flex; flex-direction: column; gap: 6px; z-index: 10; }}
    .map-controls button {{ width: 36px; height: 36px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.15); background: rgba(15, 22, 34, 0.85); color: #eef4ff; font-size: 1.1rem; font-weight: 700; cursor: pointer; transition: all 0.15s ease; }}
    .map-controls button:hover {{ background: var(--accent); color: var(--bg); border-color: var(--accent); }}
    .map-controls button.toggle-active {{ background: var(--accent); color: var(--bg); }}
    .map-controls .zoom-h {{ display: flex; gap: 6px; }}
    .status-overlay {{ position: absolute; bottom: 12px; left: 14px; background: rgba(15, 22, 34, 0.85); border-radius: 8px; padding: 4px 10px; font-size: 0.78rem; z-index: 10; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
    .status-overlay#status {{ right: 14px; left: auto; overflow-x: auto; }}
    .status-overlay#lava-mode-status {{ bottom: 44px; left: 14px; background: rgba(255, 107, 107, 0.85); }}
    .meta {{ color: var(--muted); font-size: 0.75rem; padding: 8px 12px; border-top: 1px solid rgba(255,255,255,0.08); }}
    .stats-panel {{ display: flex; flex-direction: column; height: 100%; }}
    .stats-panel .header {{ padding: 12px 16px; border-bottom: 1px solid rgba(255,255,255,0.08); display: flex; justify-content: space-between; align-items: center; }}
    .stats-panel .title {{ font-size: 1.05rem; font-weight: 700; }}
    .stats-panel .badge {{ color: var(--accent); font-size: 0.8rem; font-weight: 600; }}
    .stats-scroll {{ flex: 1; overflow: auto; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ padding: 7px 8px; border-bottom: 1px solid rgba(255,255,255,0.06); text-align: left; font-size: 0.85rem; }}
    th {{ position: sticky; top: 0; background: rgba(15, 22, 34, 0.98); color: var(--accent); }}
    tbody tr:nth-child(odd) {{ background: rgba(255,255,255,0.01); }}
    .chip {{ display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 0.72rem; font-weight: 700; }}
    .chip.good {{ background: rgba(103, 243, 155, 0.2); color: var(--good); }}
    .chip.warn {{ background: rgba(255, 209, 102, 0.2); color: var(--warning); }}
    .chip.bad {{ background: rgba(255, 107, 107, 0.2); color: var(--danger); }}
    .mosaic-panel {{ display: flex; flex-direction: column; height: 100%; }}
    .mosaic-content {{ flex: 1; display: flex; align-items: center; justify-content: center; overflow: auto; padding: 12px; }}
    .mosaic-content img {{ max-width: 100%; max-height: 100%; border-radius: 10px; border: 1px solid rgba(255,255,255,0.08); }}
    #dynamic-mosaic-grid {{ display: grid !important; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)) !important; gap: 12px !important; width: 100% !important; height: auto !important; overflow: visible !important; align-content: start !important; }}
    .dynamic-mosaic-cell {{ position: relative; border-radius: 8px; overflow: hidden; border: 1px solid rgba(255,255,255,0.08); cursor: pointer; transition: all 0.2s ease; background: rgba(0,0,0,0.3); aspect-ratio: 160/144; flex-shrink: 0; }}
    .dynamic-mosaic-cell img {{ width: 100% !important; height: 100% !important; object-fit: contain !important; display: block !important; background: #000; }}
  </style>
</head>
<body>
   <div class="tab-bar">
     <button class="tab-btn active" data-tab="map-tab">Map</button>
     <button class="tab-btn" data-tab="mosaic-tab">Mosaic Stream</button>
     <button class="tab-btn" data-tab="dynamic-mosaic-tab">Dynamic Mosaic</button>
     <button class="tab-btn" data-tab="inspector-tab">Environment Inspector</button>
     <button class="tab-btn" data-tab="stats-tab">Environment Stats</button>
   </div>
  <div class="tab-content">
    <div id="map-tab" class="tab-pane active">
      <div class="panel map-panel">
        <div class="map-wrap">
          <svg id="map" viewBox="0 0 {svg_w} {svg_h}" preserveAspectRatio="xMidYMid meet">
            <g id="map-zoom-group">
              <image href="/map.png" x="0" y="0" width="{svg_w}" height="{svg_h}" preserveAspectRatio="none" />
               <g id="lava-layer"></g>
               <g id="env-layer"></g>
               <g id="highlight-layer"></g>
            </g>
          </svg>
           <div class="map-controls">
             <div class="zoom-h">
               <button id="zoom-in" title="Zoom in (+)">+</button>
               <button id="zoom-reset" title="Reset zoom">R</button>
               <button id="zoom-out" title="Zoom out (-)">-</button>
             </div>
             <button id="toggle-lava" title="Toggle lava placement mode (L)" class="toggle-active">🔥</button>
           </div>
            <div class="status-overlay" id="status">waiting…</div>
            <div class="status-overlay" id="lava-mode-status"></div>
        </div>
        <div class="meta">Scroll to zoom, drag to pan. Click map in lava placement mode to add/remove 16x16 tile zones. 🔥 toggles placement mode.</div>
      </div>
     </div>
     <div id="mosaic-tab" class="tab-pane">
       <div class="panel mosaic-panel">
         <div class="header">
           <div class="title">Mosaic Stream</div>
           <div class="badge" id="mosaic-status">waiting…</div>
         </div>
         <div class="mosaic-content">
           <img id="mosaic-image" src="" alt="Mosaic stream" />
         </div>
       </div>
     </div>
     <div id="dynamic-mosaic-tab" class="tab-pane">
       <div class="panel mosaic-panel">
         <div class="header">
           <div class="title">Dynamic Mosaic - Individual Streams</div>
           <div class="badge" id="dynamic-mosaic-status">waiting…</div>
         </div>
         <div style="display: flex; align-items: center; gap: 16px; padding: 8px 12px; background: rgba(0,0,0,0.2); border-radius: 6px; margin-bottom: 8px;">
           <label style="color: #a0aec0; font-size: 0.85rem;">Visible Environments:</label>
           <input type="range" id="dynamic-mosaic-page-size" min="6" max="100" step="2" value="42" style="flex: 1; accent-color: var(--accent);" />
           <span id="dynamic-mosaic-page-size-value" style="color: var(--accent); font-weight: 600; min-width: 3ch;">42</span>
           <label style="margin-left: 20px; color: #a0aec0; font-size: 0.85rem; display: flex; align-items: center; gap: 6px; cursor: pointer;">
             <input type="checkbox" id="dynamic-mosaic-live-update" checked style="accent-color: var(--accent);" />
             Update Live
           </label>
           <button id="dynamic-mosaic-prev-btn" style="background: var(--panel); color: var(--text); border: 1px solid rgba(255,255,255,0.15); padding: 4px 12px; border-radius: 4px; cursor: pointer; margin-left: 20px;">◀ Prev</button>
           <span id="dynamic-mosaic-page-indicator" style="color: #718096; font-size: 0.85rem;">Page 1</span>
           <button id="dynamic-mosaic-next-btn" style="background: var(--panel); color: var(--text); border: 1px solid rgba(255,255,255,0.15); padding: 4px 12px; border-radius: 4px; cursor: pointer;">Next ▶</button>
           <span id="dynamic-mosaic-bandwidth" style="margin-left: auto; color: #718096; font-size: 0.85rem;">Bandwidth: --</span>
         </div>
         <div class="mosaic-content" id="dynamic-mosaic-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px; width: 100%;"></div>
       </div>
     </div>
     <div id="inspector-tab" class="tab-pane">
       <div class="panel stats-panel">
         <div class="header">
           <div class="title">Environment Inspector</div>
           <div class="badge" id="inspector-env-select-container">
             <select id="inspector-env-select" style="background: var(--panel); color: var(--accent); border: 1px solid rgba(255,255,255,0.15); padding: 4px 8px; border-radius: 4px;"></select>
           </div>
         </div>
         <div class="stats-scroll" style="overflow: auto; padding: 12px;">
           <div id="inspector-content" style="display: flex; gap: 16px; flex-wrap: wrap;">
             <div style="flex: 0 0 320px;">
               <img id="inspector-screen" src="" alt="Emulator screen" style="width: 100%; border-radius: 8px; border: 1px solid rgba(255,255,255,0.08);" />
             </div>
             <div style="flex: 1; min-width: 300px;">
               <div id="inspector-details" style="color: #eef4ff; font-family: monospace; white-space: pre-wrap;"></div>
             </div>
           </div>
         </div>
       </div>
     </div>
     <div id="stats-tab" class="tab-pane">
       <div class="panel stats-panel">
         <div class="header">
           <div class="title">Live environment stats</div>
           <div class="badge"><span id="env-count">0</span> envs</div>
         </div>
         <div class="stats-scroll">
           <table>
             <thead>
                <tr>
                  <th>Env</th>
                  <th>HP</th>
                  <th>Pokémon</th>
                  <th>Trainer Wins</th>
                  <th>Wild Wins</th>
                  <th>Deaths/KO</th>
                  <th>Items Won</th>
                  <th>Walls</th>
                  <th>Steps</th>
                  <th>Map</th>
                  <th>Game XY</th>
                  <th>Score</th>
                </tr>
             </thead>
             <tbody id="stats-body"></tbody>
           </table>
          </div>
        </div>
      </div>
      <div id="config-tab" class="tab-pane">
        <div class="panel config-panel">
          <div class="header">
            <div class="title">Environment Config</div>
            <div class="badge" id="config-status">idle</div>
          </div>
          <div class="config-form">
            <label>
              <span>Max Steps</span>
              <input type="range" id="max-steps" min="600" max="12000" step="120" value="2880" />
              <span id="max-steps-value">2880</span>
            </label>
            <label>
              <input type="checkbox" id="save-on-catch" checked />
              Enable Save on Catch
            </label>
            <label>
              <input type="checkbox" id="perfect-sound" checked />
              Perfect DV Sound Effect
            </label>
            <button id="apply-config-btn">Apply Config</button>
          </div>
        </div>
      </div>
      <div id="inspector-tab" class="tab-pane">
        <div class="panel inspector-panel">
          <div class="header">
            <div class="title">Observation Inspector</div>
            <div class="badge" id="inspector-status">idle</div>
          </div>
          <div class="inspector-content">
            <table>
              <thead>
                <tr><th>Address</th><th>Value</th><th>Description</th></tr>
              </thead>
              <tbody id="inspector-body"></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>

  <script>
    const mapSvg = document.getElementById('map');
    const envLayer = document.getElementById('env-layer');
    const lavaLayer = document.getElementById('lava-layer');
    const statsBody = document.getElementById('stats-body');
    const envCount = document.getElementById('env-count');
    const status = document.getElementById('status');
    const mosaicImage = document.getElementById('mosaic-image');
    const mosaicStatus = document.getElementById('mosaic-status');
    const dynamicMosaicGrid = document.getElementById('dynamic-mosaic-grid');
    const dynamicMosaicStatus = document.getElementById('dynamic-mosaic-status');
    const dynamicMosaicPageSize = document.getElementById('dynamic-mosaic-page-size');
    const dynamicMosaicPageSizeValue = document.getElementById('dynamic-mosaic-page-size-value');
    const dynamicMosaicPrevBtn = document.getElementById('dynamic-mosaic-prev-btn');
    const dynamicMosaicNextBtn = document.getElementById('dynamic-mosaic-next-btn');
    const dynamicMosaicPageIndicator = document.getElementById('dynamic-mosaic-page-indicator');
    const inspectorEnvSelect = document.getElementById('inspector-env-select');
    const inspectorScreen = document.getElementById('inspector-screen');
    const inspectorDetails = document.getElementById('inspector-details');
    let mosaicObjectUrl = null;
    let dynamicMosaicObjectUrls = {{}};
    let inspectorObjectUrl = null;
    let selectedInspectorEnv = 0;
    let dynamicMosaicCurrentPage = 0;
    let dynamicMosaicPageSizeVal = 42;
    mosaicImage.addEventListener('error', function() {{
      mosaicStatus.textContent = 'offline';
    }});
    const zoomInBtn = document.getElementById('zoom-in');
    const zoomOutBtn = document.getElementById('zoom-out');
    const zoomResetBtn = document.getElementById('zoom-reset');
    const toggleLavaBtn = document.getElementById('toggle-lava');
    const lavaModeStatus = document.getElementById('lava-mode-status');
    var maxStepsSlider = document.getElementById('max-steps');
    var maxStepsValue = document.getElementById('max-steps-value');
    var saveOnCatchCheckbox = document.getElementById('save-on-catch');
    var applyConfigBtn = document.getElementById('apply-config-btn');
    var configStatus = document.getElementById('config-status');
    var inspectorBody = document.getElementById('inspector-body');
    var inspectorStatus = document.getElementById('inspector-status');
    const tabBtns = document.querySelectorAll('.tab-bar .tab-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');

    if (maxStepsSlider) {{
      maxStepsSlider.addEventListener('input', function() {{
        maxStepsValue.textContent = String(maxStepsSlider.value);
      }});
    }}

    if (applyConfigBtn) {{
      applyConfigBtn.addEventListener('click', function() {{
        var payload = {{
          max_steps: parseInt(maxStepsSlider.value, 10),
          save_on_catch: saveOnCatchCheckbox.checked,
        }};
        configStatus.textContent = 'saving...';
        fetch('/api/config', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify(payload)
        }})
          .then(function(r) {{ return r.json(); }})
          .then(function(data) {{
            configStatus.textContent = data.status || 'saved';
          }})
          .catch(function() {{
            configStatus.textContent = 'error';
          }});
      }});
    }}

    function renderInspector(data) {{
      inspectorBody.innerHTML = '';
      if (!data || !data.inspector || Array.isArray(data.inspector)) {{
        if (Array.isArray(data.inspector)) {{
          data.inspector.forEach(function(entry) {{
            var cls = entry.changed ? ' changed' : '';
            var row = '<tr class="' + cls + '">' +
              '<td>0x' + entry.address.toString(16).toUpperCase().padStart(4, '0') + '</td>' +
              '<td>' + entry.value + '</td>' +
              '<td>' + entry.description + '</td>' +
              '</tr>';
            inspectorBody.insertAdjacentHTML('beforeend', row);
          }});
        }}
        inspectorStatus.textContent = 'live';
      }} else {{
        inspectorStatus.textContent = 'offline';
      }}
    }}

    function isConfigTabActive() {{
      return document.getElementById('config-tab').classList.contains('active');
    }}

    function isInspectorTabActive() {{
      return document.getElementById('inspector-tab').classList.contains('active');
    }}
     let zoomScale = 1;
    let panX = 0;
    let panY = 0;
    let isPanning = false;
    let lavaPlacementMode = true;
    let clickStart = null;
    let dragStart = null;
    let panStart = {{ x: 0, y: 0 }};
    let lastState = {{ envs: [], lava_zones: [] }};
    const mapGroup = document.getElementById('map-zoom-group');
    const highlightLayer = document.getElementById('highlight-layer');
    const lavaHighlight = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    lavaHighlight.setAttribute('width', 16);
    lavaHighlight.setAttribute('height', 16);
    lavaHighlight.setAttribute('fill', '#ff6b6b');
    lavaHighlight.setAttribute('opacity', '0.3');
    lavaHighlight.setAttribute('stroke', '#ff6b6b');
    lavaHighlight.setAttribute('stroke-width', '1');
    lavaHighlight.setAttribute('pointer-events', 'none');
    highlightLayer.appendChild(lavaHighlight);
    lavaHighlight.style.display = 'none';
    const selectRect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
    selectRect.setAttribute('fill', '#ff6b6b');
    selectRect.setAttribute('opacity', '0.15');
    selectRect.setAttribute('stroke', '#ff6b6b');
    selectRect.setAttribute('stroke-width', '1');
    selectRect.setAttribute('stroke-dasharray', '4,2');
    selectRect.setAttribute('pointer-events', 'none');
    highlightLayer.appendChild(selectRect);
    selectRect.style.display = 'none';

    function applyTransform() {{
      mapGroup.setAttribute('transform', 'translate(' + panX + ',' + panY + ') scale(' + zoomScale + ')');
    }}

    function setZoom(delta) {{
      const newScale = zoomScale * delta;
      if (newScale < 0.4 || newScale > 8) return;
      zoomScale = newScale;
      applyTransform();
    }}

    function resetZoom() {{
      zoomScale = 1;
      panX = 0;
      panY = 0;
      applyTransform();
    }}

    function hpChip(value) {{
      const label = (value * 100).toFixed(0) + '%';
      if (value >= 0.6) return '<span class="chip good">' + label + '</span>';
      if (value >= 0.25) return '<span class="chip warn">' + label + '</span>';
      return '<span class="chip bad">' + label + '</span>';
    }}

     function renderMap(data) {{
      lastState = data;
      envLayer.innerHTML = '';
      lavaLayer.innerHTML = '';
      const lavaZones = data.lava_zones || [];
      for (const zone of lavaZones) {{
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', zone[0]);
        rect.setAttribute('y', zone[1]);
        rect.setAttribute('width', 16);
        rect.setAttribute('height', 16);
        rect.setAttribute('fill', '#ff6b6b');
        rect.setAttribute('opacity', '0.5');
        lavaLayer.appendChild(rect);
      }}

      for (const env of data.envs || []) {{
        const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        circle.setAttribute('cx', env.x);
        circle.setAttribute('cy', env.y);
        circle.setAttribute('r', 6);
        circle.setAttribute('fill', '#67f39b');
        circle.setAttribute('stroke', '#ffffff');
        circle.setAttribute('stroke-width', 1.2);
        const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
        label.setAttribute('x', env.x + 10);
        label.setAttribute('y', env.y - 8);
        label.setAttribute('fill', '#eaf2ff');
        label.setAttribute('font-size', '12');
        label.textContent = 'E' + (env.env_index + 1);
        envLayer.appendChild(circle);
        envLayer.appendChild(label);
      }}
    }}

    function renderStats(data) {{
      const envs = data.envs || [];
      statsBody.innerHTML = envs.map(function(env) {{
        var hpHtml = hpChip(env.hp);
        var scoreText = (env.score >= 0 ? '+' : '') + env.score.toFixed(1);
        return '<tr><td>Env ' + (env.env_index + 1) + '</td><td>' + hpHtml + '</td><td>' + env.pkmn + '</td><td>' + env.trainer_wins + '</td><td>' + env.wild_wins + '</td><td>' + env.deaths + '</td><td>' + env.item_won_count + '</td><td>' + env.walls + '</td><td>' + env.steps + '</td><td>' + env.map_id.toString(16).toUpperCase().padStart(2, '0') + '</td><td>' + (env.raw_x ?? 0) + ',' + (env.raw_y ?? 0) + '</td><td>' + scoreText + '</td></tr>';
      }}).join('');
      envCount.textContent = String(envs.length);
    }}

    function updateInspectorSelect(envs) {{
      const currentVal = inspectorEnvSelect.value;
      inspectorEnvSelect.innerHTML = envs.map(function(env) {{
        return '<option value="' + env.env_index + '">Env ' + (env.env_index + 1) + ' - HP: ' + (env.hp * 100).toFixed(0) + '%</option>';
      }}).join('');
      if (currentVal !== '' && envs.some(e => e.env_index == currentVal)) {{
        inspectorEnvSelect.value = currentVal;
      }}
      selectedInspectorEnv = parseInt(inspectorEnvSelect.value) || 0;
    }}

    inspectorEnvSelect.addEventListener('change', function() {{
      selectedInspectorEnv = parseInt(this.value) || 0;
      updateInspectorScreen();
    }});

    function update() {{
      fetch('/api/state')
        .then(function(r) {{ return r.json(); }})
        .then(function(data) {{
          if (!data || !Array.isArray(data.envs)) return;
          status.textContent = 'live';
          renderMap(data);
          renderStats(data);
        }})
        .catch(function() {{
          status.textContent = 'offline';
        }});
      if (document.getElementById('mosaic-tab').classList.contains('active')) {{
        updateMosaic();
      }}
      if (isInspectorTabActive()) {{
        fetch('/api/inspector')
          .then(function(r) {{ return r.json(); }})
          .then(function(data) {{
            renderInspector(data);
          }})
          .catch(function() {{
            inspectorStatus.textContent = 'offline';
          }});
      }}
    }}

    mapSvg.addEventListener('wheel', function(event) {{
      event.preventDefault();
      event.stopPropagation();
      const delta = event.deltaY < 0 ? 1.15 : 0.85;
      setZoom(delta);
    }}, {{ passive: false }});

     mapSvg.addEventListener('mousedown', function(event) {{
       if (event.button !== 0) return;
       if (lavaPlacementMode) {{
         dragStart = {{ x: event.clientX, y: event.clientY }};
         clickStart = null;
         isPanning = false;
         return;
       }}
       clickStart = {{ x: event.clientX, y: event.clientY }};
       isPanning = true;
       panStart = {{ x: event.clientX, y: event.clientY }};
       mapSvg.classList.add('grabbing');
     }});

     document.addEventListener('mousemove', function(event) {{
       if (lavaPlacementMode && dragStart) {{
         const rect = mapSvg.getBoundingClientRect();
         const svgX = ((event.clientX - rect.left) / rect.width) * {svg_w};
         const svgY = ((event.clientY - rect.top) / rect.height) * {svg_h};
         const invScale = 1 / zoomScale;
         const viewBoxX = (svgX - panX) * invScale;
         const viewBoxY = (svgY - panY) * invScale;
         const startRect = mapSvg.getBoundingClientRect();
         const startSvgX = ((dragStart.x - startRect.left) / startRect.width) * {svg_w};
         const startSvgY = ((dragStart.y - startRect.top) / startRect.height) * {svg_h};
         const startViewX = (startSvgX - panX) * invScale;
         const startViewY = (startSvgY - panY) * invScale;
         const startX = Math.min(startViewX, viewBoxX);
         const startY = Math.min(startViewY, viewBoxY);
         const endX = Math.max(startViewX, viewBoxX);
         const endY = Math.max(startViewY, viewBoxY);
         selectRect.setAttribute('x', startX);
         selectRect.setAttribute('y', startY);
         selectRect.setAttribute('width', endX - startX);
         selectRect.setAttribute('height', endY - startY);
          selectRect.style.display = 'block';
          lavaHighlight.style.display = 'none';
          return;
        }}
        if (!isPanning && !lavaPlacementMode) return;
       if (isPanning) {{
         const dx = event.clientX - panStart.x;
         const dy = event.clientY - panStart.y;
         panX += dx;
         panY += dy;
         panStart = {{ x: event.clientX, y: event.clientY }};
         applyTransform();
       }}
       if (lavaPlacementMode) {{
         const rect = mapSvg.getBoundingClientRect();
         const svgX = ((event.clientX - rect.left) / rect.width) * {svg_w};
         const svgY = ((event.clientY - rect.top) / rect.height) * {svg_h};
         const invScale = 1 / zoomScale;
         const viewBoxX = (svgX - panX) * invScale;
         const viewBoxY = (svgY - panY) * invScale;
         const tileX = Math.round(viewBoxX / 16) * 16;
         const tileY = Math.round(viewBoxY / 16) * 16;
         lavaHighlight.setAttribute('x', tileX);
         lavaHighlight.setAttribute('y', tileY);
         lavaHighlight.style.display = 'block';
       }}
     }});

      document.addEventListener('mouseup', function(event) {{
        if (lavaPlacementMode && dragStart) {{
          if (selectRect.style.display !== 'none') {{
            const rect = mapSvg.getBoundingClientRect();
            const invScale = 1 / zoomScale;
            const startSvgX = ((dragStart.x - rect.left) / rect.width) * {svg_w};
            const startSvgY = ((dragStart.y - rect.top) / rect.height) * {svg_h};
            const startViewX = (startSvgX - panX) * invScale;
            const startViewY = (startSvgY - panY) * invScale;
            const endSvgX = ((event.clientX - rect.left) / rect.width) * {svg_w};
            const endSvgY = ((event.clientY - rect.top) / rect.height) * {svg_h};
            const endViewX = (endSvgX - panX) * invScale;
            const endViewY = (endSvgY - panY) * invScale;
            const startX = Math.min(startViewX, endViewX);
            const startY = Math.min(startViewY, endViewY);
            const endX = Math.max(startViewX, endViewX);
            const endY = Math.max(startViewY, endViewY);
            const zones = [];
            for (let tx = Math.floor(startX / 16); tx <= Math.floor(endX / 16); tx++) {{
              for (let ty = Math.floor(startY / 16); ty <= Math.floor(endY / 16); ty++) {{
                zones.push({{ x: tx * 16, y: ty * 16 }});
              }}
            }}
            console.log('[LAVA DEBUG] Drag select zones:', zones.length, 'tiles, first:', zones[0]);
            fetch('/api/lava', {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify({{ zones: zones }})
            }}).then(function(r) {{ return r.json(); }}).then(function(data) {{
              console.log('[LAVA DEBUG] Lava zones after drag:', data.lava_zones);
            }}).catch(function() {{}});
          }} else {{
            const rect = mapSvg.getBoundingClientRect();
            const svgX = ((event.clientX - rect.left) / rect.width) * {svg_w};
            const svgY = ((event.clientY - rect.top) / rect.height) * {svg_h};
            const invScale = 1 / zoomScale;
            const viewBoxX = (svgX - panX) * invScale;
            const viewBoxY = (svgY - panY) * invScale;
            const tileX = Math.round(viewBoxX / 16) * 16;
            const tileY = Math.round(viewBoxY / 16) * 16;
            console.log('[LAVA DEBUG] Single click tile:', tileX, tileY);
            fetch('/api/lava', {{
              method: 'POST',
              headers: {{ 'Content-Type': 'application/json' }},
              body: JSON.stringify({{ x: tileX, y: tileY }})
            }}).then(function(r) {{ return r.json(); }}).then(function(data) {{
              console.log('[LAVA DEBUG] Lava zones after click:', data.lava_zones);
            }}).catch(function() {{}});
          }}
          dragStart = null;
          selectRect.style.display = 'none';
          return;
        }}
        if (!isPanning) return;
        isPanning = false;
        clickStart = null;
        mapSvg.classList.remove('grabbing');
      }});

    function isMapTabActive() {{
      return document.getElementById('map-tab').classList.contains('active');
    }}

    document.addEventListener('keydown', function(event) {{
      if (event.key === 'l' && (event.ctrlKey || event.metaKey)) {{
        event.preventDefault();
        updateLavaToggle();
      }}
      if (isMapTabActive() && (event.key === '+' || event.key === '-' || event.key === '=')) {{
        event.preventDefault();
        if (event.key === '+' || event.key === '=') {{
          setZoom(1.15);
        }} else {{
          setZoom(0.85);
        }}
      }}
      if (isMapTabActive() && event.key === 'r' && (event.ctrlKey || event.metaKey)) {{
        event.preventDefault();
        resetZoom();
      }}
    }});

    zoomInBtn.addEventListener('click', function() {{ setZoom(1.15); }});
    zoomOutBtn.addEventListener('click', function() {{ setZoom(0.85); }});
    zoomResetBtn.addEventListener('click', function() {{ resetZoom(); }});

    function updateLavaToggle() {{
      lavaPlacementMode = !lavaPlacementMode;
      toggleLavaBtn.classList.toggle('toggle-active', lavaPlacementMode);
      if (lavaPlacementMode) {{
        lavaModeStatus.textContent = 'LAVA PLACEMENT MODE - click to place/remove zones';
        mapSvg.style.cursor = 'crosshair';
      }} else {{
        lavaModeStatus.textContent = '';
        mapSvg.style.cursor = '';
        lavaHighlight.style.display = 'none';
      }}
    }}

     toggleLavaBtn.addEventListener('click', updateLavaToggle);

    if (lavaPlacementMode) {{
      lavaModeStatus.textContent = 'LAVA PLACEMENT MODE - click to place/remove zones';
      mapSvg.style.cursor = 'crosshair';
    }}

     tabBtns.forEach(function(btn) {{
       btn.addEventListener('click', function() {{
         tabBtns.forEach(function(b) {{ b.classList.remove('active'); }});
         tabPanes.forEach(function(p) {{ p.classList.remove('active'); }});
         btn.classList.add('active');
         const target = btn.getAttribute('data-tab');
         document.getElementById(target).classList.add('active');
         if (target === 'mosaic-tab') {{
           updateMosaic();
         }}
       }});
     }});

    function updateMosaic() {{
      fetch('/api/mosaic', {{ cache: 'no-store' }})
        .then(function(r) {{
          if (r.status === 204) {{
            mosaicStatus.textContent = 'no stream';
            if (mosaicObjectUrl) {{
              URL.revokeObjectURL(mosaicObjectUrl);
              mosaicObjectUrl = null;
            }}
            mosaicImage.removeAttribute('src');
            return null;
          }}
          return r.blob();
        }})
        .then(function(blob) {{
          if (!blob) return;
          if (mosaicObjectUrl) {{
            URL.revokeObjectURL(mosaicObjectUrl);
          }}
          mosaicObjectUrl = URL.createObjectURL(blob);
          mosaicImage.src = mosaicObjectUrl;
          mosaicStatus.textContent = 'live';
        }})
        .catch(function() {{
          mosaicStatus.textContent = 'offline';
        }});
    }}

    // Dynamic mosaic pagination controls
    const dynamicMosaicLiveUpdate = document.getElementById('dynamic-mosaic-live-update');
    const dynamicMosaicBandwidth = document.getElementById('dynamic-mosaic-bandwidth');
    let bandwidthHistory = [];
    let lastBytesSent = 0;
    let lastBandwidthTime = Date.now();
    
    dynamicMosaicPageSize.addEventListener('input', function() {{
      dynamicMosaicPageSizeVal = parseInt(this.value, 10);
      dynamicMosaicPageSizeValue.textContent = dynamicMosaicPageSizeVal.toString();
      dynamicMosaicCurrentPage = 0;
      if (document.getElementById('dynamic-mosaic-tab').classList.contains('active')) {{
        const envCount = lastState.envs ? lastState.envs.length : 0;
        if (envCount > 0) {{
          updateDynamicMosaic(envCount);
        }}
      }}
    }});

    dynamicMosaicPrevBtn.addEventListener('click', function() {{
      if (dynamicMosaicCurrentPage > 0) {{
        dynamicMosaicCurrentPage--;
        if (document.getElementById('dynamic-mosaic-tab').classList.contains('active')) {{
          const envCount = lastState.envs ? lastState.envs.length : 0;
          if (envCount > 0) {{
            updateDynamicMosaic(envCount);
          }}
        }}
      }}
    }});

    dynamicMosaicNextBtn.addEventListener('click', function() {{
      const envCount = lastState.envs ? lastState.envs.length : 0;
      const maxPage = Math.max(0, Math.ceil(envCount / dynamicMosaicPageSizeVal) - 1);
      if (dynamicMosaicCurrentPage < maxPage) {{
        dynamicMosaicCurrentPage++;
        if (document.getElementById('dynamic-mosaic-tab').classList.contains('active')) {{
          const envCount = lastState.envs ? lastState.envs.length : 0;
          if (envCount > 0) {{
            updateDynamicMosaic(envCount);
          }}
        }}
      }}
    }});

    function updateDynamicMosaic(envCount) {{
      const grid = document.getElementById('dynamic-mosaic-grid');
      if (!grid) return;

      // Calculate pagination
      const maxPage = Math.max(0, Math.ceil(envCount / dynamicMosaicPageSizeVal) - 1);
      if (dynamicMosaicCurrentPage > maxPage) {{
        dynamicMosaicCurrentPage = maxPage;
      }}
      const startIndex = dynamicMosaicCurrentPage * dynamicMosaicPageSizeVal;
      const endIndex = Math.min(startIndex + dynamicMosaicPageSizeVal, envCount);
      const visibleCount = endIndex - startIndex;
      
      // Update page indicator
      dynamicMosaicPageIndicator.textContent = 'Page ' + (dynamicMosaicCurrentPage + 1) + ' of ' + (maxPage + 1);

      // Clear existing cells if count changed or we're on a different page
      const currentCells = grid.querySelectorAll('.dynamic-mosaic-cell');
      if (currentCells.length !== visibleCount) {{
        grid.innerHTML = '';
        for (let i = startIndex; i < endIndex; i++) {{
          const cell = document.createElement('div');
          cell.className = 'dynamic-mosaic-cell';
          cell.onclick = (function(idx) {{
            return function() {{
              selectInspectorEnv(idx);
            }};
          }})(i);

          const img = document.createElement('img');
          img.id = 'dynamic-frame-' + i;
          img.alt = 'Env ' + (i + 1);
          img.addEventListener('error', function() {{
            this.style.opacity = '0.3';
          }});

          const label = document.createElement('div');
          label.style.cssText = 'position: absolute; top: 4px; left: 4px; background: rgba(15, 22, 34, 0.85); padding: 2px 6px; border-radius: 4px; font-size: 0.75rem; color: var(--accent); font-weight: 600;';
          label.textContent = 'E' + (i + 1);

          cell.appendChild(img);
          cell.appendChild(label);
          grid.appendChild(cell);
        }}
      }}

      // Update each visible frame
      for (let i = startIndex; i < endIndex; i++) {{
        const img = document.getElementById('dynamic-frame-' + i);
        if (img) {{
          const newUrl = '/api/individual/' + i + '?t=' + Date.now();
          img.src = newUrl;
        }}
      }}
      dynamicMosaicStatus.textContent = 'live (' + envCount + ' streams, showing ' + visibleCount + ')';
    }}

    function calculateBandwidth() {{
      const now = Date.now();
      const timeDiff = (now - lastBandwidthTime) / 1000;
      if (timeDiff < 1) return;
      
      // Estimate based on image size (PNG ~10KB per 160x144 frame) and update rate
      const visibleEnvs = parseInt(document.getElementById('dynamic-mosaic-page-size').value, 10);
      const isLive = document.getElementById('dynamic-mosaic-live-update').checked;
      if (!isLive) {{
        dynamicMosaicBandwidth.textContent = 'Bandwidth: Paused';
        return;
      }}
      
      // Each PNG frame is roughly 8-15KB, updating at 5Hz (200ms)
      const estimatedBytesPerFrame = 12000;
      const framesPerSecond = 5;
      const totalBytesPerSecond = visibleEnvs * estimatedBytesPerFrame * framesPerSecond;
      
      let bandwidthStr;
      if (totalBytesPerSecond > 1000000) {{
        bandwidthStr = (totalBytesPerSecond / 1000000).toFixed(2) + ' MB/s';
      }} else if (totalBytesPerSecond > 1000) {{
        bandwidthStr = (totalBytesPerSecond / 1000).toFixed(2) + ' KB/s';
      }} else {{
        bandwidthStr = totalBytesPerSecond.toFixed(0) + ' B/s';
      }}
      dynamicMosaicBandwidth.textContent = 'Bandwidth: ~' + bandwidthStr;
    }}

    function selectInspectorEnv(envIndex) {{
      selectedInspectorEnv = envIndex;
      inspectorEnvSelect.value = envIndex.toString();
      updateInspectorScreen();
      updateSelectionHighlight();
    }}

    function updateSelectionHighlight() {{
      // Highlight selected cell in dynamic mosaic
      document.querySelectorAll('.dynamic-mosaic-cell').forEach(function(cell, idx) {{
        if (idx === selectedInspectorEnv) {{
          cell.style.borderColor = 'var(--accent)';
          cell.style.boxShadow = '0 0 12px rgba(110, 231, 255, 0.4)';
        }} else {{
          cell.style.borderColor = 'rgba(255,255,255,0.08)';
          cell.style.boxShadow = 'none';
        }}
      }});
      
      // Update selection rect on map
      const envs = lastState.envs || [];
      const selectedEnv = envs.find(e => e.env_index === selectedInspectorEnv);
      if (selectedEnv && selectedEnv.x !== undefined) {{
        selectRect.setAttribute('x', selectedEnv.x - 8);
        selectRect.setAttribute('y', selectedEnv.y - 8);
        selectRect.setAttribute('width', 16);
        selectRect.setAttribute('height', 16);
        selectRect.style.display = 'block';
      }} else {{
        selectRect.style.display = 'none';
      }}
    }}

    function updateInspectorScreen() {{
      const img = document.getElementById('inspector-screen');
      if (!img) return;
      
      const newUrl = '/api/individual/' + selectedInspectorEnv + '?t=' + Date.now();
      if (inspectorObjectUrl) {{
        URL.revokeObjectURL(inspectorObjectUrl);
      }}
      
      // Fetch the frame as blob
      fetch(newUrl, {{ cache: 'no-store' }})
        .then(function(r) {{
          if (r.status === 204) {{
            img.removeAttribute('src');
            return null;
          }}
          return r.blob();
        }})
        .then(function(blob) {{
          if (!blob) return;
          inspectorObjectUrl = URL.createObjectURL(blob);
          img.src = inspectorObjectUrl;
        }})
        .catch(function() {{}});
      
      updateInspectorDetails();
    }}

    function updateInspectorDetails() {{
      const envs = lastState.envs || [];
      const env = envs.find(e => e.env_index === selectedInspectorEnv);
      if (!env) {{
        inspectorDetails.textContent = 'No data available';
        return;
      }}
      
      let details = 'Environment #' + (env.env_index + 1) + '\\n';
      details += '='.repeat(30) + '\\n\\n';
      details += 'HP: ' + (env.hp * 100).toFixed(1) + '%\\n';
      details += 'Pokemon Count: ' + env.pkmn + '\\n';
      details += 'Trainer Wins: ' + env.trainer_wins + '\\n';
      details += 'Wild Wins: ' + env.wild_wins + '\\n';
      details += 'Wall Collisions: ' + env.walls + '\\n';
      details += 'Steps: ' + env.steps + '\\n';
      details += 'Map ID: 0x' + env.map_id.toString(16).toUpperCase().padStart(2, '0') + '\\n';
      details += 'Game Position: (' + env.raw_x + ', ' + env.raw_y + ')\\n';
      details += 'Global Position: (' + env.x + ', ' + env.y + ')\\n';
      details += 'Score: ' + (env.score >= 0 ? '+' : '') + env.score.toFixed(1) + '\\n';
      
      if (env.position_error) {{
        details += '\\n[ERROR] ' + env.position_error + '\\n';
      }}
      
      inspectorDetails.textContent = details;
    }}

    update();
    setInterval(update, 500);
    
    // Update dynamic mosaic at higher frequency for smoother streaming
    setInterval(function() {{
      if (document.getElementById('dynamic-mosaic-tab').classList.contains('active')) {{
        const isLive = document.getElementById('dynamic-mosaic-live-update').checked;
        if (isLive) {{
          const envCount = lastState.envs ? lastState.envs.length : 0;
          if (envCount > 0) {{
            updateDynamicMosaic(envCount);
          }}
        }}
      }}
      calculateBandwidth();
    }}, 200);
    
    // Update inspector when its tab is active
    setInterval(function() {{
      if (document.getElementById('inspector-tab').classList.contains('active')) {{
        updateInspectorScreen();
        updateSelectionHighlight();
      }}
    }}, 300);
  </script>
</body>
</html>
""".format(svg_w=svg_w, svg_h=svg_h)
                encoded = html.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

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
