"""Resolve Kakoune text objects to selection ranges.

Kakoune selects objects with ``<a-a>`` (whole) and ``<a-i>`` (inner), followed by a
key naming the object type. This differs from Helix's ``ma``/``mi``, and the type
keys differ too: Kakoune uses ``B`` for a curly block where Helix uses ``c``, and
distinguishes ``Q`` (double quote), ``q`` (single quote) and ``g`` (grave quote).

Kakoune also has objects Helix lacks: sentences, indentation blocks, numbers,
arguments and runs of whitespace. Any punctuation character entered as the type key
acts as its own delimiter.

The functions here are pure: they take text and a cursor position and return a
range, so they can be tested without a buffer or application.
"""

from __future__ import annotations

__all__ = [
    "BRACKET_PAIRS",
    "QUOTE_CHARS",
    "find_argument_range",
    "find_bracket_range",
    "find_delimiter_range",
    "find_indent_range",
    "find_number_range",
    "find_paragraph_range",
    "find_quote_range",
    "find_sentence_range",
    "find_whitespace_range",
    "find_word_range",
    "resolve_text_object",
]

#: Opening to closing bracket, keyed by every character Kakoune accepts for it.
#: Note ``B`` is the curly block and ``a`` the angle block - Helix uses ``c`` and
#: ``a`` respectively, so these tables are deliberately not interchangeable.
BRACKET_PAIRS: dict[str, tuple[str, str]] = {
    "(": ("(", ")"),
    ")": ("(", ")"),
    "b": ("(", ")"),
    "{": ("{", "}"),
    "}": ("{", "}"),
    "B": ("{", "}"),
    "[": ("[", "]"),
    "]": ("[", "]"),
    "r": ("[", "]"),
    "<": ("<", ">"),
    ">": ("<", ">"),
    "a": ("<", ">"),
}

#: Quote type keys, mapped to the quote character they select.
QUOTE_CHARS: dict[str, str] = {
    "Q": '"',
    '"': '"',
    "q": "'",
    "'": "'",
    "g": "`",
    "`": "`",
}

#: Characters which end a sentence.
_SENTENCE_ENDS = ".!?"


