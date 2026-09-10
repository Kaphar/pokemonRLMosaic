import json
from pathlib import Path
from typing import Any

import pytest
from pyboy.utils import WindowEvent

from skill_lab.emulator_with_debug import (
    ACTION_EVENTS,
    DEFAULT_ACTION_PRESS_FRAMES,
    DEFAULT_NOOP_ACTION,
    PROJECT_ROOT,
    SELECT_EVENTS,
    compute_action_timing,
    generate_input_events,
    load_replay,
    replay_action,
    replay_frame_by_frame,
    verify_recording,
    verify_recording_frame_by_frame,
)


# ---------------------------------------------------------------------------
# compute_action_timing
# ---------------------------------------------------------------------------

def test_compute_action_timing_matches_environment_step_cycle() -> None:
    press_frames, idle_frames, release_tick = compute_action_timing(24)

    assert press_frames == DEFAULT_ACTION_PRESS_FRAMES == 8
    assert idle_frames == 15
    assert release_tick == 1
    assert press_frames + idle_frames + release_tick == 24


def test_compute_action_timing_keeps_minimum_frequency() -> None:
    press_frames, idle_frames, release_tick = compute_action_timing(9)

    assert press_frames == 8
    assert idle_frames == 0
    assert release_tick == 1
    assert press_frames + idle_frames + release_tick == 9


def test_compute_action_timing_custom_press_frames() -> None:
    press_frames, idle_frames, release_tick = compute_action_timing(24, press_frames=5)

    assert press_frames == 5
    assert idle_frames == 18
    assert release_tick == 1
    assert press_frames + idle_frames + release_tick == 24


def test_compute_action_timing_clamps_press_to_default() -> None:
    press_frames, idle_frames, release_tick = compute_action_timing(24, press_frames=99)

    assert press_frames == DEFAULT_ACTION_PRESS_FRAMES
    assert press_frames + idle_frames + release_tick == 24


# ---------------------------------------------------------------------------
# Mock PyBoy for replay_action tests
# ---------------------------------------------------------------------------

class _MockPyBoy:
    """Minimal stand-in that records every send_input / tick call."""

    def __init__(self) -> None:
        self.inputs: list[Any] = []
        self.ticks: list[tuple[int, bool]] = []

    def send_input(self, event: WindowEvent) -> None:
        self.inputs.append(event)

    def tick(self, frames: int = 1, render: bool = False) -> None:
        self.ticks.append((frames, render))


@pytest.fixture
def mock_pyboy() -> _MockPyBoy:
    return _MockPyBoy()


# ---------------------------------------------------------------------------
# replay_action
# ---------------------------------------------------------------------------

def test_replay_action_timing_matches_env(mock_pyboy: _MockPyBoy) -> None:
    """The replayer sends press, ticks 8, sends release, ticks 15, ticks 1."""
    action = 4  # PRESS_BUTTON_A
    replay_action(mock_pyboy, action, 24, verbose=False)

    press, release = ACTION_EVENTS[action]
    assert mock_pyboy.inputs == [press, release]

    total_ticks = sum(count for count, _ in mock_pyboy.ticks)
    assert total_ticks == 24
    assert mock_pyboy.ticks == [(8, True), (15, True), (1, True)]


def test_replay_action_headless_render_false(mock_pyboy: _MockPyBoy) -> None:
    """With render=False, non-final ticks use render=False, final tick is True."""
    action = 4  # PRESS_BUTTON_A
    replay_action(mock_pyboy, action, 24, verbose=False, render=False)

    press, release = ACTION_EVENTS[action]
    assert mock_pyboy.inputs == [press, release]

    total_ticks = sum(count for count, _ in mock_pyboy.ticks)
    assert total_ticks == 24
    assert mock_pyboy.ticks == [(8, False), (15, False), (1, True)]


