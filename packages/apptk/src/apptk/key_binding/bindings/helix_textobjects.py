"""Resolve Helix text objects to selection ranges.

Helix's ``mi`` and ``ma`` select "inside" and "around" a text object - a word, a
bracketed pair, a quoted string or a paragraph. These are resolved directly to
``(start, end)`` ranges rather than reusing :py:mod:`prompt_toolkit`'s Vi
``TextObject`` machinery, which is built around operator-pending mode and does not
fit Helix's select-then-act model.

The functions here are pure: they take text and a cursor position and return a
range, so they can be tested without a buffer or application.
"""

from __future__ import annotations

__all__ = [
    "BRACKET_PAIRS",
    "QUOTE_CHARS",
    "find_bracket_range",
    "find_paragraph_range",
    "find_quote_range",
    "find_word_range",
    "resolve_text_object",
]

# Opening to closing bracket, keyed by both characters so either selects the pair.
BRACKET_PAIRS: dict[str, tuple[str, str]] = {
    "(": ("(", ")"),
    ")": ("(", ")"),
    "b": ("(", ")"),
    "[": ("[", "]"),
    "]": ("[", "]"),
    "r": ("[", "]"),
    "{": ("{", "}"),
    "}": ("{", "}"),
    "c": ("{", "}"),
    "<": ("<", ">"),
    ">": ("<", ">"),
    "a": ("<", ">"),
}

QUOTE_CHARS = {'"', "'", "`"}


def _is_word_char(char: str, *, long: bool = False) -> bool:
    """Check whether a character forms part of a word.

    Args:
        char: The character to test.
        long: Treat any non-whitespace as part of the word, as Helix's ``W`` does.

    Returns:
        True if the character belongs to a word.
    """
    if long:
        return not char.isspace()
    return char.isalnum() or char == "_"


def find_word_range(
    text: str, cursor: int, *, around: bool = False, long: bool = False
) -> tuple[int, int] | None:
    """Find the word surrounding the cursor.

    Args:
        text: The full buffer text.
        cursor: The cursor offset.
        around: Include trailing whitespace, as ``ma`` does.
        long: Use WORD semantics, treating punctuation as part of the word.

    Returns:
        The word's range, or None when the cursor is not on a word.
    """
    if not text:
        return None
    index = min(cursor, len(text) - 1)
    if not _is_word_char(text[index], long=long):
        return None

    start = index
    while start > 0 and _is_word_char(text[start - 1], long=long):
        start -= 1
    end = index + 1
    while end < len(text) and _is_word_char(text[end], long=long):
        end += 1

    if around:
        while end < len(text) and text[end].isspace() and text[end] != "\n":
            end += 1
    return (start, end)


def find_bracket_range(
    text: str, cursor: int, opening: str, closing: str, *, around: bool = False
) -> tuple[int, int] | None:
    """Find the bracketed region enclosing the cursor.

    Nesting is handled by counting depth outwards from the cursor in each
    direction, so an inner pair is matched before an outer one.

    Args:
        text: The full buffer text.
        cursor: The cursor offset.
        opening: The opening bracket character.
        closing: The closing bracket character.
        around: Include the brackets themselves.

    Returns:
        The enclosing range, or None when the cursor is not inside a pair.
    """
    if not text:
        return None
    index = min(cursor, len(text) - 1)

    # Scan left for the unmatched opening bracket.
    depth = 0
    start = -1
    position = index
    if text[position] == closing:
        position -= 1
    while position >= 0:
        char = text[position]
        if char == closing:
            depth += 1
        elif char == opening:
            if depth == 0:
                start = position
                break
            depth -= 1
        position -= 1
    if start < 0:
        return None

    # Scan right for the matching closing bracket.
    depth = 0
    end = -1
    for position in range(start + 1, len(text)):
        char = text[position]
        if char == opening:
            depth += 1
        elif char == closing:
            if depth == 0:
                end = position
                break
            depth -= 1
    if end < 0:
        return None

    return (start, end + 1) if around else (start + 1, end)


def find_quote_range(
    text: str, cursor: int, quote: str, *, around: bool = False
) -> tuple[int, int] | None:
    """Find the quoted region enclosing the cursor.

    Quotes do not nest, so the region is determined by pairing quote characters
    from the start of the line.

    Args:
        text: The full buffer text.
        cursor: The cursor offset.
        quote: The quote character.
        around: Include the quote characters themselves.

    Returns:
        The enclosing range, or None when the cursor is not inside a quoted region.
    """
    if not text:
        return None
    line_start = text.rfind("\n", 0, cursor) + 1
    line_end = text.find("\n", cursor)
    if line_end < 0:
        line_end = len(text)

    positions = [index for index in range(line_start, line_end) if text[index] == quote]
    for first, second in zip(positions[::2], positions[1::2]):
        if first <= cursor <= second:
            return (first, second + 1) if around else (first + 1, second)
    return None


def find_paragraph_range(
    text: str, cursor: int, *, around: bool = False
) -> tuple[int, int] | None:
    """Find the paragraph surrounding the cursor.

    Paragraphs are separated by blank lines.

    Args:
        text: The full buffer text.
        cursor: The cursor offset.
        around: Include the trailing blank lines.

    Returns:
        The paragraph's range, or None when the text is empty.
    """
    if not text:
        return None

    lines = text.split("\n")
    offsets: list[tuple[int, int]] = []
    position = 0
    for line in lines:
        offsets.append((position, position + len(line)))
        position += len(line) + 1

    row = 0
    for index, (line_start, line_end) in enumerate(offsets):
        if line_start <= cursor <= line_end:
            row = index
            break

    if not lines[row].strip():
        return None

    first = row
    while first > 0 and lines[first - 1].strip():
        first -= 1
    last = row
    while last < len(lines) - 1 and lines[last + 1].strip():
        last += 1

    end = offsets[last][1]
    if around:
        while last < len(lines) - 1 and not lines[last + 1].strip():
            last += 1
            end = offsets[last][1]
    return (offsets[first][0], end)


def resolve_text_object(
    text: str, cursor: int, key: str, *, around: bool
) -> tuple[int, int] | None:
    """Resolve a text-object key to a range.

    Args:
        text: The full buffer text.
        cursor: The cursor offset.
        key: The text-object key, such as ``w``, ``(`` or ``p``.
        around: Select around the object rather than inside it.

    Returns:
        The resolved range, or None when the object cannot be resolved.
    """
    if key == "w":
        return find_word_range(text, cursor, around=around)
    if key == "W":
        return find_word_range(text, cursor, around=around, long=True)
    if key == "p":
        return find_paragraph_range(text, cursor, around=around)
    if key in QUOTE_CHARS:
        return find_quote_range(text, cursor, key, around=around)
    if key in BRACKET_PAIRS:
        opening, closing = BRACKET_PAIRS[key]
        return find_bracket_range(text, cursor, opening, closing, around=around)
    return None
