"""Test registers, macros and marks in the Kakoune editing mode.

Marks have no Helix equivalent at all, and macros are bound the opposite way
round: Kakoune records with ``Q`` and replays with ``q``.
"""

from __future__ import annotations

import pytest
from apptk.application.current import set_app
from apptk.clipboard import ClipboardData
from apptk.commands import get_cmd
from kakoune_utils import make_event, run_kakoune, selection_ranges

# Registers


def test_select_register_awaits_a_name() -> None:
    """``"`` arms a pending slot rather than acting immediately."""
    _, app = run_kakoune("text", "kakoune-select-register", cursor=0)
    assert app.kakoune_state.waiting_for_register is True


def test_register_name_is_recorded() -> None:
    """The key after ``"`` names the register for the next operation."""
    _buffer, app = run_kakoune("text", "kakoune-select-register", cursor=0)
    with set_app(app):
        get_cmd("kakoune-handle-register").handler(make_event(app, data="a"))
    assert app.kakoune_state.pending_register == "a"


def test_invalid_register_name_is_rejected() -> None:
    """A multi-character or unsupported name is refused."""
    _buffer, app = run_kakoune("text", "kakoune-select-register", cursor=0)
    with set_app(app):
        get_cmd("kakoune-handle-register").handler(make_event(app, data=" "))
    assert app.kakoune_state.pending_register is None


def test_yank_to_a_named_register_bypasses_the_clipboard() -> None:
    """A selected register receives the yank instead of the clipboard."""
    _buffer, app = run_kakoune("one two", "kakoune-yank", selections=[(0, 3)])
    with set_app(app):
        app.kakoune_state.pending_register = "a"
        get_cmd("kakoune-yank").handler(make_event(app))

    assert app.kakoune_state.named_registers["a"].text == "one"


def test_register_is_consumed_once() -> None:
    """A pending register applies to one operation only."""
    _, app = run_kakoune("one two", [], selections=[(0, 3)])
    with set_app(app):
        app.kakoune_state.pending_register = "a"
        assert app.kakoune_state.take_register() == "a"
        assert app.kakoune_state.take_register() is None


def test_paste_reads_from_the_named_register() -> None:
    """A selected register supplies the text to paste."""
    buffer, app = run_kakoune("one two", [], selections=[(0, 3)])
    with set_app(app):
        app.kakoune_state.named_registers["a"] = ClipboardData("XYZ")
        app.kakoune_state.pending_register = "a"
        get_cmd("kakoune-paste-after").handler(make_event(app))

    assert buffer.text == "oneXYZ two"


def test_default_register_is_the_clipboard() -> None:
    """Without a selected register the application clipboard is used.

    Kakoune's default text register is ``"``; mapping it onto the clipboard keeps
    yanking interoperable with the rest of euporie.
    """
    _, app = run_kakoune("one two", "kakoune-yank", selections=[(0, 3)])
    assert app.clipboard.get_data().text == "one"


# Macros


def test_start_and_stop_recording() -> None:
    """``Q`` starts recording and a second ``Q`` stores it.

    NOTE: Kakoune records with ``Q`` and replays with ``q``. Helix binds these
    the other way round.
    """
    _buffer, app = run_kakoune("text", "kakoune-start-record-macro", cursor=0)
    assert app.kakoune_state.recording_register == "@"

    with set_app(app):
        app.kakoune_state.current_recording = "ll"
        get_cmd("kakoune-stop-record-macro").handler(make_event(app))

    assert app.kakoune_state.recording_register is None
    assert app.kakoune_state.named_registers["@"].text == "ll"


def test_recording_into_a_named_register() -> None:
    """A selected register receives the recording."""
    _, app = run_kakoune("text", [], cursor=0)
    with set_app(app):
        app.kakoune_state.pending_register = "x"
        get_cmd("kakoune-start-record-macro").handler(make_event(app))

    assert app.kakoune_state.recording_register == "x"


def test_playing_an_empty_macro_rings_the_bell() -> None:
    """Replaying an unset register does nothing rather than raising."""
    buffer, _app = run_kakoune("text", "kakoune-play-macro", cursor=0)
    assert buffer.text == "text"


def test_macro_fields_are_initialised() -> None:
    """The recording fields exist without relying on the Vi base class.

    ``HelixState`` reads these but never initialises them, working only through
    inheritance; Kakoune's state sets them explicitly so ``reset`` can clear them.
    """
    _, app = run_kakoune("text", [], cursor=0)
    state = app.kakoune_state
    assert state.recording_register is None
    assert state.current_recording == ""

    state.recording_register = "a"
    state.current_recording = "xx"
    state.reset()
    assert state.recording_register is None
    assert state.current_recording == ""