def test_replay_action_noop_sends_no_input(mock_pyboy: _MockPyBoy) -> None:
    """Action 7 (noop / PASS) sends no inputs, only ticks."""
    replay_action(mock_pyboy, 7, 24, verbose=False)

    assert mock_pyboy.inputs == []
    assert sum(count for count, _ in mock_pyboy.ticks) == 24
    assert mock_pyboy.ticks == [(8, True), (15, True), (1, True)]


def test_replay_action_minimum_freq(mock_pyboy: _MockPyBoy) -> None:
    """With freq=9 the button is held 8 frames, 0 idle, 1 final tick."""
    replay_action(mock_pyboy, 0, 9, verbose=False)

    press, release = ACTION_EVENTS[0]
    assert mock_pyboy.inputs == [press, release]
    assert sum(count for count, _ in mock_pyboy.ticks) == 9
    assert mock_pyboy.ticks == [(8, True), (0, True), (1, True)]


def test_replay_action_all_button_actions() -> None:
    for action in range(7):
        mock = _MockPyBoy()
        replay_action(mock, action, 24, verbose=False)
        press, release = ACTION_EVENTS[action]
        assert mock.inputs == [press, release]
        assert sum(count for count, _ in mock.ticks) == 24


# ---------------------------------------------------------------------------
# replay_frame_by_frame
# ---------------------------------------------------------------------------

def test_replay_frame_by_frame_sends_events_at_correct_frames(mock_pyboy: _MockPyBoy) -> None:
    """Events are sent at their absolute frame offsets, one tick per frame."""
    input_events = [
        {"frame": 0, "event": int(ACTION_EVENTS[4][0])},
        {"frame": 8, "event": int(ACTION_EVENTS[4][1])},
    ]
    replay_frame_by_frame(mock_pyboy, input_events, total_frames=24, verbose=False)

    # 24 ticks of 1 frame each
    assert len(mock_pyboy.ticks) == 24
    assert all(count == 1 for count, _ in mock_pyboy.ticks)
    # Last tick always renders
    assert mock_pyboy.ticks[-1] == (1, True)
    # Inputs at frame 0 and frame 8
    assert len(mock_pyboy.inputs) == 2


def test_replay_frame_by_frame_render_false(mock_pyboy: _MockPyBoy) -> None:
    """With render=False, non-final ticks use False, final tick is True."""
    input_events: list = []
    replay_frame_by_frame(mock_pyboy, input_events, total_frames=24, render=False)

    assert len(mock_pyboy.ticks) == 24
    for count, render in mock_pyboy.ticks[:-1]:
        assert count == 1
        assert render is False
    assert mock_pyboy.ticks[-1] == (1, True)


def test_select_events_are_masked_in_frame_replay(mock_pyboy: _MockPyBoy) -> None:
    """SELECT press/release events in input_events are skipped (masked)."""
    select_press = int(WindowEvent.PRESS_BUTTON_SELECT)
    select_release = int(WindowEvent.RELEASE_BUTTON_SELECT)
    a_press = int(ACTION_EVENTS[4][0])
    a_release = int(ACTION_EVENTS[4][1])

    input_events = [
        {"frame": 0, "event": select_press},
        {"frame": 0, "event": a_press},
        {"frame": 8, "event": select_release},
        {"frame": 8, "event": a_release},
    ]
    replay_frame_by_frame(mock_pyboy, input_events, total_frames=24, verbose=False)

    assert select_press not in mock_pyboy.inputs
    assert select_release not in mock_pyboy.inputs
    assert mock_pyboy.inputs == [a_press, a_release]
    assert len(mock_pyboy.ticks) == 24


def test_replay_action_masks_select_action(mock_pyboy: _MockPyBoy) -> None:
    """An action index absent from ACTION_EVENTS (e.g. SELECT) sends no inputs."""
    select_idx = 10  # not in ACTION_EVENTS
    replay_action(mock_pyboy, select_idx, 24, verbose=False)

    assert mock_pyboy.inputs == []
    assert sum(count for count, _ in mock_pyboy.ticks) == 24


