"""Test editing across several Helix selections at once.

The defining property is that an edit spanning N selections is applied as a single
text assignment: it produces one undo entry rather than N, and the ranges which
follow the first are not invalidated part-way through.
"""

from __future__ import annotations

import pytest
from apptk.application.current import set_app
from apptk.clipboard import ClipboardData
from apptk.commands import get_cmd
from apptk.key_binding.bindings.helix_selections import (
    apply_edit_at_ranges,
    replace_ranges,
    set_selections,
    text_at_ranges,
)
from helix_utils import make_event, run_helix

THREE_LINES = "one\ntwo\nthree"
THREE_RANGES = [(0, 3), (4, 7), (8, 13)]


def _multi(text: str, ranges: list[tuple[int, int]], *commands: str) -> tuple:
    """Install selections and run commands against them.

    Args:
        text: The initial buffer contents.
        ranges: The selection ranges to install.
        commands: The command names to run, in order.

    Returns:
        The buffer and application.
    """
    buffer, app = run_helix(text, [], cursor=0)
    with set_app(app):
        set_selections(buffer, ranges)
        for name in commands:
            get_cmd(name).handler(make_event(app))
    return buffer, app


# Pure range replacement


def test_text_at_ranges_extracts_in_buffer_order() -> None:
    """Text is extracted from each range, ordered by position."""
    assert text_at_ranges(THREE_LINES, THREE_RANGES) == ["one", "two", "three"]


def test_replace_ranges_deletes_every_range() -> None:
    """Replacing every range with nothing removes all of them."""
    text, ranges = replace_ranges(THREE_LINES, THREE_RANGES, [""])
    assert text == "\n\n"
    assert ranges == [(0, 0), (1, 1), (2, 2)]


def test_replace_ranges_tracks_shifting_offsets() -> None:
    """Later ranges account for length changes made by earlier ones."""
    text, ranges = replace_ranges(THREE_LINES, [(0, 3), (4, 7)], ["XXXXX", "Y"])
    assert text == "XXXXX\nY\nthree"
    assert ranges == [(0, 5), (6, 7)]


def test_replace_ranges_broadcasts_a_single_replacement() -> None:
    """One replacement is applied to every range."""
    text, _ = replace_ranges(THREE_LINES, THREE_RANGES, ["X"])
    assert text == "X\nX\nX"


def test_replace_ranges_with_one_range_is_a_plain_substitution() -> None:
    """The single-range case behaves like an ordinary replacement."""
    assert replace_ranges("abc", [(1, 2)], ["ZZ"]) == ("aZZc", [(1, 3)])


def test_replace_ranges_accepts_reversed_ranges() -> None:
    """A range given head-first is normalised before use."""
    text, _ = replace_ranges("abcdef", [(3, 1)], ["X"])
    assert text == "aXdef"


# Buffer-level edits


def test_uppercase_applies_to_every_selection() -> None:
    """``A-`` uppercases all selections at once."""
    buffer, _ = _multi(THREE_LINES, THREE_RANGES, "helix-to-uppercase")
    assert buffer.text == "ONE\nTWO\nTHREE"


def test_lowercase_applies_to_every_selection() -> None:
    """Lowercasing applies to all selections at once."""
    buffer, _ = _multi("ONE\nTWO\nTHREE", THREE_RANGES, "helix-to-lowercase")
    assert buffer.text == "one\ntwo\nthree"


def test_switch_case_applies_to_every_selection() -> None:
    """``~`` switches the case of every selection."""
    buffer, _ = _multi("abc\ndef", [(0, 1), (4, 5)], "helix-switch-case")
    assert buffer.text == "Abc\nDef"


def test_delete_removes_every_selection() -> None:
    """``d`` deletes all selections in one edit."""
    buffer, _ = _multi(THREE_LINES, THREE_RANGES, "helix-delete-selection")
    assert buffer.text == "\n\n"


def test_delete_yanks_every_selection() -> None:
    """Deleting several selections stores them joined by newlines."""
    _, app = _multi(THREE_LINES, THREE_RANGES, "helix-delete-selection")
    assert app.clipboard.get_data().text == "one\ntwo\nthree"


