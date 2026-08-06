"""Test Helix match-mode commands: text objects, surround and number adjustment."""

from __future__ import annotations

import pytest
from apptk.application.current import set_app
from apptk.commands import get_cmd
from apptk.key_binding.helix_state import HelixMode
from helix_utils import make_event, run_helix, selection_range

MATCH_INSIDE = ["helix-enter-match-mode", "helix-match-inside"]
MATCH_AROUND = ["helix-enter-match-mode", "helix-match-around"]


def _surround(text: str, setup: list[str], *chars: str, cursor: int = 0) -> str:
    """Run a surround operation and return the resulting buffer text.

    Args:
        text: The initial buffer contents.
        setup: Commands to run before the surround characters are supplied.
        chars: The characters to feed to the surround handler, in order.
        cursor: The initial cursor position.

    Returns:
        The buffer text after the operation.
    """
    buffer, app = run_helix(text, setup, cursor=cursor)
    with set_app(app):
        for char in chars:
            get_cmd("helix-handle-surround").handler(make_event(app, data=char))
    return buffer.text


# Text objects


def test_match_inside_selects_the_word() -> None:
    """``mi w`` selects the word under the cursor."""
    buffer, _ = run_helix(
        "hello world", [*MATCH_INSIDE, "helix-handle-text-object"], cursor=2, data="w"
    )
    assert selection_range(buffer) == (0, 5)


def test_match_inside_selects_the_second_word() -> None:
    """``mi w`` resolves relative to the cursor, not the buffer start."""
    buffer, _ = run_helix(
        "hello world", [*MATCH_INSIDE, "helix-handle-text-object"], cursor=8, data="w"
    )
    assert selection_range(buffer) == (6, 11)


def test_match_around_includes_trailing_space() -> None:
    """``ma w`` extends over the whitespace after the word."""
    buffer, _ = run_helix(
        "hello world", [*MATCH_AROUND, "helix-handle-text-object"], cursor=2, data="w"
    )
    assert selection_range(buffer) == (0, 6)


def test_match_inside_selects_bracket_contents() -> None:
    """``mi (`` selects the contents of the enclosing brackets."""
    buffer, _ = run_helix(
        "a (bc) d", [*MATCH_INSIDE, "helix-handle-text-object"], cursor=4, data="("
    )
    assert selection_range(buffer) == (3, 5)


def test_match_mode_is_left_after_resolving() -> None:
    """Resolving a text object returns to normal mode."""
    _, app = run_helix(
        "hello world", [*MATCH_INSIDE, "helix-handle-text-object"], cursor=2, data="w"
    )
    assert app.helix_state.mode == HelixMode.NORMAL
    assert app.helix_state.pending_text_object is None


def test_unresolvable_text_object_leaves_selection_alone() -> None:
    """A text object which cannot be resolved does not change the selection."""
    buffer, _ = run_helix(
        "   ", [*MATCH_INSIDE, "helix-handle-text-object"], cursor=1, data="w"
    )
    assert selection_range(buffer) is None


# Surround


def test_surround_add_wraps_the_selection() -> None:
    """``ms (`` wraps the selection in brackets."""
    result = _surround(
        "hello world",
        [
            "helix-select-next-word-start",
            "helix-enter-match-mode",
            "helix-surround-add",
        ],
        "(",
    )
    assert result == "(hello )world"


def test_surround_add_with_quotes() -> None:
    """``ms "`` wraps the selection in quotes, which are their own closing pair."""
    result = _surround(
        "hello world",
        [
            "helix-select-next-word-start",
            "helix-enter-match-mode",
            "helix-surround-add",
        ],
        '"',
    )
    assert result == '"hello "world'


def test_surround_delete_removes_the_pair() -> None:
    """``md (`` removes the brackets around the cursor."""
    result = _surround(
        "a (bc) d",
        ["helix-enter-match-mode", "helix-surround-delete"],
        "(",
        cursor=4,
    )
    assert result == "a bc d"


def test_surround_replace_swaps_the_pair() -> None:
    """``mr ( [`` replaces one bracket pair with another."""
    result = _surround(
        "a (bc) d",
        ["helix-enter-match-mode", "helix-surround-replace"],
        "(",
        "[",
        cursor=4,
    )
    assert result == "a [bc] d"


