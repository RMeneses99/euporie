"""Test multiple-selection creation and manipulation in the Kakoune mode.

Multiple selections are Kakoune's defining feature, and its vocabulary here is
richer than Helix's: rotating which selection is main, rotating the *contents*
between selections, merging contiguous versus overlapping ranges, and filtering
selections by regular expression.
"""

from __future__ import annotations

import pytest
from kakoune_utils import run_kakoune, selection_ranges


def _selected(text: str, buffer: object) -> list[str]:
    """Return the selected substrings, for readable assertions."""
    return [text[s:e] for s, e in selection_ranges(buffer)]  # type: ignore[arg-type]


TEXT = "alpha\nbeta\ngamma"


# Splitting


def test_split_on_lines() -> None:
    """``<a-s>`` gives one selection per line."""
    buffer, _ = run_kakoune(TEXT, "kakoune-split-lines", selections=[(0, 16)])
    assert _selected(TEXT, buffer) == ["alpha", "beta", "gamma"]


def test_select_ends_keeps_first_and_last_characters() -> None:
    """``<a-S>`` reduces a selection to its two end characters."""
    buffer, _ = run_kakoune(TEXT, "kakoune-select-ends", selections=[(0, 5)])
    assert selection_ranges(buffer) == [(0, 1), (4, 5)]


def test_select_ends_leaves_short_selections_alone() -> None:
    """A selection of two characters or fewer is already its own ends."""
    buffer, _ = run_kakoune(TEXT, "kakoune-select-ends", selections=[(0, 2)])
    assert selection_ranges(buffer) == [(0, 2)]


# Duplicating and merging


def test_duplicate_selections() -> None:
    """``+`` duplicates each selection."""
    buffer, _ = run_kakoune(TEXT, "kakoune-duplicate-selections", selections=[(0, 5)])
    assert selection_ranges(buffer) == [(0, 5), (0, 5)]


def test_merge_contiguous_joins_touching_selections() -> None:
    """``<a-_>`` merges selections which touch."""
    buffer, _ = run_kakoune(
        TEXT, "kakoune-merge-contiguous", selections=[(0, 3), (3, 5)]
    )
    assert selection_ranges(buffer) == [(0, 5)]


def test_merge_overlapping_leaves_touching_selections_apart() -> None:
    """``<a-+>`` merges only genuine overlaps, unlike ``<a-_>``."""
    touching, _ = run_kakoune(
        TEXT, "kakoune-merge-overlapping", selections=[(0, 3), (3, 5)]
    )
    assert selection_ranges(touching) == [(0, 3), (3, 5)]

    overlapping, _ = run_kakoune(
        TEXT, "kakoune-merge-overlapping", selections=[(0, 4), (3, 5)]
    )
    assert selection_ranges(overlapping) == [(0, 5)]


# Reducing


def test_keep_main_selection() -> None:
    """``,`` discards every selection but the main one."""
    buffer, _ = run_kakoune(
        TEXT, "kakoune-keep-main-selection", selections=[(0, 3), (6, 10)]
    )
    assert selection_ranges(buffer) == [(0, 3)]


def test_remove_main_selection() -> None:
    """``<a-,>`` discards the main selection and keeps the others."""
    buffer, _ = run_kakoune(
        TEXT, "kakoune-remove-main-selection", selections=[(0, 3), (6, 10)]
    )
    assert selection_ranges(buffer) == [(6, 10)]


def test_remove_main_selection_needs_more_than_one() -> None:
    """With a single selection there is nothing to remove."""
    buffer, _ = run_kakoune(TEXT, "kakoune-remove-main-selection", selections=[(0, 3)])
    assert selection_ranges(buffer) == [(0, 3)]


# Rotating


def test_rotate_main_forward_moves_the_primary_marker() -> None:
    """``)`` makes the next selection the main one.

    NOTE: Helix ships the underlying ``rotate_primary`` but binds no key to it.
    """
    _, app = run_kakoune(
        TEXT, "kakoune-rotate-main-forward", selections=[(0, 3), (6, 10)]
    )
    assert app.kakoune_state.primary_index == 1


def test_rotate_main_wraps_around() -> None:
    """Rotating past the last selection returns to the first."""
    _, app = run_kakoune(
        TEXT,
        ["kakoune-rotate-main-forward"] * 2,
        selections=[(0, 3), (6, 10)],
    )
    assert app.kakoune_state.primary_index == 0


def test_rotate_main_backward() -> None:
    """``(`` moves the main marker the other way, wrapping to the end."""
    _, app = run_kakoune(
        TEXT, "kakoune-rotate-main-backward", selections=[(0, 3), (6, 10)]
    )
    assert app.kakoune_state.primary_index == 1