# Marks


def test_save_and_restore_selections() -> None:
    """``Z`` saves the selections and ``z`` brings them back.

    NOTE: Helix uses ``z`` for view mode. Kakoune's view mode is ``v``.
    """
    buffer, app = run_kakoune(
        "alpha beta gamma", "kakoune-save-selections", selections=[(0, 5), (6, 10)]
    )
    assert app.kakoune_state.marks["^"] == [(0, 5), (6, 10)]

    with set_app(app):
        get_cmd("kakoune-keep-main-selection").handler(make_event(app))
        assert len(selection_ranges(buffer)) == 1
        get_cmd("kakoune-restore-selections").handler(make_event(app))

    assert selection_ranges(buffer) == [(0, 5), (6, 10)]


def test_marks_use_a_named_register() -> None:
    """A selected register stores the mark."""
    _, app = run_kakoune("alpha beta", [], selections=[(0, 5)])
    with set_app(app):
        app.kakoune_state.pending_register = "m"
        get_cmd("kakoune-save-selections").handler(make_event(app))

    assert "m" in app.kakoune_state.marks


def test_restoring_an_unset_mark_rings_the_bell() -> None:
    """Restoring from an empty register leaves the selections alone."""
    buffer, _ = run_kakoune(
        "alpha beta", "kakoune-restore-selections", selections=[(0, 5)]
    )
    assert selection_ranges(buffer) == [(0, 5)]


def test_restored_marks_are_clamped_to_the_text() -> None:
    """A mark surviving a shortened buffer is clamped rather than overflowing."""
    buffer, app = run_kakoune(
        "alpha beta gamma", "kakoune-save-selections", selections=[(11, 16)]
    )
    with set_app(app):
        buffer.text = "alpha"
        get_cmd("kakoune-restore-selections").handler(make_event(app))

    for _start, end in selection_ranges(buffer):
        assert end <= len(buffer.text)


@pytest.mark.parametrize(
    ("menu_key", "expected"),
    [
        ("u", [(0, 5), (6, 10)]),
        ("a", [(0, 5), (6, 10)]),
    ],
)
def test_mark_combine_union_and_append(
    menu_key: str, expected: list[tuple[int, int]]
) -> None:
    """``<a-z>`` combines the saved selections with the current ones."""
    buffer, app = run_kakoune(
        "alpha beta gamma", "kakoune-save-selections", selections=[(0, 5)]
    )
    with set_app(app):
        from apptk.key_binding.bindings.kakoune_selections import set_selections

        set_selections(buffer, [(6, 10)])
        get_cmd("kakoune-combine-from-register").handler(make_event(app))
        get_cmd("kakoune-handle-mark-combine").handler(make_event(app, data=menu_key))

    assert selection_ranges(buffer) == expected


def test_mark_combine_intersection() -> None:
    """The ``i`` menu key keeps only the overlapping parts."""
    buffer, app = run_kakoune(
        "alpha beta gamma", "kakoune-save-selections", selections=[(0, 8)]
    )
    with set_app(app):
        from apptk.key_binding.bindings.kakoune_selections import set_selections

        set_selections(buffer, [(5, 12)])
        get_cmd("kakoune-combine-from-register").handler(make_event(app))
        get_cmd("kakoune-handle-mark-combine").handler(make_event(app, data="i"))

    assert selection_ranges(buffer) == [(5, 8)]


def test_mark_combine_longest() -> None:
    """The ``+`` menu key keeps the longer of each pair."""
    buffer, app = run_kakoune(
        "alpha beta gamma", "kakoune-save-selections", selections=[(0, 2)]
    )
    with set_app(app):
        from apptk.key_binding.bindings.kakoune_selections import set_selections

        set_selections(buffer, [(0, 5)])
        get_cmd("kakoune-combine-from-register").handler(make_event(app))
        get_cmd("kakoune-handle-mark-combine").handler(make_event(app, data="+"))

    assert selection_ranges(buffer) == [(0, 5)]


def test_unknown_combine_key_rings_the_bell() -> None:
    """A key outside the menu cancels the operation."""
    _buffer, app = run_kakoune(
        "alpha beta", "kakoune-save-selections", selections=[(0, 5)]
    )
    with set_app(app):
        get_cmd("kakoune-combine-from-register").handler(make_event(app))
        get_cmd("kakoune-handle-mark-combine").handler(make_event(app, data="!"))

    assert app.kakoune_state.pending_mark_combine is None
