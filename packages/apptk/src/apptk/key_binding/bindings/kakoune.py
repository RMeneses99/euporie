"""Define editor key-bindings and commands for the Kakoune editing mode.

Kakoune is a modal editor built on *selections*: every command acts on the set of
currently selected ranges, and a bare cursor is itself a one-character selection.
Movement replaces the selection; movement with :kbd:`Shift` extends it.

Helix descends from Kakoune, so the two share an architecture - but not a keymap,
and not all behaviour. The differences which matter most, and which this module
deliberately implements Kakoune's way:

- ``x`` expands selections to whole lines (Helix extends downwards by a line);
  ``<a-x>`` trims them to whole lines.
- ``m`` is a matching-pair *motion*, with ``M``, ``<a-m>`` and ``<a-M>`` variants.
  Kakoune has no match sub-mode.
- ``v`` enters view mode and ``V`` locks it. There is no select mode: Shift
  extends instead.
- Text objects are ``<a-a>`` (whole) and ``<a-i>`` (inner), plus ``[``/``]``/``{``/
  ``}`` and their ``<a-…>`` inner forms, not Helix's ``ma``/``mi``.
- ``Q`` records a macro and ``q`` replays it - the opposite way round from Helix.
- ``z`` restores selections from a mark register and ``Z`` saves them.
- Case commands are ``` ` ``` lower, ``~`` upper, ``` <a-`> ``` swap. Helix maps
  ``~`` and ``` <a-`> ``` the other way round.
- :kbd:`Escape` never leaves the buffer: it cancels whatever is pending. Leaving a
  notebook cell takes a second :kbd:`Escape`.

Selections are never empty, so commands act on ranges unconditionally rather than
branching on whether anything is selected.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from apptk.application.current import get_app
from apptk.clipboard import ClipboardData
from apptk.commands import COMMANDS, add_cmd, get_cmd
from apptk.filters import (
    Condition,
    buffer_has_focus,
    has_arg,
    is_read_only,
)
from apptk.filters.app import is_multiline, is_searching
from apptk.filters.modes import (
    kakoune_goto_mode,
    kakoune_insert_mode,
    kakoune_mode,
    kakoune_normal_mode,
    kakoune_user_mode,
    kakoune_view_mode,
)
from apptk.key_binding import ConditionalKeyBindings, KeyBindings
from apptk.key_binding.bindings.kakoune_selections import (
    align_ranges,
    apply_edit_at_ranges,
    collapse_to_primary,
    copy_indent,
    copy_range_to_line,
    drop_matching,
    duplicate_ranges,
    expand_to_full_lines,
    first_and_last_chars,
    force_forward,
    get_selections,
    intersection,
    keep_matching,
    leftmost,
    longest,
    merge_contiguous,
    merge_overlapping,
    normalise,
    rightmost,
    rotate_contents,
    rotate_primary,
    select_regex_within,
    set_selections,
    shortest,
    split_on_newlines,
    split_on_regex,
    text_at_ranges,
    trim_ranges,
    trim_to_full_lines,
    union,
)
from apptk.key_binding.bindings.kakoune_textobjects import resolve_text_object
from apptk.key_binding.kakoune_state import InputMode, KakouneMode
from apptk.key_binding.key_processor import KeyPress

if TYPE_CHECKING:
    from collections.abc import Callable

    from apptk.buffer import Buffer
    from apptk.key_binding.kakoune_state import KakouneState
    from apptk.key_binding.key_bindings import KeyBindingsBase
    from apptk.key_binding.key_processor import KeyPressEvent

__all__ = [
    "load_kakoune_bindings",
    "load_kakoune_search_bindings",
]

log = logging.getLogger(__name__)


# Helpers


def _state(event: KeyPressEvent) -> KakouneState:
    """Return the Kakoune state for the event's buffer.

    Args:
        event: The key press being handled.

    Returns:
        The state belonging to the focused buffer.
    """
    return event.app.kakoune_state


def _selections(event: KeyPressEvent) -> list[tuple[int, int]]:
    """Return the active selection ranges, never empty and never zero-width.

    Args:
        event: The key press being handled.

    Returns:
        The active ranges.
    """
    return get_selections(event.current_buffer)


def _apply(
    event: KeyPressEvent,
    ranges: list[tuple[int, int]],
    *,
    primary: int | None = None,
) -> None:
    """Install selection ranges, ringing the bell when there are none.

    Args:
        event: The key press being handled.
        ranges: The ranges to install.
        primary: Index of the main range; the existing index is kept when omitted.
    """
    if not ranges:
        event.app.output.bell()
        return
    state = _state(event)
    index = state.primary_index if primary is None else primary
    set_selections(event.current_buffer, ranges, primary=min(index, len(ranges) - 1))


def _move(
    event: KeyPressEvent,
    to_offset: Callable[[str, int, int], int],
    *,
    extend: bool,
) -> None:
    """Move or extend every selection by mapping each cursor to a new offset.

    This is the single place selection-versus-extension is decided. Kakoune has no
    select mode: without :kbd:`Shift` the selection collapses onto the movement,
    and with it the anchor is kept.

    Args:
        event: The key press being handled.
        to_offset: Maps ``(text, anchor, head)`` to the new head offset.
        extend: Keep each anchor rather than collapsing onto the movement.
    """
    buff = event.current_buffer
    text = buff.text
    ranges: list[tuple[int, int]] = []
    for anchor, head in _selections(event):
        new_head = max(0, min(to_offset(text, anchor, head), len(text)))
        if extend:
            ranges.append((anchor, new_head))
        else:
            # Collapsing leaves a one-character selection, per the never-empty rule.
            start, end = normalise((new_head, new_head))
            ranges.append(
                (start, end + 1) if end < len(text) else (max(start - 1, 0), end)
            )
    _apply(event, ranges)


def _select_range(
    event: KeyPressEvent,
    to_range: Callable[[str, int, int], tuple[int, int] | None],
    *,
    extend: bool,
) -> None:
    """Select or extend over a range computed per selection.

    Args:
        event: The key press being handled.
        to_range: Maps ``(text, anchor, head)`` to a new range, or None to skip.
        extend: Extend from the existing anchor rather than replacing the range.
    """
    buff = event.current_buffer
    text = buff.text
    ranges: list[tuple[int, int]] = []
    for anchor, head in _selections(event):
        found = to_range(text, anchor, head)
        if found is None:
            continue
        ranges.append((anchor, found[1]) if extend else found)
    _apply(event, ranges)


def _cursor_of(anchor: int, head: int) -> int:
    """Return the offset a motion should start from.

    For a forward selection the cursor sits on the last selected character, so
    motions start from there rather than from the exclusive end.

    Args:
        anchor: The selection's anchor offset.
        head: The selection's head offset.

    Returns:
        The offset to compute from.
    """
    if head > anchor:
        return head - 1
    return head


def enter_normal_mode(event: KeyPressEvent) -> None:
    """Return to normal mode from insert or replace mode.

    Args:
        event: The key press being handled.
    """
    state = _state(event)
    buff = event.current_buffer
    if state.input_mode in (InputMode.INSERT, InputMode.REPLACE):
        if state.recording_insert:
            state.recording_insert = False
        # Kakoune leaves the cursor on the last inserted character.
        ranges = [(head, head) for _, head in _selections(event)]
        if len(ranges) > 1:
            set_selections(buff, [(h, h) for h, _ in ranges])
        buff.cursor_position += buff.document.get_cursor_left_position()
    state.input_mode = InputMode.NAVIGATION
    state.exit_submode()
    state.clear_pending()


def store_clipboard_data(event: KeyPressEvent, data: ClipboardData) -> None:
    """Store yanked or deleted text in the pending register, or the clipboard.

    Kakoune defaults to the ``"`` register, which is mapped onto the application
    clipboard so that yanking interoperates with the rest of euporie.

    Args:
        event: The key press being handled.
        data: The clipboard data to store.
    """
    register = _state(event).take_register()
    if register is None or register == '"':
        event.app.clipboard.set_data(data)
    else:
        _state(event).named_registers[register] = data


def fetch_clipboard_data(event: KeyPressEvent) -> ClipboardData:
    """Fetch text to paste from the pending register, or the clipboard.

    Args:
        event: The key press being handled.

    Returns:
        The clipboard data, empty for a register never written to.
    """
    register = _state(event).take_register()
    if register is None or register == '"':
        return event.app.clipboard.get_data()
    return _state(event).named_registers.get(register, ClipboardData(""))


# Mode switching


@add_cmd(
    keys=["escape"],
    filter=kakoune_mode & buffer_has_focus & ~is_searching,
    hidden=True,
    name="kakoune-escape",
)
def kakoune_escape(event: KeyPressEvent) -> None:
    """Cancel whatever is pending, or do nothing in plain normal mode.

    Kakoune's :kbd:`Escape` never leaves the buffer. Leaving a notebook cell takes
    a second :kbd:`Escape`, which the notebook binds as a two-key sequence.
    """
    state = _state(event)
    if state.input_mode != InputMode.NAVIGATION:
        enter_normal_mode(event)
        return
    if state.has_pending():
        state.exit_submode()
        state.clear_pending()
        return
    # Already in plain normal mode: reduce to the main selection, as Kakoune does.
    ranges = _selections(event)
    if len(ranges) > 1:
        _apply(event, collapse_to_primary(ranges, state.primary_index), primary=0)


@add_cmd(
    keys=["i"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-insert",
)
def kakoune_insert(event: KeyPressEvent) -> None:
    """Enter insert mode before each selection."""
    state = _state(event)
    ranges = [(min(a, h), min(a, h)) for a, h in _selections(event)]
    state.input_mode = InputMode.INSERT
    state.last_insert = ""
    state.recording_insert = True
    if len(ranges) > 1:
        state.selections = ranges
        event.current_buffer.cursor_position = ranges[0][0]
    else:
        event.current_buffer.exit_selection()
        event.current_buffer.cursor_position = ranges[0][0]


@add_cmd(
    keys=["a"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-append",
)
def kakoune_append(event: KeyPressEvent) -> None:
    """Enter insert mode after each selection."""
    state = _state(event)
    ranges = [(max(a, h), max(a, h)) for a, h in _selections(event)]
    state.input_mode = InputMode.INSERT
    state.last_insert = ""
    state.recording_insert = True
    if len(ranges) > 1:
        state.selections = ranges
        event.current_buffer.cursor_position = ranges[0][0]
    else:
        event.current_buffer.exit_selection()
        event.current_buffer.cursor_position = ranges[0][0]


@add_cmd(
    keys=["I"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-insert-line-start",
)
def kakoune_insert_line_start(event: KeyPressEvent) -> None:
    """Enter insert mode at the first non-blank of each selection's first line."""
    buff = event.current_buffer
    text = buff.text
    state = _state(event)
    ranges: list[tuple[int, int]] = []
    for anchor, head in _selections(event):
        start = min(anchor, head)
        line_start = text.rfind("\n", 0, start) + 1
        offset = line_start
        while offset < len(text) and text[offset] in " \t":
            offset += 1
        ranges.append((offset, offset))
    state.input_mode = InputMode.INSERT
    state.recording_insert = True
    if len(ranges) > 1:
        state.selections = ranges
        buff.cursor_position = ranges[0][0]
    else:
        buff.exit_selection()
        buff.cursor_position = ranges[0][0]


