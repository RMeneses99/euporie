"""Define editor key-bindings and commands for the Helix editing mode.

Helix is a modal editor with a "select-then-act" paradigm. Unlike Vi's
"verb-then-object" approach, Helix selections are made first, then
operations are applied to them.

Key differences from Vi:
- Movement keys select text by default (in select mode)
- `w`, `b`, `e` select words rather than just moving
- `x` selects the current line
- `d` deletes selection, `c` changes selection
- `g` enters goto mode, `m` enters match mode
- `z` enters view mode for scrolling without moving cursor
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from apptk.application.current import get_app
from apptk.buffer import indent, unindent
from apptk.clipboard import ClipboardData
from apptk.commands import COMMANDS, add_cmd, get_cmd
from apptk.filters import (
    Condition,
    buffer_has_focus,
    has_arg,
    has_selection,
    is_read_only,
)
from apptk.filters.app import (
    in_paste_mode,
    is_multiline,
    is_searching,
)
from apptk.filters.buffer import is_returnable
from apptk.filters.modes import (
    helix_goto_mode,
    helix_insert_mode,
    helix_match_mode,
    helix_mode,
    helix_normal_mode,
    helix_select_mode,
    helix_space_mode,
    helix_view_mode,
    helix_window_mode,
)
from apptk.key_binding import ConditionalKeyBindings, KeyBindings
from apptk.key_binding.bindings.helix_selections import (
    align_ranges,
    apply_edit_at_ranges,
    collapse_to_primary,
    copy_range_to_line,
    get_selections,
    select_regex_within,
    set_selections,
    split_on_newlines,
    split_on_regex,
    text_at_ranges,
    trim_ranges,
)
from apptk.key_binding.bindings.helix_textobjects import (
    BRACKET_PAIRS,
    resolve_text_object,
)
from apptk.key_binding.helix_state import CharacterFind, InputMode
from apptk.key_binding.key_processor import KeyPress
from apptk.selection import SelectionState, SelectionType

if TYPE_CHECKING:
    from collections.abc import Callable

    from apptk.buffer import Buffer
    from apptk.key_binding.key_bindings import KeyBindingsBase
    from apptk.key_binding.key_processor import KeyPressEvent

__all__ = [
    "load_helix_bindings",
    "load_helix_search_bindings",
]

log = logging.getLogger(__name__)


# Helper functions


def _exit_helix_submodes() -> None:
    """Exit all Helix sub-modes (goto, match, view, window)."""
    get_app().helix_state.exit_submode()


def _enter_helix_normal_mode() -> None:
    """Enter Helix normal mode."""
    app = get_app()
    buffer = app.current_buffer
    helix_state = app.helix_state

    if helix_state.input_mode in (InputMode.INSERT, InputMode.REPLACE):
        buffer.cursor_position += buffer.document.get_cursor_left_position()

    helix_state.input_mode = InputMode.NAVIGATION
    helix_state.select_mode = False
    _exit_helix_submodes()

    if buffer.selection_state:
        buffer.exit_selection()


# Normal mode commands


@add_cmd(
    keys=["escape"],
    filter=helix_mode & buffer_has_focus,
    hidden=True,
    name="helix-normal-mode",
)
def helix_escape(event: KeyPressEvent) -> None:
    """Return to normal mode and collapse selection."""
    _enter_helix_normal_mode()


@add_cmd(
    keys=["i"],
    filter=(helix_normal_mode | helix_select_mode) & ~is_read_only,
    hidden=True,
    name="helix-insert-mode",
)
def helix_insert_mode_cmd(event: KeyPressEvent) -> None:
    """Enter insert mode before selection."""
    buff = event.current_buffer
    if buff.selection_state:
        buff.exit_selection()
    event.app.helix_state.input_mode = InputMode.INSERT
    _exit_helix_submodes()


@add_cmd(
    keys=["a"],
    filter=(helix_normal_mode | helix_select_mode) & ~is_read_only,
    hidden=True,
    name="helix-append-mode",
)
def helix_append_mode(event: KeyPressEvent) -> None:
    """Enter insert mode after selection."""
    buff = event.current_buffer
    if buff.selection_state:
        buff.exit_selection()
    buff.cursor_position += buff.document.get_cursor_right_position()
    event.app.helix_state.input_mode = InputMode.INSERT
    _exit_helix_submodes()


@add_cmd(
    keys=["I"],
    filter=helix_normal_mode & ~is_read_only,
    hidden=True,
    name="helix-insert-line-start",
)
def helix_insert_line_start(event: KeyPressEvent) -> None:
    """Insert at start of line."""
    buff = event.current_buffer
    buff.cursor_position += buff.document.get_start_of_line_position(
        after_whitespace=True
    )
    event.app.helix_state.input_mode = InputMode.INSERT


@add_cmd(
    keys=["A"],
    filter=helix_normal_mode & ~is_read_only,
    hidden=True,
    name="helix-insert-line-end",
)
def helix_insert_line_end(event: KeyPressEvent) -> None:
    """Insert at end of line."""
    buff = event.current_buffer
    buff.cursor_position += buff.document.get_end_of_line_position()
    event.app.helix_state.input_mode = InputMode.INSERT


@add_cmd(
    keys=["o"],
    filter=helix_normal_mode & ~is_read_only,
    hidden=True,
    name="helix-open-below",
)
def helix_open_below(event: KeyPressEvent) -> None:
    """Open new line below and enter insert mode."""
    event.current_buffer.insert_line_below(copy_margin=not in_paste_mode())
    event.app.helix_state.input_mode = InputMode.INSERT


@add_cmd(
    keys=["O"],
    filter=helix_normal_mode & ~is_read_only,
    hidden=True,
    name="helix-open-above",
)
def helix_open_above(event: KeyPressEvent) -> None:
    """Open new line above and enter insert mode."""
    event.current_buffer.insert_line_above(copy_margin=not in_paste_mode())
    event.app.helix_state.input_mode = InputMode.INSERT


# Helper to ensure selection state is correct for the current mode


def _prepare_movement(event: KeyPressEvent) -> None:
    """Prepare buffer for a movement command.

    In explicit select mode (via ``v``), ensure a selection exists to extend.
    In normal mode, discard any existing selection from a previous motion.
    """
    buff = event.current_buffer
    if event.app.helix_state.select_mode:
        if buff.selection_state is None:
            buff.start_selection(selection_type=SelectionType.CHARACTERS)
    else:
        if buff.selection_state is not None:
            buff.exit_selection()


# Movement commands


@add_cmd(
    keys=["h", "left"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-move-left",
)
def helix_move_left(event: KeyPressEvent) -> None:
    """Move left."""
    _prepare_movement(event)
    buff = event.current_buffer
    buff.cursor_position = max(0, buff.cursor_position - event.arg)


@add_cmd(
    keys=["l", "right"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-move-right",
)
def helix_move_right(event: KeyPressEvent) -> None:
    """Move right."""
    _prepare_movement(event)
    buff = event.current_buffer
    buff.cursor_position = min(len(buff.text), buff.cursor_position + event.arg)


@add_cmd(
    keys=["j", "down"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-move-down",
)
def helix_move_down(event: KeyPressEvent) -> None:
    """Move down."""
    _prepare_movement(event)
    event.current_buffer.cursor_down(count=event.arg)


@add_cmd(
    keys=["k", "up"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-move-up",
)
def helix_move_up(event: KeyPressEvent) -> None:
    """Move up."""
    _prepare_movement(event)
    event.current_buffer.cursor_up(count=event.arg)


@add_cmd(
    keys=["w"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-select-next-word-start",
)
def helix_select_next_word_start(event: KeyPressEvent) -> None:
    """Select to next word start."""
    buff = event.current_buffer
    if event.app.helix_state.select_mode:
        # Extend existing selection
        if buff.selection_state is None:
            buff.start_selection(selection_type=SelectionType.CHARACTERS)
    else:
        # Start a fresh selection from current position
        if buff.selection_state is not None:
            buff.exit_selection()
        buff.start_selection(selection_type=SelectionType.CHARACTERS)
    pos = buff.document.find_next_word_beginning(count=event.arg)
    if pos:
        buff.cursor_position += pos


@add_cmd(
    keys=["W"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-select-next-long-word-start",
)
def helix_select_next_long_word_start(event: KeyPressEvent) -> None:
    """Select to next WORD start."""
    buff = event.current_buffer
    if event.app.helix_state.select_mode:
        if buff.selection_state is None:
            buff.start_selection(selection_type=SelectionType.CHARACTERS)
    else:
        if buff.selection_state is not None:
            buff.exit_selection()
        buff.start_selection(selection_type=SelectionType.CHARACTERS)
    pos = buff.document.find_next_word_beginning(count=event.arg, WORD=True)
    if pos:
        buff.cursor_position += pos


@add_cmd(
    keys=["b"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-select-prev-word-start",
)
def helix_select_prev_word_start(event: KeyPressEvent) -> None:
    """Select to previous word start."""
    buff = event.current_buffer
    if event.app.helix_state.select_mode:
        if buff.selection_state is None:
            buff.start_selection(selection_type=SelectionType.CHARACTERS)
    else:
        if buff.selection_state is not None:
            buff.exit_selection()
        buff.start_selection(selection_type=SelectionType.CHARACTERS)
    pos = buff.document.find_start_of_previous_word(count=event.arg)
    if pos:
        buff.cursor_position += pos


@add_cmd(
    keys=["B"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-select-prev-long-word-start",
)
def helix_select_prev_long_word_start(event: KeyPressEvent) -> None:
    """Select to previous WORD start."""
    buff = event.current_buffer
    if event.app.helix_state.select_mode:
        if buff.selection_state is None:
            buff.start_selection(selection_type=SelectionType.CHARACTERS)
    else:
        if buff.selection_state is not None:
            buff.exit_selection()
        buff.start_selection(selection_type=SelectionType.CHARACTERS)
    pos = buff.document.find_start_of_previous_word(count=event.arg, WORD=True)
    if pos:
        buff.cursor_position += pos


@add_cmd(
    keys=["e"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-select-next-word-end",
)
def helix_select_next_word_end(event: KeyPressEvent) -> None:
    """Select to next word end."""
    buff = event.current_buffer
    if event.app.helix_state.select_mode:
        if buff.selection_state is None:
            buff.start_selection(selection_type=SelectionType.CHARACTERS)
    else:
        if buff.selection_state is not None:
            buff.exit_selection()
        buff.start_selection(selection_type=SelectionType.CHARACTERS)
    pos = buff.document.find_next_word_ending(count=event.arg)
    if pos:
        buff.cursor_position += pos - 1


@add_cmd(
    keys=["E"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-select-next-long-word-end",
)
def helix_select_next_long_word_end(event: KeyPressEvent) -> None:
    """Select to next WORD end."""
    buff = event.current_buffer
    if event.app.helix_state.select_mode:
        if buff.selection_state is None:
            buff.start_selection(selection_type=SelectionType.CHARACTERS)
    else:
        if buff.selection_state is not None:
            buff.exit_selection()
        buff.start_selection(selection_type=SelectionType.CHARACTERS)
    pos = buff.document.find_next_word_ending(count=event.arg, WORD=True)
    if pos:
        buff.cursor_position += pos - 1


# Line selection (Helix's x command)


@add_cmd(
    keys=["x"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-extend-line-below",
)
def helix_extend_line_below(event: KeyPressEvent) -> None:
    """Select current line, extend to next line if already selected."""
    buff = event.current_buffer
    doc = buff.document

    if buff.selection_state is None or (
        buff.selection_state.type != SelectionType.LINES
    ):
        # Start a fresh line selection at beginning of current line
        start = buff.cursor_position + doc.get_start_of_line_position()
        buff.selection_state = SelectionState(start, SelectionType.LINES)
        # Move to end of current line
        buff.cursor_position += buff.document.get_end_of_line_position()
    else:
        # Already have a line selection, extend to next line
        for _ in range(event.arg):
            buff.cursor_down()
        buff.cursor_position += buff.document.get_end_of_line_position()


@add_cmd(
    keys=["X"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-extend-to-line-bounds",
)
def helix_extend_to_line_bounds(event: KeyPressEvent) -> None:
    """Extend selection to line bounds."""
    buff = event.current_buffer
    if buff.selection_state:
        event.app.helix_state.select_mode = True
        buff.selection_state.type = SelectionType.LINES


# Find character commands


@add_cmd(
    keys=["f"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-find-char",
)
def helix_find_char(event: KeyPressEvent) -> None:
    """Find next occurrence of character."""
    # This needs to wait for the next character input
    event.app.helix_state.waiting_for_char = "f"


@add_cmd(
    keys=["F"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-find-char-backward",
)
def helix_find_char_backward(event: KeyPressEvent) -> None:
    """Find previous occurrence of character."""
    event.app.helix_state.waiting_for_char = "F"


@add_cmd(
    keys=["t"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-find-till-char",
)
def helix_find_till_char(event: KeyPressEvent) -> None:
    """Find till next occurrence of character."""
    event.app.helix_state.waiting_for_char = "t"


@add_cmd(
    keys=["T"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-find-till-char-backward",
)
def helix_find_till_char_backward(event: KeyPressEvent) -> None:
    """Find till previous occurrence of character."""
    event.app.helix_state.waiting_for_char = "T"


@Condition
def waiting_for_char() -> bool:
    """Check if waiting for a character input for f/F/t/T."""
    if not helix_mode():
        return False
    return get_app().helix_state.waiting_for_char is not None


@add_cmd(
    keys=["<any>"],
    filter=(helix_normal_mode | helix_select_mode) & waiting_for_char,
    hidden=True,
    eager=True,
    name="helix-handle-find-char",
)
def helix_handle_find_char(event: KeyPressEvent) -> None:
    """Handle character input for f/F/t/T commands."""
    app = event.app
    buff = event.current_buffer
    char = event.data
    mode = app.helix_state.waiting_for_char
    app.helix_state.waiting_for_char = None

    if app.helix_state.select_mode:
        if buff.selection_state is None:
            buff.start_selection(selection_type=SelectionType.CHARACTERS)
    else:
        if buff.selection_state is not None:
            buff.exit_selection()
        buff.start_selection(selection_type=SelectionType.CHARACTERS)

    if mode == "f":
        app.helix_state.last_character_find = CharacterFind(char, False)
        match = buff.document.find(char, in_current_line=False, count=event.arg)
        if match:
            buff.cursor_position += match
    elif mode == "F":
        app.helix_state.last_character_find = CharacterFind(char, True)
        pos = buff.document.find_backwards(char, in_current_line=False, count=event.arg)
        if pos:
            buff.cursor_position += pos
    elif mode == "t":
        app.helix_state.last_character_find = CharacterFind(char, False)
        match = buff.document.find(char, in_current_line=False, count=event.arg)
        if match:
            buff.cursor_position += match - 1
    elif mode == "T":
        app.helix_state.last_character_find = CharacterFind(char, True)
        pos = buff.document.find_backwards(char, in_current_line=False, count=event.arg)
        if pos:
            buff.cursor_position += pos + 1


# Registers and macros


@Condition
def waiting_for_register() -> bool:
    """Check whether a register name is being awaited after ``"``."""
    if not helix_mode():
        return False
    return get_app().helix_state.waiting_for_register


