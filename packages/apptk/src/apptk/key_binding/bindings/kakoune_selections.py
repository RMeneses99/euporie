"""Support multiple simultaneous selections for the Kakoune editing mode.

Kakoune's defining feature is that several ranges of text are selected at once and
every subsequent command acts on all of them. :py:mod:`prompt_toolkit` buffers hold
exactly one :py:class:`SelectionState`, so the additional ranges live alongside it on
the buffer's :py:class:`~apptk.key_binding.kakoune_state.KakouneState`.

A range is an ``(anchor, head)`` pair of buffer offsets. ``head`` is the cursor end
and may precede ``anchor``, which is how a reversed selection is represented.

**Selections are never empty.** In Kakoune a bare cursor *is* a one-character
selection, which is why ``d`` deletes a character when nothing appears to be
selected. :py:func:`get_selections` therefore widens a zero-width range to one
character, and every command can rely on that invariant rather than branching on
whether anything is selected.

The range transforms here are pure: they take text and ranges and return ranges,
with no buffer or application involved, so they can be tested directly.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from weakref import WeakSet

from apptk.key_binding.kakoune_state import get_state
from apptk.selection import SelectionState, SelectionType

if TYPE_CHECKING:
    from apptk.buffer import Buffer

__all__ = [
    "align_ranges",
    "apply_edit_at_ranges",
    "collapse_to_primary",
    "copy_indent",
    "copy_range_to_line",
    "drop_matching",
    "duplicate_ranges",
    "expand_to_full_lines",
    "first_and_last_chars",
    "force_forward",
    "get_selections",
    "intersection",
    "keep_matching",
    "leftmost",
    "longest",
    "merge_contiguous",
    "merge_overlapping",
    "normalise",
    "replace_ranges",
    "rightmost",
    "rotate_contents",
    "rotate_primary",
    "select_regex_within",
    "set_selections",
    "shortest",
    "split_on_newlines",
    "split_on_regex",
    "text_at_ranges",
    "trim_ranges",
    "trim_to_full_lines",
    "union",
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


def force_forward(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Ensure every range runs forwards, with the cursor after the anchor.

    This is Kakoune's ``<a-:>``.

    Args:
        ranges: The ranges to orient.

    Returns:
        The ranges, each with ``anchor <= head``.
    """
    return [normalise(text_range) for text_range in ranges]


