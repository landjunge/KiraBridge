from kirabridge.platform_adapters.terminal_app import attach_visual_windows


def _tab(window_id, tty, *, bounds=None, frontmost=False, index=1, script_tabs=1, selected=False):
    return {
        "window_id": window_id,
        "tty": tty,
        "index": index,
        "frontmost": frontmost,
        "selected": selected,
        "script_tab_count": script_tabs,
        "bounds": bounds
        or {"x": 0, "y": 25, "width": 1600, "height": 637},
    }


def test_shared_bounds_are_one_window_of_tabs():
    rows = attach_visual_windows(
        [
            _tab(626, "/dev/ttys001", frontmost=True, index=1),
            _tab(476, "/dev/ttys000", index=2),
            _tab(1785, "/dev/ttys002", index=3),
            _tab(1963, "/dev/ttys003", index=4),
        ]
    )
    assert {row["ui_window_count"] for row in rows} == {1}
    assert {row["tab_count"] for row in rows} == {4}
    assert {row["visual_window_id"] for row in rows} == {476}
    selected = [row for row in rows if row["tab_selected"]]
    assert len(selected) == 1
    assert selected[0]["tty"] == "/dev/ttys001"
    assert [row["tab_index"] for row in sorted(rows, key=lambda item: item["index"])] == [1, 2, 3, 4]


def test_different_bounds_are_separate_windows():
    rows = attach_visual_windows(
        [
            _tab(1, "/dev/ttys001", bounds={"x": 0, "y": 0, "width": 800, "height": 600}, frontmost=True),
            _tab(2, "/dev/ttys002", bounds={"x": 900, "y": 0, "width": 800, "height": 600}),
        ]
    )
    assert {row["ui_window_count"] for row in rows} == {2}
    assert {row["tab_count"] for row in rows} == {1}
    assert all(row["tab_selected"] for row in rows)


def test_ended_tab_does_not_claim_a_reused_tty():
    rows = attach_visual_windows(
        [
            {**_tab(1785, "/dev/ttys002", index=1), "ended": True},
            _tab(2040, "/dev/ttys002", index=2, frontmost=True),
        ]
    )
    live = next(row for row in rows if row["window_id"] == 2040)
    ended = next(row for row in rows if row["window_id"] == 1785)
    assert live["identity_ambiguous"] is False
    assert ended["identity_ambiguous"] is False


def test_duplicate_tty_is_not_addressable():
    rows = attach_visual_windows(
        [
            _tab(1785, "/dev/ttys002", index=1),
            _tab(1963, "/dev/ttys002", index=2, frontmost=True),
        ]
    )
    assert all(row["identity_ambiguous"] for row in rows)