@Condition
def helix_recording_macro() -> bool:
    """Check whether a Helix macro is currently being recorded."""
    if not helix_mode():
        return False
    return bool(get_app().helix_state.recording_register)


@add_cmd(
    keys=['"'],
    filter=(helix_normal_mode | helix_select_mode) & ~waiting_for_register,
    hidden=True,
    name="helix-select-register",
)
def helix_select_register(event: KeyPressEvent) -> None:
    """Await a register name for the next yank, paste or delete."""
    event.app.helix_state.waiting_for_register = True


@add_cmd(
    keys=["<any>"],
    filter=(helix_normal_mode | helix_select_mode) & waiting_for_register,
    hidden=True,
    eager=True,
    name="helix-handle-register",
)
def helix_handle_register(event: KeyPressEvent) -> None:
    """Record the register named by the key press following ``"``."""
    helix_state = event.app.helix_state
    helix_state.waiting_for_register = False
    char = event.data
    if char and len(char) == 1 and char.isalnum():
        helix_state.pending_register = char
    else:
        event.app.output.bell()


@add_cmd(
    keys=["q"],
    filter=helix_normal_mode & ~helix_recording_macro,
    hidden=True,
    name="helix-record-macro",
)
def helix_record_macro(event: KeyPressEvent) -> None:
    """Begin recording a macro into the pending register, or ``@`` by default."""
    helix_state = event.app.helix_state
    helix_state.recording_register = helix_state.take_register() or "@"
    helix_state.current_recording = ""


@add_cmd(
    keys=["q"],
    filter=helix_normal_mode & helix_recording_macro,
    hidden=True,
    name="helix-stop-record-macro",
)
def helix_stop_record_macro(event: KeyPressEvent) -> None:
    """Stop recording and store the macro in its register."""
    helix_state = event.app.helix_state
    register = helix_state.recording_register
    if register is not None:
        helix_state.named_registers[register] = ClipboardData(
            helix_state.current_recording
        )
    helix_state.recording_register = None
    helix_state.current_recording = ""


@add_cmd(
    keys=["Q"],
    filter=helix_normal_mode & ~helix_recording_macro,
    hidden=True,
    record_in_macro=False,
    name="helix-play-macro",
)
def helix_play_macro(event: KeyPressEvent) -> None:
    """Replay the macro held in the pending register, or ``@`` by default."""
    helix_state = event.app.helix_state
    register = helix_state.take_register() or "@"
    data = helix_state.named_registers.get(register)
    if data is None or not data.text:
        event.app.output.bell()
        return
    event.app.key_processor.feed_multiple(
        [KeyPress(key, key) for key in data.text], first=True
    )


# Selection mode (v)


@add_cmd(
    keys=["v"],
    filter=helix_normal_mode,
    hidden=True,
    name="helix-select-mode",
)
def helix_select_mode_cmd(event: KeyPressEvent) -> None:
    """Enter select/extend mode."""
    buff = event.current_buffer
    event.app.helix_state.select_mode = True
    buff.start_selection(selection_type=SelectionType.CHARACTERS)


@add_cmd(
    keys=["v"],
    filter=helix_select_mode,
    hidden=True,
    name="helix-exit-select-mode",
)
def helix_exit_select_mode(event: KeyPressEvent) -> None:
    """Exit select mode, keeping the current selection."""
    event.app.helix_state.select_mode = False


# Changes


def store_clipboard_data(event: KeyPressEvent, data: ClipboardData) -> None:
    """Store yanked or deleted text in the pending register, or the clipboard.

    Args:
        event: The triggering key-press event.
        data: The text to store.
    """
    register = event.app.helix_state.take_register()
    if register is None:
        event.app.clipboard.set_data(data)
    else:
        event.app.helix_state.named_registers[register] = data