def test_surround_replace_awaits_two_characters() -> None:
    """``mr`` records the pair to replace before reading the replacement."""
    _, app = run_helix(
        "a (bc) d", ["helix-enter-match-mode", "helix-surround-replace"], cursor=4
    )
    with set_app(app):
        get_cmd("helix-handle-surround").handler(make_event(app, data="("))
        assert app.helix_state.pending_surround == "replace-to:("


def test_surround_delete_outside_a_pair_is_harmless() -> None:
    """Deleting a surround which does not exist leaves the text unchanged."""
    result = _surround(
        "no brackets",
        ["helix-enter-match-mode", "helix-surround-delete"],
        "(",
        cursor=3,
    )
    assert result == "no brackets"


def test_surround_add_is_a_single_undo_step() -> None:
    """A surround operation is reversed by one undo."""
    buffer, app = run_helix(
        "hello world",
        [
            "helix-select-next-word-start",
            "helix-enter-match-mode",
            "helix-surround-add",
        ],
        cursor=0,
    )
    with set_app(app):
        get_cmd("helix-handle-surround").handler(make_event(app, data="("))
        assert buffer.text == "(hello )world"
        buffer.undo()
    assert buffer.text == "hello world"


# Increment and decrement


@pytest.mark.parametrize(
    ("command", "expected"),
    [("helix-increment", "value 42 end"), ("helix-decrement", "value 40 end")],
)
def test_adjust_number_under_cursor(command: str, expected: str) -> None:
    """``c-a`` and ``c-x`` adjust the number at the cursor."""
    buffer, _ = run_helix("value 41 end", command, cursor=6)
    assert buffer.text == expected


def test_increment_finds_a_number_after_the_cursor() -> None:
    """The number need not be under the cursor, only later on the line."""
    buffer, _ = run_helix("value 41 end", "helix-increment", cursor=0)
    assert buffer.text == "value 42 end"


def test_increment_handles_negative_numbers() -> None:
    """A leading minus sign is part of the number."""
    buffer, _ = run_helix("temp -5 c", "helix-increment", cursor=6)
    assert buffer.text == "temp -4 c"


def test_increment_crossing_zero() -> None:
    """Decrementing past zero produces a negative number."""
    buffer, _ = run_helix("n 0", "helix-decrement", cursor=2)
    assert buffer.text == "n -1"


def test_increment_with_no_number_is_harmless() -> None:
    """A line with no number is left unchanged."""
    buffer, _ = run_helix("no digits", "helix-increment", cursor=0)
    assert buffer.text == "no digits"


def test_increment_is_a_single_undo_step() -> None:
    """Adjusting a number is reversed by one undo."""
    buffer, app = run_helix("value 41 end", "helix-increment", cursor=6)
    assert buffer.text == "value 42 end"
    with set_app(app):
        buffer.undo()
    assert buffer.text == "value 41 end"


# Space and window sub-modes


def test_enter_and_exit_space_mode() -> None:
    """``space`` enters the space sub-mode and ``escape`` leaves it."""
    _, app = run_helix("abc", "helix-enter-space-mode", cursor=0)
    assert app.helix_state.space_mode

    _, app = run_helix(
        "abc", ["helix-enter-space-mode", "helix-exit-space-mode"], cursor=0
    )
    assert app.helix_state.mode == HelixMode.NORMAL


def test_enter_and_exit_window_mode() -> None:
    """``c-w`` enters the window sub-mode and ``escape`` leaves it."""
    _, app = run_helix("abc", "helix-enter-window-mode", cursor=0)
    assert app.helix_state.window_mode

    _, app = run_helix(
        "abc", ["helix-enter-window-mode", "helix-exit-window-mode"], cursor=0
    )
    assert app.helix_state.mode == HelixMode.NORMAL


def test_sub_modes_are_mutually_exclusive() -> None:
    """Entering one sub-mode leaves any other."""
    _, app = run_helix(
        "abc", ["helix-enter-space-mode", "helix-enter-window-mode"], cursor=0
    )
    assert app.helix_state.window_mode
    assert not app.helix_state.space_mode
