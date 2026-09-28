"""Test core motions and selection commands for the Kakoune editing mode.

These assert Kakoune's own semantics, which differ from Helix's on several keys
that look identical. Where the two diverge a ``NOTE`` records it, so that a later
refactor cannot quietly drift towards the Helix meaning.
"""

from __future__ import annotations

import pytest
from kakoune_utils import run_kakoune, selection_ranges

from apptk.key_binding.kakoune_state import InputMode


def _anchor_head(buffer: object) -> tuple[int | None, int]:
    """Return a buffer's selection anchor and head, for direction assertions."""
    state = buffer.selection_state  # type: ignore[attr-defined]
    anchor = state.original_cursor_position if state else None
    return anchor, buffer.cursor_position  # type: ignore[attr-defined]


# Never-empty selections


def test_bare_cursor_is_a_one_character_selection() -> None:
    """A cursor with nothing selected still covers one character.

    This is the invariant every other command relies on, and the main behavioural
    difference from Helix, whose selections may be empty.
    """
    buffer, _ = run_kakoune("hello", [], cursor=2)
    assert selection_ranges(buffer) == [(2, 3)]


def test_cursor_at_end_of_buffer_selects_backwards() -> None:
    """At the very end there is no character ahead, so the one behind is used."""
    buffer, _ = run_kakoune("abc", [], cursor=3)
    assert selection_ranges(buffer) == [(2, 3)]


def test_empty_buffer_yields_an_empty_range() -> None:
    """With no text at all there is nothing to select."""
    buffer, _ = run_kakoune("", [], cursor=0)
    assert selection_ranges(buffer) == [(0, 0)]


# Character and line movement


@pytest.mark.parametrize(
    ("command", "cursor", "expected"),
    [
        ("kakoune-left", 5, [(4, 5)]),
        ("kakoune-right", 5, [(6, 7)]),
        ("kakoune-left", 0, [(0, 1)]),
    ],
)
def test_character_movement(command: str, cursor: int, expected: list) -> None:
    """``h`` and ``l`` move by a character and clamp at the buffer bounds."""
    buffer, _ = run_kakoune("one two three", command, cursor=cursor)
    assert selection_ranges(buffer) == expected


def test_shift_extends_rather_than_replacing() -> None:
    """``H`` keeps the anchor and moves only the cursor.

    Kakoune has no select mode; Shift is what extends.
    """
    buffer, _ = run_kakoune("one two three", "kakoune-left-extend", cursor=5)
    anchor, head = _anchor_head(buffer)
    assert (anchor, head) == (5, 4)


def test_repeated_extend_grows_the_selection() -> None:
    """Successive ``H`` presses keep growing the same selection."""
    buffer, _ = run_kakoune("one two three", ["kakoune-left-extend"] * 3, cursor=8)
    assert selection_ranges(buffer) == [(5, 8)]


def test_vertical_movement_keeps_the_column() -> None:
    """``j`` and ``k`` preserve the column where the target line is long enough."""
    buffer, _ = run_kakoune("alpha\nbeta\ngamma", "kakoune-down", cursor=2)
    assert selection_ranges(buffer) == [(8, 9)]


def test_vertical_movement_clamps_to_short_lines() -> None:
    """Moving onto a shorter line clamps to its end rather than overshooting."""
    buffer, _ = run_kakoune("alpha\nab\ngamma", "kakoune-down", cursor=4)
    assert selection_ranges(buffer) == [(8, 9)]


# Word motions - Kakoune includes adjacent whitespace, Helix does not


def test_next_word_includes_trailing_whitespace() -> None:
    """``w`` selects the word *and the whitespace after it*.

    NOTE: this is why ``w`` then ``d`` removes a word and its separator in one
    go. Helix's ``w`` stops at the word boundary.
    """
    text = "one two three"
    buffer, _ = run_kakoune(text, "kakoune-next-word", cursor=0)
    ranges = selection_ranges(buffer)
    assert [text[s:e] for s, e in ranges] == ["one "]


def test_word_end_excludes_trailing_whitespace() -> None:
    """``e`` stops on the word's last character."""
    text = "one two three"
    buffer, _ = run_kakoune(text, "kakoune-word-end", cursor=0)
    assert [text[s:e] for s, e in selection_ranges(buffer)] == ["one"]


def test_prev_word_selects_backwards() -> None:
    """``b`` runs backwards, leaving the head before the anchor."""
    buffer, _ = run_kakoune("one two three", "kakoune-prev-word", cursor=8)
    anchor, head = _anchor_head(buffer)
    assert anchor == 8
    assert head == 4
    assert head < anchor


