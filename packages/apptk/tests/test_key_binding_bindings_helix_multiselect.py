"""Test the Helix multiple-selection commands against a buffer."""

from __future__ import annotations

from apptk.application.current import set_app
from apptk.commands import get_cmd
from apptk.key_binding.bindings.helix_selections import get_selections, set_selections
from helix_utils import make_event, run_helix

SPLIT_THREE_LINES = [
    "helix-extend-line-below",
    "helix-extend-line-below",
    "helix-extend-line-below",
    "helix-split-selection-newlines",
]


def test_split_selection_on_newlines_creates_one_range_per_line() -> None:
    """``A-s`` turns a multi-line selection into one selection per line."""
    _, app = run_helix("one\ntwo\nthree", SPLIT_THREE_LINES, cursor=0, select_mode=True)
    assert app.helix_state.selections == [(0, 3), (4, 7), (8, 13)]


def test_split_selection_sets_a_cursor_per_range() -> None:
    """Each selection contributes a cursor position for rendering."""
    buffer, _ = run_helix(
        "one\ntwo\nthree", SPLIT_THREE_LINES, cursor=0, select_mode=True
    )
    assert buffer.multiple_cursor_positions == [3, 7, 13]


def test_primary_selection_is_mirrored_onto_the_buffer() -> None:
    """The primary range is reflected in the buffer's own selection state."""
    buffer, _ = run_helix(
        "one\ntwo\nthree", SPLIT_THREE_LINES, cursor=0, select_mode=True
    )
    assert buffer.selection_state is not None
    assert buffer.selection_state.original_cursor_position == 0
    assert buffer.cursor_position == 3


def test_keep_primary_selection_collapses_to_one() -> None:
    """``,`` discards every selection but the primary."""
    buffer, app = run_helix(
        "one\ntwo\nthree",
        [*SPLIT_THREE_LINES, "helix-keep-primary-selection"],
        cursor=0,
        select_mode=True,
    )
    # A single selection is held on the buffer, so the extra ranges are cleared.
    assert app.helix_state.selections == []
    assert buffer.multiple_cursor_positions == []
    assert buffer.selection_state is not None


def test_remove_primary_selection_keeps_the_others() -> None:
    """``A-,`` drops the primary selection and keeps the rest."""
    _, app = run_helix(
        "one\ntwo\nthree",
        [*SPLIT_THREE_LINES, "helix-remove-primary-selection"],
        cursor=0,
        select_mode=True,
    )
    assert app.helix_state.selections == [(4, 7), (8, 13)]


def test_remove_last_selection_clears_select_mode() -> None:
    """Removing the only selection leaves select mode."""
    _, app = run_helix(
        "hello",
        ["helix-extend-line-below", "helix-remove-primary-selection"],
        cursor=0,
        select_mode=True,
    )
    assert not app.helix_state.select_mode


def test_trim_selections_removes_whitespace() -> None:
    """``_`` tightens each selection onto its non-whitespace content."""
    buffer, _ = run_helix(
        "  ab  ",
        ["helix-extend-line-below", "helix-trim-selections"],
        cursor=0,
        select_mode=True,
    )
    assert buffer.selection_state is not None
    assert (
        buffer.selection_state.original_cursor_position,
        buffer.cursor_position,
    ) == (
        2,
        4,
    )


def test_copy_selection_below_adds_a_second_range() -> None:
    """``C`` adds a further selection on the following line."""
    _, app = run_helix("abc\ndef", ["helix-copy-selection-below"], cursor=0)
    assert app.helix_state.selections == [(0, 0), (4, 4)]


def test_copy_selection_above_from_second_line() -> None:
    """``A-C`` adds a further selection on the preceding line."""
    _, app = run_helix("abc\ndef", ["helix-copy-selection-above"], cursor=4)
    assert app.helix_state.selections == [(0, 0), (4, 4)]


def test_copy_selection_below_at_last_line_does_nothing() -> None:
    """``C`` on the final line leaves the selections unchanged."""
    _, app = run_helix("abc", ["helix-copy-selection-below"], cursor=0)
    assert app.helix_state.selections == []


def test_align_selections_pads_into_a_common_column() -> None:
    """``&`` inserts padding so the selections share a column."""
    buffer, app = run_helix("a\n  b", [], cursor=0, select_mode=True)
    with set_app(app):
        set_selections(buffer, [(0, 1), (4, 5)])
        get_cmd("helix-align-selections").handler(make_event(app))
    assert buffer.text == "  a\n  b"


def test_align_selections_is_a_single_undo_step() -> None:
    """``&`` records one undo entry, not one per selection.

    A multi-site edit which pushed one undo entry per selection would need as
    many undos to reverse, which is the property most likely to regress.
    """
    buffer, app = run_helix("a\n  b", [], cursor=0, select_mode=True)
    with set_app(app):
        set_selections(buffer, [(0, 1), (4, 5)])
        get_cmd("helix-align-selections").handler(make_event(app))
        assert buffer.text == "  a\n  b"
        buffer.undo()
    assert buffer.text == "a\n  b"


# Degenerate single-selection behaviour


def test_get_selections_derives_a_range_from_the_cursor() -> None:
    """With nothing selected, a single empty range at the cursor is reported."""
    buffer, app = run_helix("hello", [], cursor=2)
    with set_app(app):
        assert get_selections(buffer) == [(2, 2)]


def test_get_selections_derives_a_range_from_the_buffer_selection() -> None:
    """With one selection, it is derived from the buffer rather than helix state."""
    buffer, app = run_helix("hello", ["helix-extend-line-below"], cursor=0)
    with set_app(app):
        assert get_selections(buffer) == [(0, 5)]


def test_single_range_is_not_stored_as_multiple() -> None:
    """Installing one range leaves the multi-selection state empty."""
    buffer, app = run_helix("hello", [], cursor=0)
    with set_app(app):
        set_selections(buffer, [(0, 3)])
    assert app.helix_state.selections == []
    assert buffer.selection_state is not None


# Invalidation


def test_editing_text_discards_multiple_selections() -> None:
    """An edit from any source clears stale multi-selection ranges."""
    buffer, app = run_helix("one\ntwo", [], cursor=0)
    with set_app(app):
        set_selections(buffer, [(0, 3), (4, 7)])
        assert app.helix_state.selections == [(0, 3), (4, 7)]
        # An edit not made by a multi-site command must invalidate the ranges,
        # since their offsets are no longer meaningful.
        buffer.insert_text("xyz")
    assert app.helix_state.selections == []


def test_multi_edit_flag_preserves_selections() -> None:
    """A multi-site edit may keep its own ranges while editing."""
    buffer, app = run_helix("one\ntwo", [], cursor=0)
    with set_app(app):
        set_selections(buffer, [(0, 3), (4, 7)])
        app.helix_state._applying_multi_edit = True
        buffer.insert_text("xyz")
        app.helix_state._applying_multi_edit = False
    assert app.helix_state.selections == [(0, 3), (4, 7)]
