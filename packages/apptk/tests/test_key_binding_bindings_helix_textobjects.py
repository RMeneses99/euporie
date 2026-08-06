"""Test Helix text-object resolution.

The resolution functions are pure, so they are tested directly against text and
cursor offsets, with no buffer or application involved.
"""

from __future__ import annotations

import pytest
from apptk.key_binding.bindings.helix_textobjects import (
    find_bracket_range,
    find_paragraph_range,
    find_quote_range,
    find_word_range,
    resolve_text_object,
)

NESTED = "hello (wor[ld]) end"


# Words


@pytest.mark.parametrize("cursor", [0, 2, 4])
def test_word_range_from_anywhere_in_the_word(cursor: int) -> None:
    """A word is resolved identically from any position within it."""
    assert find_word_range("hello world", cursor) == (0, 5)


def test_word_range_around_includes_trailing_space() -> None:
    """``ma w`` extends over the whitespace which follows the word."""
    assert find_word_range("hello world", 2, around=True) == (0, 6)


def test_word_range_on_whitespace_is_none() -> None:
    """The cursor must be on a word for a word object to resolve."""
    assert find_word_range("hello world", 5) is None


def test_long_word_spans_punctuation() -> None:
    """WORD semantics treat punctuation as part of the word."""
    assert find_word_range("foo.bar baz", 2, long=True) == (0, 7)


def test_word_range_of_empty_text_is_none() -> None:
    """An empty buffer has no word to select."""
    assert find_word_range("", 0) is None


def test_word_range_includes_underscores() -> None:
    """Underscores are part of a word."""
    assert find_word_range("some_name here", 2) == (0, 9)


# Brackets


def test_bracket_range_inside() -> None:
    """``mi (`` selects the contents of the enclosing pair."""
    assert find_bracket_range(NESTED, 8, "(", ")") == (7, 14)


def test_bracket_range_around_includes_the_brackets() -> None:
    """``ma (`` includes the bracket characters themselves."""
    assert find_bracket_range(NESTED, 8, "(", ")") != find_bracket_range(
        NESTED, 8, "(", ")", around=True
    )
    assert find_bracket_range(NESTED, 8, "(", ")", around=True) == (6, 15)


def test_bracket_range_resolves_the_innermost_pair() -> None:
    """From inside a nested pair, the inner pair is selected first."""
    assert find_bracket_range(NESTED, 11, "[", "]") == (11, 13)


def test_bracket_range_resolves_outer_pair_by_type() -> None:
    """Asking for a different bracket type skips past the inner pair."""
    assert find_bracket_range(NESTED, 11, "(", ")") == (7, 14)


def test_bracket_range_outside_any_pair_is_none() -> None:
    """A cursor outside every pair resolves to nothing."""
    assert find_bracket_range("no brackets", 3, "(", ")") is None


def test_bracket_range_unclosed_pair_is_none() -> None:
    """An unclosed pair does not resolve."""
    assert find_bracket_range("a (bc", 3, "(", ")") is None


# Quotes


def test_quote_range_inside() -> None:
    """``mi "`` selects the contents of the quoted region."""
    assert find_quote_range('say "hi there" now', 7, '"') == (5, 13)


def test_quote_range_around_includes_the_quotes() -> None:
    """``ma "`` includes the quote characters."""
    assert find_quote_range('say "hi there" now', 7, '"', around=True) == (4, 14)


def test_quote_range_outside_is_none() -> None:
    """A cursor outside the quoted region resolves to nothing."""
    assert find_quote_range('say "hi" now', 11, '"') is None


def test_quote_range_is_line_scoped() -> None:
    """Quotes on a different line do not pair with those on this one.

    The quotes at offsets 2 and 4 are on the first line; the cursor on the second
    line pairs only with the quotes at 8 and 10.
    """
    assert find_quote_range('a "b"\nc "d"', 9, '"') == (9, 10)


# Paragraphs


def test_paragraph_range_stops_at_blank_lines() -> None:
    """A paragraph extends to the surrounding blank lines."""
    assert find_paragraph_range("one two\n\nthree four", 2) == (0, 7)


def test_paragraph_range_from_the_second_paragraph() -> None:
    """The paragraph containing the cursor is the one selected."""
    assert find_paragraph_range("one two\n\nthree four", 12) == (9, 19)


def test_paragraph_range_on_a_blank_line_is_none() -> None:
    """A blank line belongs to no paragraph."""
    assert find_paragraph_range("one\n\ntwo", 4) is None


def test_paragraph_range_spans_consecutive_lines() -> None:
    """Consecutive non-blank lines form one paragraph."""
    assert find_paragraph_range("one\ntwo\n\nthree", 0) == (0, 7)


# Dispatch


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("w", (11, 13)),
        ("(", (7, 14)),
        (")", (7, 14)),
        ("b", (7, 14)),
        ("[", (11, 13)),
        ("r", (11, 13)),
    ],
)
def test_resolve_text_object_dispatch(key: str, expected: tuple[int, int]) -> None:
    """Each text-object key resolves to its corresponding range."""
    assert resolve_text_object(NESTED, 11, key, around=False) == expected


def test_resolve_unknown_text_object_is_none() -> None:
    """An unrecognised text-object key resolves to nothing."""
    assert resolve_text_object(NESTED, 8, "z", around=False) is None
