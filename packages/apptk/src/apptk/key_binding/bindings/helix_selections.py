"""Support multiple simultaneous selections for the Helix editing mode.

Helix's defining feature is that several ranges of text are selected at once and
every subsequent command acts on all of them. :py:mod:`prompt_toolkit` buffers hold
exactly one :py:class:`SelectionState`, so the additional ranges live alongside it
on :py:class:`~apptk.key_binding.helix_state.HelixState`.

A range is an ``(anchor, head)`` pair of buffer offsets. ``head`` is the cursor end
and may precede ``anchor``, which is how a reversed selection is represented.

The range transforms in this module are deliberately pure: they take text and
ranges and return ranges, with no buffer or application involved, so that they can
be tested directly.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from weakref import WeakSet

from apptk.selection import SelectionState, SelectionType

if TYPE_CHECKING:
    from apptk.buffer import Buffer

__all__ = [
    "align_ranges",
    "apply_edit_at_ranges",
    "collapse_to_primary",
    "copy_range_to_line",
    "get_selections",
    "normalise",
    "replace_ranges",
    "rotate_primary",
    "select_regex_within",
    "set_selections",
    "split_on_newlines",
    "split_on_regex",
    "text_at_ranges",
    "trim_ranges",
]


# Buffers which already have an invalidation handler installed. A ``WeakSet`` so
# that buffers are not kept alive by this module.
_WATCHED: WeakSet[Buffer] = WeakSet()


# Pure range transforms


def normalise(text_range: tuple[int, int]) -> tuple[int, int]:
    """Return a range as a sorted ``(start, end)`` pair.

    Args:
        text_range: An ``(anchor, head)`` pair in either order.

    Returns:
        The same range with the lower offset first.
    """
    anchor, head = text_range
    return (anchor, head) if anchor <= head else (head, anchor)


def split_on_newlines(
    text: str, ranges: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Split each range at line boundaries.

    Args:
        text: The full buffer text.
        ranges: The ranges to split.

    Returns:
        One range per line covered by the input ranges, in buffer order.
    """
    result: list[tuple[int, int]] = []
    for text_range in ranges:
        start, end = normalise(text_range)
        line_start = start
        for index in range(start, end):
            if text[index] == "\n":
                result.append((line_start, index))
                line_start = index + 1
        result.append((line_start, end))
    return result


def split_on_regex(
    text: str, ranges: list[tuple[int, int]], pattern: str
) -> list[tuple[int, int]]:
    """Split each range on every match of a regular expression.

    The matches themselves are removed from the result, leaving the text between
    them - this is the Helix ``S`` behaviour.

    Args:
        text: The full buffer text.
        ranges: The ranges to split.
        pattern: The regular expression to split on.

    Returns:
        The resulting ranges, excluding empty ones.

    Raises:
        re.error: If the pattern is not a valid regular expression.
    """
    compiled = re.compile(pattern)
    result: list[tuple[int, int]] = []
    for text_range in ranges:
        start, end = normalise(text_range)
        cursor = start
        for match in compiled.finditer(text, start, end):
            if match.end() == match.start():
                # Never advance on a zero-width match, or this loops forever.
                continue
            if match.start() > cursor:
                result.append((cursor, match.start()))
            cursor = match.end()
        if cursor < end:
            result.append((cursor, end))
    return result


def select_regex_within(
    text: str, ranges: list[tuple[int, int]], pattern: str
) -> list[tuple[int, int]]:
    """Select every match of a regular expression inside the given ranges.

    Args:
        text: The full buffer text.
        ranges: The ranges to search within.
        pattern: The regular expression to match.

    Returns:
        One range per match, excluding zero-width matches.

    Raises:
        re.error: If the pattern is not a valid regular expression.
    """
    compiled = re.compile(pattern)
    result: list[tuple[int, int]] = []
    for text_range in ranges:
        start, end = normalise(text_range)
        for match in compiled.finditer(text, start, end):
            if match.end() > match.start():
                result.append((match.start(), match.end()))
    return result