def expand_to_full_lines(
    text: str, ranges: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Expand each range to cover whole lines, including the trailing newline.

    This is Kakoune's ``x``. Note it differs from Helix's ``x``, which extends the
    selection downwards by one line instead.

    Args:
        text: The full buffer text.
        ranges: The ranges to expand.

    Returns:
        The expanded ranges.
    """
    result: list[tuple[int, int]] = []
    for text_range in ranges:
        start, end = normalise(text_range)
        line_start = text.rfind("\n", 0, start) + 1
        # Search from ``end`` when the range already stops at a line boundary, so
        # that a repeated press extends onto the next line rather than finding the
        # same newline again. Otherwise search from within the final line.
        at_boundary = end > start and (end >= len(text) or text[end - 1] == "\n")
        search_from = end if at_boundary else max(end - 1, line_start)
        newline = text.find("\n", search_from)
        # Include the newline so repeated presses walk down the buffer.
        line_end = len(text) if newline < 0 else newline + 1
        result.append((line_start, line_end))
    return result


def trim_to_full_lines(
    text: str, ranges: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Trim each range to the whole lines it fully contains.

    This is Kakoune's ``<a-x>``. The trailing newline is excluded. Ranges which
    contain no complete line are dropped.

    Args:
        text: The full buffer text.
        ranges: The ranges to trim.

    Returns:
        The trimmed ranges.
    """
    result: list[tuple[int, int]] = []
    for text_range in ranges:
        start, end = normalise(text_range)
        # Advance to a line start.
        if start > 0 and text[start - 1] != "\n":
            newline = text.find("\n", start)
            if newline < 0 or newline >= end:
                continue
            start = newline + 1
        # Retreat to the end of the last complete line. A line counts as complete
        # only when a newline follows it, so a final line with no trailing newline
        # is dropped even where the range reaches the end of the buffer.
        if end > start and text[end - 1] == "\n":
            end -= 1
        else:
            newline = text.rfind("\n", start, end)
            if newline < 0:
                continue
            end = newline
        if start < end:
            result.append((start, end))
    return result


def split_on_newlines(
    text: str, ranges: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Split each range at line boundaries.

    This is Kakoune's ``<a-s>``.

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
    them - this is Kakoune's ``S``.

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

    This is Kakoune's ``s``.

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


def keep_matching(
    text: str, ranges: list[tuple[int, int]], pattern: str
) -> list[tuple[int, int]]:
    """Keep only the ranges whose text matches a regular expression.

    This is Kakoune's ``<a-k>``.

    Args:
        text: The full buffer text.
        ranges: The ranges to filter.
        pattern: The regular expression to test against.

    Returns:
        The ranges which contain a match.

    Raises:
        re.error: If the pattern is not a valid regular expression.
    """
    compiled = re.compile(pattern)
    return [
        text_range
        for text_range in ranges
        if compiled.search(text[slice(*normalise(text_range))])
    ]


def drop_matching(
    text: str, ranges: list[tuple[int, int]], pattern: str
) -> list[tuple[int, int]]:
    """Drop the ranges whose text matches a regular expression.

    This is Kakoune's ``<a-K>``.

    Args:
        text: The full buffer text.
        ranges: The ranges to filter.
        pattern: The regular expression to test against.

    Returns:
        The ranges which contain no match.

    Raises:
        re.error: If the pattern is not a valid regular expression.
    """
    compiled = re.compile(pattern)
    return [
        text_range
        for text_range in ranges
        if not compiled.search(text[slice(*normalise(text_range))])
    ]


def trim_ranges(text: str, ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Trim leading and trailing whitespace from each range.

    This is Kakoune's ``_``. Ranges containing nothing but whitespace are dropped.

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


def first_and_last_chars(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Reduce each range to its first and last characters.

    This is Kakoune's ``<a-S>``: a range of three or more characters becomes two
    separate single-character ranges.

    Args:
        ranges: The ranges to reduce.

    Returns:
        The resulting ranges, in buffer order.
    """
    result: list[tuple[int, int]] = []
    for text_range in ranges:
        start, end = normalise(text_range)
        if end - start <= 2:
            result.append((start, end))
            continue
        result.append((start, start + 1))
        result.append((end - 1, end))
    return result


def merge_contiguous(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge ranges which touch or overlap into single ranges.

    This is Kakoune's ``<a-_>``.

    Args:
        ranges: The ranges to merge.

    Returns:
        The merged ranges, in buffer order.
    """
    if not ranges:
        return []
    ordered = sorted(normalise(text_range) for text_range in ranges)
    result = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = result[-1]
        if start <= last_end:
            result[-1] = (last_start, max(last_end, end))
        else:
            result.append((start, end))
    return result


def merge_overlapping(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge only the ranges which genuinely overlap.

    This is Kakoune's ``<a-+>``. Unlike :py:func:`merge_contiguous`, ranges which
    merely touch end-to-start are left separate.

    Args:
        ranges: The ranges to merge.

    Returns:
        The merged ranges, in buffer order.
    """
    if not ranges:
        return []
    ordered = sorted(normalise(text_range) for text_range in ranges)
    result = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = result[-1]
        if start < last_end:
            result[-1] = (last_start, max(last_end, end))
        else:
            result.append((start, end))
    return result


def duplicate_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Duplicate every range, producing overlapping selections.

    This is Kakoune's ``+``.

    Args:
        ranges: The ranges to duplicate.

    Returns:
        Each range twice, in buffer order.
    """
    result: list[tuple[int, int]] = []
    for text_range in sorted(normalise(r) for r in ranges):
        result.append(text_range)
        result.append(text_range)
    return result


def rotate_contents(contents: list[str], step: int) -> list[str]:
    """Rotate a list of selection contents.

    This is Kakoune's ``<a-)>`` and ``<a-(>``: the *text* moves between selections
    while the selections themselves stay put.

    Args:
        contents: The text of each selection, in buffer order.
        step: How far to rotate, positive to move text forwards.

    Returns:
        The rotated contents.
    """
    if not contents:
        return []
    count = len(contents)
    shift = step % count
    return contents[-shift:] + contents[:-shift]


def copy_range_to_line(
    text: str, text_range: tuple[int, int], *, below: bool
) -> tuple[int, int] | None:
    """Copy a range onto the adjacent line, preserving its columns.

    This backs Kakoune's ``C`` and ``<a-C>``.

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

    This is Kakoune's ``&``.

    Args:
        text: The full buffer text.
        ranges: The ranges to align.

    Returns:
        The new buffer text, with padding inserted before each range.
    """
    if not ranges:
        return text

    starts = sorted({normalise(text_range)[0] for text_range in ranges})
    columns = {start: start - (text.rfind("\n", 0, start) + 1) for start in starts}
    target = max(columns.values())

    # Insert right to left so that earlier offsets stay valid.
    result = text
    for start in sorted(starts, reverse=True):
        padding = target - columns[start]
        if padding > 0:
            result = result[:start] + " " * padding + result[start:]
    return result


def copy_indent(text: str, ranges: list[tuple[int, int]], source: int = 0) -> str:
    """Copy one range's line indentation to the lines of every other range.

    This is Kakoune's ``<a-&>``.

    Args:
        text: The full buffer text.
        ranges: The ranges whose lines should be re-indented.
        source: Index of the range supplying the indentation.

    Returns:
        The new buffer text.
    """
    if not ranges:
        return text

    ordered = sorted(normalise(text_range) for text_range in ranges)
    source = max(0, min(source, len(ordered) - 1))

    def line_start(offset: int) -> int:
        return text.rfind("\n", 0, offset) + 1

    def indent_of(offset: int) -> str:
        begin = line_start(offset)
        rest = text[begin:]
        return rest[: len(rest) - len(rest.lstrip(" \t"))]

    wanted = indent_of(ordered[source][0])

    # Re-indent each distinct line, right to left so offsets stay valid.
    targets = sorted({line_start(start) for start, _ in ordered}, reverse=True)
    result = text
    for begin in targets:
        existing = indent_of(begin)
        result = result[:begin] + wanted + result[begin + len(existing) :]
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
    would both invalidate the later ranges and push N entries onto the undo stack.

    Args:
        text: The full buffer text.
        ranges: The ranges to replace.
        replacements: The replacement for each range, in the same buffer order as
            ``ranges`` once sorted. A single replacement is applied to every range.

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


def collapse_to_primary(
    ranges: list[tuple[int, int]], primary_index: int
) -> list[tuple[int, int]]:
    """Reduce a set of ranges to the main one alone.

    This is Kakoune's ``,``.

    Args:
        ranges: The current ranges.
        primary_index: Index of the main range.

    Returns:
        A list holding just the main range, or empty if there are none.
    """
    if not ranges:
        return []
    return [ranges[min(primary_index, len(ranges) - 1)]]


def rotate_primary(ranges: list[tuple[int, int]], primary_index: int, step: int) -> int:
    """Move the main marker to another range.

    This backs Kakoune's ``)`` and ``(``.

    Args:
        ranges: The current ranges.
        primary_index: The current main index.
        step: How far to move, positive for forwards.

    Returns:
        The new main index, wrapping around the ends.
    """
    if not ranges:
        return 0
    return (primary_index + step) % len(ranges)


# Set combination, for the ``<a-z>`` / ``<a-Z>`` menu


def union(
    left: list[tuple[int, int]], right: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Combine two sets of ranges, merging those which overlap.

    Args:
        left: The first set of ranges.
        right: The second set of ranges.

    Returns:
        The union, in buffer order.
    """
    return merge_contiguous([*left, *right])


def intersection(
    left: list[tuple[int, int]], right: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Keep only the overlapping parts of two sets of ranges.

    Args:
        left: The first set of ranges.
        right: The second set of ranges.

    Returns:
        The intersection, in buffer order.
    """
    result: list[tuple[int, int]] = []
    for left_start, left_end in sorted(normalise(r) for r in left):
        for right_start, right_end in sorted(normalise(r) for r in right):
            start = max(left_start, right_start)
            end = min(left_end, right_end)
            if start < end:
                result.append((start, end))
    return result


def _pairwise(
    left: list[tuple[int, int]],
    right: list[tuple[int, int]],
    pick: str,
) -> list[tuple[int, int]]:
    """Choose one range from each pair of ranges.

    Args:
        left: The first set of ranges.
        right: The second set of ranges.
        pick: Which of each pair to keep - ``"leftmost"``, ``"rightmost"``,
            ``"longest"`` or ``"shortest"``.

    Returns:
        One range per pair; surplus ranges from the longer set are kept as-is.
    """
    result: list[tuple[int, int]] = []
    for first, second in zip(left, right):
        first_n, second_n = normalise(first), normalise(second)
        if pick == "leftmost":
            result.append(min(first_n, second_n, key=lambda r: r[0]))
        elif pick == "rightmost":
            result.append(max(first_n, second_n, key=lambda r: r[1]))
        elif pick == "longest":
            result.append(max(first_n, second_n, key=lambda r: r[1] - r[0]))
        else:
            result.append(min(first_n, second_n, key=lambda r: r[1] - r[0]))
    # Anything unpaired is kept, so combining sets of unequal size is not lossy.
    longer = left if len(left) > len(right) else right
    result.extend(normalise(r) for r in longer[len(result) :])
    return result


def leftmost(
    left: list[tuple[int, int]], right: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Keep the range with the leftmost cursor from each pair."""
    return _pairwise(left, right, "leftmost")


def rightmost(
    left: list[tuple[int, int]], right: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Keep the range with the rightmost cursor from each pair."""
    return _pairwise(left, right, "rightmost")


def longest(
    left: list[tuple[int, int]], right: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Keep the longer range from each pair."""
    return _pairwise(left, right, "longest")


def shortest(
    left: list[tuple[int, int]], right: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    """Keep the shorter range from each pair."""
    return _pairwise(left, right, "shortest")


# Buffer-facing helpers


def _invalidate_on_text_change(buffer: Buffer) -> None:
    """Discard multiple selections when the buffer text changes.

    ``Buffer._text_changed`` clears ``selection_state`` and then fires
    ``on_text_changed``, so this runs exactly when the single-selection state is
    invalidated - keeping the additional ranges consistent with it. Edits made
    through :py:func:`apply_edit_at_ranges` are exempt, since they maintain the
    ranges themselves.

    Args:
        buffer: The buffer whose text changed.
    """
    state = get_state(buffer)
    if state._applying_multi_edit:
        return
    state.clear_selections()


def get_selections(buffer: Buffer) -> list[tuple[int, int]]:
    """Return every active selection range, as ``(anchor, head)`` pairs.

    Always returns at least one range, and **never a zero-width one**: a bare
    cursor is widened to the single character under it, which is what Kakoune
    means by a selection. Commands can therefore act on ranges unconditionally.

    Args:
        buffer: The buffer to inspect.

    Returns:
        The active ranges, in the order they were set.
    """
    state = get_state(buffer)
    if state.selections:
        return list(state.selections)

    selection_state = buffer.selection_state
    if selection_state is None:
        return [_widen(buffer.text, buffer.cursor_position)]
    anchor = selection_state.original_cursor_position
    head = buffer.cursor_position
    if anchor == head:
        # An explicitly-started but still empty selection is widened too, so the
        # never-empty invariant holds however the selection came about.
        return [_widen(buffer.text, head)]
    return [(anchor, head)]


def _widen(text: str, cursor: int) -> tuple[int, int]:
    """Widen a bare cursor position to a one-character range.

    Args:
        text: The full buffer text.
        cursor: The cursor offset.

    Returns:
        A range covering the character under the cursor, or a zero-width range at
        the end of the buffer where there is no character to cover.
    """
    if cursor < len(text):
        return (cursor, cursor + 1)
    # At the very end of the buffer there is nothing to select; prefer the
    # preceding character so that ``d`` still has something to act on.
    if cursor > 0:
        return (cursor - 1, cursor)
    return (cursor, cursor)


def set_selections(
    buffer: Buffer,
    ranges: list[tuple[int, int]],
    *,
    primary: int = 0,
    selection_type: SelectionType = SelectionType.CHARACTERS,
) -> None:
    """Install a set of selection ranges on a buffer.

    The main range is mirrored onto ``buffer.selection_state`` and the cursor, so
    that rendering and any single-selection command continue to work. When only one
    range is given, no additional state is stored.

    Args:
        buffer: The buffer to update.
        ranges: The ranges to install, as ``(anchor, head)`` pairs.
        primary: Index of the range which should become main.
        selection_type: The selection type to apply to the main range.
    """
    state = get_state(buffer)

    if not ranges:
        state.clear_selections()
        buffer.exit_selection()
        return

    primary = max(0, min(primary, len(ranges) - 1))
    anchor, head = ranges[primary]

    # Only track additional ranges when there really is more than one; a lone
    # range lives on the buffer alone.
    state.selections = list(ranges) if len(ranges) > 1 else []
    state.primary_index = primary if len(ranges) > 1 else 0

    if buffer not in _WATCHED:
        buffer.on_text_changed += _invalidate_on_text_change
        _WATCHED.add(buffer)

    buffer.cursor_position = head
    buffer.selection_state = SelectionState(anchor, selection_type)
    buffer.multiple_cursor_positions = [h for _, h in ranges] if len(ranges) > 1 else []


def apply_edit_at_ranges(
    buffer: Buffer,
    ranges: list[tuple[int, int]],
    replacements: list[str],
) -> list[tuple[int, int]]:
    """Replace several ranges in a buffer as a single undoable edit.

    The whole new text is built in one pass and assigned once, so the edit is
    reversed by a single undo rather than one per range. The returned ranges are
    where the replacements now sit, which is what keeps multi-cursor insert alive
    across successive keystrokes.

    Args:
        buffer: The buffer to edit.
        ranges: The ranges to replace.
        replacements: The replacement for each range, or a single replacement to
            apply to every range.

    Returns:
        The ranges the replacements now occupy.
    """
    if not ranges:
        return []

    new_text, new_ranges = replace_ranges(buffer.text, ranges, replacements)

    state = get_state(buffer)
    state._applying_multi_edit = True
    try:
        buffer.save_to_undo_stack()
        buffer.text = new_text
        if new_ranges:
            buffer.cursor_position = min(new_ranges[0][1], len(new_text))
    finally:
        state._applying_multi_edit = False

    return new_ranges
