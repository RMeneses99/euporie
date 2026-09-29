"""Test Kakoune key *dispatch* through a real prompt session.

Layer 1 of the harness. Slower than invoking commands directly, but the only way
to check that a binding's keys and filters actually resolve: multi-key sequences
such as ``<a-a>w``, the sub-mode prefixes, Escape handling, and the interaction
between the pending-key handlers and the catch-all.
"""

from __future__ import annotations

import pytest
from kakoune_utils import feed_kakoune

# Basic dispatch


def test_motion_then_edit() -> None:
    """``w`` then ``d`` removes a word and its trailing space in one go."""
    document, _ = feed_kakoune("hello world", "wd\r", cursor=0)
    assert document.text == "world"


def test_insert_round_trips_through_escape() -> None:
    """``i`` inserts and Escape returns to normal mode."""
    document, _ = feed_kakoune("hello", "ixyz\x1b\r", cursor=0)
    assert document.text == "xyzhello"


@pytest.mark.parametrize(
    ("text", "keys", "expected"),
    [
        ("abc", "~\r", "Abc"),
        ("ABC", "`\r", "aBC"),
    ],
)
def test_case_keys_dispatch_the_kakoune_way(
    text: str, keys: str, expected: str
) -> None:
    """``~`` upper-cases and ``` ` ``` lower-cases.

    Only one character changes, because a bare cursor selects exactly one.

    NOTE: Helix maps ``~`` to swap case, so this test would fail against Helix's
    bindings even though the keys are spelled the same.
    """
    document, _ = feed_kakoune(text, keys, cursor=0)
    assert document.text == expected


def test_delete_with_no_selection_removes_one_character() -> None:
    """``d`` on a bare cursor deletes a character, via the never-empty rule."""
    document, _ = feed_kakoune("hello", "d\r", cursor=1)
    assert document.text == "hllo"


# Counts


def test_count_prefix_reaches_the_command() -> None:
    """``3w`` selects the third word, then ``d`` removes it.

    The trailing space goes too, since Kakoune's ``w`` includes it.
    """
    document, _ = feed_kakoune("one two three four", "3wd\r", cursor=0)
    assert document.text == "one twofour"


def test_count_applies_to_line_expansion() -> None:
    """``2x`` expands over two lines."""
    document, _ = feed_kakoune("l1 l2 l3", "2xd\r", cursor=0)
    assert document.text == ""


# Multi-key sequences


def test_object_selection_sequence() -> None:
    """``<a-i>b`` then ``d`` empties the parentheses.

    Alt keys arrive as an Escape prefix, which is how apptk spells ``A-i``.
    """
    document, _ = feed_kakoune("call(arg)", "\x1bibd\r", cursor=6)
    assert document.text == "call()"


def test_goto_sequence() -> None:
    """``gg`` goes to the first line.

    Asserted through a following ``d`` rather than on the cursor offset: a
    forward one-character selection puts the cursor *past* the selected
    character, which is the convention that makes the highlight render.
    """
    document, _ = feed_kakoune("alpha beta", "ggd\r", cursor=8)
    assert document.text == "lpha beta"


def test_goto_line_end_sequence() -> None:
    """``gl`` goes to the end of the line."""
    document, _ = feed_kakoune("alpha beta", "gld\r", cursor=0)
    assert document.text == "alpha bet"


def test_find_char_sequence() -> None:
    """``f`` then a character selects up to it, and ``d`` removes the span."""
    document, _ = feed_kakoune("one two three", "ftd\r", cursor=0)
    assert document.text == "wo three"


def test_replace_char_sequence() -> None:
    """``r`` then a character replaces the selection."""
    document, _ = feed_kakoune("abc", "rz\r", cursor=0)
    assert document.text == "zbc"


# Escape semantics


def test_escape_in_normal_mode_does_not_disturb_the_text() -> None:
    """Escape in plain normal mode is a no-op on the buffer.

    In Kakoune Escape never leaves the buffer; in euporie a second Escape is what
    leaves the cell, which the notebook binds separately.
    """
    document, _ = feed_kakoune("hello", "\x1b\r", cursor=1)
    assert document.text == "hello"


def test_escape_cancels_a_pending_sub_mode() -> None:
    """Escape leaves goto mode without moving."""
    document, _ = feed_kakoune("alpha beta", "g\x1b\r", cursor=4)
    assert document.text == "alpha beta"


def test_escape_leaves_the_buffer_untouched() -> None:
    """Escape never edits the text, whatever is pending.

    The collapse of several selections to the main one is asserted at layer 2,
    where the selection state can be inspected directly.
    """
    document, _ = feed_kakoune("aa bb cc", "\x1b\x1b\r", cursor=0)
    assert document.text == "aa bb cc"


# Unbound keys


def test_unbound_key_does_not_insert_text() -> None:
    """A stray key in normal mode rings the bell rather than typing."""
    document, _ = feed_kakoune("hello", "\x01\r", cursor=0)
    assert document.text == "hello"


def test_digits_do_not_insert_text() -> None:
    """A count prefix is consumed rather than typed into the buffer."""
    document, _ = feed_kakoune("hello", "3\r", cursor=0)
    assert document.text == "hello"