def _is_word_char(char: str, *, long: bool = False) -> bool:
    """Check whether a character forms part of a word.

    Args:
        char: The character to test.
        long: Treat any non-whitespace as part of the word, as ``<a-w>`` does.

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
        around: Include trailing whitespace, as the whole object does.
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
    text: str,
    cursor: int,
    opening: str,
    closing: str,
    *,
    around: bool = False,
    level: int = 1,
) -> tuple[int, int] | None:
    """Find the bracketed region enclosing the cursor.

    Nesting is handled by counting depth outwards from the cursor in each
    direction, so an inner pair is matched before an outer one. A ``level`` above
    one selects that many pairs further out, which is how Kakoune's count works on
    nestable objects.

    Args:
        text: The full buffer text.
        cursor: The cursor offset.
        opening: The opening bracket character.
        closing: The closing bracket character.
        around: Include the brackets themselves.
        level: Which enclosing pair to select, counting outwards from one.

    Returns:
        The enclosing range, or None when there is no such enclosing pair.
    """
    if not text:
        return None

    found: tuple[int, int] | None = None
    search_from = min(cursor, len(text) - 1)

    for _ in range(max(level, 1)):
        pair = _enclosing_pair(text, search_from, opening, closing)
        if pair is None:
            return None
        found = pair
        # Step outside this pair to look for the next one out.
        search_from = pair[0] - 1
        if search_from < 0:
            if _ < max(level, 1) - 1:
                return None
            break

    if found is None:
        return None
    start, end = found
    return (start, end + 1) if around else (start + 1, end)


def _enclosing_pair(
    text: str, index: int, opening: str, closing: str
) -> tuple[int, int] | None:
    """Find the innermost bracket pair enclosing an offset.

    Args:
        text: The full buffer text.
        index: The offset to search outwards from.
        opening: The opening bracket character.
        closing: The closing bracket character.

    Returns:
        The ``(open_offset, close_offset)`` pair, or None when there is none.
    """
    if index < 0 or index >= len(text):
        return None

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
    for position in range(start + 1, len(text)):
        char = text[position]
        if char == opening:
            depth += 1
        elif char == closing:
            if depth == 0:
                return (start, position)
            depth -= 1
    return None


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


def find_delimiter_range(
    text: str, cursor: int, delimiter: str, *, around: bool = False
) -> tuple[int, int] | None:
    """Find the region between two occurrences of an arbitrary delimiter.

    Kakoune treats any punctuation entered as the object type as its own
    delimiter: with the cursor on ``bar`` in ``/home/bar``, ``<a-a>/`` selects
    ``/home/``.

    Args:
        text: The full buffer text.
        cursor: The cursor offset.
        delimiter: The delimiter character.
        around: Include the delimiters themselves.

    Returns:
        The enclosing range, or None when the cursor is not between two delimiters.
    """
    if not text:
        return None
    index = min(cursor, len(text) - 1)

    start = text.rfind(delimiter, 0, index + 1)
    if start < 0:
        return None
    end = text.find(delimiter, start + 1)
    if end < 0:
        return None
    if not start <= index <= end:
        return None
    return (start, end + 1) if around else (start + 1, end)


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


def find_sentence_range(
    text: str, cursor: int, *, around: bool = False
) -> tuple[int, int] | None:
    """Find the sentence surrounding the cursor.

    Sentences end at ``.``, ``!`` or ``?``. The whole object includes the
    whitespace following the terminator.

    Args:
        text: The full buffer text.
        cursor: The cursor offset.
        around: Include the trailing whitespace.

    Returns:
        The sentence's range, or None when the text is empty.
    """
    if not text:
        return None
    index = min(cursor, len(text) - 1)

    # Walk back to just after the previous terminator.
    start = index
    while start > 0 and text[start - 1] not in _SENTENCE_ENDS:
        start -= 1
    # Skip the whitespace which belongs to the preceding sentence.
    while start < len(text) and text[start].isspace():
        start += 1

    # Walk forward to the terminator, which is part of the sentence.
    end = index
    while end < len(text) and text[end] not in _SENTENCE_ENDS:
        end += 1
    if end < len(text):
        end += 1

    if around:
        while end < len(text) and text[end].isspace():
            end += 1

    if start >= end:
        return None
    return (start, end)


def find_indent_range(
    text: str, cursor: int, *, around: bool = False
) -> tuple[int, int] | None:
    """Find the indentation block surrounding the cursor.

    An indentation block is the run of lines indented at least as far as the
    cursor's line. Blank lines do not break the block. This is the object most
    useful for Python, where it corresponds to a suite.

    Args:
        text: The full buffer text.
        cursor: The cursor offset.
        around: Include the line introducing the block, where there is one.

    Returns:
        The block's range, or None when the text is empty.
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

    def indent_of(line: str) -> int | None:
        """Return a line's indent width, or None when it is blank."""
        if not line.strip():
            return None
        return len(line) - len(line.lstrip())

    wanted = indent_of(lines[row])
    if wanted is None:
        return None

    first = row
    while first > 0:
        candidate = indent_of(lines[first - 1])
        if candidate is None or candidate >= wanted:
            first -= 1
        else:
            break
    # Do not let a run of blank lines dangle at the start of the block.
    while first < row and indent_of(lines[first]) is None:
        first += 1

    last = row
    while last < len(lines) - 1:
        candidate = indent_of(lines[last + 1])
        if candidate is None or candidate >= wanted:
            last += 1
        else:
            break
    while last > row and indent_of(lines[last]) is None:
        last -= 1

    if around and first > 0 and wanted > 0:
        # The introducing line is the nearest preceding line indented less.
        for index in range(first - 1, -1, -1):
            candidate = indent_of(lines[index])
            if candidate is not None and candidate < wanted:
                first = index
                break

    return (offsets[first][0], offsets[last][1])


def find_number_range(
    text: str, cursor: int, *, around: bool = False
) -> tuple[int, int] | None:
    """Find the number at or after the cursor.

    Recognises an optional sign and a single decimal point.

    Args:
        text: The full buffer text.
        cursor: The cursor offset.
        around: Ignored; a number has no surrounding characters.

    Returns:
        The number's range, or None when the cursor is not on a number.
    """
    if not text:
        return None
    index = min(cursor, len(text) - 1)
    if not text[index].isdigit():
        return None

    start = index
    while start > 0 and text[start - 1].isdigit():
        start -= 1
    # Take a decimal point only when digits continue after it.
    if start > 1 and text[start - 1] == "." and text[start - 2].isdigit():
        start -= 1
        while start > 0 and text[start - 1].isdigit():
            start -= 1
    if start > 0 and text[start - 1] == "-":
        start -= 1

    end = index + 1
    while end < len(text) and text[end].isdigit():
        end += 1
    if end + 1 < len(text) and text[end] == "." and text[end + 1].isdigit():
        end += 1
        while end < len(text) and text[end].isdigit():
            end += 1

    return (start, end)


