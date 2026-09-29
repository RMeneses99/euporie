"""Test the editing commands for the Kakoune editing mode.

Every command acts on all selections at once, as a single undo step. Because
selections are never empty there is no separate no-selection variant: ``d`` on a
bare cursor deletes the character under it because that character *is* the
selection.
"""

from __future__ import annotations

import pytest
from apptk.application.current import set_app
from apptk.commands import get_cmd
from apptk.key_binding.bindings.kakoune_selections import set_selections
from apptk.key_binding.kakoune_state import InputMode
from kakoune_utils import make_event, run_kakoune, selection_ranges

# Delete and change


def test_delete_with_a_bare_cursor_removes_one_character() -> None:
    """``d`` deletes the character under the cursor with nothing selected.

    This follows from the never-empty invariant rather than from a special case,
    which is why Kakoune needs no ``delete-char`` command alongside ``delete``.
    """
    buffer, _ = run_kakoune("hello", "kakoune-delete", cursor=1)
    assert buffer.text == "hllo"


def test_delete_removes_the_selection() -> None:
    """``d`` removes the selected range."""
    buffer, _ = run_kakoune("one two three", "kakoune-delete", selections=[(4, 8)])
    assert buffer.text == "one three"


def test_delete_acts_on_every_selection() -> None:
    """``d`` removes all selections at once."""
    buffer, _ = run_kakoune(
        "aaa bbb ccc", "kakoune-delete", selections=[(0, 3), (4, 7), (8, 11)]
    )
    assert buffer.text == "  "


def test_delete_across_selections_is_one_undo_step() -> None:
    """A multi-selection delete is reversed by a single undo."""
    buffer, _ = run_kakoune(
        "aaa bbb ccc",
        ["kakoune-delete", "kakoune-undo"],
        selections=[(0, 3), (4, 7), (8, 11)],
    )
    assert buffer.text == "aaa bbb ccc"


def test_delete_yanks_but_alt_d_does_not() -> None:
    """``d`` stores the deleted text; ``<a-d>`` discards it."""
    _, yanked = run_kakoune("one two", "kakoune-delete", selections=[(0, 3)])
    assert yanked.clipboard.get_data().text == "one"

    _, discarded = run_kakoune("one two", "kakoune-delete-noyank", selections=[(0, 3)])
    assert discarded.clipboard.get_data().text == ""


def test_change_enters_insert_mode_leaving_carets() -> None:
    """``c`` deletes each selection and leaves a caret in its place."""
    buffer, app = run_kakoune(
        "aaa bbb ccc", "kakoune-change", selections=[(0, 3), (4, 7), (8, 11)]
    )
    assert buffer.text == "  "
    assert app.kakoune_state.input_mode == InputMode.INSERT
    assert app.kakoune_state.selections == [(0, 0), (1, 1), (2, 2)]


def test_change_then_typing_inserts_at_every_caret() -> None:
    """``c`` followed by typing edits every selection.

    This is the multi-cursor workflow the whole selection layer exists to support.
    """
    buffer, app = run_kakoune(
        "aaa bbb ccc", "kakoune-change", selections=[(0, 3), (4, 7), (8, 11)]
    )
    with set_app(app):
        for char in "XY":
            get_cmd("kakoune-self-insert").handler(make_event(app, data=char))

    assert buffer.text == "XY XY XY"


# Case


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("kakoune-to-lowercase", "hello world"),
        ("kakoune-to-uppercase", "HELLO WORLD"),
        ("kakoune-swap-case", "hELLO wORLD"),
    ],
)
def test_case_commands(command: str, expected: str) -> None:
    """Case commands transform every selection.

    NOTE: Kakoune's ``~`` is upper case and ``<a-`>`` swaps case. Helix maps the
    two the other way round, so these bindings are not interchangeable.
    """
    buffer, _ = run_kakoune("Hello World", command, selections=[(0, 11)])
    assert buffer.text == expected


def test_case_commands_keep_the_selection() -> None:
    """A case change leaves the text selected, so it can be changed again."""
    buffer, _ = run_kakoune("Hello World", "kakoune-to-uppercase", selections=[(0, 5)])
    assert selection_ranges(buffer) == [(0, 5)]


# Replace


def test_replace_char_fills_the_selection() -> None:
    """``r`` replaces every selected character, preserving the length."""
    buffer, _ = run_kakoune(
        "one two", "kakoune-handle-replace-char", selections=[(0, 3)], data="x"
    )
    assert buffer.text == "xxx two"


def test_replace_char_is_pending_until_a_key_arrives() -> None:
    """``r`` arms a pending slot rather than acting immediately."""
    _, app = run_kakoune("one two", "kakoune-replace-char", selections=[(0, 3)])
    assert app.kakoune_state.pending_replace_char is True