def trim_ranges(text: str, ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Trim leading and trailing whitespace from each range.

    Ranges which contain nothing but whitespace are dropped.

    Args:
        text: The full buffer text.
        ranges: The ranges to trim.

    Returns:
        The trimmed ranges.
    """
    result: list[tuple[int, int]] = []
    for text_range in ranges:
        start, end = normalise(text_range)
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            result.append((start, end))
    return result


def copy_range_to_line(
    text: str, text_range: tuple[int, int], *, below: bool
) -> tuple[int, int] | None:
    """Copy a range onto the adjacent line, preserving its columns.

    Args:
        text: The full buffer text.
        text_range: The range to copy.
        below: Copy to the following line when True, the preceding line otherwise.

    Returns:
        The copied range, or None when there is no adjacent line or it is too
        short to hold the range.
    """
    start, end = normalise(text_range)
    lines = text.split("\n")

    # Locate the line containing the start of the range, and the column offsets.
    offset = 0
    row = 0
    for index, line in enumerate(lines):
        if offset + len(line) >= start:
            row = index
            break
        offset += len(line) + 1
    else:
        return None

    start_col = start - offset
    end_col = end - offset

    target_row = row + 1 if below else row - 1
    if not 0 <= target_row < len(lines):
        return None
    if len(lines[target_row]) < end_col:
        return None

    target_offset = sum(len(line) + 1 for line in lines[:target_row])
    return (target_offset + start_col, target_offset + end_col)


def align_ranges(text: str, ranges: list[tuple[int, int]]) -> str:
    """Align the start of each range into a common column by inserting spaces.

    Args:
        text: The full buffer text.
        ranges: The ranges to align.

    Returns:
        The new buffer text, with padding inserted before each range.
    """
    if not ranges:
        return text

    starts = sorted({normalise(text_range)[0] for text_range in ranges})

    # Determine each range's column, and align to the rightmost.
    columns = {start: start - (text.rfind("\n", 0, start) + 1) for start in starts}
    target = max(columns.values())

    # Insert right to left so that earlier offsets stay valid.
    result = text
    for start in sorted(starts, reverse=True):
        padding = target - columns[start]
        if padding > 0:
            result = result[:start] + " " * padding + result[start:]
    return result


def text_at_ranges(text: str, ranges: list[tuple[int, int]]) -> list[str]:
    """Extract the text covered by each range, in buffer order.

    Args:
        text: The full buffer text.
        ranges: The ranges to extract.

    Returns:
        One string per range.
    """
    ordered = sorted(normalise(text_range) for text_range in ranges)
    return [text[start:end] for start, end in ordered]


def replace_ranges(
    text: str, ranges: list[tuple[int, int]], replacements: list[str]
) -> tuple[str, list[tuple[int, int]]]:
    """Replace several ranges of text in a single pass.

    Ranges are applied in buffer order with a running offset, so that the whole
    edit can be performed as one text assignment. Doing it as N separate edits
    would both invalidate the later ranges and push N entries onto the undo
    stack.

    Args:
        text: The full buffer text.
        ranges: The ranges to replace.
        replacements: The replacement for each range, in the same buffer order
            as ``ranges`` once sorted. A single replacement is applied to every
            range.

    Returns:
        The new text, and the ranges the replacements now occupy.
    """
    ordered = sorted(normalise(text_range) for text_range in ranges)
    if len(replacements) == 1:
        replacements = replacements * len(ordered)

    pieces: list[str] = []
    new_ranges: list[tuple[int, int]] = []
    cursor = 0
    offset = 0

    for (start, end), replacement in zip(ordered, replacements):
        pieces.append(text[cursor:start])
        pieces.append(replacement)
        new_start = start + offset
        new_ranges.append((new_start, new_start + len(replacement)))
        offset += len(replacement) - (end - start)
        cursor = end

    pieces.append(text[cursor:])
    return "".join(pieces), new_ranges


def apply_edit_at_ranges(
    buffer: Buffer,
    ranges: list[tuple[int, int]],
    replacements: list[str],
) -> list[tuple[int, int]]:
    """Replace several ranges in a buffer as a single undoable edit.

    The whole new text is built in one pass and assigned once, so the edit is
    reversed by a single undo rather than one per range.

    Args:
        buffer: The buffer to edit.
        ranges: The ranges to replace.
        replacements: The replacement for each range, or a single replacement to
            apply to every range.

    Returns:
        The ranges the replacements now occupy.
    """
    from apptk.application.current import get_app

    if not ranges:
        return []

    new_text, new_ranges = replace_ranges(buffer.text, ranges, replacements)

    try:
        helix_state = get_app().helix_state
    except Exception:
        helix_state = None

    if helix_state is not None:
        helix_state._applying_multi_edit = True
    try:
        buffer.save_to_undo_stack()
        buffer.text = new_text
        if new_ranges:
            buffer.cursor_position = min(new_ranges[0][1], len(new_text))
    finally:
        if helix_state is not None:
            helix_state._applying_multi_edit = False

    return new_ranges


def collapse_to_primary(
    ranges: list[tuple[int, int]], primary_index: int
) -> list[tuple[int, int]]:
    """Reduce a set of ranges to the primary one alone.

    Args:
        ranges: The current ranges.
        primary_index: Index of the primary range.

    Returns:
        A list holding just the primary range, or empty if there are none.
    """
    if not ranges:
        return []
    return [ranges[min(primary_index, len(ranges) - 1)]]


def rotate_primary(ranges: list[tuple[int, int]], primary_index: int, step: int) -> int:
    """Move the primary marker to another range.

    Args:
        ranges: The current ranges.
        primary_index: The current primary index.
        step: How far to move, positive for forwards.

    Returns:
        The new primary index, wrapping around the ends.
    """
    if not ranges:
        return 0
    return (primary_index + step) % len(ranges)


# Buffer-facing helpers


def _invalidate_on_text_change(buffer: Buffer) -> None:
    """Discard multiple selections when the buffer text changes.

    ``Buffer._text_changed`` clears ``selection_state`` and then fires
    ``on_text_changed``, so this runs exactly when the single-selection state is
    invalidated - keeping the additional ranges consistent with it.

    Args:
        buffer: The buffer whose text changed.
    """
    from apptk.application.current import get_app

    try:
        app = get_app()
    except Exception:
        return
    helix_state = getattr(app, "helix_state", None)
    if helix_state is None or helix_state._applying_multi_edit:
        return
    helix_state.clear_selections()


def get_selections(buffer: Buffer) -> list[tuple[int, int]]:
    """Return every active selection range, as ``(anchor, head)`` pairs.

    Always returns at least one range, deriving it from the buffer's own selection
    state - or from the cursor position when nothing is selected. Commands can
    therefore be written once against several ranges and still behave correctly
    when only one is active.

    Args:
        buffer: The buffer to inspect.

    Returns:
        The active ranges, in the order they were set.
    """
    from apptk.application.current import get_app

    try:
        helix_state = get_app().helix_state
    except Exception:
        helix_state = None

    if helix_state is not None and helix_state.selections:
        return list(helix_state.selections)

    state = buffer.selection_state
    if state is None:
        return [(buffer.cursor_position, buffer.cursor_position)]
    return [(state.original_cursor_position, buffer.cursor_position)]


def set_selections(
    buffer: Buffer,
    ranges: list[tuple[int, int]],
    *,
    primary: int = 0,
    selection_type: SelectionType = SelectionType.CHARACTERS,
) -> None:
    """Install a set of selection ranges on a buffer.

    The primary range is mirrored onto ``buffer.selection_state`` and the cursor,
    so that rendering and any single-selection command continue to work. When only
    one range is given, no additional state is stored at all.

    Args:
        buffer: The buffer to update.
        ranges: The ranges to install, as ``(anchor, head)`` pairs.
        primary: Index of the range which should become primary.
        selection_type: The selection type to apply to the primary range.
    """
    from apptk.application.current import get_app

    try:
        helix_state = get_app().helix_state
    except Exception:
        helix_state = None

    if not ranges:
        if helix_state is not None:
            helix_state.clear_selections()
        buffer.exit_selection()
        return

    primary = max(0, min(primary, len(ranges) - 1))
    anchor, head = ranges[primary]

    if helix_state is not None:
        # Only track additional ranges when there really is more than one; a lone
        # range lives on the buffer, exactly as it did before multiple selections
        # were supported.
        helix_state.selections = list(ranges) if len(ranges) > 1 else []
        helix_state.primary_index = primary if len(ranges) > 1 else 0

    if buffer not in _WATCHED:
        buffer.on_text_changed += _invalidate_on_text_change
        _WATCHED.add(buffer)

    buffer.cursor_position = head
    buffer.selection_state = SelectionState(anchor, selection_type)
    buffer.multiple_cursor_positions = [h for _, h in ranges] if len(ranges) > 1 else []
