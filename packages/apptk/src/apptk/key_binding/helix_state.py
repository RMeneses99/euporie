"""Helix editor state management."""

from __future__ import annotations

import logging
from enum import Enum

from apptk.key_binding.vi_state import CharacterFind as CharacterFind
from apptk.key_binding.vi_state import InputMode as InputMode
from apptk.key_binding.vi_state import ViState

__all__ = ["CharacterFind", "HelixMode", "HelixState", "InputMode"]

log = logging.getLogger(__name__)


class HelixMode(Enum):
    """Helix sub-modes for modal editing."""

    NORMAL = "normal"
    GOTO = "goto"
    MATCH = "match"
    VIEW = "view"
    WINDOW = "window"
    SPACE = "space"


class HelixState(ViState):
    """Mutable class to hold the state of Helix navigation.

    Extends ``ViState`` with Helix-specific sub-modes (goto, match, view,
    window, space) layered on top of the standard Vi input modes, and with
    support for multiple simultaneous selections.

    Attributes:
        mode: The current Helix sub-mode.
        waiting_for_char: Character command being waited for (f/F/t/T).
        select_mode: Whether explicit select mode is active (via ``v``).
        selections: Additional selection ranges, when more than one is active.
        primary_index: Index into ``selections`` of the primary selection.
    """

    def __init__(self) -> None:
        """Initialize Helix state."""
        super().__init__()

        # Helix-specific state
        self._mode: HelixMode = HelixMode.NORMAL
        self._waiting_for_char: str | None = None
        self._select_mode: bool = False

        # Multiple selections, as ``(anchor, head)`` pairs where ``head`` is the
        # cursor end. Deliberately empty while a single selection is active: in
        # that case ``buffer.selection_state`` remains the single source of truth,
        # so every pre-existing single-selection command keeps working untouched.
        self._selections: list[tuple[int, int]] = []
        self._primary_index: int = 0

        # Set while a multi-site edit is in progress, so that the invalidation
        # handler installed on the buffer does not discard the ranges that edit
        # is itself maintaining.
        self._applying_multi_edit: bool = False

        # A regex-prompt operation awaiting input: "select", "split" or None,
        # together with the ranges it should be applied to.
        self._pending_regex_op: str | None = None
        self._pending_regex_ranges: list[tuple[int, int]] = []

        # Register selected with ``"``, consumed by the next yank, paste or
        # delete. ``named_registers`` itself is inherited from ``ViState``.
        self._pending_register: str | None = None
        self._waiting_for_register: bool = False

        # Match-mode operations awaiting a following key: "inside"/"around" for
        # text objects, and "add"/"delete"/"replace-from"/"replace-to:<char>"
        # for surround.
        self._pending_text_object: str | None = None
        self._pending_surround: str | None = None

    @property
    def mode(self) -> HelixMode:
        """Get the current Helix sub-mode."""
        return self._mode

    @mode.setter
    def mode(self, value: HelixMode) -> None:
        """Set the current Helix sub-mode."""
        self._mode = value

    @property
    def waiting_for_char(self) -> str | None:
        """Get the character command being waited for."""
        return self._waiting_for_char

    @waiting_for_char.setter
    def waiting_for_char(self, value: str | None) -> None:
        """Set the character command being waited for."""
        self._waiting_for_char = value

    @property
    def goto_mode(self) -> bool:
        """Check if in goto mode."""
        return self._mode == HelixMode.GOTO

    @goto_mode.setter
    def goto_mode(self, value: bool) -> None:
        """Set goto mode."""
        if value:
            self._mode = HelixMode.GOTO
        elif self._mode == HelixMode.GOTO:
            self._mode = HelixMode.NORMAL

    @property
    def match_mode(self) -> bool:
        """Check if in match mode."""
        return self._mode == HelixMode.MATCH

    @match_mode.setter
    def match_mode(self, value: bool) -> None:
        """Set match mode."""
        if value:
            self._mode = HelixMode.MATCH
        elif self._mode == HelixMode.MATCH:
            self._mode = HelixMode.NORMAL

    @property
    def view_mode(self) -> bool:
        """Check if in view mode."""
        return self._mode == HelixMode.VIEW

    @view_mode.setter
    def view_mode(self, value: bool) -> None:
        """Set view mode."""
        if value:
            self._mode = HelixMode.VIEW
        elif self._mode == HelixMode.VIEW:
            self._mode = HelixMode.NORMAL

    @property
    def window_mode(self) -> bool:
        """Check if in window mode."""
        return self._mode == HelixMode.WINDOW

    @window_mode.setter
    def window_mode(self, value: bool) -> None:
        """Set window mode."""
        if value:
            self._mode = HelixMode.WINDOW
        elif self._mode == HelixMode.WINDOW:
            self._mode = HelixMode.NORMAL

    @property
    def space_mode(self) -> bool:
        """Check if in space mode."""
        return self._mode == HelixMode.SPACE

    @space_mode.setter
    def space_mode(self, value: bool) -> None:
        """Set space mode."""
        if value:
            self._mode = HelixMode.SPACE
        elif self._mode == HelixMode.SPACE:
            self._mode = HelixMode.NORMAL

    @property
    def select_mode(self) -> bool:
        """Check if explicitly in select mode (via ``v``)."""
        return self._select_mode

    @select_mode.setter
    def select_mode(self, value: bool) -> None:
        """Set explicit select mode."""
        self._select_mode = value

    @property
    def selections(self) -> list[tuple[int, int]]:
        """Get the additional selection ranges, empty unless several are active."""
        return self._selections

    @selections.setter
    def selections(self, value: list[tuple[int, int]]) -> None:
        """Set the additional selection ranges."""
        self._selections = value

    @property
    def primary_index(self) -> int:
        """Get the index of the primary selection within ``selections``."""
        return self._primary_index

    @primary_index.setter
    def primary_index(self, value: int) -> None:
        """Set the index of the primary selection."""
        self._primary_index = value

    @property
    def pending_regex_op(self) -> str | None:
        """Get the regex operation awaiting input, if any."""
        return self._pending_regex_op

    @pending_regex_op.setter
    def pending_regex_op(self, value: str | None) -> None:
        """Set the regex operation awaiting input."""
        self._pending_regex_op = value

    @property
    def pending_regex_ranges(self) -> list[tuple[int, int]]:
        """Get the ranges a pending regex operation should apply to."""
        return self._pending_regex_ranges

    @pending_regex_ranges.setter
    def pending_regex_ranges(self, value: list[tuple[int, int]]) -> None:
        """Set the ranges a pending regex operation should apply to."""
        self._pending_regex_ranges = value

    @property
    def pending_register(self) -> str | None:
        """Get the register selected for the next yank, paste or delete."""
        return self._pending_register

    @pending_register.setter
    def pending_register(self, value: str | None) -> None:
        """Set the register for the next yank, paste or delete."""
        self._pending_register = value

    @property
    def waiting_for_register(self) -> bool:
        """Check whether a register name is being awaited after ``"``."""
        return self._waiting_for_register

    @waiting_for_register.setter
    def waiting_for_register(self, value: bool) -> None:
        """Set whether a register name is being awaited."""
        self._waiting_for_register = value

    @property
    def pending_text_object(self) -> str | None:
        """Get the text-object operation awaiting a key, if any."""
        return self._pending_text_object

    @pending_text_object.setter
    def pending_text_object(self, value: str | None) -> None:
        """Set the text-object operation awaiting a key."""
        self._pending_text_object = value

    @property
    def pending_surround(self) -> str | None:
        """Get the surround operation awaiting a key, if any."""
        return self._pending_surround

    @pending_surround.setter
    def pending_surround(self, value: str | None) -> None:
        """Set the surround operation awaiting a key."""
        self._pending_surround = value

    def take_register(self) -> str | None:
        """Consume and return the pending register, if any.

        Returns:
            The register name, or None when no register was selected.
        """
        register, self._pending_register = self._pending_register, None
        return register

    def clear_selections(self) -> None:
        """Discard any additional selections, returning to a single selection."""
        self._selections = []
        self._primary_index = 0

    def reset(self) -> None:
        """Reset state, go back to INSERT mode."""
        super().reset()

        # Reset Helix-specific state.
        self._mode = HelixMode.NORMAL
        self._waiting_for_char = None
        self._select_mode = False
        self.clear_selections()
        self._applying_multi_edit = False
        self._pending_register = None
        self._waiting_for_register = False
        self._pending_text_object = None
        self._pending_surround = None

    def exit_submode(self) -> None:
        """Exit current sub-mode and return to normal."""
        self._mode = HelixMode.NORMAL
