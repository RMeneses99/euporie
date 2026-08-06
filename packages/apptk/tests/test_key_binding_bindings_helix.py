"""Characterise the behaviour of the existing Helix key bindings.

These tests pin down what the current implementation does, so that later
refactoring - in particular deriving key-binding registration from the command
registry - can be shown not to change behaviour. They assert actual behaviour
rather than idealised upstream Helix semantics; where the two differ, a ``NOTE``
comment records it.
"""

from __future__ import annotations

import pytest
from apptk.key_binding.helix_state import HelixMode, InputMode
from apptk.selection import SelectionType
from helix_utils import assert_selection, feed_helix, run_helix, selection_range

# Motions


@pytest.mark.parametrize(
    ("command", "cursor", "expected"),
    [
        ("helix-move-right", 0, 1),
        ("helix-move-right", 4, 5),
        ("helix-move-left", 3, 2),
        ("helix-move-left", 0, 0),
    ],
)
def test_horizontal_motions(command: str, cursor: int, expected: int) -> None:
    """Horizontal motions move the cursor and clamp at buffer bounds."""
    buffer, _ = run_helix("hello", command, cursor=cursor)
    assert buffer.cursor_position == expected


def test_move_right_stops_at_end_of_buffer() -> None:
    """Moving right at the end of the buffer does not overrun."""
    buffer, _ = run_helix("ab", "helix-move-right", cursor=2)
    assert buffer.cursor_position == 2


@pytest.mark.parametrize(
    ("command", "cursor", "expected_row"),
    [
        ("helix-move-down", 0, 1),
        ("helix-move-up", 6, 0),
    ],
)
def test_vertical_motions(command: str, cursor: int, expected_row: int) -> None:
    """Vertical motions move between lines."""
    buffer, _ = run_helix("line1\nline2", command, cursor=cursor)
    assert buffer.document.cursor_position_row == expected_row


# Word selection


def test_select_next_word_start_selects_to_next_word() -> None:
    """``w`` selects from the cursor up to the start of the next word."""
    buffer, app = run_helix("hello world", "helix-select-next-word-start", cursor=0)
    assert buffer.cursor_position == 6
    assert_selection(buffer, app, (0, 6))


def test_select_next_long_word_start_spans_punctuation() -> None:
    """``W`` treats punctuation as part of the word."""
    buffer, _ = run_helix("foo.bar baz", "helix-select-next-long-word-start", cursor=0)
    assert buffer.cursor_position == 8


def test_select_prev_word_start_moves_backwards() -> None:
    """``b`` selects backwards to the previous word start."""
    buffer, _ = run_helix("hello world", "helix-select-prev-word-start", cursor=6)
    assert buffer.cursor_position == 0


def test_select_next_word_end_lands_on_word_end() -> None:
    """``e`` selects to the last character of the current word, inclusive."""
    buffer, _ = run_helix("hello world", "helix-select-next-word-end", cursor=0)
    # NOTE: lands on index 4 - the final "o" of "hello" - rather than the
    # exclusive bound 5, because Helix word-end selection is inclusive.
    assert buffer.cursor_position == 4


def test_word_selection_at_end_of_buffer_is_safe() -> None:
    """Word selection at the very end of the buffer does not raise."""
    buffer, _ = run_helix("hi", "helix-select-next-word-start", cursor=2)
    assert buffer.cursor_position <= len(buffer.text)


# Line selection and line motions


def test_extend_line_below_selects_whole_line() -> None:
    """``x`` selects the current line, linewise."""
    buffer, _ = run_helix("hello\nworld", "helix-extend-line-below", cursor=2)
    assert buffer.selection_state is not None
    assert buffer.selection_state.type == SelectionType.LINES
    assert selection_range(buffer) == (0, 5)


def test_extend_line_below_twice_extends_to_next_line() -> None:
    """A second ``x`` extends the existing line selection downwards."""
    buffer, _ = run_helix(
        "one\ntwo\nthree",
        ["helix-extend-line-below", "helix-extend-line-below"],
        cursor=0,
    )
    assert buffer.document.cursor_position_row == 1
    assert selection_range(buffer) == (0, 7)


def test_goto_line_start_and_end() -> None:
    """Line start and end motions move within the current line."""
    buffer, _ = run_helix("hello\nworld", "helix-goto-line-start", cursor=9)
    assert buffer.cursor_position == 6

    buffer, _ = run_helix("hello\nworld", "helix-goto-line-end", cursor=6)
    assert buffer.cursor_position == 11


def test_goto_first_nonwhitespace_skips_indent() -> None:
    """``g s`` moves to the first non-whitespace character of the line."""
    buffer, _ = run_helix("    indented", "helix-goto-first-nonwhitespace", cursor=10)
    assert buffer.cursor_position == 4


# Edits


def test_delete_selection_removes_selected_text() -> None:
    """``d`` deletes the current selection."""
    buffer, _ = run_helix(
        "hello world",
        ["helix-select-next-word-start", "helix-delete-selection"],
        cursor=0,
    )
    assert buffer.text == "world"