def fetch_clipboard_data(event: KeyPressEvent) -> ClipboardData:
    """Fetch text to paste from the pending register, or the clipboard.

    Args:
        event: The triggering key-press event.

    Returns:
        The stored text. An empty clipboard entry is returned for a register
        which has never been written to.
    """
    register = event.app.helix_state.take_register()
    if register is None:
        return event.app.clipboard.get_data()
    return event.app.helix_state.named_registers.get(register, ClipboardData(""))


@add_cmd(
    keys=["d"],
    filter=(helix_normal_mode | helix_select_mode) & has_selection,
    hidden=True,
    name="helix-delete-selection",
)
def helix_delete_selection(event: KeyPressEvent) -> None:
    """Delete every selection."""
    buff = event.current_buffer
    ranges = get_selections(buff)

    if len(ranges) < 2:
        store_clipboard_data(event, buff.cut_selection())
        return

    store_clipboard_data(
        event, ClipboardData("\n".join(text_at_ranges(buff.text, ranges)))
    )
    new_ranges = apply_edit_at_ranges(buff, ranges, [""])
    # Every range is now empty and collapsed onto the same points; keep the
    # cursors so a following insert applies at each site.
    set_selections(buff, new_ranges)


@add_cmd(
    keys=["d"],
    filter=helix_normal_mode & ~has_selection,
    hidden=True,
    name="helix-delete-char",
)
def helix_delete_char(event: KeyPressEvent) -> None:
    """Delete character under cursor."""
    buff = event.current_buffer
    text = buff.delete(count=event.arg)
    event.app.clipboard.set_text(text)


@add_cmd(
    keys=["c"],
    filter=(helix_normal_mode | helix_select_mode) & has_selection & ~is_read_only,
    hidden=True,
    name="helix-change-selection",
)
def helix_change_selection(event: KeyPressEvent) -> None:
    """Change every selection: delete it and enter insert mode."""
    buff = event.current_buffer
    ranges = get_selections(buff)

    if len(ranges) < 2:
        store_clipboard_data(event, buff.cut_selection())
    else:
        store_clipboard_data(
            event, ClipboardData("\n".join(text_at_ranges(buff.text, ranges)))
        )
        set_selections(buff, apply_edit_at_ranges(buff, ranges, [""]))

    event.app.helix_state.input_mode = InputMode.INSERT


@add_cmd(
    keys=["c"],
    filter=helix_normal_mode & ~has_selection & ~is_read_only,
    hidden=True,
    name="helix-change-char",
)
def helix_change_char(event: KeyPressEvent) -> None:
    """Change character under cursor."""
    buff = event.current_buffer
    text = buff.delete(count=event.arg)
    event.app.clipboard.set_text(text)
    event.app.helix_state.input_mode = InputMode.INSERT


@add_cmd(
    keys=["A-d"],
    filter=(helix_normal_mode | helix_select_mode) & has_selection,
    hidden=True,
    name="helix-delete-selection-noyank",
)
def helix_delete_selection_noyank(event: KeyPressEvent) -> None:
    """Delete selection without yanking."""
    event.current_buffer.cut_selection()


@add_cmd(
    keys=["A-d"],
    filter=helix_normal_mode & ~has_selection,
    hidden=True,
    name="helix-delete-char-noyank",
)
def helix_delete_char_noyank(event: KeyPressEvent) -> None:
    """Delete character under cursor without yanking."""
    event.current_buffer.delete(count=event.arg)


@add_cmd(
    keys=["A-c"],
    filter=(helix_normal_mode | helix_select_mode) & has_selection & ~is_read_only,
    hidden=True,
    name="helix-change-selection-noyank",
)
def helix_change_selection_noyank(event: KeyPressEvent) -> None:
    """Change selection without yanking."""
    event.current_buffer.cut_selection()
    event.app.helix_state.input_mode = InputMode.INSERT


@add_cmd(
    keys=["A-c"],
    filter=helix_normal_mode & ~has_selection & ~is_read_only,
    hidden=True,
    name="helix-change-char-noyank",
)
def helix_change_char_noyank(event: KeyPressEvent) -> None:
    """Change character under cursor without yanking."""
    event.current_buffer.delete(count=event.arg)
    event.app.helix_state.input_mode = InputMode.INSERT


@add_cmd(
    keys=["r"],
    filter=helix_normal_mode,
    hidden=True,
    name="helix-replace-char",
)
def helix_replace_char(event: KeyPressEvent) -> None:
    """Replace character."""
    event.app.helix_state.input_mode = InputMode.REPLACE_SINGLE


@add_cmd(
    keys=["R"],
    filter=(helix_normal_mode | helix_select_mode) & has_selection & ~is_read_only,
    hidden=True,
    name="helix-replace-with-yanked",
)
def helix_replace_with_yanked(event: KeyPressEvent) -> None:
    """Replace selection with yanked text."""
    buff = event.current_buffer
    buff.cut_selection()
    buff.paste_clipboard_data(fetch_clipboard_data(event))


def _transform_selections(
    event: KeyPressEvent, transform: Callable[[str], str], *, keep_selection: bool
) -> bool:
    """Apply a text transform to every selection as one undoable edit.

    Args:
        event: The triggering key-press event.
        transform: The transform to apply to each selection's text.
        keep_selection: Leave the transformed ranges selected afterwards.

    Returns:
        True if a multi-selection edit was applied, False when there are fewer
        than two selections and the caller should handle the single case.
    """
    buff = event.current_buffer
    ranges = get_selections(buff)
    if len(ranges) < 2:
        return False

    replacements = [transform(part) for part in text_at_ranges(buff.text, ranges)]
    new_ranges = apply_edit_at_ranges(buff, ranges, replacements)
    if keep_selection:
        set_selections(buff, new_ranges)
    else:
        set_selections(buff, [])
    return True