@add_cmd(
    keys=["A"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-insert-line-end",
)
def kakoune_insert_line_end(event: KeyPressEvent) -> None:
    """Enter insert mode at the end of each selection's last line."""
    buff = event.current_buffer
    text = buff.text
    state = _state(event)
    ranges: list[tuple[int, int]] = []
    for anchor, head in _selections(event):
        end = max(anchor, head)
        newline = text.find("\n", max(end - 1, 0))
        offset = len(text) if newline < 0 else newline
        ranges.append((offset, offset))
    state.input_mode = InputMode.INSERT
    state.recording_insert = True
    if len(ranges) > 1:
        state.selections = ranges
        buff.cursor_position = ranges[0][0]
    else:
        buff.exit_selection()
        buff.cursor_position = ranges[0][0]


@add_cmd(
    keys=["o"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-open-below",
)
def kakoune_open_below(event: KeyPressEvent) -> None:
    """Open a new line below each selection and enter insert mode."""
    _open_line(event, below=True)


@add_cmd(
    keys=["O"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-open-above",
)
def kakoune_open_above(event: KeyPressEvent) -> None:
    """Open a new line above each selection and enter insert mode."""
    _open_line(event, below=False)


def _open_line(event: KeyPressEvent, *, below: bool) -> None:
    """Open blank lines next to each selection and enter insert mode.

    Args:
        event: The key press being handled.
        below: Open below each selection rather than above.
    """
    buff = event.current_buffer
    text = buff.text
    state = _state(event)
    count = event.arg

    insertions: list[tuple[int, int]] = []
    for anchor, head in _selections(event):
        if below:
            end = max(anchor, head)
            newline = text.find("\n", max(end - 1, 0))
            offset = len(text) if newline < 0 else newline
        else:
            start = min(anchor, head)
            offset = text.rfind("\n", 0, start) + 1
        insertions.append((offset, offset))

    payload = "\n" * count
    new_ranges = apply_edit_at_ranges(buff, insertions, [payload])
    # Land on the blank line itself: after the inserted newline when opening
    # below, and on the last of the run when opening above.
    if below:
        carets = [(end, end) for _, end in new_ranges]
    else:
        carets = [(start + count - 1, start + count - 1) for start, _ in new_ranges]

    state.input_mode = InputMode.INSERT
    state.recording_insert = True
    if len(carets) > 1:
        state.selections = carets
        buff.cursor_position = carets[0][0]
    else:
        state.clear_selections()
        buff.exit_selection()
        buff.cursor_position = carets[0][0]


@add_cmd(
    keys=["A-o"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-add-line-below",
)
def kakoune_add_line_below(event: KeyPressEvent) -> None:
    """Add an empty line below each selection, staying in normal mode."""
    _add_blank_line(event, below=True)


@add_cmd(
    keys=["A-O"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-add-line-above",
)
def kakoune_add_line_above(event: KeyPressEvent) -> None:
    """Add an empty line above each selection, staying in normal mode."""
    _add_blank_line(event, below=False)


def _add_blank_line(event: KeyPressEvent, *, below: bool) -> None:
    """Insert a blank line beside each selection without changing mode.

    Args:
        event: The key press being handled.
        below: Insert below each selection rather than above.
    """
    buff = event.current_buffer
    text = buff.text
    kept = _selections(event)
    insertions: list[tuple[int, int]] = []
    for anchor, head in kept:
        if below:
            end = max(anchor, head)
            newline = text.find("\n", max(end - 1, 0))
            offset = len(text) if newline < 0 else newline
        else:
            start = min(anchor, head)
            offset = text.rfind("\n", 0, start) + 1
        insertions.append((offset, offset))
    apply_edit_at_ranges(buff, insertions, ["\n"])


# Insert mode
#
# These commands exist because a plain ``Buffer.insert_text`` collapses multiple
# selections: ``Buffer._text_changed`` clears the selection state and fires
# ``on_text_changed``, which discards the additional ranges. Routing every
# insert-mode edit through ``apply_edit_at_ranges`` instead keeps all the insertion
# points alive across successive keystrokes, and keeps each keystroke a single undo
# step. With one selection they fall through to the ordinary buffer methods.


def _multi_carets(event: KeyPressEvent) -> list[tuple[int, int]] | None:
    """Return the active insertion points when there are several, else None.

    Args:
        event: The key press being handled.

    Returns:
        The current ranges when multi-cursor editing is in progress.
    """
    state = _state(event)
    ranges = state.selections
    return list(ranges) if len(ranges) > 1 else None


def _insert_at_carets(event: KeyPressEvent, text: str) -> None:
    """Insert text at every caret, keeping them all alive.

    Args:
        event: The key press being handled.
        text: The text to insert at each caret.
    """
    state = _state(event)
    carets = _multi_carets(event)
    if carets is None:
        event.current_buffer.insert_text(text)
        return
    new_ranges = apply_edit_at_ranges(event.current_buffer, carets, [text])
    state.selections = [(end, end) for _, end in new_ranges]
    state.primary_index = min(state.primary_index, len(new_ranges) - 1)
    event.current_buffer.multiple_cursor_positions = [e for _, e in new_ranges]


@add_cmd(
    keys=["<any>"],
    filter=kakoune_insert_mode & ~is_read_only & buffer_has_focus,
    hidden=True,
    name="kakoune-self-insert",
)
def kakoune_self_insert(event: KeyPressEvent) -> None:
    """Insert the typed character at every caret."""
    data = event.data
    if data and len(data) == 1 and data.isprintable():
        state = _state(event)
        if state.recording_insert:
            state.last_insert += data
        _insert_at_carets(event, data)


@add_cmd(
    keys=["enter", "c-j"],
    filter=kakoune_insert_mode & is_multiline & ~is_read_only,
    hidden=True,
    name="kakoune-insert-newline",
)
def kakoune_insert_newline(event: KeyPressEvent) -> None:
    """Insert a newline at every caret."""
    state = _state(event)
    if state.recording_insert:
        state.last_insert += "\n"
    _insert_at_carets(event, "\n")


@add_cmd(
    keys=["backspace", "c-h"],
    filter=kakoune_insert_mode & ~is_read_only,
    hidden=True,
    name="kakoune-insert-backspace",
)
def kakoune_insert_backspace(event: KeyPressEvent) -> None:
    """Delete the character before every caret."""
    state = _state(event)
    carets = _multi_carets(event)
    if carets is None:
        event.current_buffer.delete_before_cursor(count=1)
        return
    # Widen each caret leftwards by one and replace with nothing.
    targets = [(max(head - 1, 0), head) for _, head in carets]
    if all(start == end for start, end in targets):
        return
    new_ranges = apply_edit_at_ranges(event.current_buffer, targets, [""])
    state.selections = [(end, end) for _, end in new_ranges]
    event.current_buffer.multiple_cursor_positions = [e for _, e in new_ranges]


@add_cmd(
    keys=["delete", "c-d"],
    filter=kakoune_insert_mode & ~is_read_only,
    hidden=True,
    name="kakoune-insert-delete",
)
def kakoune_insert_delete(event: KeyPressEvent) -> None:
    """Delete the character under every caret."""
    state = _state(event)
    carets = _multi_carets(event)
    if carets is None:
        event.current_buffer.delete(count=1)
        return
    length = len(event.current_buffer.text)
    targets = [(head, min(head + 1, length)) for _, head in carets]
    if all(start == end for start, end in targets):
        return
    new_ranges = apply_edit_at_ranges(event.current_buffer, targets, [""])
    state.selections = [(start, start) for start, _ in new_ranges]
    event.current_buffer.multiple_cursor_positions = [s for s, _ in new_ranges]


@add_cmd(
    keys=["c-w", "A-backspace"],
    filter=kakoune_insert_mode & ~is_read_only,
    hidden=True,
    name="kakoune-insert-delete-word-before",
)
def kakoune_insert_delete_word_before(event: KeyPressEvent) -> None:
    """Delete the word before every caret."""
    buff = event.current_buffer
    state = _state(event)
    carets = _multi_carets(event)
    text = buff.text

    def word_start(offset: int) -> int:
        """Return the start of the word preceding an offset."""
        index = offset
        while index > 0 and text[index - 1].isspace():
            index -= 1
        while index > 0 and not text[index - 1].isspace():
            index -= 1
        return index

    if carets is None:
        position = buff.cursor_position
        start = word_start(position)
        if start < position:
            buff.delete_before_cursor(count=position - start)
        return
    targets = [(word_start(head), head) for _, head in carets]
    new_ranges = apply_edit_at_ranges(buff, targets, [""])
    state.selections = [(end, end) for _, end in new_ranges]
    buff.multiple_cursor_positions = [e for _, e in new_ranges]


@add_cmd(
    keys=["c-u"],
    filter=kakoune_insert_mode & ~is_read_only,
    hidden=True,
    name="kakoune-insert-commit-undo",
)
def kakoune_insert_commit_undo(event: KeyPressEvent) -> None:
    """Commit the changes so far as a single undo group."""
    event.current_buffer.save_to_undo_stack()


@add_cmd(
    keys=["A-;"],
    filter=kakoune_insert_mode,
    hidden=True,
    name="kakoune-insert-one-normal-command",
)
def kakoune_insert_one_normal_command(event: KeyPressEvent) -> None:
    """Escape to normal mode for a single command, then return to insert mode.

    Kakoune's ``<a-;>`` in insert mode. The temporary flag is honoured by
    ``kakoune-resume-insert``, which runs after the next command completes.
    """
    state = _state(event)
    state.input_mode = InputMode.NAVIGATION
    state.temporary_navigation_mode = True


# Movement
#
# A plain movement replaces each selection; the same key with Shift extends it.
# Kakoune has no select mode, so ``extend`` is decided by the key alone.


def _char_offset(delta: int) -> Callable[[str, int, int], int]:
    """Build an offset function moving by a number of characters.

    Args:
        delta: How far to move, negative for leftwards.

    Returns:
        A function suitable for :py:func:`_move`.
    """

    def offset(text: str, anchor: int, head: int) -> int:
        return _cursor_of(anchor, head) + delta

    return offset


def _line_offset(delta: int) -> Callable[[str, int, int], int]:
    """Build an offset function moving by a number of lines, keeping the column.

    Args:
        delta: How many lines to move, negative for upwards.

    Returns:
        A function suitable for :py:func:`_move`.
    """

    def offset(text: str, anchor: int, head: int) -> int:
        cursor = _cursor_of(anchor, head)
        line_start = text.rfind("\n", 0, cursor) + 1
        column = cursor - line_start

        if delta < 0:
            for _ in range(-delta):
                if line_start == 0:
                    break
                line_start = text.rfind("\n", 0, line_start - 1) + 1
        else:
            for _ in range(delta):
                newline = text.find("\n", line_start)
                if newline < 0:
                    break
                line_start = newline + 1

        newline = text.find("\n", line_start)
        line_end = len(text) if newline < 0 else newline
        return min(line_start + column, line_end)

    return offset


def _register_movement(
    key: str, extend_key: str, offset: Callable[[str, int, int], int], name: str
) -> None:
    """Register a movement key and its Shift-extending counterpart.

    Args:
        key: The key which replaces each selection.
        extend_key: The key which extends each selection.
        offset: Maps ``(text, anchor, head)`` to the new head offset.
        name: The command name stem, suffixed with ``-extend`` for the Shift form.
    """

    @add_cmd(keys=[key], filter=kakoune_normal_mode, hidden=True, name=name)
    def _select(event: KeyPressEvent, offset: object = offset) -> None:
        """Move each selection."""
        count = event.arg
        current = offset
        for _ in range(count):
            _move(event, current, extend=False)  # type: ignore[arg-type]

    @add_cmd(
        keys=[extend_key],
        filter=kakoune_normal_mode,
        hidden=True,
        name=f"{name}-extend",
    )
    def _extend(event: KeyPressEvent, offset: object = offset) -> None:
        """Extend each selection."""
        count = event.arg
        for _ in range(count):
            _move(event, offset, extend=True)  # type: ignore[arg-type]


_register_movement("h", "H", _char_offset(-1), "kakoune-left")
_register_movement("l", "L", _char_offset(1), "kakoune-right")
_register_movement("j", "J", _line_offset(1), "kakoune-down")
_register_movement("k", "K", _line_offset(-1), "kakoune-up")


def _is_word_char(char: str, *, long: bool) -> bool:
    """Check whether a character belongs to a word.

    Args:
        char: The character to test.
        long: Use WORD semantics, where any non-whitespace counts.

    Returns:
        True when the character is part of a word.
    """
    if long:
        return not char.isspace()
    return char.isalnum() or char == "_"


def _next_word(text: str, start: int, *, long: bool) -> tuple[int, int] | None:
    """Select the word to the right, together with the whitespace following it.

    This is Kakoune's ``w``: the trailing whitespace is part of the selection,
    which is why ``w`` then ``d`` removes a word and its separator in one go.

    Args:
        text: The full buffer text.
        start: The offset to search from.
        long: Use WORD semantics.

    Returns:
        The range to select, or None at the end of the buffer.
    """
    index = start
    if index >= len(text):
        return None
    # Step over the character under the cursor first.
    index += 1
    while index < len(text) and not _is_word_char(text[index], long=long):
        if text[index] == "\n":
            break
        index += 1
    end = index
    while end < len(text) and _is_word_char(text[end], long=long):
        end += 1
    while end < len(text) and text[end] in " \t":
        end += 1
    if end == start:
        return None
    return (start, end)


def _prev_word(text: str, start: int, *, long: bool) -> tuple[int, int] | None:
    """Select the word to the left, together with the whitespace preceding it.

    This is Kakoune's ``b``, which runs backwards so the returned range has its
    head before its anchor.

    Args:
        text: The full buffer text.
        start: The offset to search from.
        long: Use WORD semantics.

    Returns:
        The range to select, or None at the start of the buffer.
    """
    index = start
    if index <= 0:
        return None
    index -= 1
    while index > 0 and not _is_word_char(text[index], long=long):
        index -= 1
    begin = index
    while begin > 0 and _is_word_char(text[begin - 1], long=long):
        begin -= 1
    if begin == start:
        return None
    # Head before anchor: a backward selection.
    return (start, begin)


def _word_end(text: str, start: int, *, long: bool) -> tuple[int, int] | None:
    """Select the preceding whitespace and the word to the right.

    This is Kakoune's ``e``, which stops on the word's last character rather than
    consuming the whitespace after it.

    Args:
        text: The full buffer text.
        start: The offset to search from.
        long: Use WORD semantics.

    Returns:
        The range to select, or None at the end of the buffer.
    """
    index = start
    if index >= len(text):
        return None
    index += 1
    while index < len(text) and not _is_word_char(text[index], long=long):
        index += 1
    end = index
    while end < len(text) and _is_word_char(text[end], long=long):
        end += 1
    if end == start:
        return None
    return (start, end)


def _register_word_motion(
    key: str,
    extend_key: str,
    finder: Callable[[str, int], tuple[int, int] | None],
    name: str,
) -> None:
    """Register a word motion and its extending counterpart.

    Args:
        key: The key which replaces each selection.
        extend_key: The key which extends each selection.
        finder: Maps ``(text, cursor)`` to a range, or None.
        name: The command name stem.
    """

    @add_cmd(keys=[key], filter=kakoune_normal_mode, hidden=True, name=name)
    def _select(event: KeyPressEvent, finder: object = finder) -> None:
        """Select over the motion."""
        count = event.arg
        for _ in range(count):
            _select_range(
                event,
                lambda text, anchor, head: finder(  # type: ignore[operator]
                    text, _cursor_of(anchor, head)
                ),
                extend=False,
            )

    @add_cmd(
        keys=[extend_key],
        filter=kakoune_normal_mode,
        hidden=True,
        name=f"{name}-extend",
    )
    def _extend(event: KeyPressEvent, finder: object = finder) -> None:
        """Extend over the motion."""
        count = event.arg
        for _ in range(count):
            _select_range(
                event,
                lambda text, anchor, head: finder(  # type: ignore[operator]
                    text, _cursor_of(anchor, head)
                ),
                extend=True,
            )


# ``w``/``b``/``e`` use word semantics; the ``<a-…>`` forms use WORD semantics.
# Note Kakoune spells the WORD variants with Alt, where Helix uses Shift - Shift is
# taken here by extension.
_register_word_motion(
    "w", "W", lambda t, c: _next_word(t, c, long=False), "kakoune-next-word"
)
_register_word_motion(
    "b", "B", lambda t, c: _prev_word(t, c, long=False), "kakoune-prev-word"
)
_register_word_motion(
    "e", "E", lambda t, c: _word_end(t, c, long=False), "kakoune-word-end"
)
_register_word_motion(
    "A-w", "A-W", lambda t, c: _next_word(t, c, long=True), "kakoune-next-long-word"
)
_register_word_motion(
    "A-b", "A-B", lambda t, c: _prev_word(t, c, long=True), "kakoune-prev-long-word"
)
_register_word_motion(
    "A-e", "A-E", lambda t, c: _word_end(t, c, long=True), "kakoune-long-word-end"
)


@add_cmd(
    keys=["A-h", "home"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-line-start",
)
def kakoune_line_start(event: KeyPressEvent) -> None:
    """Select to the beginning of the line."""

    def to_range(text: str, anchor: int, head: int) -> tuple[int, int]:
        cursor = _cursor_of(anchor, head)
        return (cursor, text.rfind("\n", 0, cursor) + 1)

    _select_range(event, to_range, extend=False)


@add_cmd(
    keys=["A-l", "end"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-line-end",
)
def kakoune_line_end(event: KeyPressEvent) -> None:
    """Select to the end of the line."""

    def to_range(text: str, anchor: int, head: int) -> tuple[int, int]:
        cursor = _cursor_of(anchor, head)
        newline = text.find("\n", cursor)
        return (cursor, len(text) if newline < 0 else newline)

    _select_range(event, to_range, extend=False)


@add_cmd(
    keys=["x"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-expand-lines",
)
def kakoune_expand_lines(event: KeyPressEvent) -> None:
    """Expand each selection to cover whole lines.

    Kakoune's ``x``. Pressing it again extends onto the following line. This is
    *not* Helix's ``x``, which extends downwards by one line from the outset.
    """
    count = event.arg
    ranges = _selections(event)
    for _ in range(count):
        ranges = expand_to_full_lines(event.current_buffer.text, ranges)
    _apply(event, ranges)


@add_cmd(
    keys=["A-x"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-trim-lines",
)
def kakoune_trim_lines(event: KeyPressEvent) -> None:
    """Trim each selection to the whole lines it fully contains."""
    _apply(event, trim_to_full_lines(event.current_buffer.text, _selections(event)))


@add_cmd(
    keys=["%"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-select-buffer",
)
def kakoune_select_buffer(event: KeyPressEvent) -> None:
    """Select the whole buffer."""
    _apply(event, [(0, len(event.current_buffer.text))], primary=0)


@add_cmd(
    keys=[";"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-reduce-to-cursor",
)
def kakoune_reduce_to_cursor(event: KeyPressEvent) -> None:
    """Reduce each selection to its cursor, a single character."""
    text = event.current_buffer.text
    ranges: list[tuple[int, int]] = []
    for anchor, head in _selections(event):
        cursor = _cursor_of(anchor, head)
        ranges.append(
            (cursor, cursor + 1) if cursor < len(text) else (max(cursor - 1, 0), cursor)
        )
    _apply(event, ranges)


@add_cmd(
    keys=["A-;"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-flip-selections",
)
def kakoune_flip_selections(event: KeyPressEvent) -> None:
    """Flip the direction of each selection."""
    _apply(event, [(head, anchor) for anchor, head in _selections(event)])


@add_cmd(
    keys=["A-:"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-forward-selections",
)
def kakoune_forward_selections(event: KeyPressEvent) -> None:
    """Ensure every selection runs forwards, with the cursor after the anchor."""
    _apply(event, force_forward(_selections(event)))


# Changes
#
# Every command here acts on all selections. Because selections are never empty,
# there is no no-selection variant to write: ``d`` on a bare cursor deletes the
# character under it because that character *is* the selection.


def _yank(event: KeyPressEvent, ranges: list[tuple[int, int]]) -> None:
    """Store the text of the given ranges in the pending register.

    Several selections are joined with newlines, so that pasting distributes one
    line to each.

    Args:
        event: The key press being handled.
        ranges: The ranges whose text should be stored.
    """
    pieces = text_at_ranges(event.current_buffer.text, ranges)
    store_clipboard_data(event, ClipboardData("\n".join(pieces)))


def _delete(event: KeyPressEvent, *, yank: bool, change: bool) -> None:
    """Delete every selection, optionally yanking first or entering insert mode.

    Args:
        event: The key press being handled.
        yank: Store the deleted text before removing it.
        change: Enter insert mode afterwards, leaving carets behind.
    """
    buff = event.current_buffer
    ranges = _selections(event)
    if yank:
        _yank(event, ranges)

    new_ranges = apply_edit_at_ranges(buff, ranges, [""])
    state = _state(event)

    if change:
        state.input_mode = InputMode.INSERT
        state.last_insert = ""
        state.recording_insert = True
        carets = [(start, start) for start, _ in new_ranges]
        if len(carets) > 1:
            state.selections = carets
            buff.multiple_cursor_positions = [s for s, _ in carets]
            buff.cursor_position = carets[0][0]
        else:
            state.clear_selections()
            buff.exit_selection()
            buff.cursor_position = carets[0][0]
        return

    # Leave a selection on whatever now sits where the text was.
    text = buff.text
    kept: list[tuple[int, int]] = []
    for start, _ in new_ranges:
        kept.append(
            (start, start + 1) if start < len(text) else (max(start - 1, 0), start)
        )
    if kept:
        set_selections(buff, kept, primary=min(state.primary_index, len(kept) - 1))


@add_cmd(
    keys=["d"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-delete",
)
def kakoune_delete(event: KeyPressEvent) -> None:
    """Yank and delete every selection."""
    _delete(event, yank=True, change=False)


@add_cmd(
    keys=["A-d"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-delete-noyank",
)
def kakoune_delete_noyank(event: KeyPressEvent) -> None:
    """Delete every selection without yanking."""
    _delete(event, yank=False, change=False)


@add_cmd(
    keys=["c"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-change",
)
def kakoune_change(event: KeyPressEvent) -> None:
    """Yank and delete every selection, then enter insert mode."""
    _delete(event, yank=True, change=True)


@add_cmd(
    keys=["A-c"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-change-noyank",
)
def kakoune_change_noyank(event: KeyPressEvent) -> None:
    """Delete every selection without yanking, then enter insert mode."""
    _delete(event, yank=False, change=True)


@add_cmd(
    keys=["y"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-yank",
)
def kakoune_yank(event: KeyPressEvent) -> None:
    """Yank every selection."""
    _yank(event, _selections(event))


def _paste(event: KeyPressEvent, *, after: bool, select: bool) -> None:
    """Paste the register's contents at every selection.

    Args:
        event: The key press being handled.
        after: Paste after each selection rather than before it.
        select: Leave the pasted text selected.
    """
    buff = event.current_buffer
    data = fetch_clipboard_data(event)
    if not data.text:
        event.app.output.bell()
        return

    ranges = _selections(event)
    lines = data.text.split("\n")
    # One line per selection distributes them; otherwise every selection gets the
    # whole payload, which is what Kakoune does for a single-line register.
    payloads = lines if len(lines) == len(ranges) and len(ranges) > 1 else [data.text]

    targets = [
        (max(a, h), max(a, h)) if after else (min(a, h), min(a, h)) for a, h in ranges
    ]
    new_ranges = apply_edit_at_ranges(buff, targets, payloads)

    if select:
        set_selections(buff, new_ranges)
    else:
        # Leave the cursor on the last character of each pasted run.
        text = buff.text
        kept = [
            (max(end - 1, start), end)
            if end > start
            else (start, min(start + 1, len(text)))
            for start, end in new_ranges
        ]
        set_selections(buff, kept)


@add_cmd(
    keys=["p"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-paste-after",
)
def kakoune_paste_after(event: KeyPressEvent) -> None:
    """Paste after the end of each selection."""
    _paste(event, after=True, select=False)


@add_cmd(
    keys=["P"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-paste-before",
)
def kakoune_paste_before(event: KeyPressEvent) -> None:
    """Paste before the beginning of each selection."""
    _paste(event, after=False, select=False)


@add_cmd(
    keys=["A-p"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-paste-after-select",
)
def kakoune_paste_after_select(event: KeyPressEvent) -> None:
    """Paste after each selection and select each pasted string."""
    _paste(event, after=True, select=True)


@add_cmd(
    keys=["A-P"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-paste-before-select",
)
def kakoune_paste_before_select(event: KeyPressEvent) -> None:
    """Paste before each selection and select each pasted string."""
    _paste(event, after=False, select=True)


@add_cmd(
    keys=["R"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-replace-with-yanked",
)
def kakoune_replace_with_yanked(event: KeyPressEvent) -> None:
    """Replace every selection with the register's contents."""
    buff = event.current_buffer
    data = fetch_clipboard_data(event)
    if not data.text:
        event.app.output.bell()
        return
    ranges = _selections(event)
    lines = data.text.split("\n")
    payloads = lines if len(lines) == len(ranges) and len(ranges) > 1 else [data.text]
    set_selections(buff, apply_edit_at_ranges(buff, ranges, payloads))


@add_cmd(
    keys=["A-R"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-replace-with-every-yanked",
)
def kakoune_replace_with_every_yanked(event: KeyPressEvent) -> None:
    """Replace every selection with the whole register contents."""
    buff = event.current_buffer
    data = fetch_clipboard_data(event)
    if not data.text:
        event.app.output.bell()
        return
    ranges = _selections(event)
    set_selections(buff, apply_edit_at_ranges(buff, ranges, [data.text]))


@Condition
def waiting_for_replace_char() -> bool:
    """Check whether ``r`` is awaiting its replacement character."""
    if not kakoune_mode():
        return False
    return get_app().kakoune_state.pending_replace_char


@add_cmd(
    keys=["r"],
    filter=kakoune_normal_mode & ~waiting_for_replace_char & ~is_read_only,
    hidden=True,
    name="kakoune-replace-char",
)
def kakoune_replace_char(event: KeyPressEvent) -> None:
    """Await a character to replace every selected character with."""
    _state(event).pending_replace_char = True


@add_cmd(
    keys=["<any>"],
    filter=kakoune_normal_mode & waiting_for_replace_char & ~is_read_only,
    hidden=True,
    eager=True,
    name="kakoune-handle-replace-char",
)
def kakoune_handle_replace_char(event: KeyPressEvent) -> None:
    """Replace every character of every selection with the key pressed."""
    state = _state(event)
    state.pending_replace_char = False
    char = event.data
    if not char or len(char) != 1 or not char.isprintable():
        event.app.output.bell()
        return
    buff = event.current_buffer
    ranges = _selections(event)
    # Each selection keeps its length, so replace character for character.
    payloads = [char * (end - start) for start, end in (normalise(r) for r in ranges)]
    set_selections(buff, apply_edit_at_ranges(buff, ranges, payloads))


def _transform(event: KeyPressEvent, func: Callable[[str], str]) -> None:
    """Apply a text transformation to every selection, keeping them selected.

    Args:
        event: The key press being handled.
        func: The transformation to apply to each selection's text.
    """
    buff = event.current_buffer
    ranges = _selections(event)
    payloads = [func(piece) for piece in text_at_ranges(buff.text, ranges)]
    set_selections(buff, apply_edit_at_ranges(buff, ranges, payloads))


@add_cmd(
    keys=["`"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-to-lowercase",
)
def kakoune_to_lowercase(event: KeyPressEvent) -> None:
    """Convert every selection to lower case."""
    _transform(event, str.lower)


@add_cmd(
    keys=["~"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-to-uppercase",
)
def kakoune_to_uppercase(event: KeyPressEvent) -> None:
    """Convert every selection to upper case.

    NOTE: Kakoune's ``~`` is upper case. Helix maps ``~`` to swap case and
    ``<a-`>`` to upper case - exactly the other way round.
    """
    _transform(event, str.upper)


@add_cmd(
    keys=["A-`"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-swap-case",
)
def kakoune_swap_case(event: KeyPressEvent) -> None:
    """Swap the case of every selection."""
    _transform(event, str.swapcase)


@add_cmd(
    keys=[">"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-indent",
)
def kakoune_indent(event: KeyPressEvent) -> None:
    """Indent the lines of every selection."""
    _indent(event, add=True, include_empty=False)


@add_cmd(
    keys=["A->"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-indent-with-empty",
)
def kakoune_indent_with_empty(event: KeyPressEvent) -> None:
    """Indent the lines of every selection, including empty ones."""
    _indent(event, add=True, include_empty=True)


@add_cmd(
    keys=["<"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-unindent",
)
def kakoune_unindent(event: KeyPressEvent) -> None:
    """Unindent the lines of every selection."""
    _indent(event, add=False, include_empty=False)


def _indent(event: KeyPressEvent, *, add: bool, include_empty: bool) -> None:
    """Indent or unindent every line touched by a selection.

    Args:
        event: The key press being handled.
        add: Add indentation rather than removing it.
        include_empty: Indent empty lines too.
    """
    buff = event.current_buffer
    text = buff.text
    width = 4

    # Collect the distinct lines covered by any selection.
    starts: set[int] = set()
    for anchor, head in _selections(event):
        start, end = normalise((anchor, head))
        offset = text.rfind("\n", 0, start) + 1
        while offset < max(end, start + 1):
            starts.add(offset)
            newline = text.find("\n", offset)
            if newline < 0:
                break
            offset = newline + 1

    edits: list[tuple[int, int]] = []
    payloads: list[str] = []
    for offset in sorted(starts):
        newline = text.find("\n", offset)
        line_end = len(text) if newline < 0 else newline
        line = text[offset:line_end]
        if add:
            if not line.strip() and not include_empty:
                continue
            edits.append((offset, offset))
            payloads.append(" " * width)
        else:
            existing = len(line) - len(line.lstrip(" "))
            removed = min(existing, width)
            if removed == 0:
                continue
            edits.append((offset, offset + removed))
            payloads.append("")

    if not edits:
        event.app.output.bell()
        return

    kept = _selections(event)
    apply_edit_at_ranges(buff, edits, payloads)
    # Re-derive the selections: the edits shifted every offset after them.
    shift_total = 0
    shifted: list[tuple[int, int]] = []
    for anchor, head in kept:
        start, end = normalise((anchor, head))
        before_start = sum(
            len(p) - (e - s) for (s, e), p in zip(edits, payloads) if s <= start
        )
        before_end = sum(
            len(p) - (e - s) for (s, e), p in zip(edits, payloads) if s < end
        )
        shifted.append((start + before_start, end + before_end))
        shift_total += before_end
    set_selections(buff, shifted)


@add_cmd(
    keys=["A-j"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-join-lines",
)
def kakoune_join_lines(event: KeyPressEvent) -> None:
    """Join the lines of every selection.

    NOTE: Kakoune joins with ``<a-j>``; Helix uses ``J``, which here extends the
    selection downwards instead.
    """
    buff = event.current_buffer
    text = buff.text
    edits: list[tuple[int, int]] = []
    for anchor, head in _selections(event):
        start, end = normalise((anchor, head))
        offset = start
        while True:
            newline = text.find("\n", offset, max(end, start + 1))
            if newline < 0:
                break
            # Swallow the newline and the following indentation.
            stop = newline + 1
            while stop < len(text) and text[stop] in " \t":
                stop += 1
            edits.append((newline, stop))
            offset = stop
    if not edits:
        event.app.output.bell()
        return
    apply_edit_at_ranges(buff, edits, [" "])


@add_cmd(
    keys=["u"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    save_before=(lambda event: False),
    name="kakoune-undo",
)
def kakoune_undo(event: KeyPressEvent) -> None:
    """Undo the last change."""
    _state(event).clear_selections()
    event.current_buffer.undo()


@add_cmd(
    keys=["U"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    save_before=(lambda event: False),
    name="kakoune-redo",
)
def kakoune_redo(event: KeyPressEvent) -> None:
    """Redo the last undone change."""
    _state(event).clear_selections()
    event.current_buffer.redo()


@add_cmd(
    keys=["&"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-align-selections",
)
def kakoune_align_selections(event: KeyPressEvent) -> None:
    """Align the start of every selection into a common column."""
    buff = event.current_buffer
    new_text = align_ranges(buff.text, _selections(event))
    if new_text == buff.text:
        return
    buff.save_to_undo_stack()
    _state(event).clear_selections()
    buff.text = new_text


@add_cmd(
    keys=["A-&"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-copy-indent",
)
def kakoune_copy_indent(event: KeyPressEvent) -> None:
    """Copy the main selection's indentation to every other selection's line."""
    buff = event.current_buffer
    state = _state(event)
    new_text = copy_indent(buff.text, _selections(event), state.primary_index)
    if new_text == buff.text:
        return
    buff.save_to_undo_stack()
    state.clear_selections()
    buff.text = new_text


@add_cmd(
    keys=["_"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-trim-selections",
)
def kakoune_trim_selections(event: KeyPressEvent) -> None:
    """Trim surrounding whitespace from every selection."""
    _apply(event, trim_ranges(event.current_buffer.text, _selections(event)))


# Multiple selections


@add_cmd(
    keys=["A-s"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-split-lines",
)
def kakoune_split_lines(event: KeyPressEvent) -> None:
    """Split each selection on line boundaries, one selection per line."""
    _apply(event, split_on_newlines(event.current_buffer.text, _selections(event)))


@add_cmd(
    keys=["A-S"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-select-ends",
)
def kakoune_select_ends(event: KeyPressEvent) -> None:
    """Reduce each selection to its first and last characters."""
    _apply(event, first_and_last_chars(_selections(event)))


@add_cmd(
    keys=[","],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-keep-main-selection",
)
def kakoune_keep_main_selection(event: KeyPressEvent) -> None:
    """Discard every selection but the main one."""
    state = _state(event)
    _apply(
        event, collapse_to_primary(_selections(event), state.primary_index), primary=0
    )


@add_cmd(
    keys=["A-,"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-remove-main-selection",
)
def kakoune_remove_main_selection(event: KeyPressEvent) -> None:
    """Discard the main selection, keeping the rest."""
    state = _state(event)
    ranges = _selections(event)
    if len(ranges) < 2:
        event.app.output.bell()
        return
    index = min(state.primary_index, len(ranges) - 1)
    remaining = [r for position, r in enumerate(ranges) if position != index]
    _apply(event, remaining, primary=min(index, len(remaining) - 1))


@add_cmd(
    keys=["A-_"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-merge-contiguous",
)
def kakoune_merge_contiguous(event: KeyPressEvent) -> None:
    """Merge selections which touch or overlap."""
    _apply(event, merge_contiguous(_selections(event)), primary=0)


@add_cmd(
    keys=["+"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-duplicate-selections",
)
def kakoune_duplicate_selections(event: KeyPressEvent) -> None:
    """Duplicate every selection, producing overlapping ones."""
    _apply(event, duplicate_ranges(_selections(event)), primary=0)


@add_cmd(
    keys=["A-+"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-merge-overlapping",
)
def kakoune_merge_overlapping(event: KeyPressEvent) -> None:
    """Merge selections which genuinely overlap, leaving touching ones alone."""
    _apply(event, merge_overlapping(_selections(event)), primary=0)


@add_cmd(
    keys=[")"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-rotate-main-forward",
)
def kakoune_rotate_main_forward(event: KeyPressEvent) -> None:
    """Make the next selection the main one.

    NOTE: Helix ships ``rotate_primary`` but binds no key to it; Kakoune uses
    ``)`` and ``(``.
    """
    state = _state(event)
    ranges = _selections(event)
    count = event.arg
    _apply(event, ranges, primary=rotate_primary(ranges, state.primary_index, count))


@add_cmd(
    keys=["("],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-rotate-main-backward",
)
def kakoune_rotate_main_backward(event: KeyPressEvent) -> None:
    """Make the previous selection the main one."""
    state = _state(event)
    ranges = _selections(event)
    count = event.arg
    _apply(event, ranges, primary=rotate_primary(ranges, state.primary_index, -count))


def _rotate_contents(event: KeyPressEvent, step: int) -> None:
    """Rotate the text between selections, leaving the selections in place.

    Args:
        event: The key press being handled.
        step: How far to rotate, positive to move text forwards.
    """
    buff = event.current_buffer
    ranges = _selections(event)
    if len(ranges) < 2:
        event.app.output.bell()
        return
    contents = text_at_ranges(buff.text, ranges)
    rotated = rotate_contents(contents, step)
    set_selections(buff, apply_edit_at_ranges(buff, ranges, rotated))


@add_cmd(
    keys=["A-)"],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-rotate-contents-forward",
)
def kakoune_rotate_contents_forward(event: KeyPressEvent) -> None:
    """Rotate the selections' contents forwards."""
    _rotate_contents(event, event.arg)


@add_cmd(
    keys=["A-("],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-rotate-contents-backward",
)
def kakoune_rotate_contents_backward(event: KeyPressEvent) -> None:
    """Rotate the selections' contents backwards."""
    _rotate_contents(event, -(event.arg))


def _copy_to_adjacent_line(event: KeyPressEvent, *, below: bool) -> None:
    """Add a copy of every selection on the adjacent line.

    Args:
        event: The key press being handled.
        below: Copy onto the following line rather than the preceding one.
    """
    text = event.current_buffer.text
    ranges = list(_selections(event))
    added = [
        found
        for text_range in ranges
        if (found := copy_range_to_line(text, text_range, below=below)) is not None
    ]
    if not added:
        event.app.output.bell()
        return
    _apply(event, [*ranges, *added])


@add_cmd(
    keys=["C"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-copy-selection-below",
)
def kakoune_copy_selection_below(event: KeyPressEvent) -> None:
    """Add a selection on the line below each existing one."""
    _copy_to_adjacent_line(event, below=True)


@add_cmd(
    keys=["A-C"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-copy-selection-above",
)
def kakoune_copy_selection_above(event: KeyPressEvent) -> None:
    """Add a selection on the line above each existing one."""
    _copy_to_adjacent_line(event, below=False)


# Regex-driven selection. These borrow the search prompt rather than introducing a
# second prompt widget, following the approach ``helix.py`` takes for ``s``/``S``.


def _start_regex_prompt(event: KeyPressEvent, operation: str) -> None:
    """Prompt for a regular expression to apply to the current selections.

    Args:
        event: The key press being handled.
        operation: The pending operation - ``"select"``, ``"split"``, ``"keep"``
            or ``"drop"``.
    """
    from apptk.search import SearchDirection, start_global_search

    state = _state(event)
    state.pending_regex_op = operation
    state.pending_regex_ranges = _selections(event)
    start_global_search(direction=SearchDirection.FORWARD)


def apply_pending_regex(buffer: Buffer, pattern: str) -> None:
    """Apply the pending regex operation to a buffer.

    Args:
        buffer: The buffer the operation applies to.
        pattern: The regular expression entered at the prompt.
    """
    from apptk.key_binding.kakoune_state import get_state as _get_state

    state = _get_state(buffer)
    operation = state.pending_regex_op
    ranges = state.pending_regex_ranges
    state.pending_regex_op = None
    state.pending_regex_ranges = []

    if operation is None or not ranges:
        return

    try:
        if operation == "select":
            result = select_regex_within(buffer.text, ranges, pattern)
        elif operation == "split":
            result = split_on_regex(buffer.text, ranges, pattern)
        elif operation == "keep":
            result = keep_matching(buffer.text, ranges, pattern)
        elif operation == "drop":
            result = drop_matching(buffer.text, ranges, pattern)
        else:
            return
    except re.error:
        get_app().output.bell()
        return

    if result:
        set_selections(buffer, result)
    else:
        get_app().output.bell()


@add_cmd(
    keys=["s"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-select-regex",
)
def kakoune_select_regex(event: KeyPressEvent) -> None:
    """Select every match of a regular expression within the selections."""
    _start_regex_prompt(event, "select")


@add_cmd(
    keys=["S"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-split-regex",
)
def kakoune_split_regex(event: KeyPressEvent) -> None:
    """Split the selections on every match of a regular expression."""
    _start_regex_prompt(event, "split")


@add_cmd(
    keys=["A-k"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-keep-matching",
)
def kakoune_keep_matching(event: KeyPressEvent) -> None:
    """Keep only the selections matching a regular expression."""
    _start_regex_prompt(event, "keep")


@add_cmd(
    keys=["A-K"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-drop-matching",
)
def kakoune_drop_matching(event: KeyPressEvent) -> None:
    """Drop the selections matching a regular expression."""
    _start_regex_prompt(event, "drop")


# Text objects
#
# Kakoune has twelve object-entry keys: ``<a-a>``/``<a-i>`` select the whole or
# inner object, ``[``/``]``/``{``/``}`` go to or extend to its start or end, and the
# ``<a-…>`` forms of those four do the same for the inner object. Each awaits a
# second key naming the object type.
#
# They share one pending slot, encoded as ``"<action>:<scope>"``. Encoding rather
# than adding twelve slots follows the approach ``helix.py`` takes for its
# ``pending_surround = "replace-to:<char>"``.

#: Object-entry keys, mapped to the pending value they arm.
_OBJECT_ENTRIES: dict[str, str] = {
    "A-a": "select:whole",
    "A-i": "select:inner",
    "[": "to-start:whole",
    "]": "to-end:whole",
    "{": "extend-to-start:whole",
    "}": "extend-to-end:whole",
    "A-[": "to-start:inner",
    "A-]": "to-end:inner",
    "A-{": "extend-to-start:inner",
    "A-}": "extend-to-end:inner",
    "A-A": "select-nested:whole",
    "A-I": "select-nested:inner",
}


@Condition
def waiting_for_object() -> bool:
    """Check whether an object type key is awaited."""
    if not kakoune_mode():
        return False
    return get_app().kakoune_state.pending_object is not None


def _register_object_entry(key: str, pending: str) -> None:
    """Register one object-entry key.

    Args:
        key: The key which arms the pending slot.
        pending: The encoded ``"<action>:<scope>"`` value to arm it with.
    """
    action, _, scope = pending.partition(":")
    name = f"kakoune-object-{action}-{scope}"

    @add_cmd(
        keys=[key],
        filter=kakoune_normal_mode & ~waiting_for_object,
        hidden=True,
        name=name,
    )
    def _enter(event: KeyPressEvent, pending: str = pending) -> None:
        """Await an object type key."""
        _state(event).pending_object = pending


for _key, _pending in _OBJECT_ENTRIES.items():
    _register_object_entry(_key, _pending)


@add_cmd(
    keys=["<any>"],
    filter=kakoune_normal_mode & waiting_for_object,
    hidden=True,
    eager=True,
    name="kakoune-handle-object",
)
def kakoune_handle_object(event: KeyPressEvent) -> None:
    """Resolve the object named by the key press and apply the pending action."""
    state = _state(event)
    pending = state.pending_object or ""
    state.pending_object = None
    action, _, scope = pending.partition(":")
    around = scope == "whole"

    buff = event.current_buffer
    level = event.arg
    state.last_object = pending + ":" + event.data

    ranges: list[tuple[int, int]] = []
    for anchor, head in _selections(event):
        cursor = _cursor_of(anchor, head)
        found = resolve_text_object(
            buff.text, cursor, event.data, around=around, level=level
        )
        if found is None:
            continue
        start, end = found
        if action == "select":
            ranges.append((start, end))
        elif action == "to-start":
            ranges.append((cursor, start))
        elif action == "to-end":
            ranges.append((cursor, end))
        elif action == "extend-to-start":
            ranges.append((anchor, start))
        elif action == "extend-to-end":
            ranges.append((anchor, end))
        elif action == "select-nested":
            ranges.append((start, end))

    _apply(event, ranges)


@add_cmd(
    keys=["A-."],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-repeat-object",
)
def kakoune_repeat_object(event: KeyPressEvent) -> None:
    """Repeat the last object or character selection."""
    state = _state(event)
    if state.last_object is not None:
        action, scope, key = state.last_object.split(":", 2)
        state.pending_object = f"{action}:{scope}"
        event.key_sequence[-1].data = key
        kakoune_handle_object(event)
        return
    if state.last_char_find is not None:
        command, char = state.last_char_find
        state.pending_char = command
        event.key_sequence[-1].data = char
        kakoune_handle_char(event)
        return
    event.app.output.bell()


# Matching pairs
#
# In Kakoune ``m`` is a *motion*, not a sub-mode prefix: it selects to the next
# sequence enclosed by matching characters. Helix instead uses ``m`` to enter match
# mode, which is the largest structural difference between the two keymaps.

#: Characters which pair up for the ``m`` family of motions.
_MATCHING_PAIRS: dict[str, str] = {"(": ")", "[": "]", "{": "}", "<": ">"}


def _find_matching(text: str, cursor: int, *, backward: bool) -> tuple[int, int] | None:
    """Find the next or previous sequence enclosed by matching characters.

    Args:
        text: The full buffer text.
        cursor: The offset to search from.
        backward: Search towards the start of the buffer.

    Returns:
        The enclosing range, or None when there is none.
    """
    closing_to_opening = {close: open_ for open_, close in _MATCHING_PAIRS.items()}

    if not backward:
        for index in range(cursor, len(text)):
            char = text[index]
            if char in _MATCHING_PAIRS:
                closing = _MATCHING_PAIRS[char]
                depth = 0
                for position in range(index + 1, len(text)):
                    if text[position] == char:
                        depth += 1
                    elif text[position] == closing:
                        if depth == 0:
                            return (index, position + 1)
                        depth -= 1
                return None
            if char in closing_to_opening:
                opening = closing_to_opening[char]
                depth = 0
                for position in range(index - 1, -1, -1):
                    if text[position] == char:
                        depth += 1
                    elif text[position] == opening:
                        if depth == 0:
                            return (position, index + 1)
                        depth -= 1
                return None
        return None

    for index in range(min(cursor, len(text) - 1), -1, -1):
        char = text[index]
        if char in closing_to_opening:
            opening = closing_to_opening[char]
            depth = 0
            for position in range(index - 1, -1, -1):
                if text[position] == char:
                    depth += 1
                elif text[position] == opening:
                    if depth == 0:
                        return (position, index + 1)
                    depth -= 1
            return None
        if char in _MATCHING_PAIRS:
            closing = _MATCHING_PAIRS[char]
            depth = 0
            for position in range(index + 1, len(text)):
                if text[position] == char:
                    depth += 1
                elif text[position] == closing:
                    if depth == 0:
                        return (index, position + 1)
                    depth -= 1
            return None
    return None


def _register_match_motion(
    key: str, name: str, *, backward: bool, extend: bool
) -> None:
    """Register one of the four matching-pair motions.

    Args:
        key: The key to bind.
        name: The command name.
        backward: Search backwards.
        extend: Extend the selection rather than replacing it.
    """

    @add_cmd(keys=[key], filter=kakoune_normal_mode, hidden=True, name=name)
    def _motion(event: KeyPressEvent) -> None:
        """Select to a matching pair."""
        _select_range(
            event,
            lambda text, anchor, head: _find_matching(
                text, _cursor_of(anchor, head), backward=backward
            ),
            extend=extend,
        )


_register_match_motion("m", "kakoune-match-next", backward=False, extend=False)
_register_match_motion("M", "kakoune-match-next-extend", backward=False, extend=True)
_register_match_motion("A-m", "kakoune-match-prev", backward=True, extend=False)
_register_match_motion("A-M", "kakoune-match-prev-extend", backward=True, extend=True)


# Character search


@Condition
def waiting_for_char() -> bool:
    """Check whether a character is awaited for ``f``/``t`` and variants."""
    if not kakoune_mode():
        return False
    return get_app().kakoune_state.pending_char is not None


def _register_char_search(key: str, command: str, name: str) -> None:
    """Register one of the character-search keys.

    Args:
        key: The key to bind.
        command: The pending value identifying the variant.
        name: The command name.
    """

    @add_cmd(
        keys=[key],
        filter=kakoune_normal_mode & ~waiting_for_char,
        hidden=True,
        name=name,
    )
    def _enter(event: KeyPressEvent, command: str = command) -> None:
        """Await the character to search for."""
        _state(event).pending_char = command


# ``f``/``t`` search forwards and ``<a-f>``/``<a-t>`` backwards. Note Kakoune uses
# Alt for the reverse direction where Helix uses Shift.
_register_char_search("f", "f", "kakoune-find-char")
_register_char_search("t", "t", "kakoune-find-till-char")
_register_char_search("A-f", "F", "kakoune-find-char-backward")
_register_char_search("A-t", "T", "kakoune-find-till-char-backward")
_register_char_search("F", "ext-f", "kakoune-extend-find-char")
_register_char_search("T", "ext-t", "kakoune-extend-find-till-char")


@add_cmd(
    keys=["<any>"],
    filter=kakoune_normal_mode & waiting_for_char,
    hidden=True,
    eager=True,
    name="kakoune-handle-char",
)
def kakoune_handle_char(event: KeyPressEvent) -> None:
    """Select to or until the character pressed."""
    state = _state(event)
    command = state.pending_char
    state.pending_char = None
    char = event.data
    if command is None or not char or len(char) != 1:
        event.app.output.bell()
        return

    state.last_char_find = (command, char)
    count = event.arg
    extend = command.startswith("ext-")
    base = command.removeprefix("ext-")
    backward = base in ("F", "T")
    till = base.lower() == "t"

    def to_range(text: str, anchor: int, head: int) -> tuple[int, int] | None:
        cursor = _cursor_of(anchor, head)
        position = cursor
        for _ in range(count):
            if backward:
                found = text.rfind(char, 0, position)
            else:
                found = text.find(char, position + 1)
            if found < 0:
                return None
            position = found
        if backward:
            return (cursor + 1, position + 1 if till else position)
        return (cursor, position if till else position + 1)

    _select_range(event, to_range, extend=extend)


# Goto sub-mode
#
# ``g`` replaces the selection and ``G`` extends it, both then waiting for one of
# the keys below. Kakoune's goto set differs from Helix's: ``gk``/``gj`` are first
# and last line, ``ge`` the last character, and ``gi`` the first non-blank.


@add_cmd(
    keys=["g"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-enter-goto-mode",
)
def kakoune_enter_goto_mode(event: KeyPressEvent) -> None:
    """Enter goto mode, replacing the selection.

    With a count, ``g`` goes straight to that line, as Kakoune does.
    """
    if event.arg_present:
        _goto_line(event, event.arg, extend=False)
        return
    _state(event).mode = KakouneMode.GOTO


@add_cmd(
    keys=["G"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-enter-goto-extend-mode",
)
def kakoune_enter_goto_extend_mode(event: KeyPressEvent) -> None:
    """Enter goto mode, extending the selection."""
    if event.arg_present:
        _goto_line(event, event.arg, extend=True)
        return
    _state(event).mode = KakouneMode.GOTO_EXTEND


def _goto_line(event: KeyPressEvent, line: int, *, extend: bool) -> None:
    """Move to the start of a one-based line number.

    Args:
        event: The key press being handled.
        line: The one-based line number.
        extend: Extend the selection rather than replacing it.
    """

    def to_range(text: str, anchor: int, head: int) -> tuple[int, int]:
        offset = 0
        for _ in range(max(line - 1, 0)):
            newline = text.find("\n", offset)
            if newline < 0:
                break
            offset = newline + 1
        return (anchor if extend else offset, min(offset + 1, len(text)))

    _select_range(event, to_range, extend=extend)
    _state(event).exit_submode()


def _register_goto(key: str, name: str, to_offset: Callable[[str, int], int]) -> None:
    """Register a goto key for both the replacing and extending sub-modes.

    Args:
        key: The key to bind within goto mode.
        name: The command name.
        to_offset: Maps ``(text, cursor)`` to the destination offset.
    """

    @add_cmd(
        keys=[key],
        filter=kakoune_goto_mode,
        hidden=True,
        name=name,
    )
    def _goto(event: KeyPressEvent, to_offset: object = to_offset) -> None:
        """Jump within goto mode."""
        state = _state(event)
        extend = state.mode == KakouneMode.GOTO_EXTEND
        state.exit_submode()

        def to_range(text: str, anchor: int, head: int) -> tuple[int, int]:
            offset = max(
                0,
                min(to_offset(text, _cursor_of(anchor, head)), len(text)),  # type: ignore[operator]
            )
            if extend:
                return (anchor, offset)
            return (offset, min(offset + 1, len(text)))

        _select_range(event, to_range, extend=extend)


def _line_start(text: str, cursor: int) -> int:
    """Return the offset of the start of the cursor's line."""
    return text.rfind("\n", 0, cursor) + 1


def _line_end(text: str, cursor: int) -> int:
    """Return the offset of the end of the cursor's line."""
    newline = text.find("\n", cursor)
    return len(text) if newline < 0 else newline


def _first_non_blank(text: str, cursor: int) -> int:
    """Return the offset of the first non-blank character of the cursor's line."""
    offset = _line_start(text, cursor)
    while offset < len(text) and text[offset] in " \t":
        offset += 1
    return offset


def _last_line_start(text: str, cursor: int) -> int:
    """Return the offset of the start of the final line."""
    stripped = text[:-1] if text.endswith("\n") else text
    return stripped.rfind("\n") + 1


_register_goto("h", "kakoune-goto-line-start", _line_start)
_register_goto("l", "kakoune-goto-line-end", _line_end)
_register_goto("i", "kakoune-goto-first-non-blank", _first_non_blank)
# ``gg`` and ``gk`` both go to the first line; ``gj`` to the last.
_register_goto("g", "kakoune-goto-first-line", lambda text, cursor: 0)
_register_goto("k", "kakoune-goto-first-line-alt", lambda text, cursor: 0)
_register_goto("j", "kakoune-goto-last-line", _last_line_start)
_register_goto(
    "e", "kakoune-goto-buffer-end", lambda text, cursor: max(len(text) - 1, 0)
)


@add_cmd(
    keys=["escape"],
    filter=kakoune_goto_mode,
    hidden=True,
    eager=True,
    name="kakoune-exit-goto-mode",
)
def kakoune_exit_goto_mode(event: KeyPressEvent) -> None:
    """Leave goto mode without moving."""
    _state(event).exit_submode()


# View sub-mode
#
# ``v`` modifies the view once; ``V`` locks view mode until Escape. Note ``v`` is
# *not* select mode here - Kakoune has none.


@add_cmd(
    keys=["v"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-enter-view-mode",
)
def kakoune_enter_view_mode(event: KeyPressEvent) -> None:
    """Enter view mode for a single command."""
    _state(event).mode = KakouneMode.VIEW


@add_cmd(
    keys=["V"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-enter-view-locked-mode",
)
def kakoune_enter_view_locked_mode(event: KeyPressEvent) -> None:
    """Enter view mode and stay in it until :kbd:`Escape`."""
    _state(event).mode = KakouneMode.VIEW_LOCKED


def _scroll_to(event: KeyPressEvent, placement: str) -> None:
    """Scroll so that the main selection sits at a given screen position.

    Args:
        event: The key press being handled.
        placement: ``"center"``, ``"top"`` or ``"bottom"``.
    """
    window = event.app.layout.current_window
    info = window.render_info if window is not None else None
    if window is None or info is None:
        event.app.output.bell()
        return

    document = event.current_buffer.document
    if placement == "center":
        window.vertical_scroll = max(
            0, document.cursor_position_row - info.window_height // 2
        )
    elif placement == "top":
        window.vertical_scroll = document.cursor_position_row
    else:
        window.vertical_scroll = max(
            0, document.cursor_position_row - info.window_height + 1
        )


def _register_view(key: str, name: str, placement: str) -> None:
    """Register a view-mode placement key.

    Args:
        key: The key to bind within view mode.
        name: The command name.
        placement: The placement to pass to :py:func:`_scroll_to`.
    """

    @add_cmd(keys=[key], filter=kakoune_view_mode, hidden=True, name=name)
    def _view(event: KeyPressEvent, placement: str = placement) -> None:
        """Place the selection on screen."""
        state = _state(event)
        _scroll_to(event, placement)
        # A locked view mode stays put; a single-shot one returns to normal.
        if state.mode == KakouneMode.VIEW:
            state.exit_submode()


# ``v`` and ``c`` both centre vertically, matching Kakoune.
_register_view("v", "kakoune-view-center", "center")
_register_view("c", "kakoune-view-center-alt", "center")
_register_view("t", "kakoune-view-top", "top")
_register_view("b", "kakoune-view-bottom", "bottom")


def _register_view_scroll(key: str, name: str, delta: int) -> None:
    """Register a view-mode scrolling key.

    Args:
        key: The key to bind within view mode.
        name: The command name.
        delta: Lines to scroll, negative for upwards.
    """

    @add_cmd(keys=[key], filter=kakoune_view_mode, hidden=True, name=name)
    def _scroll(event: KeyPressEvent, delta: int = delta) -> None:
        """Scroll the window without moving the selection."""
        state = _state(event)
        window = event.app.layout.current_window
        if window is not None:
            count = event.arg
            window.vertical_scroll = max(0, window.vertical_scroll + delta * count)
        if state.mode == KakouneMode.VIEW:
            state.exit_submode()


_register_view_scroll("j", "kakoune-view-scroll-down", 1)
_register_view_scroll("k", "kakoune-view-scroll-up", -1)


@add_cmd(
    keys=["escape"],
    filter=kakoune_view_mode,
    hidden=True,
    eager=True,
    name="kakoune-exit-view-mode",
)
def kakoune_exit_view_mode(event: KeyPressEvent) -> None:
    """Leave view mode."""
    _state(event).exit_submode()


# User sub-mode
#
# :kbd:`Space` enters Kakoune's user mode, whose contents are defined by the
# application. euporie attaches its own commands in ``euporie.core.kakoune_bindings``.


@add_cmd(
    keys=["space"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-enter-user-mode",
)
def kakoune_enter_user_mode(event: KeyPressEvent) -> None:
    """Enter user mode, where the application's own commands live."""
    _state(event).mode = KakouneMode.USER


@add_cmd(
    keys=["escape"],
    filter=kakoune_user_mode,
    hidden=True,
    eager=True,
    name="kakoune-exit-user-mode",
)
def kakoune_exit_user_mode(event: KeyPressEvent) -> None:
    """Leave user mode."""
    _state(event).exit_submode()


# Registers
#
# ``"`` selects the register used by the next yank, paste, delete or macro
# operation. Kakoune's defaults are ``"`` for text, ``/`` for search, ``@`` for
# macros and ``^`` for marks.


@Condition
def waiting_for_register() -> bool:
    """Check whether a register name is awaited after ``"``."""
    if not kakoune_mode():
        return False
    return get_app().kakoune_state.waiting_for_register


@add_cmd(
    keys=['"'],
    filter=kakoune_normal_mode & ~waiting_for_register,
    hidden=True,
    name="kakoune-select-register",
)
def kakoune_select_register(event: KeyPressEvent) -> None:
    """Await the name of the register to use for the next operation."""
    _state(event).waiting_for_register = True


@add_cmd(
    keys=["<any>"],
    filter=kakoune_normal_mode & waiting_for_register,
    hidden=True,
    eager=True,
    name="kakoune-handle-register",
)
def kakoune_handle_register(event: KeyPressEvent) -> None:
    """Record the register named by the key press."""
    state = _state(event)
    state.waiting_for_register = False
    name = event.data
    # Kakoune register names are single characters; alphanumerics and the special
    # punctuation registers are accepted.
    if not name or len(name) != 1 or not (name.isalnum() or name in '"/@^|:.#_'):
        event.app.output.bell()
        return
    state.pending_register = name


# Macros
#
# NOTE: ``Q`` records and ``q`` replays. Helix binds these the other way round,
# which is the kind of difference that is invisible until muscle memory fails.


@Condition
def kakoune_recording_macro() -> bool:
    """Check whether a macro is being recorded."""
    if not kakoune_mode():
        return False
    return bool(get_app().kakoune_state.recording_register)


@add_cmd(
    keys=["Q"],
    filter=kakoune_normal_mode & ~kakoune_recording_macro,
    hidden=True,
    record_in_macro=False,
    name="kakoune-start-record-macro",
)
def kakoune_start_record_macro(event: KeyPressEvent) -> None:
    """Start recording a macro into the pending register, or ``@`` by default."""
    state = _state(event)
    state.recording_register = state.take_register() or "@"
    state.current_recording = ""


@add_cmd(
    keys=["Q"],
    filter=kakoune_normal_mode & kakoune_recording_macro,
    hidden=True,
    record_in_macro=False,
    name="kakoune-stop-record-macro",
)
def kakoune_stop_record_macro(event: KeyPressEvent) -> None:
    """Stop recording and store the macro."""
    state = _state(event)
    register = state.recording_register
    if register is not None:
        state.named_registers[register] = ClipboardData(state.current_recording)
    state.recording_register = None
    state.current_recording = ""


@add_cmd(
    keys=["q"],
    filter=kakoune_normal_mode & ~kakoune_recording_macro,
    hidden=True,
    record_in_macro=False,
    name="kakoune-play-macro",
)
def kakoune_play_macro(event: KeyPressEvent) -> None:
    """Replay the macro held in the pending register, or ``@`` by default."""
    state = _state(event)
    register = state.take_register() or "@"
    data = state.named_registers.get(register)
    if data is None or not data.text:
        event.app.output.bell()
        return
    count = event.arg
    presses = [KeyPress(key, key) for key in data.text] * count
    event.app.key_processor.feed_multiple(presses, first=True)


# Marks
#
# Selections can be saved to a register and restored later. ``^`` is the default
# mark register. This subsystem has no Helix equivalent.


@add_cmd(
    keys=["Z"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-save-selections",
)
def kakoune_save_selections(event: KeyPressEvent) -> None:
    """Save the current selections to the mark register."""
    state = _state(event)
    register = state.take_register() or "^"
    state.marks[register] = list(_selections(event))


@add_cmd(
    keys=["z"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-restore-selections",
)
def kakoune_restore_selections(event: KeyPressEvent) -> None:
    """Restore the selections saved in the mark register.

    NOTE: Kakoune's ``z`` restores marks. Helix uses ``z`` for view mode, which
    here is ``v``.
    """
    state = _state(event)
    register = state.take_register() or "^"
    saved = state.marks.get(register)
    if not saved:
        event.app.output.bell()
        return
    length = len(event.current_buffer.text)
    # A mark may outlive the text it referred to, so clamp before restoring.
    clamped = [(min(anchor, length), min(head, length)) for anchor, head in saved]
    _apply(event, clamped, primary=0)


@Condition
def waiting_for_mark_combine() -> bool:
    """Check whether a mark-combine operation is awaiting its menu key."""
    if not kakoune_mode():
        return False
    return get_app().kakoune_state.pending_mark_combine is not None


@add_cmd(
    keys=["A-z"],
    filter=kakoune_normal_mode & ~waiting_for_mark_combine,
    hidden=True,
    name="kakoune-combine-from-register",
)
def kakoune_combine_from_register(event: KeyPressEvent) -> None:
    """Combine the saved selections with the current ones, awaiting the operation."""
    _state(event).pending_mark_combine = "from-register"


@add_cmd(
    keys=["A-Z"],
    filter=kakoune_normal_mode & ~waiting_for_mark_combine,
    hidden=True,
    name="kakoune-combine-from-current",
)
def kakoune_combine_from_current(event: KeyPressEvent) -> None:
    """Combine the current selections with the saved ones, awaiting the operation."""
    _state(event).pending_mark_combine = "from-current"


#: The mark-combine menu, mapping its keys to set operations.
_COMBINE_OPERATIONS: dict[str, Callable[[list, list], list]] = {
    "a": lambda left, right: [*left, *right],
    "u": union,
    "i": intersection,
    "<": leftmost,
    ">": rightmost,
    "+": longest,
    "-": shortest,
}


@add_cmd(
    keys=["<any>"],
    filter=kakoune_normal_mode & waiting_for_mark_combine,
    hidden=True,
    eager=True,
    name="kakoune-handle-mark-combine",
)
def kakoune_handle_mark_combine(event: KeyPressEvent) -> None:
    """Apply the mark-combine operation named by the key press."""
    state = _state(event)
    direction = state.pending_mark_combine
    state.pending_mark_combine = None

    operation = _COMBINE_OPERATIONS.get(event.data)
    if operation is None:
        event.app.output.bell()
        return

    register = state.take_register() or "^"
    saved = state.marks.get(register)
    if not saved:
        event.app.output.bell()
        return

    current = _selections(event)
    # ``<a-z>`` combines the register's selections with the current ones; ``<a-Z>``
    # combines them the other way round, which matters for the asymmetric picks.
    if direction == "from-register":
        result = operation(saved, current)
    else:
        result = operation(current, saved)

    _apply(event, result, primary=0)


# Search


@add_cmd(
    keys=["/"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-search-forward",
)
def kakoune_search_forward(event: KeyPressEvent) -> None:
    """Search forwards, selecting the next match."""
    from apptk.search import SearchDirection, start_global_search

    start_global_search(direction=SearchDirection.FORWARD)


@add_cmd(
    keys=["A-/"],
    filter=kakoune_normal_mode,
    hidden=True,
    name="kakoune-search-backward",
)
def kakoune_search_backward(event: KeyPressEvent) -> None:
    """Search backwards, selecting the previous match."""
    from apptk.search import SearchDirection, start_global_search

    start_global_search(direction=SearchDirection.BACKWARD)


def _find_match(event: KeyPressEvent, *, backward: bool, add: bool) -> None:
    """Move to or add a selection at the next search match.

    Args:
        event: The key press being handled.
        backward: Search towards the start of the buffer.
        add: Add a selection rather than replacing the existing ones.
    """
    buff = event.current_buffer
    state = event.app.current_search_state
    pattern = state.text if state is not None else ""
    if not pattern:
        event.app.output.bell()
        return

    ranges = _selections(event)
    # Search proceeds from the main selection's cursor.
    kak_state = _state(event)
    main = ranges[min(kak_state.primary_index, len(ranges) - 1)]
    cursor = _cursor_of(*main)
    try:
        compiled = re.compile(re.escape(pattern))
    except re.error:
        event.app.output.bell()
        return

    if backward:
        matches = [m for m in compiled.finditer(buff.text) if m.end() <= cursor]
        match = matches[-1] if matches else None
    else:
        match = compiled.search(buff.text, cursor + 1)

    if match is None:
        event.app.output.bell()
        return

    found = (match.start(), match.end())
    _apply(event, [*ranges, found] if add else [found], primary=None if add else 0)


@add_cmd(
    keys=["n"],
    filter=kakoune_normal_mode & ~is_searching,
    hidden=True,
    name="kakoune-search-next",
)
def kakoune_search_next(event: KeyPressEvent) -> None:
    """Select the next match after the main selection."""
    _find_match(event, backward=False, add=False)


@add_cmd(
    keys=["A-n"],
    filter=kakoune_normal_mode & ~is_searching,
    hidden=True,
    name="kakoune-search-prev",
)
def kakoune_search_prev(event: KeyPressEvent) -> None:
    """Select the previous match before the main selection."""
    _find_match(event, backward=True, add=False)


@add_cmd(
    keys=["N"],
    filter=kakoune_normal_mode & ~is_searching,
    hidden=True,
    name="kakoune-search-next-add",
)
def kakoune_search_next_add(event: KeyPressEvent) -> None:
    """Add a selection at the next match.

    NOTE: Kakoune's ``N`` *adds* a selection. Helix uses ``N`` to search
    backwards, so this is a behavioural difference rather than a spelling one.
    """
    _find_match(event, backward=False, add=True)


@add_cmd(
    keys=["A-N"],
    filter=kakoune_normal_mode & ~is_searching,
    hidden=True,
    name="kakoune-search-prev-add",
)
def kakoune_search_prev_add(event: KeyPressEvent) -> None:
    """Add a selection at the previous match."""
    _find_match(event, backward=True, add=True)


# Counts
#
# Digits accumulate a count prefix. ``0`` only joins a count already in progress,
# since on its own it is not a Kakoune command.


def _register_count(digit: str) -> None:
    """Register a count digit.

    Args:
        digit: The digit to bind.
    """

    @add_cmd(
        keys=[digit],
        filter=kakoune_normal_mode,
        hidden=True,
        name=f"kakoune-count-{digit}",
    )
    def _count(event: KeyPressEvent) -> None:
        """Accumulate a count prefix."""
        event.append_to_arg_count(event.data)


for _digit in "123456789":
    _register_count(_digit)


@add_cmd(
    keys=["0"],
    filter=kakoune_normal_mode & has_arg,
    hidden=True,
    name="kakoune-count-0",
)
def kakoune_count_0(event: KeyPressEvent) -> None:
    """Accumulate a zero into a count already in progress."""
    event.append_to_arg_count(event.data)


# Repeat


@add_cmd(
    keys=["."],
    filter=kakoune_normal_mode & ~is_read_only,
    hidden=True,
    name="kakoune-repeat-insert",
)
def kakoune_repeat_insert(event: KeyPressEvent) -> None:
    """Repeat the last insert-mode change, including the text typed."""
    state = _state(event)
    if not state.last_insert:
        event.app.output.bell()
        return
    buff = event.current_buffer
    ranges = [(max(a, h), max(a, h)) for a, h in _selections(event)]
    new_ranges = apply_edit_at_ranges(buff, ranges, [state.last_insert])
    kept = [(max(end - 1, start), end) for start, end in new_ranges]
    set_selections(buff, kept)


# Unbound keys
#
# A catch-all so that a stray key in normal mode rings the bell rather than falling
# through to insert text. Deliberately last, and not eager, so every real binding
# wins.


@add_cmd(
    keys=["<any>"],
    filter=kakoune_normal_mode
    & ~has_arg
    & ~waiting_for_char
    & ~waiting_for_object
    & ~waiting_for_register
    & ~waiting_for_replace_char
    & ~waiting_for_mark_combine,
    hidden=True,
    name="kakoune-unbound-key",
)
def kakoune_unbound_key(event: KeyPressEvent) -> None:
    """Signal that a key is not bound in normal mode."""
    event.app.output.bell()


# Loading

#: Search commands, bound separately so that they are available while the search
#: prompt has focus. An explicit list rather than a registry scan, because only
#: these belong in the search bindings.
KAKOUNE_SEARCH_COMMANDS = (
    "kakoune-search-forward",
    "kakoune-search-backward",
    "kakoune-search-next",
    "kakoune-search-prev",
    "kakoune-search-next-add",
    "kakoune-search-prev-add",
)


def load_kakoune_bindings() -> KeyBindingsBase:
    """Load the Kakoune key bindings.

    Every command named ``kakoune-*`` in the command registry is bound, so adding a
    command with an ``@add_cmd`` decorator is enough to bind it - there is no
    separate list to keep in step.

    Returns:
        The Kakoune bindings, active only in Kakoune editing mode.
    """
    kb = KeyBindings()

    # ``COMMANDS`` maps aliases to the same ``Command`` object, so bind by object
    # identity to avoid binding an aliased command more than once.
    seen: set[int] = set()
    for name, cmd in COMMANDS.items():
        if name.startswith("kakoune-") and id(cmd) not in seen:
            seen.add(id(cmd))
            cmd.bind(kb)

    return ConditionalKeyBindings(kb, kakoune_mode)


def load_kakoune_search_bindings() -> KeyBindingsBase:
    """Load the Kakoune search key bindings.

    Returns:
        The search bindings, active only in Kakoune editing mode.
    """
    kb = KeyBindings()
    for name in KAKOUNE_SEARCH_COMMANDS:
        get_cmd(name).bind(kb)
    return ConditionalKeyBindings(kb, kakoune_mode)