def test_rotate_contents_moves_text_between_selections() -> None:
    """``<a-)>`` rotates the text while the selections stay put.

    This has no Helix equivalent.
    """
    buffer, _ = run_kakoune(
        "aaa bbb ccc",
        "kakoune-rotate-contents-forward",
        selections=[(0, 3), (4, 7), (8, 11)],
    )
    assert buffer.text == "ccc aaa bbb"


def test_rotate_contents_backward() -> None:
    """``<a-(>`` rotates the text the other way."""
    buffer, _ = run_kakoune(
        "aaa bbb ccc",
        "kakoune-rotate-contents-backward",
        selections=[(0, 3), (4, 7), (8, 11)],
    )
    assert buffer.text == "bbb ccc aaa"


def test_rotate_contents_needs_several_selections() -> None:
    """With one selection there is nothing to rotate."""
    buffer, _ = run_kakoune(
        "aaa bbb", "kakoune-rotate-contents-forward", selections=[(0, 3)]
    )
    assert buffer.text == "aaa bbb"


# Copying onto adjacent lines


def test_copy_selection_below_adds_a_selection() -> None:
    """``C`` adds a matching selection on the next line."""
    buffer, _ = run_kakoune(TEXT, "kakoune-copy-selection-below", selections=[(0, 4)])
    assert _selected(TEXT, buffer) == ["alph", "beta"]


def test_copy_selection_above_adds_a_selection() -> None:
    """``<a-C>`` adds a matching selection on the previous line."""
    buffer, _ = run_kakoune(TEXT, "kakoune-copy-selection-above", selections=[(6, 10)])
    assert _selected(TEXT, buffer) == ["alph", "beta"]


def test_copy_selection_rings_bell_with_no_room() -> None:
    """Copying past the last line leaves the selections unchanged."""
    buffer, _ = run_kakoune("only", "kakoune-copy-selection-below", selections=[(0, 4)])
    assert selection_ranges(buffer) == [(0, 4)]


# Regex operations, applied directly rather than through the prompt


@pytest.mark.parametrize(
    ("operation", "pattern", "expected"),
    [
        ("select", "a", ["a", "a", "a", "a", "a"]),
        ("split", "a", ["lph", "\nbet", "\ng", "mm"]),
    ],
)
def test_regex_operations(operation: str, pattern: str, expected: list[str]) -> None:
    """``s`` and ``S`` select and split on a regular expression."""
    from apptk.application.current import set_app
    from apptk.buffer import Buffer
    from apptk.document import Document
    from apptk.key_binding.bindings.kakoune import apply_pending_regex
    from kakoune_utils import make_kakoune_app

    buffer = Buffer(document=Document(TEXT, 0), multiline=True)
    app = make_kakoune_app(buffer)
    with set_app(app):
        app.kakoune_state.pending_regex_op = operation
        app.kakoune_state.pending_regex_ranges = [(0, len(TEXT))]
        apply_pending_regex(buffer, pattern)

    assert _selected(TEXT, buffer) == expected


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("keep", ["beta"]),
        ("drop", ["alpha", "gamma"]),
    ],
)
def test_regex_filtering(operation: str, expected: list[str]) -> None:
    """``<a-k>`` and ``<a-K>`` keep and drop selections by pattern."""
    from apptk.application.current import set_app
    from apptk.buffer import Buffer
    from apptk.document import Document
    from apptk.key_binding.bindings.kakoune import apply_pending_regex
    from kakoune_utils import make_kakoune_app

    buffer = Buffer(document=Document(TEXT, 0), multiline=True)
    app = make_kakoune_app(buffer)
    with set_app(app):
        app.kakoune_state.pending_regex_op = operation
        app.kakoune_state.pending_regex_ranges = [(0, 5), (6, 10), (11, 16)]
        apply_pending_regex(buffer, "et")

    assert _selected(TEXT, buffer) == expected


def test_invalid_regex_is_survivable() -> None:
    """A malformed pattern rings the bell rather than raising."""
    from apptk.application.current import set_app
    from apptk.buffer import Buffer
    from apptk.document import Document
    from apptk.key_binding.bindings.kakoune import apply_pending_regex
    from kakoune_utils import make_kakoune_app

    buffer = Buffer(document=Document(TEXT, 0), multiline=True)
    app = make_kakoune_app(buffer)
    with set_app(app):
        app.kakoune_state.pending_regex_op = "select"
        app.kakoune_state.pending_regex_ranges = [(0, len(TEXT))]
        apply_pending_regex(buffer, "(unclosed")

    assert buffer.text == TEXT
