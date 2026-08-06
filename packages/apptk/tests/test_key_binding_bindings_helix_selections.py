"""Test the Helix multiple-selection range transforms.

The transforms are pure functions over text and ranges, so they are tested here
directly, with no buffer or application involved.
"""

from __future__ import annotations

import pytest
from apptk.key_binding.bindings.helix_selections import (
    align_ranges,
    collapse_to_primary,
    copy_range_to_line,
    normalise,
    rotate_primary,
    select_regex_within,
    split_on_newlines,
    split_on_regex,
    trim_ranges,
)


@pytest.mark.parametrize(
    ("text_range", "expected"),
    [((0, 5), (0, 5)), ((5, 0), (0, 5)), ((3, 3), (3, 3))],
)
def test_normalise_sorts_range(
    text_range: tuple[int, int], expected: tuple[int, int]
) -> None:
    """Ranges are normalised to ``(start, end)`` order."""
    assert normalise(text_range) == expected


# split_on_newlines


def test_split_on_newlines_gives_one_range_per_line() -> None:
    """A range spanning several lines is split at each newline."""
    assert split_on_newlines("one\ntwo\nthree", [(0, 13)]) == [
        (0, 3),
        (4, 7),
        (8, 13),
    ]


def test_split_on_newlines_single_line_is_unchanged() -> None:
    """A range within one line is returned as-is."""
    assert split_on_newlines("hello", [(0, 5)]) == [(0, 5)]


def test_split_on_newlines_handles_empty_range() -> None:
    """An empty range yields a single empty range."""
    assert split_on_newlines("abc", [(1, 1)]) == [(1, 1)]


# split_on_regex


def test_split_on_regex_removes_matches() -> None:
    """Splitting keeps the text between matches, not the matches themselves."""
    assert split_on_regex("a,b,c", [(0, 5)], ",") == [(0, 1), (2, 3), (4, 5)]


def test_split_on_regex_ignores_zero_width_matches() -> None:
    """A zero-width pattern does not loop forever or produce empty ranges."""
    assert split_on_regex("abc", [(0, 3)], "") == [(0, 3)]


def test_split_on_regex_with_no_match_returns_original() -> None:
    """A pattern which never matches leaves the range intact."""
    assert split_on_regex("abc", [(0, 3)], "z") == [(0, 3)]


# select_regex_within


def test_select_regex_within_finds_all_matches() -> None:
    """Every match inside the range becomes its own selection."""
    assert select_regex_within("one two one", [(0, 11)], "one") == [(0, 3), (8, 11)]


def test_select_regex_within_is_bounded_by_the_range() -> None:
    """Matches outside the given range are not selected."""
    assert select_regex_within("one two one", [(0, 7)], "one") == [(0, 3)]


def test_select_regex_within_skips_zero_width_matches() -> None:
    """Zero-width matches do not become selections."""
    assert select_regex_within("abc", [(0, 3)], "x*") == []


# trim_ranges


def test_trim_ranges_removes_surrounding_whitespace() -> None:
    """Leading and trailing whitespace is trimmed from each range."""
    assert trim_ranges("  ab  ", [(0, 6)]) == [(2, 4)]


def test_trim_ranges_drops_whitespace_only_ranges() -> None:
    """A range containing only whitespace is discarded."""
    assert trim_ranges("    ", [(0, 4)]) == []


def test_trim_ranges_leaves_tight_ranges_alone() -> None:
    """A range with no surrounding whitespace is unchanged."""
    assert trim_ranges("ab", [(0, 2)]) == [(0, 2)]


# copy_range_to_line


def test_copy_range_to_line_below() -> None:
    """A range is copied onto the next line in the same columns."""
    assert copy_range_to_line("one\ntwo", (0, 3), below=True) == (4, 7)


def test_copy_range_to_line_above() -> None:
    """A range is copied onto the previous line in the same columns."""
    assert copy_range_to_line("one\ntwo", (4, 7), below=False) == (0, 3)


def test_copy_range_to_line_returns_none_at_first_line() -> None:
    """Copying above the first line is not possible."""
    assert copy_range_to_line("one\ntwo", (0, 3), below=False) is None


def test_copy_range_to_line_returns_none_at_last_line() -> None:
    """Copying below the last line is not possible."""
    assert copy_range_to_line("one\ntwo", (4, 7), below=True) is None


def test_copy_range_to_line_returns_none_when_target_too_short() -> None:
    """A target line too short to hold the range is rejected."""
    assert copy_range_to_line("abcdef\nxy", (0, 6), below=True) is None


# align_ranges


def test_align_ranges_pads_to_rightmost_column() -> None:
    """Ranges are aligned by inserting padding before the earlier ones."""
    assert align_ranges("a\n  b", [(0, 1), (4, 5)]) == "  a\n  b"


def test_align_ranges_already_aligned_is_unchanged() -> None:
    """Ranges already in the same column are left alone."""
    text = "ab\ncd"
    assert align_ranges(text, [(0, 1), (3, 4)]) == text


def test_align_ranges_with_no_ranges_is_unchanged() -> None:
    """Aligning nothing changes nothing."""
    assert align_ranges("abc", []) == "abc"


# primary selection helpers


def test_collapse_to_primary_keeps_only_the_primary() -> None:
    """Collapsing reduces the range set to the primary range."""
    assert collapse_to_primary([(0, 1), (2, 3), (4, 5)], 1) == [(2, 3)]


def test_collapse_to_primary_clamps_out_of_range_index() -> None:
    """An out-of-range primary index is clamped rather than raising."""
    assert collapse_to_primary([(0, 1)], 5) == [(0, 1)]


def test_collapse_to_primary_of_nothing_is_empty() -> None:
    """Collapsing an empty range set yields nothing."""
    assert collapse_to_primary([], 0) == []


@pytest.mark.parametrize(
    ("index", "step", "expected"),
    [(0, 1, 1), (2, 1, 0), (0, -1, 2), (1, -1, 0)],
)
def test_rotate_primary_wraps(index: int, step: int, expected: int) -> None:
    """Rotating the primary index wraps at both ends."""
    assert rotate_primary([(0, 1), (2, 3), (4, 5)], index, step) == expected


def test_rotate_primary_of_nothing_is_zero() -> None:
    """Rotating with no ranges yields index zero."""
    assert rotate_primary([], 3, 1) == 0