def test_long_word_motion_treats_punctuation_as_word() -> None:
    """``<a-w>`` uses WORD semantics.

    NOTE: Kakoune spells the WORD variants with Alt. Helix uses Shift, which here
    is taken by extension.
    """
    text = "a.b c"
    buffer, _ = run_kakoune(text, "kakoune-next-long-word", cursor=0)
    ranges = selection_ranges(buffer)
    assert [text[s:e] for s, e in ranges] == ["a.b "]


# Line-wise selection - the most dangerous divergence from Helix


def test_x_expands_to_whole_lines() -> None:
    """``x`` expands the selection to cover whole lines, including the newline.

    NOTE: Helix's ``x`` instead extends the selection downwards by one line. This
    is the single most commonly mistaken difference between the two editors.
    """
    text = "alpha\nbeta\ngamma"
    buffer, _ = run_kakoune(text, "kakoune-expand-lines", cursor=2)
    assert [text[s:e] for s, e in selection_ranges(buffer)] == ["alpha\n"]


def test_repeated_x_extends_onto_following_lines() -> None:
    """Pressing ``x`` again takes in the next line."""
    text = "alpha\nbeta\ngamma"
    buffer, _ = run_kakoune(text, ["kakoune-expand-lines"] * 2, cursor=2)
    assert [text[s:e] for s, e in selection_ranges(buffer)] == ["alpha\nbeta\n"]


def test_x_stops_at_end_of_buffer() -> None:
    """``x`` on the final line is idempotent rather than erroring."""
    text = "alpha\nbeta"
    buffer, _ = run_kakoune(text, ["kakoune-expand-lines"] * 4, cursor=0)
    assert selection_ranges(buffer) == [(0, len(text))]


def test_alt_x_trims_to_whole_lines() -> None:
    """``<a-x>`` keeps only the whole lines a selection fully contains."""
    text = "alpha\nbeta\ngamma"
    buffer, _ = run_kakoune(text, "kakoune-trim-lines", selections=[(2, 12)])
    assert [text[s:e] for s, e in selection_ranges(buffer)] == ["beta"]


# Whole buffer, reduce and flip


def test_percent_selects_the_whole_buffer() -> None:
    """``%`` selects everything."""
    text = "alpha\nbeta"
    buffer, _ = run_kakoune(text, "kakoune-select-buffer")
    assert selection_ranges(buffer) == [(0, len(text))]


def test_semicolon_reduces_to_the_cursor() -> None:
    """``;`` reduces each selection to the single character at its cursor."""
    buffer, _ = run_kakoune(
        "one two three", "kakoune-reduce-to-cursor", selections=[(0, 7)]
    )
    assert selection_ranges(buffer) == [(6, 7)]


def test_alt_semicolon_flips_direction() -> None:
    """``<a-;>`` swaps anchor and head without changing the covered text."""
    buffer, _ = run_kakoune(
        "one two three", ["kakoune-prev-word", "kakoune-flip-selections"], cursor=8
    )
    anchor, head = _anchor_head(buffer)
    assert (anchor, head) == (4, 8)


def test_alt_colon_forces_selections_forward() -> None:
    """``<a-:>`` orients every selection so the cursor follows the anchor."""
    buffer, _ = run_kakoune(
        "one two three", ["kakoune-prev-word", "kakoune-forward-selections"], cursor=8
    )
    anchor, head = _anchor_head(buffer)
    assert anchor is not None
    assert head > anchor


# Insert-mode entry points


@pytest.mark.parametrize(
    ("command", "expected_caret"),
    [
        ("kakoune-insert", 4),
        ("kakoune-append", 7),
    ],
)
def test_insert_entry_points(command: str, expected_caret: int) -> None:
    """``i`` goes before the selection and ``a`` after it."""
    buffer, app = run_kakoune("one two three", command, selections=[(4, 7)])
    assert app.kakoune_state.input_mode == InputMode.INSERT
    assert buffer.cursor_position == expected_caret


def test_insert_line_start_goes_to_first_non_blank() -> None:
    """``I`` enters insert mode at the first non-blank character of the line."""
    buffer, _ = run_kakoune("    indented", "kakoune-insert-line-start", cursor=8)
    assert buffer.cursor_position == 4


def test_insert_line_end_goes_to_end_of_line() -> None:
    """``A`` enters insert mode at the end of the line."""
    buffer, _ = run_kakoune("alpha\nbeta", "kakoune-insert-line-end", cursor=2)
    assert buffer.cursor_position == 5


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("kakoune-open-below", "alpha\n\nbeta"),
        ("kakoune-open-above", "\nalpha\nbeta"),
    ],
)
def test_open_line(command: str, expected: str) -> None:
    """``o`` and ``O`` open a line and enter insert mode."""
    buffer, app = run_kakoune("alpha\nbeta", command, cursor=2)
    assert buffer.text == expected
    assert app.kakoune_state.input_mode == InputMode.INSERT
