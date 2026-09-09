from skill_lab.panel_data import MemoryWatchTracker, address_range


def test_address_range_generates_expected_sequence() -> None:
    assert address_range(0xD356, 0xD35A) == [0xD356, 0xD357, 0xD358, 0xD359, 0xD35A]
    assert address_range(0xD356, offsets=[0, 2, 5]) == [0xD356, 0xD358, 0xD35B]


def test_memory_watch_tracker_tracks_changes() -> None:
    tracker = MemoryWatchTracker(address_range(0xD356, 0xD358))
    first = {0xD356: 3, 0xD357: 4, 0xD358: 5}
    second = {0xD356: 3, 0xD357: 9, 0xD358: 5}

    first_snapshot = tracker.record(first)
    second_snapshot = tracker.record(second)

    assert first_snapshot[0xD356]["changed"] is True
    assert second_snapshot[0xD357]["changed"] is True
    assert second_snapshot[0xD356]["changed"] is False