@add_cmd(
    keys=["~"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-switch-case",
)
def helix_switch_case(event: KeyPressEvent) -> None:
    """Switch the case of every selection, or of the character under the cursor."""
    buff = event.current_buffer
    if _transform_selections(event, str.swapcase, keep_selection=True):
        return

    selection_state = buff.selection_state
    if selection_state:
        for start, end in buff.document.selection_ranges():
            buff.transform_region(start, end, lambda s: s.swapcase())
        buff.selection_state = selection_state
    else:
        c = buff.document.current_char
        if c and c != "\n":
            buff.insert_text(c.swapcase(), overwrite=True)


@add_cmd(
    keys=["`"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-to-lowercase",
)
def helix_to_lowercase(event: KeyPressEvent) -> None:
    """Convert every selection to lowercase."""
    buff = event.current_buffer
    if _transform_selections(event, str.lower, keep_selection=False):
        return
    if buff.selection_state:
        for start, end in buff.document.selection_ranges():
            buff.transform_region(start, end, lambda s: s.lower())
        buff.exit_selection()


@add_cmd(
    keys=["A-`"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-to-uppercase",
)
def helix_to_uppercase(event: KeyPressEvent) -> None:
    """Convert every selection to uppercase."""
    buff = event.current_buffer
    if _transform_selections(event, str.upper, keep_selection=False):
        return
    if buff.selection_state:
        for start, end in buff.document.selection_ranges():
            buff.transform_region(start, end, lambda s: s.upper())
        buff.exit_selection()


# Yank and paste


@add_cmd(
    keys=["y"],
    filter=(helix_normal_mode | helix_select_mode) & has_selection,
    hidden=True,
    name="helix-yank",
)
def helix_yank(event: KeyPressEvent) -> None:
    """Yank every selection, joining them with newlines."""
    buff = event.current_buffer
    ranges = get_selections(buff)

    if len(ranges) > 1:
        store_clipboard_data(
            event, ClipboardData("\n".join(text_at_ranges(buff.text, ranges)))
        )
        return

    # Save selection state since copy_selection clears it
    selection_state = buff.selection_state
    data = buff.copy_selection()
    store_clipboard_data(event, data)
    # Restore selection state to maintain the selection
    buff.selection_state = selection_state


@add_cmd(
    keys=["y"],
    filter=helix_normal_mode & ~has_selection,
    hidden=True,
    name="helix-yank-line",
)
def helix_yank_line(event: KeyPressEvent) -> None:
    """Yank current line."""
    buff = event.current_buffer
    text = "\n".join(buff.document.lines_from_current[: event.arg])
    store_clipboard_data(event, ClipboardData(text, SelectionType.LINES))


def _paste_across_selections(
    event: KeyPressEvent, data: ClipboardData, *, before: bool
) -> bool:
    """Paste into every selection, distributing the clipboard line-wise.

    When the clipboard holds one line per selection, each selection receives its
    own line - this is how a multi-selection yank round-trips. Otherwise the whole
    clipboard is pasted at every selection.

    Args:
        event: The triggering key-press event.
        data: The clipboard contents to paste.
        before: Insert at the start of each selection rather than after its end.

    Returns:
        True if a multi-selection paste was applied, False when there are fewer
        than two selections and the caller should handle the single case.
    """
    buff = event.current_buffer
    ranges = get_selections(buff)
    if len(ranges) < 2:
        return False

    lines = data.text.split("\n")
    if len(lines) == len(ranges):
        replacements = [line * event.arg for line in lines]
    else:
        replacements = [data.text * event.arg] * len(ranges)

    # Paste alongside each selection rather than replacing it, by collapsing each
    # range to a zero-width point at the chosen edge.
    ordered = sorted(min(r) if before else max(r) for r in ranges)
    points = [(position, position) for position in ordered]

    set_selections(buff, apply_edit_at_ranges(buff, points, replacements))
    return True


@add_cmd(
    keys=["p"],
    filter=helix_normal_mode,
    hidden=True,
    name="helix-paste-after",
)
def helix_paste_after(event: KeyPressEvent) -> None:
    """Paste after every selection."""
    buff = event.current_buffer
    data = fetch_clipboard_data(event)
    if _paste_across_selections(event, data, before=False):
        return
    pasted_text = data.text * event.arg
    if data.type == SelectionType.LINES:
        # Line paste: insert on new line below current line
        end_of_line = buff.cursor_position + buff.document.get_end_of_line_position()
        buff.cursor_position = end_of_line
        insert_text = "\n" + pasted_text
        paste_start = buff.cursor_position + 1
        buff.insert_text(insert_text)
        # Cursor is now at end of pasted text; select from start of paste
        buff.selection_state = SelectionState(paste_start, SelectionType.LINES)
    else:
        # Character paste: insert after cursor
        paste_start = buff.cursor_position + 1
        buff.cursor_position += buff.document.get_cursor_right_position()
        buff.insert_text(pasted_text)
        # Cursor is now at end of pasted text; select from start of paste
        buff.selection_state = SelectionState(paste_start, SelectionType.CHARACTERS)


@add_cmd(
    keys=["P"],
    filter=helix_normal_mode,
    hidden=True,
    name="helix-paste-before",
)
def helix_paste_before(event: KeyPressEvent) -> None:
    """Paste before every selection."""
    buff = event.current_buffer
    data = fetch_clipboard_data(event)
    if _paste_across_selections(event, data, before=True):
        return
    pasted_text = data.text * event.arg
    if data.type == SelectionType.LINES:
        # Line paste: insert on new line above current line
        start_of_line = (
            buff.cursor_position + buff.document.get_start_of_line_position()
        )
        buff.cursor_position = start_of_line
        paste_start = buff.cursor_position
        buff.insert_text(pasted_text + "\n")
        # Cursor is after the inserted newline; move back to end of pasted text
        buff.cursor_position -= 1
        buff.selection_state = SelectionState(paste_start, SelectionType.LINES)
    else:
        # Character paste: insert before cursor
        paste_start = buff.cursor_position
        buff.insert_text(pasted_text)
        # Cursor is now at end of pasted text; select from start of paste
        buff.selection_state = SelectionState(paste_start, SelectionType.CHARACTERS)


# Undo/redo


@add_cmd(
    keys=["u"],
    filter=helix_normal_mode,
    hidden=True,
    save_before=(lambda e: False),
    name="helix-undo",
)
def helix_undo(event: KeyPressEvent) -> None:
    """Undo."""
    for _ in range(event.arg):
        event.current_buffer.undo()


@add_cmd(
    keys=["U"],
    filter=helix_normal_mode,
    hidden=True,
    save_before=(lambda e: False),
    name="helix-redo",
)
def helix_redo(event: KeyPressEvent) -> None:
    """Redo."""
    for _ in range(event.arg):
        event.current_buffer.redo()


# Indentation


@add_cmd(
    keys=[">"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-indent",
)
def helix_indent(event: KeyPressEvent) -> None:
    """Indent selection."""
    buff = event.current_buffer
    doc = buff.document
    if buff.selection_state:
        start, end = (
            doc.translate_index_to_position(x)[0] for x in doc.selection_range()
        )
    else:
        start = end = doc.cursor_position_row
    indent(buff, start, end + 1, count=event.arg)


@add_cmd(
    keys=["<"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-unindent",
)
def helix_unindent(event: KeyPressEvent) -> None:
    """Unindent selection."""
    buff = event.current_buffer
    doc = buff.document
    if buff.selection_state:
        start, end = (
            doc.translate_index_to_position(x)[0] for x in doc.selection_range()
        )
    else:
        start = end = doc.cursor_position_row
    unindent(buff, start, end + 1, count=event.arg)


# Selection manipulation


@add_cmd(
    keys=[";"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-collapse-selection",
)
def helix_collapse_selection(event: KeyPressEvent) -> None:
    """Collapse selection to cursor."""
    event.app.helix_state.select_mode = False
    event.current_buffer.exit_selection()


@add_cmd(
    keys=["A-;"],
    filter=(helix_normal_mode | helix_select_mode) & has_selection,
    hidden=True,
    name="helix-flip-selection",
)
def helix_flip_selection(event: KeyPressEvent) -> None:
    """Flip selection cursor and anchor."""
    buff = event.current_buffer
    if buff.selection_state:
        anchor = buff.selection_state.original_cursor_position
        cursor = buff.cursor_position
        buff.cursor_position = anchor
        buff.selection_state.original_cursor_position = cursor


@add_cmd(
    keys=["%"],
    filter=helix_normal_mode,
    hidden=True,
    name="helix-select-all",
)
def helix_select_all(event: KeyPressEvent) -> None:
    """Select entire file."""
    buff = event.current_buffer
    event.app.helix_state.select_mode = True
    buff.cursor_position = 0
    buff.start_selection()
    buff.cursor_position = len(buff.text)


# Join lines


@add_cmd(
    keys=["J"],
    filter=(helix_normal_mode | helix_select_mode) & ~is_read_only,
    hidden=True,
    name="helix-join-lines",
)
def helix_join_lines(event: KeyPressEvent) -> None:
    """Join lines."""
    buff = event.current_buffer
    if buff.selection_state:
        buff.join_selected_lines()
        buff.exit_selection()
    else:
        for _ in range(event.arg):
            buff.join_next_line()


# Goto mode


@add_cmd(
    keys=["g"],
    filter=helix_normal_mode & ~helix_goto_mode,
    hidden=True,
    name="helix-enter-goto-mode",
)
def helix_enter_goto_mode(event: KeyPressEvent) -> None:
    """Enter goto mode."""
    event.app.helix_state.goto_mode = True


@add_cmd(
    keys=["g"],
    filter=helix_goto_mode,
    hidden=True,
    name="helix-goto-file-start",
)
def helix_goto_file_start(event: KeyPressEvent) -> None:
    """Go to start of file or line number."""
    _prepare_movement(event)
    _exit_helix_submodes()
    buff = event.current_buffer
    if event.arg != 1 or has_arg():
        # Go to specific line
        buff.cursor_position = buff.document.translate_row_col_to_index(
            event.arg - 1, 0
        )
    else:
        buff.cursor_position = 0


@add_cmd(
    keys=["e"],
    filter=helix_goto_mode,
    hidden=True,
    name="helix-goto-file-end",
)
def helix_goto_file_end(event: KeyPressEvent) -> None:
    """Go to end of file."""
    _prepare_movement(event)
    _exit_helix_submodes()
    buff = event.current_buffer
    buff.cursor_position = len(buff.text)


@add_cmd(
    keys=["h"],
    filter=helix_goto_mode,
    hidden=True,
    name="helix-goto-line-start",
)
def helix_goto_line_start(event: KeyPressEvent) -> None:
    """Go to start of line."""
    _prepare_movement(event)
    _exit_helix_submodes()
    buff = event.current_buffer
    buff.cursor_position += buff.document.get_start_of_line_position()


@add_cmd(
    keys=["l"],
    filter=helix_goto_mode,
    hidden=True,
    name="helix-goto-line-end",
)
def helix_goto_line_end(event: KeyPressEvent) -> None:
    """Go to end of line."""
    _prepare_movement(event)
    _exit_helix_submodes()
    buff = event.current_buffer
    buff.cursor_position += buff.document.get_end_of_line_position()


@add_cmd(
    keys=["s"],
    filter=helix_goto_mode,
    hidden=True,
    name="helix-goto-first-nonwhitespace",
)
def helix_goto_first_nonwhitespace(event: KeyPressEvent) -> None:
    """Go to first non-whitespace character."""
    _prepare_movement(event)
    _exit_helix_submodes()
    buff = event.current_buffer
    buff.cursor_position += buff.document.get_start_of_line_position(
        after_whitespace=True
    )


@add_cmd(
    keys=["t"],
    filter=helix_goto_mode,
    hidden=True,
    name="helix-goto-window-top",
)
def helix_goto_window_top(event: KeyPressEvent) -> None:
    """Go to top of window."""
    _prepare_movement(event)
    _exit_helix_submodes()
    w = event.app.layout.current_window
    buff = event.current_buffer
    if w and w.render_info:
        buff.cursor_position = buff.document.translate_row_col_to_index(
            w.render_info.first_visible_line(after_scroll_offset=True), 0
        )


@add_cmd(
    keys=["c"],
    filter=helix_goto_mode,
    hidden=True,
    name="helix-goto-window-center",
)
def helix_goto_window_center(event: KeyPressEvent) -> None:
    """Go to center of window."""
    _prepare_movement(event)
    _exit_helix_submodes()
    w = event.app.layout.current_window
    buff = event.current_buffer
    if w and w.render_info:
        buff.cursor_position = buff.document.translate_row_col_to_index(
            w.render_info.center_visible_line(), 0
        )


@add_cmd(
    keys=["b"],
    filter=helix_goto_mode,
    hidden=True,
    name="helix-goto-window-bottom",
)
def helix_goto_window_bottom(event: KeyPressEvent) -> None:
    """Go to bottom of window."""
    _prepare_movement(event)
    _exit_helix_submodes()
    w = event.app.layout.current_window
    buff = event.current_buffer
    if w and w.render_info:
        buff.cursor_position = buff.document.translate_row_col_to_index(
            w.render_info.last_visible_line(before_scroll_offset=True), 0
        )


@add_cmd(
    keys=["escape"],
    filter=helix_goto_mode,
    hidden=True,
    name="helix-exit-goto-mode",
)
def helix_exit_goto_mode(event: KeyPressEvent) -> None:
    """Exit goto mode."""
    _exit_helix_submodes()


# Match mode


@add_cmd(
    keys=["m"],
    filter=helix_normal_mode & ~helix_match_mode,
    hidden=True,
    name="helix-enter-match-mode",
)
def helix_enter_match_mode(event: KeyPressEvent) -> None:
    """Enter match mode."""
    event.app.helix_state.match_mode = True


@add_cmd(
    keys=["m"],
    filter=helix_match_mode,
    hidden=True,
    name="helix-goto-matching-bracket",
)
def helix_goto_matching_bracket(event: KeyPressEvent) -> None:
    """Go to matching bracket."""
    _prepare_movement(event)
    _exit_helix_submodes()
    buff = event.current_buffer
    match = buff.document.find_matching_bracket_position()
    if match:
        buff.cursor_position += match


@add_cmd(
    keys=["escape"],
    filter=helix_match_mode,
    hidden=True,
    name="helix-exit-match-mode",
)
def helix_exit_match_mode(event: KeyPressEvent) -> None:
    """Exit match mode."""
    _exit_helix_submodes()


# Match-mode text objects, surround and case-insensitive pairs


@Condition
def waiting_for_text_object() -> bool:
    """Check whether a text-object key is awaited after ``mi`` or ``ma``."""
    if not helix_mode():
        return False
    return get_app().helix_state.pending_text_object is not None


@Condition
def waiting_for_surround() -> bool:
    """Check whether a surround character is awaited after ``ms``, ``md`` or ``mr``."""
    if not helix_mode():
        return False
    return get_app().helix_state.pending_surround is not None


@add_cmd(
    keys=["i"],
    filter=helix_match_mode & ~waiting_for_text_object,
    hidden=True,
    name="helix-match-inside",
)
def helix_match_inside(event: KeyPressEvent) -> None:
    """Await a text object to select inside."""
    event.app.helix_state.pending_text_object = "inside"


@add_cmd(
    keys=["a"],
    filter=helix_match_mode & ~waiting_for_text_object,
    hidden=True,
    name="helix-match-around",
)
def helix_match_around(event: KeyPressEvent) -> None:
    """Await a text object to select around."""
    event.app.helix_state.pending_text_object = "around"


@add_cmd(
    keys=["<any>"],
    filter=helix_match_mode & waiting_for_text_object,
    hidden=True,
    eager=True,
    name="helix-handle-text-object",
)
def helix_handle_text_object(event: KeyPressEvent) -> None:
    """Select the text object named by the key press."""
    helix_state = event.app.helix_state
    around = helix_state.pending_text_object == "around"
    helix_state.pending_text_object = None
    _exit_helix_submodes()

    buff = event.current_buffer
    ranges = [
        found
        for anchor, head in get_selections(buff)
        if (
            found := resolve_text_object(
                buff.text,
                head if head == anchor else max(anchor, head) - 1,
                event.data,
                around=around,
            )
        )
        is not None
    ]
    if ranges:
        set_selections(buff, ranges)
    else:
        event.app.output.bell()


@add_cmd(
    keys=["s"],
    filter=helix_match_mode & ~waiting_for_surround,
    hidden=True,
    name="helix-surround-add",
)
def helix_surround_add(event: KeyPressEvent) -> None:
    """Await a character to surround the selection with."""
    event.app.helix_state.pending_surround = "add"


@add_cmd(
    keys=["d"],
    filter=helix_match_mode & ~waiting_for_surround,
    hidden=True,
    name="helix-surround-delete",
)
def helix_surround_delete(event: KeyPressEvent) -> None:
    """Await a character whose surrounding pair should be removed."""
    event.app.helix_state.pending_surround = "delete"


@add_cmd(
    keys=["r"],
    filter=helix_match_mode & ~waiting_for_surround,
    hidden=True,
    name="helix-surround-replace",
)
def helix_surround_replace(event: KeyPressEvent) -> None:
    """Await the character whose surrounding pair should be replaced."""
    event.app.helix_state.pending_surround = "replace-from"


@add_cmd(
    keys=["<any>"],
    filter=helix_match_mode & waiting_for_surround,
    hidden=True,
    eager=True,
    name="helix-handle-surround",
)
def helix_handle_surround(event: KeyPressEvent) -> None:
    """Apply a pending surround operation using the key press as its character."""
    helix_state = event.app.helix_state
    operation = helix_state.pending_surround
    char = event.data
    buff = event.current_buffer

    if operation == "replace-from":
        # The first character names the pair to replace; wait for the replacement.
        helix_state.pending_surround = f"replace-to:{char}"
        return

    helix_state.pending_surround = None
    _exit_helix_submodes()

    if operation == "add":
        _surround_add(event, buff, char)
    elif operation == "delete":
        _surround_delete(event, buff, char)
    elif operation is not None and operation.startswith("replace-to:"):
        _surround_replace(event, buff, operation.removeprefix("replace-to:"), char)


def _surround_pair(char: str) -> tuple[str, str]:
    """Return the opening and closing characters for a surround key.

    Args:
        char: The key naming the pair.

    Returns:
        The opening and closing characters, which are equal for quotes.
    """
    if char in BRACKET_PAIRS:
        return BRACKET_PAIRS[char]
    return (char, char)


def _surround_add(event: KeyPressEvent, buff: Buffer, char: str) -> None:
    """Wrap the primary selection in a pair of characters.

    Args:
        event: The triggering key-press event.
        buff: The buffer to edit.
        char: The key naming the pair.
    """
    opening, closing = _surround_pair(char)
    anchor, head = get_selections(buff)[0]
    start, end = (anchor, head) if anchor <= head else (head, anchor)
    if start == end:
        event.app.output.bell()
        return

    buff.save_to_undo_stack()
    buff.text = (
        buff.text[:start] + opening + buff.text[start:end] + closing + buff.text[end:]
    )
    buff.cursor_position = end + 1
    set_selections(buff, [(start + 1, end + 1)])


def _surround_delete(event: KeyPressEvent, buff: Buffer, char: str) -> None:
    """Remove the pair of characters surrounding the cursor.

    Args:
        event: The triggering key-press event.
        buff: The buffer to edit.
        char: The key naming the pair.
    """
    found = resolve_text_object(buff.text, buff.cursor_position, char, around=True)
    if found is None:
        event.app.output.bell()
        return
    start, end = found

    buff.save_to_undo_stack()
    buff.text = buff.text[:start] + buff.text[start + 1 : end - 1] + buff.text[end:]
    buff.cursor_position = min(buff.cursor_position, len(buff.text))
    set_selections(buff, [(start, max(start, end - 2))])


def _surround_replace(
    event: KeyPressEvent, buff: Buffer, from_char: str, to_char: str
) -> None:
    """Replace the pair of characters surrounding the cursor with another pair.

    Args:
        event: The triggering key-press event.
        buff: The buffer to edit.
        from_char: The key naming the existing pair.
        to_char: The key naming the replacement pair.
    """
    found = resolve_text_object(buff.text, buff.cursor_position, from_char, around=True)
    if found is None:
        event.app.output.bell()
        return
    start, end = found
    opening, closing = _surround_pair(to_char)

    buff.save_to_undo_stack()
    buff.text = (
        buff.text[:start]
        + opening
        + buff.text[start + 1 : end - 1]
        + closing
        + buff.text[end:]
    )
    buff.cursor_position = min(buff.cursor_position, len(buff.text))
    set_selections(buff, [(start, end)])


# Increment and decrement


def _adjust_number(event: KeyPressEvent, delta: int) -> None:
    """Add to the number at or after the cursor.

    Args:
        event: The triggering key-press event.
        delta: The amount to add, which may be negative.
    """
    buff = event.current_buffer
    text = buff.text
    cursor = buff.cursor_position

    # Expand outwards from the cursor over digits, then look forwards on the line.
    start = cursor
    while start > 0 and text[start - 1].isdigit():
        start -= 1
    end = start
    while end < len(text) and text[end].isdigit():
        end += 1

    if start == end:
        match = re.compile(r"-?\d+").search(text, cursor)
        if match is None or "\n" in text[cursor : match.start()]:
            event.app.output.bell()
            return
        start, end = match.span()
    elif start > 0 and text[start - 1] == "-":
        start -= 1

    value = int(text[start:end]) + delta * event.arg
    replacement = str(value)

    buff.save_to_undo_stack()
    buff.text = text[:start] + replacement + text[end:]
    buff.cursor_position = start + len(replacement) - 1


@add_cmd(
    keys=["c-a"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-increment",
)
def helix_increment(event: KeyPressEvent) -> None:
    """Increment the number at or after the cursor."""
    _adjust_number(event, 1)


@add_cmd(
    keys=["c-x"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-decrement",
)
def helix_decrement(event: KeyPressEvent) -> None:
    """Decrement the number at or after the cursor."""
    _adjust_number(event, -1)


# View mode


@add_cmd(
    keys=["z"],
    filter=helix_normal_mode & ~helix_view_mode,
    hidden=True,
    name="helix-enter-view-mode",
)
def helix_enter_view_mode(event: KeyPressEvent) -> None:
    """Enter view mode."""
    event.app.helix_state.view_mode = True


@add_cmd(
    keys=["z", "c"],
    filter=helix_view_mode,
    hidden=True,
    name="helix-view-center",
    eager=True,
)
def helix_view_center(event: KeyPressEvent) -> None:
    """Center view on cursor."""
    _exit_helix_submodes()
    w = event.app.layout.current_window
    buff = event.current_buffer
    if w and w.render_info:
        scroll_height = w.render_info.window_height // 2
        y = max(0, buff.document.cursor_position_row - scroll_height)
        w.vertical_scroll = y


@add_cmd(
    keys=["t"],
    filter=helix_view_mode,
    hidden=True,
    name="helix-view-top",
)
def helix_view_top(event: KeyPressEvent) -> None:
    """Align view to top."""
    _exit_helix_submodes()
    w = event.app.layout.current_window
    buff = event.current_buffer
    if w:
        w.vertical_scroll = buff.document.cursor_position_row


@add_cmd(
    keys=["b"],
    filter=helix_view_mode,
    hidden=True,
    name="helix-view-bottom",
)
def helix_view_bottom(event: KeyPressEvent) -> None:
    """Align view to bottom."""
    _exit_helix_submodes()
    w = event.app.layout.current_window
    buff = event.current_buffer
    if w and w.render_info:
        cursor_row = buff.document.cursor_position_row
        w.vertical_scroll = max(0, cursor_row - w.render_info.window_height + 1)


@add_cmd(
    keys=["j", "down"],
    filter=helix_view_mode,
    hidden=True,
    name="helix-scroll-down",
)
def helix_scroll_down(event: KeyPressEvent) -> None:
    """Scroll down."""
    w = event.app.layout.current_window
    if w:
        w.vertical_scroll += event.arg


@add_cmd(
    keys=["k", "up"],
    filter=helix_view_mode,
    hidden=True,
    name="helix-scroll-up",
)
def helix_scroll_up(event: KeyPressEvent) -> None:
    """Scroll up."""
    w = event.app.layout.current_window
    if w:
        w.vertical_scroll = max(0, w.vertical_scroll - event.arg)


@add_cmd(
    keys=["c-f", "pagedown"],
    filter=helix_view_mode | helix_normal_mode,
    hidden=True,
    name="helix-page-down",
)
def helix_page_down(event: KeyPressEvent) -> None:
    """Page down."""
    _prepare_movement(event)
    _exit_helix_submodes()
    w = event.app.layout.current_window
    buff = event.current_buffer
    if w and w.render_info:
        buff.cursor_position = buff.document.translate_row_col_to_index(
            min(
                buff.document.cursor_position_row + w.render_info.window_height,
                buff.document.line_count - 1,
            ),
            buff.document.cursor_position_col,
        )


@add_cmd(
    keys=["c-b", "pageup"],
    filter=helix_view_mode | helix_normal_mode,
    hidden=True,
    name="helix-page-up",
)
def helix_page_up(event: KeyPressEvent) -> None:
    """Page up."""
    _prepare_movement(event)
    _exit_helix_submodes()
    w = event.app.layout.current_window
    buff = event.current_buffer
    if w and w.render_info:
        buff.cursor_position = buff.document.translate_row_col_to_index(
            max(buff.document.cursor_position_row - w.render_info.window_height, 0),
            buff.document.cursor_position_col,
        )


@add_cmd(
    keys=["c-u"],
    filter=helix_view_mode | helix_normal_mode,
    hidden=True,
    name="helix-half-page-up",
)
def helix_half_page_up(event: KeyPressEvent) -> None:
    """Half page up."""
    _prepare_movement(event)
    _exit_helix_submodes()
    w = event.app.layout.current_window
    buff = event.current_buffer
    if w and w.render_info:
        half = w.render_info.window_height // 2
        buff.cursor_position = buff.document.translate_row_col_to_index(
            max(buff.document.cursor_position_row - half, 0),
            buff.document.cursor_position_col,
        )


@add_cmd(
    keys=["c-d"],
    filter=helix_view_mode | helix_normal_mode,
    hidden=True,
    name="helix-half-page-down",
)
def helix_half_page_down(event: KeyPressEvent) -> None:
    """Half page down."""
    _prepare_movement(event)
    _exit_helix_submodes()
    w = event.app.layout.current_window
    buff = event.current_buffer
    if w and w.render_info:
        half = w.render_info.window_height // 2
        buff.cursor_position = buff.document.translate_row_col_to_index(
            min(
                buff.document.cursor_position_row + half,
                buff.document.line_count - 1,
            ),
            buff.document.cursor_position_col,
        )


@add_cmd(
    keys=["escape"],
    filter=helix_view_mode,
    hidden=True,
    name="helix-exit-view-mode",
)
def helix_exit_view_mode(event: KeyPressEvent) -> None:
    """Exit view mode."""
    _exit_helix_submodes()


# Space and window sub-modes
#
# Only the mode transitions live here. The actions reached through these modes -
# file and buffer pickers, window splitting - are application concerns, so
# applications register their own ``helix-space-*`` and ``helix-window-*``
# commands under the ``helix_space_mode`` and ``helix_window_mode`` filters.
# Those are picked up automatically by ``load_helix_bindings``.


@add_cmd(
    keys=["space"],
    filter=helix_normal_mode & ~helix_space_mode,
    hidden=True,
    name="helix-enter-space-mode",
)
def helix_enter_space_mode(event: KeyPressEvent) -> None:
    """Enter the space sub-mode, from which pickers and actions are reached."""
    event.app.helix_state.space_mode = True


@add_cmd(
    keys=["escape"],
    filter=helix_space_mode,
    hidden=True,
    name="helix-exit-space-mode",
)
def helix_exit_space_mode(event: KeyPressEvent) -> None:
    """Leave the space sub-mode."""
    _exit_helix_submodes()


@add_cmd(
    keys=["c-w"],
    filter=(helix_normal_mode | helix_select_mode) & ~helix_window_mode,
    hidden=True,
    name="helix-enter-window-mode",
)
def helix_enter_window_mode(event: KeyPressEvent) -> None:
    """Enter the window sub-mode, from which window actions are reached."""
    event.app.helix_state.window_mode = True


@add_cmd(
    keys=["escape"],
    filter=helix_window_mode,
    hidden=True,
    name="helix-exit-window-mode",
)
def helix_exit_window_mode(event: KeyPressEvent) -> None:
    """Leave the window sub-mode."""
    _exit_helix_submodes()


# Search


@add_cmd(
    keys=["/"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-search-forward",
)
def helix_search_forward(event: KeyPressEvent) -> None:
    """Search forward."""
    from apptk.search import SearchDirection, start_global_search

    start_global_search(direction=SearchDirection.FORWARD)


@add_cmd(
    keys=["?"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-search-backward",
)
def helix_search_backward(event: KeyPressEvent) -> None:
    """Search backward."""
    from apptk.search import SearchDirection, start_global_search

    start_global_search(direction=SearchDirection.BACKWARD)


@add_cmd(
    keys=["n"],
    filter=helix_normal_mode,
    hidden=True,
    name="helix-search-next",
)
def helix_search_next(event: KeyPressEvent) -> None:
    """Select next search match."""
    from apptk.search import SearchDirection, find_next_match

    find_next_match(SearchDirection.FORWARD)


@add_cmd(
    keys=["N"],
    filter=helix_normal_mode,
    hidden=True,
    name="helix-search-prev",
)
def helix_search_prev(event: KeyPressEvent) -> None:
    """Select previous search match."""
    from apptk.search import SearchDirection, find_next_match

    find_next_match(SearchDirection.BACKWARD)


@add_cmd(
    keys=["enter"],
    filter=helix_mode & is_searching,
    hidden=True,
    name="helix-accept-search",
)
def helix_accept_search(event: KeyPressEvent) -> None:
    """Accept the search input, or apply a pending regex operation."""
    from apptk.search import accept_global_search, stop_global_search

    helix_state = event.app.helix_state
    if helix_state.pending_regex_op is not None:
        # ``s`` and ``S`` borrow the search prompt, so intercept the accept and
        # apply the selection operation rather than performing a search.
        pattern = event.current_buffer.text
        layout = event.app.layout
        target = layout.search_target_buffer_control
        stop_global_search()
        if target is not None:
            apply_pending_regex(target.buffer, pattern)
        return

    accept_global_search()


@add_cmd(
    keys=["escape"],
    filter=helix_mode & is_searching,
    hidden=True,
    name="helix-stop-search",
)
def helix_stop_search(event: KeyPressEvent) -> None:
    """Abort the search, discarding any pending regex operation."""
    from apptk.search import stop_global_search

    helix_state = event.app.helix_state
    helix_state.pending_regex_op = None
    helix_state.pending_regex_ranges = []
    stop_global_search()


@add_cmd(
    keys=["*"],
    filter=helix_normal_mode,
    hidden=True,
    name="helix-search-selection",
)
def helix_search_selection(event: KeyPressEvent) -> None:
    """Use current selection as search pattern."""
    buff = event.current_buffer
    search_state = event.app.current_search_state
    search_state.text = buff.document.get_word_under_cursor()


# Numeric arguments


def _create_arg_handler(digit: str) -> None:
    """Create a handler for a numeric argument digit."""

    @add_cmd(
        keys=[digit],
        filter=helix_normal_mode | helix_select_mode,
        hidden=True,
        name=f"helix-arg-{digit}",
    )
    def _arg(event: KeyPressEvent) -> None:
        """Handle numeric argument."""
        event.append_to_arg_count(event.data)


for n in "123456789":
    _create_arg_handler(n)


@add_cmd(
    keys=["0"],
    filter=(helix_normal_mode | helix_select_mode) & has_arg,
    hidden=True,
    name="helix-arg-0",
)
def helix_arg_0(event: KeyPressEvent) -> None:
    """Handle zero in numeric argument."""
    event.append_to_arg_count(event.data)


@add_cmd(
    keys=["home"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-home",
)
def helix_home(event: KeyPressEvent) -> None:
    """Move to start of line."""
    _prepare_movement(event)
    buff = event.current_buffer
    buff.cursor_position += buff.document.get_start_of_line_position()


@add_cmd(
    keys=["end"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-end",
)
def helix_end(event: KeyPressEvent) -> None:
    """Move to end of line."""
    _prepare_movement(event)
    buff = event.current_buffer
    buff.cursor_position += buff.document.get_end_of_line_position()


@add_cmd(
    keys=["G"],
    filter=(helix_normal_mode | helix_select_mode) & has_arg,
    hidden=True,
    name="helix-goto-line",
)
def helix_goto_line(event: KeyPressEvent) -> None:
    """Go to line number."""
    _prepare_movement(event)
    buff = event.current_buffer
    buff.cursor_position = buff.document.translate_row_col_to_index(event.arg - 1, 0)


@add_cmd(
    keys=["|"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-goto-column",
)
def helix_goto_column(event: KeyPressEvent) -> None:
    """Go to column number."""
    _prepare_movement(event)
    buff = event.current_buffer
    col = (event.arg or 1) - 1
    buff.cursor_position += buff.document.get_column_cursor_position(col)


# Unimpaired-style bindings


@add_cmd(
    keys=[("]", "space")],
    filter=helix_normal_mode,
    hidden=True,
    name="helix-add-newline-below",
)
def helix_add_newline_below(event: KeyPressEvent) -> None:
    """Add newline below current line."""
    buff = event.current_buffer
    doc = buff.document
    cursor_pos = buff.cursor_position
    end_of_line = cursor_pos + doc.get_end_of_line_position()
    buff.cursor_position = end_of_line
    buff.insert_text("\n")
    buff.cursor_position = cursor_pos


@add_cmd(
    keys=[("[", "space")],
    filter=helix_normal_mode,
    hidden=True,
    name="helix-add-newline-above",
)
def helix_add_newline_above(event: KeyPressEvent) -> None:
    """Add newline above current line."""
    buff = event.current_buffer
    doc = buff.document
    cursor_pos = buff.cursor_position
    start_of_line = cursor_pos + doc.get_start_of_line_position()
    buff.cursor_position = start_of_line
    buff.insert_text("\n")
    # Cursor shifts down by 1 due to inserted newline
    buff.cursor_position = cursor_pos + 1


@add_cmd(
    keys=["A-."],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-repeat-last-motion",
)
def helix_repeat_last_motion(event: KeyPressEvent) -> None:
    """Repeat last motion (f/F/t/T)."""
    app = event.app
    buff = event.current_buffer
    find = app.helix_state.last_character_find

    if find is None:
        return

    if event.app.helix_state.select_mode:
        if buff.selection_state is None:
            buff.start_selection(selection_type=SelectionType.CHARACTERS)
    else:
        if buff.selection_state is not None:
            buff.exit_selection()
        buff.start_selection(selection_type=SelectionType.CHARACTERS)

    if find.backwards:
        pos = buff.document.find_backwards(
            find.character, in_current_line=False, count=event.arg
        )
        if pos:
            buff.cursor_position += pos
    else:
        pos = buff.document.find(find.character, in_current_line=False, count=event.arg)
        if pos:
            buff.cursor_position += pos


def _copy_selection_to_adjacent_line(event: KeyPressEvent, *, below: bool) -> None:
    """Add a copy of the primary selection on the line above or below.

    Args:
        event: The triggering key-press event.
        below: Copy downwards when True, upwards otherwise.
    """
    buff = event.current_buffer
    helix_state = event.app.helix_state
    ranges = get_selections(buff)
    index = min(helix_state.primary_index, len(ranges) - 1)

    copied = copy_range_to_line(buff.text, ranges[index], below=below)
    if copied is None:
        event.app.output.bell()
        return

    new_ranges = [*ranges, copied]
    new_ranges.sort(key=lambda text_range: min(text_range))
    set_selections(buff, new_ranges, primary=new_ranges.index(copied))


def _start_regex_prompt(event: KeyPressEvent, operation: str) -> None:
    """Prompt for a regular expression to apply to the current selections.

    Reuses the search buffer rather than introducing a second prompt widget, so
    that focus handling stays in one place. The pending operation is recorded on
    the Helix state and applied when the prompt is accepted.

    Args:
        event: The triggering key-press event.
        operation: Either ``"select"`` or ``"split"``.
    """
    from apptk.search import SearchDirection, start_global_search

    helix_state = event.app.helix_state
    helix_state.pending_regex_op = operation
    helix_state.pending_regex_ranges = get_selections(event.current_buffer)
    start_global_search(direction=SearchDirection.FORWARD)


def apply_pending_regex(buff: Buffer, pattern: str) -> bool:
    """Apply a pending regex operation to the recorded selections.

    Args:
        buff: The buffer the operation applies to.
        pattern: The regular expression entered at the prompt.

    Returns:
        True if a pending operation was applied, False if there was none or the
        pattern was invalid.
    """
    helix_state = get_app().helix_state
    operation = helix_state.pending_regex_op
    if operation is None:
        return False

    ranges = helix_state.pending_regex_ranges or [(0, len(buff.text))]
    helix_state.pending_regex_op = None
    helix_state.pending_regex_ranges = []

    try:
        if operation == "select":
            new_ranges = select_regex_within(buff.text, ranges, pattern)
        else:
            new_ranges = split_on_regex(buff.text, ranges, pattern)
    except re.error:
        get_app().output.bell()
        return False

    if new_ranges:
        set_selections(buff, new_ranges)
    return True


@add_cmd(
    keys=["s"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-select-regex",
)
def helix_select_regex(event: KeyPressEvent) -> None:
    """Select every regular-expression match inside the current selections."""
    _start_regex_prompt(event, "select")


@add_cmd(
    keys=["S"],
    filter=helix_select_mode,
    hidden=True,
    name="helix-split-selection",
)
def helix_split_selection(event: KeyPressEvent) -> None:
    """Split the current selections on regular-expression matches."""
    _start_regex_prompt(event, "split")


@add_cmd(
    keys=[","],
    filter=helix_select_mode,
    hidden=True,
    name="helix-keep-primary-selection",
)
def helix_keep_primary_selection(event: KeyPressEvent) -> None:
    """Keep only the primary selection."""
    buff = event.current_buffer
    helix_state = event.app.helix_state
    ranges = collapse_to_primary(get_selections(buff), helix_state.primary_index)
    set_selections(buff, ranges)


@add_cmd(
    keys=["A-,"],
    filter=helix_select_mode,
    hidden=True,
    name="helix-remove-primary-selection",
)
def helix_remove_primary_selection(event: KeyPressEvent) -> None:
    """Remove the primary selection, keeping the others."""
    buff = event.current_buffer
    helix_state = event.app.helix_state
    ranges = get_selections(buff)

    if len(ranges) <= 1:
        helix_state.select_mode = False
        set_selections(buff, [])
        return

    index = min(helix_state.primary_index, len(ranges) - 1)
    remaining = ranges[:index] + ranges[index + 1 :]
    set_selections(buff, remaining, primary=min(index, len(remaining) - 1))


@add_cmd(
    keys=["A-s"],
    filter=helix_select_mode,
    hidden=True,
    name="helix-split-selection-newlines",
)
def helix_split_selection_newlines(event: KeyPressEvent) -> None:
    """Split each selection on newlines, giving one selection per line."""
    buff = event.current_buffer
    ranges = split_on_newlines(buff.text, get_selections(buff))
    set_selections(buff, ranges)


@add_cmd(
    keys=["&"],
    filter=helix_select_mode,
    hidden=True,
    name="helix-align-selections",
)
def helix_align_selections(event: KeyPressEvent) -> None:
    """Align selections into a common column by inserting padding."""
    buff = event.current_buffer
    helix_state = event.app.helix_state
    ranges = get_selections(buff)
    if len(ranges) < 2:
        return

    aligned = align_ranges(buff.text, ranges)
    if aligned == buff.text:
        return

    # Insert-only edit applied as a single text assignment, so that it lands on
    # the undo stack as one step rather than one per selection. The ``text``
    # setter does not push onto the undo stack itself, so do that explicitly.
    helix_state._applying_multi_edit = True
    try:
        cursor = buff.cursor_position
        buff.save_to_undo_stack()
        buff.text = aligned
        buff.cursor_position = min(cursor, len(aligned))
    finally:
        helix_state._applying_multi_edit = False

    # Recompute the ranges against the padded text.
    set_selections(buff, select_regex_within(aligned, [(0, len(aligned))], r"\S+"))


@add_cmd(
    keys=["_"],
    filter=helix_select_mode,
    hidden=True,
    name="helix-trim-selections",
)
def helix_trim_selections(event: KeyPressEvent) -> None:
    """Trim leading and trailing whitespace from each selection."""
    buff = event.current_buffer
    trimmed = trim_ranges(buff.text, get_selections(buff))
    if trimmed:
        set_selections(buff, trimmed)


@add_cmd(
    keys=["C"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-copy-selection-below",
)
def helix_copy_selection_below(event: KeyPressEvent) -> None:
    """Add a further selection on the line below, in the same columns."""
    _copy_selection_to_adjacent_line(event, below=True)


@add_cmd(
    keys=["A-C"],
    filter=helix_normal_mode | helix_select_mode,
    hidden=True,
    name="helix-copy-selection-above",
)
def helix_copy_selection_above(event: KeyPressEvent) -> None:
    """Add a further selection on the line above, in the same columns."""
    _copy_selection_to_adjacent_line(event, below=False)


get_cmd("helix-toggle-comments").add_keys(
    keys=["c-c"],
    filter=helix_normal_mode | helix_select_mode,
)


@add_cmd(
    keys=["c-i"],
    filter=helix_normal_mode,
    hidden=True,
    name="helix-jump-forward",
)
def helix_jump_forward(event: KeyPressEvent) -> None:
    """Jump forward on the jumplist."""
    event.current_buffer.history_forward()


@add_cmd(
    keys=["c-o"],
    filter=helix_normal_mode,
    hidden=True,
    name="helix-jump-backward",
)
def helix_jump_backward(event: KeyPressEvent) -> None:
    """Jump backward on the jumplist."""
    event.current_buffer.history_backward()


@add_cmd(
    keys=["c-s"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-commit-undo",
)
def helix_commit_undo(event: KeyPressEvent) -> None:
    """Commit undo checkpoint."""
    # Create an undo boundary
    buff = event.current_buffer
    buff.save_to_undo_stack()


# Insert mode commands


@add_cmd(
    keys=["<any>"],
    filter=helix_insert_mode & ~is_read_only & buffer_has_focus,
    hidden=True,
    name="helix-self-insert",
)
def helix_self_insert(event: KeyPressEvent) -> None:
    """Insert character."""
    # Only insert printable characters
    data = event.data
    if data and len(data) == 1 and data.isprintable():
        event.current_buffer.insert_text(data, overwrite=False)


@Condition
def helix_replace_single_mode() -> bool:
    """Check if in Helix single-character replace mode."""
    if not helix_mode():
        return False
    app = get_app()
    return app.helix_state.input_mode == InputMode.REPLACE_SINGLE


@Condition
def helix_replace_continuous_mode() -> bool:
    """Check if in Helix continuous replace mode, excluding single-character replace.

    ``helix_replace_mode`` covers both ``REPLACE`` and ``REPLACE_SINGLE``. The two
    ``<any>`` handlers below must stay disjoint, so this narrows to ``REPLACE`` only.
    """
    if not helix_mode():
        return False
    app = get_app()
    return app.helix_state.input_mode == InputMode.REPLACE


@add_cmd(
    keys=["<any>"],
    filter=helix_replace_continuous_mode & ~is_read_only & buffer_has_focus,
    hidden=True,
    name="helix-replace-insert",
)
def helix_replace_insert(event: KeyPressEvent) -> None:
    """Replace character."""
    data = event.data
    if data and len(data) == 1 and data.isprintable():
        event.current_buffer.insert_text(data, overwrite=True)


@add_cmd(
    keys=["<any>"],
    filter=helix_replace_single_mode & ~is_read_only & buffer_has_focus,
    hidden=True,
    name="helix-replace-single-char",
)
def helix_replace_single_char(event: KeyPressEvent) -> None:
    """Replace single character and return to normal mode."""
    data = event.data
    if data and len(data) == 1 and data.isprintable():
        event.current_buffer.insert_text(data, overwrite=True)
        event.app.helix_state.input_mode = InputMode.NAVIGATION


@add_cmd(
    keys=["enter", "c-j"],
    filter=helix_insert_mode & is_multiline,
    hidden=True,
    name="helix-newline",
)
def helix_newline(event: KeyPressEvent) -> None:
    """Insert newline."""
    event.current_buffer.newline(copy_margin=not in_paste_mode())


@add_cmd(
    keys=["enter"],
    filter=helix_insert_mode & is_returnable & ~is_multiline,
    hidden=True,
    name="helix-accept-line",
)
def helix_accept_line(event: KeyPressEvent) -> None:
    """Accept line."""
    event.current_buffer.validate_and_handle()


@add_cmd(
    keys=["backspace", "c-h"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-delete-backward",
)
def helix_delete_backward(event: KeyPressEvent) -> None:
    """Delete character backward."""
    event.current_buffer.delete_before_cursor(count=event.arg)


@add_cmd(
    keys=["delete", "c-d"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-delete-forward",
)
def helix_delete_forward(event: KeyPressEvent) -> None:
    """Delete character forward."""
    event.current_buffer.delete(count=event.arg)


@add_cmd(
    keys=["c-w", "A-backspace"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-delete-word-backward",
)
def helix_delete_word_backward(event: KeyPressEvent) -> None:
    """Delete word backward."""
    buff = event.current_buffer
    pos = buff.document.find_start_of_previous_word()
    if pos:
        buff.delete_before_cursor(count=-pos)


@add_cmd(
    keys=["A-d", "A-delete"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-delete-word-forward",
)
def helix_delete_word_forward(event: KeyPressEvent) -> None:
    """Delete word forward."""
    buff = event.current_buffer
    pos = buff.document.find_next_word_ending()
    if pos:
        buff.delete(count=pos)


@add_cmd(
    keys=["c-u"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-kill-to-line-start",
)
def helix_kill_to_line_start(event: KeyPressEvent) -> None:
    """Kill to start of line."""
    buff = event.current_buffer
    pos = buff.document.get_start_of_line_position()
    if pos:
        buff.delete_before_cursor(count=-pos)


@add_cmd(
    keys=["c-k"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-kill-to-line-end",
)
def helix_kill_to_line_end(event: KeyPressEvent) -> None:
    """Kill to end of line."""
    buff = event.current_buffer
    pos = buff.document.get_end_of_line_position()
    if pos:
        buff.delete(count=pos)


# Arrow keys in insert mode


@add_cmd(
    keys=["left"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-insert-left",
)
def helix_insert_left(event: KeyPressEvent) -> None:
    """Move left in insert mode."""
    buff = event.current_buffer
    buff.cursor_position = max(0, buff.cursor_position - event.arg)


@add_cmd(
    keys=["right"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-insert-right",
)
def helix_insert_right(event: KeyPressEvent) -> None:
    """Move right in insert mode."""
    buff = event.current_buffer
    buff.cursor_position = min(len(buff.text), buff.cursor_position + event.arg)


@add_cmd(
    keys=["up"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-insert-up",
)
def helix_insert_up(event: KeyPressEvent) -> None:
    """Move up in insert mode."""
    event.current_buffer.cursor_up()


@add_cmd(
    keys=["down"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-insert-down",
)
def helix_insert_down(event: KeyPressEvent) -> None:
    """Move down in insert mode."""
    event.current_buffer.cursor_down()


@add_cmd(
    keys=["home"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-insert-home",
)
def helix_insert_home(event: KeyPressEvent) -> None:
    """Move to start of line in insert mode."""
    buff = event.current_buffer
    buff.cursor_position += buff.document.get_start_of_line_position()


@add_cmd(
    keys=["end"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-insert-end",
)
def helix_insert_end(event: KeyPressEvent) -> None:
    """Move to end of line in insert mode."""
    buff = event.current_buffer
    buff.cursor_position += buff.document.get_end_of_line_position()


# Handle unbound keys in navigation mode (do nothing)


@add_cmd(
    keys=["<any>"],
    filter=(helix_normal_mode | helix_select_mode) & ~has_arg & ~waiting_for_char,
    hidden=True,
    name="helix-unbound-key",
)
def helix_unbound_key(event: KeyPressEvent) -> None:
    """Handle unbound keys in navigation mode - do nothing."""
    # Bell to indicate unbound key
    event.app.output.bell()


# Autocomplete trigger in insert mode


@add_cmd(
    keys=["c-x"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-autocomplete",
)
def helix_autocomplete(event: KeyPressEvent) -> None:
    """Trigger autocomplete."""
    buff = event.current_buffer
    buff.start_completion(select_first=False)


@add_cmd(
    keys=["c-r"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-insert-register",
)
def helix_insert_register(event: KeyPressEvent) -> None:
    """Insert register content."""
    # Wait for next key to determine which register
    # For now, insert from the default clipboard
    data = fetch_clipboard_data(event)
    event.current_buffer.insert_text(data.text)


# Completion in insert mode


@add_cmd(
    keys=["c-n"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-complete-next",
)
def helix_complete_next(event: KeyPressEvent) -> None:
    """Next completion."""
    buff = event.current_buffer
    if buff.complete_state:
        buff.complete_next()
    else:
        buff.start_completion(select_first=True)


@add_cmd(
    keys=["c-p"],
    filter=helix_insert_mode,
    hidden=True,
    name="helix-complete-prev",
)
def helix_complete_prev(event: KeyPressEvent) -> None:
    """Previous completion."""
    buff = event.current_buffer
    if buff.complete_state:
        buff.complete_previous()
    else:
        buff.start_completion(select_last=True)


HELIX_SEARCH_COMMANDS = (
    "helix-search-forward",
    "helix-search-backward",
    "helix-search-next",
    "helix-search-prev",
    "helix-search-selection",
    "helix-accept-search",
    "helix-stop-search",
)


def load_helix_bindings() -> KeyBindingsBase:
    """Load Helix key bindings.

    Every command named ``helix-*`` in the command registry is bound, so that
    adding a command with an ``@add_cmd`` decorator is sufficient to bind it -
    there is no separate list to keep in step.

    Returns:
        A KeyBindings object with Helix-style bindings.
    """
    kb = KeyBindings()

    # ``COMMANDS`` maps aliases to the same ``Command`` object, so bind by object
    # identity to avoid binding an aliased command more than once.
    seen: set[int] = set()
    for name, cmd in COMMANDS.items():
        if name.startswith("helix-") and id(cmd) not in seen:
            seen.add(id(cmd))
            cmd.bind(kb)

    return ConditionalKeyBindings(kb, helix_mode)


def load_helix_search_bindings() -> KeyBindingsBase:
    """Load Helix search key bindings.

    This is deliberately an explicit subset rather than a registry scan: only the
    search commands are wanted here, not every ``helix-*`` command.

    Returns:
        A KeyBindings object with Helix search bindings.
    """
    kb = KeyBindings()
    for name in HELIX_SEARCH_COMMANDS:
        get_cmd(name).bind(kb)
    return ConditionalKeyBindings(kb, helix_mode)
