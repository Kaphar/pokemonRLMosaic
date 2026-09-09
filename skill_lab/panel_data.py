"""Shared data and rendering helpers for the Skill Lab debug panels."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import math
import time

import cv2
import numpy as np

from skill_lab.bag_reader import Gen1PlayerReader
from skill_lab.party_reader import Gen1PartyReader, PyBoyMemoryReader

MAP_N_ADDRESS = 0xD35E
X_POS_ADDRESS = 0xD362
Y_POS_ADDRESS = 0xD361
BADGE_COUNT_ADDRESS = 0xD356
MENU_HANDLER_START = 0xCC26
MENU_HANDLER_END = 0xCC2F

PARTY_ADDRESSES = {
    "partyAddr": Gen1PartyReader.PARTY_ADDRESS,
    "partySlotsCounterAddr": Gen1PartyReader.PARTY_SIZE_ADDRESS,
    "partySpeciesAddr": Gen1PartyReader.PARTY_SPECIES_ADDRESS,
    "partyNicknamesAddr": Gen1PartyReader.PARTY_NICKNAMES_ADDRESS,
}

positioned_windows: set[str] = set()


def get_screen_size() -> tuple[int, int]:
    """Return the primary screen dimensions (width, height) in pixels."""
    try:
        import ctypes
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except (AttributeError, OSError):
        return 1920, 1080


def address_range(start: int, end: int | None = None, *, offsets: Sequence[int] | None = None) -> list[int]:
    """Return a list of addresses from a start address, a range, or an explicit offset list."""
    start = int(start)
    if offsets is not None:
        return [start + int(offset) for offset in offsets]
    if end is None:
        return [start]
    end = int(end)
    if start <= end:
        return list(range(start, end + 1))
    return list(range(start, end - 1, -1))


def read_memory_values(memory: Any, addresses: Sequence[int]) -> dict[int, int]:
    """Read a list of addresses into a stable dictionary keyed by address."""
    values: dict[int, int] = {}
    for address in addresses:
        numeric_address = int(address)
        if hasattr(memory, "get"):
            value = memory.get(numeric_address, 0)
        else:
            value = memory[numeric_address]
        values[numeric_address] = int(value)
    return values


class MemoryWatchTracker:
    """Track address values and highlight when the value changed since the last read."""

    def __init__(self, addresses: Sequence[int] | None = None) -> None:
        self.addresses = list(dict.fromkeys(int(address) for address in (addresses or [])))
        self._last_values: dict[int, int] = {}
        self._flash_until: dict[int, float] = {}

    def record(self, memory_or_values: Any) -> dict[int, dict[str, Any]]:
        if isinstance(memory_or_values, Mapping):
            current = {address: int(memory_or_values.get(address, 0)) for address in self.addresses}
        else:
            current = read_memory_values(memory_or_values, self.addresses)

        now = time.monotonic()
        snapshot: dict[int, dict[str, Any]] = {}
        for address in self.addresses:
            value = int(current.get(address, 0))
            previous = self._last_values.get(address)
            changed = previous is None or previous != value
            if changed:
                self._flash_until[address] = now + 0.75
            flash = now < self._flash_until.get(address, 0.0)
            snapshot[address] = {
                "address": address,
                "value": value,
                "previous": previous,
                "changed": changed,
                "flash": flash,
            }
            self._last_values[address] = value
        return snapshot

    def clear(self) -> None:
        self._last_values.clear()

    def add_addresses(self, addresses: Sequence[int]) -> None:
        """Add new addresses to track.  Already-present addresses are preserved."""
        for address in addresses:
            address = int(address)
            if address not in self.addresses:
                self.addresses.append(address)

    def remove_addresses(self, addresses: Sequence[int]) -> None:
        """Remove addresses from tracking."""
        address_set = {int(a) for a in addresses}
        self.addresses = [a for a in self.addresses if a not in address_set]
        self._last_values = {k: v for k, v in self._last_values.items() if k not in address_set}
        self._flash_until = {k: v for k, v in self._flash_until.items() if k not in address_set}


def read_panel_data(memory: Any) -> dict[str, Any]:
    """Read the common live data displayed by both inspectors."""
    party_reader = Gen1PartyReader(PyBoyMemoryReader(memory))
    player_reader = Gen1PlayerReader(PyBoyMemoryReader(memory))
    trainer = player_reader.update_trainer_info()
    bag = player_reader.read_bag().get("items", [])
    return {
        "map_id": int(memory[MAP_N_ADDRESS]),
        "map_address": MAP_N_ADDRESS,
        "x": int(memory[X_POS_ADDRESS]),
        "y": int(memory[Y_POS_ADDRESS]),
        "position_addresses": {"x": X_POS_ADDRESS, "y": Y_POS_ADDRESS},
        "badges": int(memory[BADGE_COUNT_ADDRESS]).bit_count(),
        "party": party_reader.read_party(PARTY_ADDRESSES),
        "trainer": trainer or {},
        "bag": bag,
        "stats": {
            "badges": int(memory[BADGE_COUNT_ADDRESS]).bit_count(),
        },
    }


def draw_party_panel(
    image: np.ndarray,
    x: int,
    y: int,
    width: int,
    height: int,
    party: list[dict[str, Any]] | None,
) -> None:
    """Draw the shared party presentation into an existing image."""
    party = party or []
    cv2.putText(image, "Party", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 1)
    row_y = y + 22
    for slot, pokemon in enumerate(party[:6]):
        if pokemon.get("speciesID", 0) == 0:
            continue
        type_names = pokemon.get("type1Name", "?")
        if pokemon.get("type2") != pokemon.get("type1"):
            type_names += f"/{pokemon.get('type2Name', '?')}"
        name = pokemon.get("nickname") or pokemon.get("speciesName", "Unknown")
        header = f"{slot + 1}. {name} ({pokemon.get('speciesName', '?')}) Lv{pokemon.get('level', 0)} {type_names}"
        stats = (
            f"HP {pokemon.get('curHP', 0)}/{pokemon.get('maxHP', 0)}  "
            f"Atk {pokemon.get('attack', 0)} Def {pokemon.get('defense', 0)} "
            f"Spe {pokemon.get('speed', 0)} Sp {pokemon.get('spAttack', 0)}"
        )
        dvs = (
            f"DV HP {pokemon.get('ivHP', 0)} Atk {pokemon.get('ivAttack', 0)} "
            f"Def {pokemon.get('ivDefense', 0)} Spe {pokemon.get('ivSpeed', 0)} "
            f"Sp {pokemon.get('ivSpAttack', 0)}"
        )
        cv2.putText(image, header[: max(1, width // 7)], (x, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (255, 255, 255), 1)
        cv2.putText(image, stats[: max(1, width // 6)], (x, row_y + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.31, (180, 220, 255), 1)
        cv2.putText(image, dvs[: max(1, width // 6)], (x, row_y + 26), cv2.FONT_HERSHEY_SIMPLEX, 0.31, (180, 255, 180), 1)
        cv2.line(image, (x, row_y + 33), (x + width, row_y + 33), (65, 65, 65), 1)
        row_y += 44
        if row_y + 44 > y + height:
            break
    if not party:
        cv2.putText(image, "No Pokemon", (x, y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (150, 150, 150), 1)


def draw_trainer_panel(
    image: np.ndarray,
    x: int,
    y: int,
    width: int,
    trainer: dict[str, Any] | None,
) -> None:
    """Render trainer details in a dedicated, reusable block."""
    trainer = trainer or {}
    cv2.putText(image, "Trainer", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    trainer_line = (
        f"{trainer.get('name', '?')}  ${trainer.get('money', 0)}  "
        f"Coins {trainer.get('coins', 0)}  Badges {trainer.get('badge_count', 0)}/8"
    )
    if not trainer:
        trainer_line = "Not available in this view"
    cv2.putText(image, trainer_line[: max(1, width // 7)], (x, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (255, 230, 160), 1)


def draw_bag_panel(
    image: np.ndarray,
    x: int,
    y: int,
    width: int,
    bag: list[dict[str, Any]] | None,
) -> None:
    """Render the bag contents in a dedicated section."""
    bag = bag or []
    cv2.putText(image, "Bag", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    bag_line = ", ".join(f"{item.get('name', '?')} x{item.get('quantity', 0)}" for item in bag) or "Empty"
    if not bag:
        bag_line = "No bag data available"
    cv2.putText(image, bag_line[: max(1, width // 6)], (x, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.31, (200, 220, 255), 1)


def draw_trainer_bag_panel(
    image: np.ndarray,
    x: int,
    y: int,
    width: int,
    trainer: dict[str, Any] | None,
    bag: list[dict[str, Any]] | None,
) -> None:
    """Backward-compatible combined trainer+bag block."""
    draw_trainer_panel(image, x, y, width, trainer)
    draw_bag_panel(image, x, y + 35, width, bag)


def draw_world_info(image: np.ndarray, x: int, y: int, data: dict[str, Any]) -> None:
    """Draw map identity and player coordinates using shared labels."""
    lines = (
        f"Map {data.get('map_id', 0):02X} ({data.get('map_id', 0)}) @ 0x{data.get('map_address', 0):04X}",
        f"Position X={data.get('x', 0)} Y={data.get('y', 0)} @ 0x{data.get('position_addresses', {}).get('x', 0):04X}/0x{data.get('position_addresses', {}).get('y', 0):04X}",
    )
    for offset, line in enumerate(lines):
        cv2.putText(image, line, (x, y + offset * 18), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 0), 1)


def draw_stats_panel(
    image: np.ndarray,
    x: int,
    y: int,
    width: int,
    stats: dict[str, Any] | None,
) -> None:
    """Render environment or session statistics in a dedicated panel section."""
    cv2.putText(image, "Stats / Env", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (255, 255, 255), 1)
    if not stats:
        cv2.putText(image, "Not available", (x, y + 18), cv2.FONT_HERSHEY_SIMPLEX, 0.32, (180, 180, 180), 1)
        return
    lines = [
        f"Badges: {stats.get('badges', 0)}/8",
        f"Events: {stats.get('events', 'n/a')}",
        f"Steps: {stats.get('steps', 'n/a')}",
        f"HP: {stats.get('hp', 'n/a')}",
        f"Env: {stats.get('env', 'n/a')}",
    ]
    for index, line in enumerate(lines):
        cv2.putText(image, line[: max(1, width // 7)], (x, y + 18 + index * 16), cv2.FONT_HERSHEY_SIMPLEX, 0.31, (200, 240, 255), 1)


def _copy_to_clipboard(text: str) -> bool:
    """Attempt to copy text to the system clipboard.  Returns True on success."""
    if hasattr(cv2, "setClipboard"):
        try:
            cv2.setClipboard(text)
            return True
        except Exception:
            pass
    return False


class MemoryWatchWindow:
    """Persistent, updating memory-watch window with pagination and change feedback.

    Unlike the one-shot ``open_memory_watch_window``, this class is designed to be
    rendered every frame so that values update live.  When there are more
    addresses than fit on a single page, clickable *Prev* / *Next* buttons let
    the user page through the full list.  Each address cell mirrors the visual
    feedback of the compact ``draw_memory_watch_panel``: red text for just-changed
    (flash) values, green borders for changed values, and gray borders otherwise.
    Double-clicking a cell copies ``0xADDR=VALUE`` to the system clipboard.
    Left-clicking a cell tags it with a deep-purple border; changes to tagged
    addresses are logged to the terminal.  Use ``set_range`` to narrow or expand
    the watched range while preserving previously tagged addresses.
    """

    PAGE_SIZE = 40
    COLS = 4
    CELL_W = 200
    CELL_H = 28
    PAD_X = 18
    PAD_Y = 26
    SELECT_COLOR = (100, 0, 200)

    def __init__(self, title: str = "Memory watch details") -> None:
        self.title = title
        self._visible = False
        self._window_created = False
        self._page = 0
        self._button_rects: dict[str, tuple[int, int, int, int]] = {}
        self._cell_rects: dict[int, tuple[int, int, int, int]] = {}
        self._last_snapshot: dict[int, dict[str, Any]] | None = None
        self._selected_addresses: set[int] = set()
        self._selected_values: dict[int, int] = {}
        self._range_addresses: set[int] = set()
        self._start_address: int = 0xCC06
        self._end_address: int = 0xD362
        self._watcher = MemoryWatchTracker()
        self.set_range(self._start_address, self._end_address)

    @property
    def visible(self) -> bool:
        return self._visible

    @property
    def start_address(self) -> int:
        return self._start_address

    @property
    def end_address(self) -> int:
        return self._end_address

    def set_range(self, start_address: int, end_address: int) -> None:
        """Set the address range to watch, preserving previously tagged addresses."""
        self._start_address = int(start_address)
        self._end_address = int(end_address)
        new_addresses = set(address_range(self._start_address, self._end_address))
        to_remove = self._range_addresses - new_addresses
        to_remove -= self._selected_addresses
        self._watcher.remove_addresses(to_remove)
        self._watcher.add_addresses(new_addresses)
        self._range_addresses = new_addresses
        self._page = 0

    def show(self) -> None:
        self._visible = True
        self._page = 0
        if not self._window_created:
            cv2.namedWindow(self.title, cv2.WINDOW_NORMAL)
            cv2.setMouseCallback(self.title, self._on_mouse)
            self._window_created = True

    def hide(self) -> None:
        self._visible = False
        self._page = 0

    def is_open(self) -> bool:
        if not self._window_created:
            return False
        try:
            return cv2.getWindowProperty(self.title, cv2.WND_PROP_VISIBLE) >= 1
        except cv2.error:
            return False

    def close(self) -> None:
        self._visible = False
        self._window_created = False
        self._button_rects.clear()
        self._cell_rects.clear()
        self._last_snapshot = None
        self._selected_addresses.clear()
        self._selected_values.clear()
        try:
            cv2.destroyWindow(self.title)
        except cv2.error:
            pass

    def _on_mouse(self, event: int, x: int, y: int, flags: int, param: Any) -> None:
        if event == cv2.EVENT_LBUTTONDBLCLK:
            for address, rect in self._cell_rects.items():
                bx, by, bw, bh = rect
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    if self._last_snapshot is not None and address in self._last_snapshot:
                        value = int(self._last_snapshot[address]["value"])
                        text = f"0x{address:04X}={value:02X}"
                        if _copy_to_clipboard(text):
                            print(f"Copied {text} to clipboard", flush=True)
                    return
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        for name, rect in self._button_rects.items():
            bx, by, bw, bh = rect
            if bx <= x <= bx + bw and by <= y <= by + bh:
                if name == "prev":
                    self._page = max(0, self._page - 1)
                elif name == "next":
                    self._page += 1
                return
        for address, rect in self._cell_rects.items():
            bx, by, bw, bh = rect
            if bx <= x <= bx + bw and by <= y <= by + bh:
                if address in self._selected_addresses:
                    self._selected_addresses.discard(address)
                    self._selected_values.pop(address, None)
                else:
                    self._selected_addresses.add(address)
                return

    def render(self, memory: Any) -> None:
        """Redraw the watch window with fresh data read from *memory*.  Call every frame while visible."""
        if not self._visible:
            return
        if not self.is_open():
            self._visible = False
            self._window_created = False
            self._button_rects.clear()
            self._cell_rects.clear()
            self._last_snapshot = None
            return

        watch_snapshot = self._watcher.record(memory)
        self._last_snapshot = watch_snapshot

        for address in self._selected_addresses:
            if address in watch_snapshot:
                current_value = int(watch_snapshot[address]["value"])
                previous_value = self._selected_values.get(address)
                if previous_value is not None and previous_value != current_value:
                    print(f"Select Watched address 0x{address:04X} value was {previous_value} and switch to {current_value}", flush=True)
                self._selected_values[address] = current_value

        addresses = sorted(watch_snapshot)
        if not addresses:
            return

        cols = self.COLS
        cell_w = self.CELL_W
        cell_h = self.CELL_H
        pad_x = self.PAD_X
        pad_y = self.PAD_Y

        start = self._page * self.PAGE_SIZE
        page_addresses = addresses[start:start + self.PAGE_SIZE]
        has_next = start + self.PAGE_SIZE < len(addresses)
        has_prev = self._page > 0

        max_rows = math.ceil(self.PAGE_SIZE / cols)
        panel_h = max_rows * cell_h + pad_y + 50
        panel_w = cols * cell_w + pad_x * 2
        panel = np.full((panel_h, panel_w, 3), 26, dtype=np.uint8)

        self._button_rects.clear()
        self._cell_rects.clear()

        for index, address in enumerate(page_addresses):
            row = index // cols
            col = index % cols
            cell_x = pad_x + col * cell_w
            cell_y = pad_y + row * cell_h
            entry = watch_snapshot[address]
            value = int(entry["value"])
            text_color = (0, 0, 255) if entry.get("flash", False) else (255, 255, 255)
            border_color = (0, 255, 0) if entry["changed"] else (90, 90, 90)
            self._cell_rects[address] = (cell_x, cell_y - 14, cell_w - 12, cell_h)
            cv2.putText(panel, f"0x{address:04X}", (cell_x, cell_y), cv2.FONT_HERSHEY_SIMPLEX, 0.50, text_color, 1)
            cv2.putText(panel, f"={value:02X}", (cell_x + 65, cell_y), cv2.FONT_HERSHEY_SIMPLEX, 0.50, text_color, 1)
            if entry["changed"]:
                cv2.rectangle(panel, (cell_x - 6, cell_y - 14), (cell_x + cell_w - 8, cell_y + 10), border_color, 1)
            if address in self._selected_addresses:
                cv2.rectangle(panel, (cell_x - 3, cell_y - 12), (cell_x + cell_w - 5, cell_y + 8), self.SELECT_COLOR, 1)

        button_y = max_rows * cell_h + pad_y + 12
        if has_prev:
            self._button_rects["prev"] = (pad_x, button_y, 80, 24)
            cv2.rectangle(panel, (pad_x, button_y), (pad_x + 80, button_y + 24), (200, 200, 200), 1)
            cv2.putText(panel, "Prev", (pad_x + 10, button_y + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        if has_next:
            next_x = pad_x + 90 if has_prev else pad_x
            self._button_rects["next"] = (next_x, button_y, 80, 24)
            cv2.rectangle(panel, (next_x, button_y), (next_x + 80, button_y + 24), (200, 200, 200), 1)
            cv2.putText(panel, "Next", (next_x + 10, button_y + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)

        total = len(addresses)
        page_num = self._page + 1
        total_pages = math.ceil(total / self.PAGE_SIZE)
        info = f"Page {page_num}/{total_pages} ({total} addresses)"
        cv2.putText(panel, info, (pad_x, button_y + 42), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (180, 180, 180), 1)

        cv2.imshow(self.title, panel)
        if self.title not in positioned_windows:
            cv2.resizeWindow(self.title, panel_w, panel_h)
            screen_w, _ = get_screen_size()
            win_x = max(0, screen_w - panel_w - 20)
            cv2.moveWindow(self.title, win_x, 40)
            positioned_windows.add(self.title)


def draw_memory_watch_panel(
    image: np.ndarray,
    x: int,
    y: int,
    width: int,
    watch_snapshot: dict[int, dict[str, Any]],
    title: str = "Memory watch",
    max_rows: int = 10,
) -> tuple[int, int, int, int] | None:
    """Render a compact table with address/value labels and a Show more overflow trigger.

    Returns the (x, y, w, h) rectangle of the "Show more" button when there are
    more addresses than ``max_rows``, otherwise None.
    """
    addresses = sorted(watch_snapshot)
    cv2.putText(image, title, (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.60, (255, 255, 255), 1)
    row_y = y + 28
    visible = addresses[:max_rows]
    overflowed = len(addresses) > max_rows

    for address in visible:
        entry = watch_snapshot[address]
        value = int(entry["value"])
        text_color = (0, 0, 255) if entry.get("flash", False) else (255, 255, 255)
        border_color = (0, 255, 0) if entry["changed"] else (90, 90, 90)
        cv2.putText(image, f"0x{address:04X}", (x, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.50, text_color, 1)
        cv2.putText(image, f": {value:02X}", (x + 65, row_y), cv2.FONT_HERSHEY_SIMPLEX, 0.50, text_color, 1)
        if entry["changed"]:
            cv2.rectangle(image, (x, row_y - 9), (x + min(width, 190), row_y + 8), border_color, 1)
        row_y += 18

    if overflowed:
        button_x = x
        button_y = row_y + 8
        button_w = min(width, 160)
        button_h = 18
        cv2.rectangle(image, (button_x, button_y), (button_x + button_w, button_y + button_h), (200, 200, 200), 1)
        cv2.putText(image, "Show more", (button_x + 10, button_y + 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)
        return (button_x, button_y, button_w, button_h)
    return None


def read_menu_handler_bytes(memory: Any) -> dict[int, int]:
    """Read the WRAM menu/text handler probe range for diagnostics."""
    return {
        address: int(memory[address])
        for address in range(MENU_HANDLER_START, MENU_HANDLER_END + 1)
    }


def draw_menu_handler_info(image: np.ndarray, x: int, y: int, memory: Any) -> None:
    """Draw raw CC26-CC2F values without assuming their exact meanings."""
    values = read_menu_handler_bytes(memory)
    watch_snapshot = {address: {"address": address, "value": value, "previous": None, "changed": True} for address, value in values.items()}
    draw_memory_watch_panel(image, x, y, 280, watch_snapshot, title="WRAM probe")