def test_change_deletes_and_enters_insert_mode() -> None:
    """``c`` removes every selection and switches to insert mode."""
    from apptk.key_binding.helix_state import InputMode

    buffer, app = _multi(THREE_LINES, THREE_RANGES, "helix-change-selection")
    assert buffer.text == "\n\n"
    assert app.helix_state.input_mode == InputMode.INSERT


def test_yank_joins_selections_with_newlines() -> None:
    """``y`` stores every selection, joined by newlines."""
    _, app = _multi(THREE_LINES, THREE_RANGES, "helix-yank")
    assert app.clipboard.get_data().text == "one\ntwo\nthree"


def test_yank_leaves_the_buffer_unchanged() -> None:
    """Yanking does not modify the text."""
    buffer, _ = _multi(THREE_LINES, THREE_RANGES, "helix-yank")
    assert buffer.text == THREE_LINES


# Paste distribution


def test_paste_distributes_one_line_per_selection() -> None:
    """A clipboard with one line per selection is distributed across them."""
    buffer, _ = _multi(THREE_LINES, THREE_RANGES, "helix-yank", "helix-paste-after")
    assert buffer.text == "oneone\ntwotwo\nthreethree"


def test_paste_repeats_a_single_line_at_every_selection() -> None:
    """A clipboard which does not match the selection count is pasted whole."""
    buffer, app = run_helix(THREE_LINES, [], cursor=0)
    app.clipboard.set_data(ClipboardData("X"))
    with set_app(app):
        set_selections(buffer, THREE_RANGES)
        get_cmd("helix-paste-after").handler(make_event(app))
    assert buffer.text == "oneX\ntwoX\nthreeX"


def test_paste_before_inserts_at_the_start_of_each_selection() -> None:
    """``P`` pastes at the leading edge of every selection."""
    buffer, app = run_helix(THREE_LINES, [], cursor=0)
    app.clipboard.set_data(ClipboardData("X"))
    with set_app(app):
        set_selections(buffer, THREE_RANGES)
        get_cmd("helix-paste-before").handler(make_event(app))
    assert buffer.text == "Xone\nXtwo\nXthree"


# Undo coalescing - the property most likely to regress


@pytest.mark.parametrize(
    ("command", "text", "ranges"),
    [
        ("helix-to-uppercase", THREE_LINES, THREE_RANGES),
        ("helix-delete-selection", THREE_LINES, THREE_RANGES),
        ("helix-switch-case", "abc\ndef", [(0, 1), (4, 5)]),
    ],
)
def test_multi_site_edit_is_a_single_undo_step(
    command: str, text: str, ranges: list[tuple[int, int]]
) -> None:
    """One undo reverses an edit made across several selections."""
    buffer, app = _multi(text, ranges, command)
    assert buffer.text != text
    with set_app(app):
        buffer.undo()
    assert buffer.text == text


def test_apply_edit_at_ranges_returns_the_new_ranges() -> None:
    """The helper reports where the replacements ended up."""
    buffer, app = run_helix(THREE_LINES, [], cursor=0)
    with set_app(app):
        new_ranges = apply_edit_at_ranges(buffer, THREE_RANGES, ["X"])
    assert buffer.text == "X\nX\nX"
    assert new_ranges == [(0, 1), (2, 3), (4, 5)]


def test_apply_edit_at_ranges_with_no_ranges_is_a_no_op() -> None:
    """An edit over no ranges changes nothing."""
    buffer, app = run_helix("abc", [], cursor=0)
    with set_app(app):
        assert apply_edit_at_ranges(buffer, [], ["X"]) == []
    assert buffer.text == "abc"


# Single-selection behaviour is unchanged


def test_single_selection_delete_is_unchanged() -> None:
    """With one selection, the original single-selection path is used."""
    buffer, _ = run_helix(
        "hello world",
        ["helix-select-next-word-start", "helix-delete-selection"],
        cursor=0,
    )
    assert buffer.text == "world"


def test_single_selection_yank_preserves_the_selection() -> None:
    """A single-selection yank still leaves the selection in place."""
    buffer, _ = run_helix(
        "hello world", ["helix-select-next-word-start", "helix-yank"], cursor=0
    )
    assert buffer.selection_state is not None