def test_change_selection_deletes_and_enters_insert_mode() -> None:
    """``c`` deletes the selection and switches to insert mode."""
    buffer, app = run_helix(
        "hello world",
        ["helix-select-next-word-start", "helix-change-selection"],
        cursor=0,
    )
    assert buffer.text == "world"
    assert app.helix_state.input_mode == InputMode.INSERT


def test_yank_preserves_selection() -> None:
    """``y`` copies the selection and leaves it selected."""
    buffer, app = run_helix(
        "hello world", ["helix-select-next-word-start", "helix-yank"], cursor=0
    )
    assert app.clipboard.get_data().text == "hello "
    assert buffer.selection_state is not None


def test_paste_after_inserts_clipboard_contents() -> None:
    """``p`` pastes the yanked text after the cursor."""
    buffer, _ = run_helix(
        "ab cd",
        ["helix-select-next-word-start", "helix-yank", "helix-paste-after"],
        cursor=0,
    )
    # "w" selects "ab ", which is yanked and then pasted after the cursor.
    assert buffer.text == "ab cab d"


def test_word_selection_with_no_following_word_selects_nothing() -> None:
    """``w`` on the last word of a buffer produces an empty selection."""
    buffer, app = run_helix("ab", "helix-select-next-word-start", cursor=0)
    assert buffer.cursor_position == 0
    assert_selection(buffer, app, (0, 0))


def test_switch_case_without_selection_flips_current_char() -> None:
    """``~`` with no selection flips the case of the character under the cursor."""
    buffer, _ = run_helix("abc", "helix-switch-case", cursor=0)
    assert buffer.text == "Abc"


def test_switch_case_with_selection_flips_selection() -> None:
    """``~`` with a selection flips the case of every selected character."""
    buffer, _ = run_helix(
        "hello world",
        ["helix-select-next-word-start", "helix-switch-case"],
        cursor=0,
    )
    assert buffer.text.startswith("HELLO ")


def test_join_lines_merges_next_line() -> None:
    """``J`` joins the following line onto the current one."""
    buffer, _ = run_helix("one\ntwo", "helix-join-lines", cursor=0)
    assert "\n" not in buffer.text


def test_indent_and_unindent_round_trip() -> None:
    """``>`` then ``<`` restores the original indentation."""
    buffer, _ = run_helix("code", "helix-indent", cursor=0)
    indented = buffer.text
    assert indented.startswith(" ")

    buffer, _ = run_helix(indented, "helix-unindent", cursor=0)
    assert buffer.text == "code"


# Mode transitions


def test_insert_mode_entered() -> None:
    """``i`` enters insert mode."""
    _, app = run_helix("abc", "helix-insert-mode", cursor=1)
    assert app.helix_state.input_mode == InputMode.INSERT


def test_append_mode_enters_insert_and_moves_right() -> None:
    """``a`` enters insert mode positioned after the cursor."""
    buffer, app = run_helix("abc", "helix-append-mode", cursor=0)
    assert app.helix_state.input_mode == InputMode.INSERT
    assert buffer.cursor_position == 1


def test_normal_mode_exits_insert_mode() -> None:
    """``escape`` returns to navigation mode."""
    _, app = run_helix("abc", ["helix-insert-mode", "helix-normal-mode"], cursor=1)
    assert app.helix_state.input_mode == InputMode.NAVIGATION


def test_select_mode_sets_select_flag() -> None:
    """``v`` toggles explicit select mode on the Helix state."""
    _, app = run_helix("abc", "helix-select-mode", cursor=0)
    assert app.helix_state.select_mode


def test_normal_mode_clears_select_mode_and_submode() -> None:
    """Returning to normal mode clears select mode and any sub-mode."""
    _, app = run_helix("abc", ["helix-select-mode", "helix-normal-mode"], cursor=0)
    assert not app.helix_state.select_mode
    assert app.helix_state.mode == HelixMode.NORMAL


# Sub-mode entry


def test_enter_goto_mode_sets_submode() -> None:
    """``g`` enters the goto sub-mode."""
    _, app = run_helix("abc", "helix-enter-goto-mode", cursor=0)
    assert app.helix_state.goto_mode


def test_enter_match_mode_sets_submode() -> None:
    """``m`` enters the match sub-mode."""
    _, app = run_helix("abc", "helix-enter-match-mode", cursor=0)
    assert app.helix_state.match_mode


# Key dispatch - these need the full prompt session


def test_goto_file_start_via_key_sequence() -> None:
    """``g g`` dispatches through goto mode to the start of the buffer."""
    doc, _ = feed_helix("one\ntwo\nthree", "gg\r", cursor=9)
    assert doc.cursor_position == 0


def test_goto_file_end_via_key_sequence() -> None:
    """``g e`` dispatches through goto mode to the end of the buffer."""
    doc, _ = feed_helix("one\ntwo\nthree", "ge\r", cursor=0)
    assert doc.cursor_position > 0


def test_horizontal_motion_via_key_sequence() -> None:
    """Plain ``l`` motions dispatch in navigation mode."""
    doc, _ = feed_helix("hello world", "lll\r", cursor=0)
    assert doc.cursor_position == 3


def test_insert_mode_via_key_sequence_types_text() -> None:
    """``i`` followed by printable keys inserts text at the cursor."""
    doc, _ = feed_helix("world", "ihello \r", cursor=0)
    assert doc.text == "hello world"