def test_select_events_constant() -> None:
    """SELECT_EVENTS contains both select press and release WindowEvent codes."""
    assert int(WindowEvent.PRESS_BUTTON_SELECT) in SELECT_EVENTS
    assert int(WindowEvent.RELEASE_BUTTON_SELECT) in SELECT_EVENTS


def test_generate_input_events_press_release_timing() -> None:
    """generate_input_events places press at frame 0 and release at press_length within the cycle."""
    actions = [4, 0]  # A button, then Down
    events = generate_input_events(actions, action_freq=24, noop_action=7)

    by_frame: dict[int, list] = {}
    for ev in events:
        by_frame.setdefault(ev["frame"], []).append(ev)

    # Action 0: press at frame 0, release at frame 8
    assert by_frame[0][0]["event"] == int(ACTION_EVENTS[4][0])
    assert by_frame[8][0]["event"] == int(ACTION_EVENTS[4][1])

    # Action 1: press at frame 24, release at frame 32
    assert by_frame[24][0]["event"] == int(ACTION_EVENTS[0][0])
    assert by_frame[32][0]["event"] == int(ACTION_EVENTS[0][1])


# ---------------------------------------------------------------------------
# load_replay
# ---------------------------------------------------------------------------

def test_load_replay_uses_noop_action_from_json(tmp_path: Path) -> None:
    recording = {
        "init_state": "init.state",
        "action_freq": 24,
        "noop_action": 9,
        "actions": [
            {"step": 1, "action": 0, "requested_action": 0, "masked": False},
            {"step": 2, "action": 9, "requested_action": 6, "masked": True},
            {"step": 3, "action": 3, "requested_action": 3, "masked": False},
        ],
    }
    path = tmp_path / "recording.json"
    path.write_text(json.dumps(recording))

    actions, data = load_replay(path)
    assert actions == [0, 9, 3]
    assert data["noop_action"] == 9


def test_load_replay_defaults_noop_action(tmp_path: Path) -> None:
    recording = {
        "actions": [
            {"step": 1, "action": 0, "masked": False},
            {"step": 2, "action": 5, "masked": True},
        ],
    }
    path = tmp_path / "recording.json"
    path.write_text(json.dumps(recording))

    actions, data = load_replay(path)
    assert actions == [0, DEFAULT_NOOP_ACTION]


def test_load_replay_handles_plain_int_entries(tmp_path: Path) -> None:
    recording = {"actions": [0, 1, 2, 7]}
    path = tmp_path / "recording.json"
    path.write_text(json.dumps(recording))

    actions, data = load_replay(path)
    assert actions == [0, 1, 2, 7]


def test_load_replay_none_path() -> None:
    actions, data = load_replay(None)
    assert actions == []
    assert data == {}


def test_load_replay_preserves_action_freq(tmp_path: Path) -> None:
    recording = {"action_freq": 18, "actions": []}
    path = tmp_path / "recording.json"
    path.write_text(json.dumps(recording))

    _, data = load_replay(path)
    assert data["action_freq"] == 18


# ---------------------------------------------------------------------------
# Integration tests — require the real ROM, init.state, and a recording
# ---------------------------------------------------------------------------

ROM_PATH = PROJECT_ROOT / "PokemonRed.gb"
INIT_STATE_PATH = PROJECT_ROOT / "init.state"
RECORDING_PATH = (
    PROJECT_ROOT / "skill_lab" / "envs" / "Env053" / "inputs" / "Squirtle - PERFECT.json"
)

_HAS_ROM = ROM_PATH.is_file()
_HAS_STATE = INIT_STATE_PATH.is_file()
_HAS_RECORDING = RECORDING_PATH.is_file()