def find_argument_range(
    text: str, cursor: int, *, around: bool = False
) -> tuple[int, int] | None:
    """Find the argument surrounding the cursor.

    An argument is one comma-separated item inside the enclosing parentheses. The
    whole object includes the separating comma.

    Args:
        text: The full buffer text.
        cursor: The cursor offset.
        around: Include the trailing comma and following space.

    Returns:
        The argument's range, or None when the cursor is not inside parentheses.
    """
    pair = _enclosing_pair(text, min(cursor, len(text) - 1) if text else 0, "(", ")")
    if pair is None:
        return None
    open_offset, close_offset = pair

    index = min(cursor, len(text) - 1)

    # Scan outwards for the commas bounding this argument, ignoring those nested
    # inside further brackets.
    start = open_offset + 1
    depth = 0
    # Scan strictly left of the cursor: when the cursor sits on a comma, that comma
    # terminates the argument to its left rather than starting a new one.
    for position in range(index - 1, open_offset, -1):
        char = text[position]
        if char in ")]}":
            depth += 1
        elif char in "([{":
            depth -= 1
        elif char == "," and depth == 0:
            start = position + 1
            break

    end = close_offset
    depth = 0
    for position in range(index, close_offset):
        char = text[position]
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            end = position
            break

    # The inner object excludes the separator's whitespace either way; the whole
    # object additionally takes the trailing comma and the space following it.
    while start < end and text[start] == " ":
        start += 1
    if around and end < close_offset:
        end += 1
        while end < close_offset and text[end] == " ":
            end += 1

    if start > end:
        return None
    return (start, end)


def find_whitespace_range(
    text: str, cursor: int, *, around: bool = False
) -> tuple[int, int] | None:
    """Find the run of whitespace at the cursor.

    Args:
        text: The full buffer text.
        cursor: The cursor offset.
        around: Include newlines in the run.

    Returns:
        The whitespace range, or None when the cursor is not on whitespace.
    """
    if not text:
        return None
    index = min(cursor, len(text) - 1)

    def is_space(char: str) -> bool:
        return char.isspace() if around else (char.isspace() and char != "\n")

    if not is_space(text[index]):
        return None

    start = index
    while start > 0 and is_space(text[start - 1]):
        start -= 1
    end = index + 1
    while end < len(text) and is_space(text[end]):
        end += 1
    return (start, end)


def resolve_text_object(
    text: str, cursor: int, key: str, *, around: bool, level: int = 1
) -> tuple[int, int] | None:
    """Resolve an object type key to a range.

    Args:
        text: The full buffer text.
        cursor: The cursor offset.
        key: The object type key, such as ``w``, ``B`` or ``s``.
        around: Select the whole object rather than the inner one.
        level: Which enclosing level to select, for nestable objects.

    Returns:
        The resolved range, or None when the object cannot be resolved.
    """
    if key == "w":
        return find_word_range(text, cursor, around=around)
    if key == "W":
        return find_word_range(text, cursor, around=around, long=True)
    if key == "s":
        return find_sentence_range(text, cursor, around=around)
    if key == "p":
        return find_paragraph_range(text, cursor, around=around)
    if key == "i":
        return find_indent_range(text, cursor, around=around)
    if key == "n":
        return find_number_range(text, cursor, around=around)
    if key == "u":
        return find_argument_range(text, cursor, around=around)
    if key == " ":
        return find_whitespace_range(text, cursor, around=around)
    if key in QUOTE_CHARS:
        return find_quote_range(text, cursor, QUOTE_CHARS[key], around=around)
    if key in BRACKET_PAIRS:
        opening, closing = BRACKET_PAIRS[key]
        return find_bracket_range(
            text, cursor, opening, closing, around=around, level=level
        )
    # Any other punctuation acts as its own delimiter.
    if len(key) == 1 and not key.isalnum() and not key.isspace():
        return find_delimiter_range(text, cursor, key, around=around)
    return None