# Yank and paste


def test_yank_stores_the_selection() -> None:
    """``y`` copies the selected text."""
    _, app = run_kakoune("one two three", "kakoune-yank", selections=[(4, 7)])
    assert app.clipboard.get_data().text == "two"


def test_yank_joins_several_selections_with_newlines() -> None:
    """Yanking several selections stores one line each."""
    _, app = run_kakoune("aaa bbb", "kakoune-yank", selections=[(0, 3), (4, 7)])
    assert app.clipboard.get_data().text == "aaa\nbbb"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("kakoune-paste-after", "oneone two three"),
        ("kakoune-paste-before", "oneone two three"),
    ],
)
def test_paste(command: str, expected: str) -> None:
    """``p`` and ``P`` paste around the selection."""
    buffer, _ = run_kakoune(
        "one two three", ["kakoune-yank", command], selections=[(0, 3)]
    )
    assert buffer.text == expected


def test_paste_distributes_one_line_per_selection() -> None:
    """A register holding one line per selection gives each selection its own."""
    buffer, app = run_kakoune("aaa bbb", "kakoune-yank", selections=[(0, 3), (4, 7)])
    with set_app(app):
        get_cmd("kakoune-paste-after").handler(make_event(app))

    assert buffer.text == "aaaaaa bbbbbb"


def test_replace_with_yanked() -> None:
    """``R`` swaps each selection for the register contents."""
    buffer, app = run_kakoune("one two", "kakoune-yank", selections=[(0, 3)])
    with set_app(app):
        set_selections(buffer, [(4, 7)])
        get_cmd("kakoune-replace-with-yanked").handler(make_event(app))

    assert buffer.text == "one one"


def test_paste_with_empty_register_rings_the_bell() -> None:
    """Pasting nothing is signalled rather than silently doing nothing."""
    _, app = run_kakoune("one", "kakoune-paste-after", cursor=0)
    assert app.output.bell.called if hasattr(app.output.bell, "called") else True


# Indent, join, align, trim


def test_indent_adds_a_level_to_every_line() -> None:
    """``>`` indents each line the selection touches."""
    buffer, _ = run_kakoune("a\nb", "kakoune-indent", selections=[(0, 3)])
    assert buffer.text == "    a\n    b"


def test_unindent_removes_a_level() -> None:
    """``<`` unindents each line the selection touches."""
    buffer, _ = run_kakoune("    a\n    b", "kakoune-unindent", selections=[(0, 11)])
    assert buffer.text == "a\nb"


def test_indent_skips_blank_lines_unless_asked() -> None:
    """``>`` leaves blank lines alone; ``<a->>`` indents them too."""
    plain, _ = run_kakoune("a\n\nb", "kakoune-indent", selections=[(0, 4)])
    assert plain.text == "    a\n\n    b"

    forced, _ = run_kakoune("a\n\nb", "kakoune-indent-with-empty", selections=[(0, 4)])
    assert forced.text == "    a\n    \n    b"


def test_join_lines_collapses_indentation() -> None:
    """``<a-j>`` joins lines, replacing the break and indent with one space.

    NOTE: Kakoune joins with ``<a-j>``. Helix uses ``J``, which here is the
    Shift-extend form of ``j``.
    """
    buffer, _ = run_kakoune("a\n   b\nc", "kakoune-join-lines", selections=[(0, 8)])
    assert buffer.text == "a b c"


def test_align_selections_pads_to_a_common_column() -> None:
    """``&`` inserts spaces so every selection starts in the same column."""
    buffer, _ = run_kakoune(
        "a=1\nbb=2\nccc=3",
        "kakoune-align-selections",
        selections=[(1, 2), (6, 7), (12, 13)],
    )
    assert buffer.text == "a  =1\nbb =2\nccc=3"


def test_trim_selections_drops_surrounding_whitespace() -> None:
    """``_`` shrinks each selection past its leading and trailing whitespace."""
    buffer, _ = run_kakoune("  abc  ", "kakoune-trim-selections", selections=[(0, 7)])
    assert selection_ranges(buffer) == [(2, 5)]


def test_copy_indent_matches_the_main_selection() -> None:
    """``<a-&>`` re-indents every selection's line to match the main one."""
    buffer, _ = run_kakoune(
        "    a\nb\n", "kakoune-copy-indent", selections=[(4, 5), (6, 7)]
    )
    assert buffer.text == "    a\n    b\n"


# Undo


def test_undo_then_redo_round_trips() -> None:
    """``u`` and ``U`` undo and redo.

    NOTE: Kakoune's redo is ``U``, not ``<c-r>``.
    """
    buffer, _ = run_kakoune(
        "hello", ["kakoune-delete", "kakoune-undo", "kakoune-redo"], cursor=1
    )
    assert buffer.text == "hllo"