@pytest.mark.skipif(not _HAS_ROM, reason="PokemonRed.gb not available")
@pytest.mark.skipif(not _HAS_STATE, reason="init.state not available")
@pytest.mark.skipif(not _HAS_RECORDING, reason="recording not available")
def test_verify_recording_structure() -> None:
    result = verify_recording(RECORDING_PATH, ROM_PATH)

    assert result["total_actions"] > 0
    assert result["action_freq"] == 24
    assert result["total_frames"] == result["total_actions"] * 24
    assert "final_state" in result
    for key in ("x", "y", "map", "badges", "party", "battle"):
        assert key in result["final_state"]


@pytest.mark.skipif(not _HAS_ROM, reason="PokemonRed.gb not available")
@pytest.mark.skipif(not _HAS_STATE, reason="init.state not available")
@pytest.mark.skipif(not _HAS_RECORDING, reason="recording not available")
def test_verify_recording_is_deterministic() -> None:
    """The same recording must always produce the same final state."""
    result1 = verify_recording(RECORDING_PATH, ROM_PATH)
    result2 = verify_recording(RECORDING_PATH, ROM_PATH)

    assert result1["final_state"] == result2["final_state"]
    assert result1["total_actions"] == result2["total_actions"]


@pytest.mark.skipif(not _HAS_ROM, reason="PokemonRed.gb not available")
@pytest.mark.skipif(not _HAS_STATE, reason="init.state not available")
@pytest.mark.skipif(not _HAS_RECORDING, reason="recording not available")
def test_verify_recording_dump_states() -> None:
    result = verify_recording(RECORDING_PATH, ROM_PATH, dump_states=True)

    assert "snapshots" in result
    assert len(result["snapshots"]) == result["total_actions"]
    first = result["snapshots"][0]
    for key in ("step", "x", "y", "map", "badges", "party", "battle"):
        assert key in first


@pytest.mark.skipif(not _HAS_ROM, reason="PokemonRed.gb not available")
@pytest.mark.skipif(not _HAS_STATE, reason="init.state not available")
@pytest.mark.skipif(not _HAS_RECORDING, reason="recording not available")
def test_verify_recording_frame_by_frame_matches_verify_recording() -> None:
    """Both verification methods must produce the same final state."""
    result1 = verify_recording(RECORDING_PATH, ROM_PATH)
    result2 = verify_recording_frame_by_frame(RECORDING_PATH, ROM_PATH)

    assert result1["final_state"] == result2["final_state"]


@pytest.mark.skipif(not _HAS_ROM, reason="PokemonRed.gb not available")
@pytest.mark.skipif(not _HAS_STATE, reason="init.state not available")
@pytest.mark.skipif(not _HAS_RECORDING, reason="recording not available")
def test_verify_recording_frame_by_frame_is_deterministic() -> None:
    """The frame-by-frame verification must be reproducible."""
    result1 = verify_recording_frame_by_frame(RECORDING_PATH, ROM_PATH)
    result2 = verify_recording_frame_by_frame(RECORDING_PATH, ROM_PATH)

    assert result1["final_state"] == result2["final_state"]
    assert result1["total_actions"] == result2["total_actions"]


@pytest.mark.skipif(not _HAS_ROM, reason="PokemonRed.gb not available")
@pytest.mark.skipif(not _HAS_STATE, reason="init.state not available")
@pytest.mark.skipif(not _HAS_RECORDING, reason="recording not available")
def test_verify_recording_frame_by_frame_structure() -> None:
    result = verify_recording_frame_by_frame(RECORDING_PATH, ROM_PATH, dump_states=True)

    assert result["total_actions"] > 0
    assert result["action_freq"] == 24
    assert result["total_frames"] == result["total_actions"] * 24
    assert "final_state" in result
    for key in ("x", "y", "map", "badges", "party", "battle"):
        assert key in result["final_state"]
    assert "snapshots" in result
    assert len(result["snapshots"]) == result["total_actions"]
