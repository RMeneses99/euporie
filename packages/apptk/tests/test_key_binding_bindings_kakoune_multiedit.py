"""Test multi-cursor editing in the Kakoune editing mode.

Multi-cursor *insert* is the behaviour most easily lost to a refactor: a plain
``Buffer.insert_text`` silently collapses the additional selections, because
``Buffer._text_changed`` clears the selection state and fires ``on_text_changed``.
These tests pin the working behaviour so that regression is caught.
"""

from __future__ import annotations

import pytest
from apptk.application.current import set_app
from apptk.commands import get_cmd
from apptk.key_binding.kakoune_state import InputMode
from kakoune_utils import make_event, run_kakoune


def test_insert_places_a_caret_before_every_selection() -> None:
    """``i`` collapses each selection to a caret at its start."""
    _buffer, app = run_kakoune(
        "aaa bbb ccc", "kakoune-insert", selections=[(0, 3), (4, 7), (8, 11)]
    )
    assert app.kakoune_state.input_mode == InputMode.INSERT
    assert app.kakoune_state.selections == [(0, 0), (4, 4), (8, 8)]


def test_append_places_a_caret_after_every_selection() -> None:
    """``a`` collapses each selection to a caret at its end."""
    _buffer, app = run_kakoune(
        "aaa bbb ccc", "kakoune-append", selections=[(0, 3), (4, 7), (8, 11)]
    )
    assert app.kakoune_state.selections == [(3, 3), (7, 7), (11, 11)]


def test_typing_inserts_at_every_caret() -> None:
    """Successive keystrokes insert at all carets, not only the first."""
    buffer, app = run_kakoune(
        "aaa bbb ccc", "kakoune-insert", selections=[(0, 3), (4, 7), (8, 11)]
    )
    with set_app(app):
        for char in "XY":
            get_cmd("kakoune-self-insert").handler(make_event(app, data=char))

    assert buffer.text == "XYaaa XYbbb XYccc"
    assert app.kakoune_state.selections == [(2, 2), (8, 8), (14, 14)]


def test_backspace_deletes_at_every_caret() -> None:
    """Backspace removes a character at each caret."""
    buffer, app = run_kakoune(
        "aaa bbb ccc", "kakoune-insert", selections=[(0, 3), (4, 7), (8, 11)]
    )
    with set_app(app):
        get_cmd("kakoune-self-insert").handler(make_event(app, data="X"))
        get_cmd("kakoune-insert-backspace").handler(make_event(app))

    assert buffer.text == "aaa bbb ccc"


def test_delete_removes_the_character_under_every_caret() -> None:
    """Delete removes the character at each caret."""
    buffer, app = run_kakoune(
        "aaa bbb ccc", "kakoune-insert", selections=[(0, 3), (4, 7), (8, 11)]
    )
    with set_app(app):
        get_cmd("kakoune-insert-delete").handler(make_event(app))

    assert buffer.text == "aa bb cc"


def test_newline_inserts_at_every_caret() -> None:
    """A newline is inserted at each caret."""
    buffer, app = run_kakoune("ab cd", "kakoune-insert", selections=[(0, 2), (3, 5)])
    with set_app(app):
        get_cmd("kakoune-insert-newline").handler(make_event(app))

    assert buffer.text == "\nab \ncd"


def test_delete_word_before_at_every_caret() -> None:
    """``c-w`` removes the preceding word at each caret."""
    buffer, app = run_kakoune(
        "one two three", "kakoune-append", selections=[(0, 3), (4, 7)]
    )
    with set_app(app):
        get_cmd("kakoune-insert-delete-word-before").handler(make_event(app))

    # Both words go, leaving the space that followed each of them.
    assert buffer.text == "  three"


def test_multi_edit_is_a_single_undo_step() -> None:
    """One keystroke across several carets is reversed by one undo."""
    buffer, app = run_kakoune(
        "aaa bbb ccc", "kakoune-insert", selections=[(0, 3), (4, 7), (8, 11)]
    )
    with set_app(app):
        get_cmd("kakoune-self-insert").handler(make_event(app, data="X"))
        assert buffer.text == "Xaaa Xbbb Xccc"
        buffer.undo()

    assert buffer.text == "aaa bbb ccc"


def test_single_selection_falls_through_to_buffer_methods() -> None:
    """With one selection the insert commands use the ordinary buffer path."""
    buffer, app = run_kakoune("hello", "kakoune-insert", cursor=0)
    with set_app(app):
        get_cmd("kakoune-self-insert").handler(make_event(app, data="X"))

    assert buffer.text == "Xhello"
    assert app.kakoune_state.selections == []


def test_insert_records_text_for_repeat() -> None:
    """Insert-mode text is captured so that ``.`` can repeat the change."""
    _buffer, app = run_kakoune("hello", "kakoune-insert", cursor=0)
    with set_app(app):
        for char in "hi":
            get_cmd("kakoune-self-insert").handler(make_event(app, data=char))

    assert app.kakoune_state.last_insert == "hi"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("kakoune-add-line-below", "one\n\ntwo"),
        ("kakoune-add-line-above", "\none\ntwo"),
    ],
)
def test_add_blank_line_keeps_normal_mode(command: str, expected: str) -> None:
    """``<a-o>`` and ``<a-O>`` add a line without entering insert mode."""
    buffer, app = run_kakoune("one\ntwo", command, cursor=0)
    assert buffer.text == expected
    assert app.kakoune_state.input_mode == InputMode.NAVIGATION
