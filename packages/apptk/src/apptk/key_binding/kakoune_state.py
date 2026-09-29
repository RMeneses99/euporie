"""Kakoune editor state management.

Kakoune's modal state is held **per buffer**, not per application. In a notebook
each cell owns its own :py:class:`~apptk.buffer.Buffer`, and a user editing several
cells expects each to remember its own mode, selections and marks - leaving one cell
in insert mode must not put every other cell into insert mode. State is therefore
looked up through :py:func:`get_state`, keyed weakly on the buffer so that a state
is collected along with the cell it belongs to.

This differs deliberately from :py:mod:`apptk.key_binding.helix_state`, whose single
``HelixState`` lives on the application.
"""

from __future__ import annotations

import logging
from enum import Enum
from typing import TYPE_CHECKING
from weakref import WeakKeyDictionary

from apptk.key_binding.vi_state import CharacterFind as CharacterFind
from apptk.key_binding.vi_state import InputMode as InputMode
from apptk.key_binding.vi_state import ViState

if TYPE_CHECKING:
    from apptk.buffer import Buffer

__all__ = [
    "CharacterFind",
    "InputMode",
    "KakouneMode",
    "KakouneState",
    "get_state",
]

log = logging.getLogger(__name__)


class KakouneMode(Enum):
    """Kakoune sub-modes.

    Kakoune has markedly fewer sub-modes than Helix: there is no match mode (``m``
    is a motion, not a prefix) and no select mode (Shift extends instead). ``v``
    enters view mode and ``V`` locks it until :kbd:`Escape`.
    """

    NORMAL = "normal"
    GOTO = "goto"
    GOTO_EXTEND = "goto-extend"
    VIEW = "view"
    VIEW_LOCKED = "view-locked"
    USER = "user"
    MARK_COMBINE = "mark-combine"


class KakouneState(ViState):
    """Hold the Kakoune state for a single buffer.

    Extends :py:class:`ViState` for ``input_mode`` and the named registers, adding
    Kakoune's sub-modes, pending-key slots, selection ranges and marks.

    Attributes:
        mode: The current sub-mode.
        selections: The active ``(anchor, head)`` ranges when more than one is live.
        primary_index: Index into ``selections`` of the main selection.
    """

    def __init__(self) -> None:
        """Initialise Kakoune state."""
        super().__init__()

        self._mode: KakouneMode = KakouneMode.NORMAL

        # Multiple selections, as ``(anchor, head)`` pairs where ``head`` is the
        # cursor end. Empty while a single selection is active, in which case
        # ``buffer.selection_state`` is the single source of truth.
        self._selections: list[tuple[int, int]] = []
        self._primary_index: int = 0

        # Set while a multi-site edit is in progress, so the invalidation handler
        # does not discard the ranges that edit is maintaining.
        self._applying_multi_edit: bool = False

        # Pending-key slots. Each is consumed by an ``<any>`` handler guarded by a
        # matching filter.
        #
        # ``pending_object`` is encoded as ``"<action>:<scope>"`` - for example
        # ``"select:whole"`` for ``<a-a>`` or ``"to-start:inner"`` for ``<a-[>`` -
        # so that all twelve object-entry keys share one slot.
        self._pending_object: str | None = None
        self._pending_char: str | None = None
        self._pending_register: str | None = None
        self._waiting_for_register: bool = False
        self._pending_replace_char: bool = False
        self._pending_mark: str | None = None
        self._pending_mark_combine: str | None = None

        # A regex-prompt operation awaiting input: "select", "split", "keep",
        # "drop", together with the ranges it applies to.
        self._pending_regex_op: str | None = None
        self._pending_regex_ranges: list[tuple[int, int]] = []

        # Saved selections, keyed by register. ``^`` is the default mark register.
        self._marks: dict[str, list[tuple[int, int]]] = {}

        # For ``<a-.>``, which repeats the last object or f/t selection.
        self._last_object: str | None = None
        self._last_char_find: tuple[str, str] | None = None

        # For ``.``, which repeats the last insert-mode change.
        self._last_insert: str = ""
        self._recording_insert: bool = False

        # Macro recording. ``ViState`` defines these upstream, but ``HelixState``
        # relies on that inheritance silently; set them explicitly here so the
        # contract is local and ``reset`` can clear them.
        self.recording_register: str | None = None
        self.current_recording: str = ""

    # Sub-mode

    @property
    def mode(self) -> KakouneMode:
        """Get the current sub-mode."""
        return self._mode

    @mode.setter
    def mode(self, value: KakouneMode) -> None:
        """Set the current sub-mode."""
        self._mode = value

    def exit_submode(self) -> None:
        """Leave any sub-mode and return to normal."""
        self._mode = KakouneMode.NORMAL

    # Selections

    @property
    def selections(self) -> list[tuple[int, int]]:
        """Get the active ranges, empty unless several are live."""
        return self._selections

    @selections.setter
    def selections(self, value: list[tuple[int, int]]) -> None:
        """Set the active ranges."""
        self._selections = value

    @property
    def primary_index(self) -> int:
        """Get the index of the main selection."""
        return self._primary_index

    @primary_index.setter
    def primary_index(self, value: int) -> None:
        """Set the index of the main selection."""
        self._primary_index = value

    def clear_selections(self) -> None:
        """Discard the additional selections, returning to a single one."""
        self._selections = []
        self._primary_index = 0

    # Pending keys

    @property
    def pending_object(self) -> str | None:
        """Get the encoded object operation awaiting a type key."""
        return self._pending_object

    @pending_object.setter
    def pending_object(self, value: str | None) -> None:
        """Set the encoded object operation awaiting a type key."""
        self._pending_object = value

    @property
    def pending_char(self) -> str | None:
        """Get the character command awaiting a key (``f``/``t`` and variants)."""
        return self._pending_char

    @pending_char.setter
    def pending_char(self, value: str | None) -> None:
        """Set the character command awaiting a key."""
        self._pending_char = value

    @property
    def pending_replace_char(self) -> bool:
        """Check whether ``r`` is awaiting its replacement character."""
        return self._pending_replace_char

    @pending_replace_char.setter
    def pending_replace_char(self, value: bool) -> None:
        """Set whether ``r`` is awaiting its replacement character."""
        self._pending_replace_char = value

    @property
    def pending_register(self) -> str | None:
        """Get the register selected for the next operation."""
        return self._pending_register

    @pending_register.setter
    def pending_register(self, value: str | None) -> None:
        """Set the register for the next operation."""
        self._pending_register = value

    @property
    def waiting_for_register(self) -> bool:
        """Check whether a register name is awaited after ``"``."""
        return self._waiting_for_register

    @waiting_for_register.setter
    def waiting_for_register(self, value: bool) -> None:
        """Set whether a register name is awaited."""
        self._waiting_for_register = value

    @property
    def pending_mark(self) -> str | None:
        """Get the pending mark operation (``"save"`` or ``"restore"``)."""
        return self._pending_mark

    @pending_mark.setter
    def pending_mark(self, value: str | None) -> None:
        """Set the pending mark operation."""
        self._pending_mark = value

    @property
    def pending_mark_combine(self) -> str | None:
        """Get the pending mark-combine direction for ``<a-z>``/``<a-Z>``."""
        return self._pending_mark_combine

    @pending_mark_combine.setter
    def pending_mark_combine(self, value: str | None) -> None:
        """Set the pending mark-combine direction."""
        self._pending_mark_combine = value

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
        """Get the ranges a pending regex operation applies to."""
        return self._pending_regex_ranges

    @pending_regex_ranges.setter
    def pending_regex_ranges(self, value: list[tuple[int, int]]) -> None:
        """Set the ranges a pending regex operation applies to."""
        self._pending_regex_ranges = value

    # Marks

    @property
    def marks(self) -> dict[str, list[tuple[int, int]]]:
        """Get the saved selections, keyed by register."""
        return self._marks

    # Repeat

    @property
    def last_object(self) -> str | None:
        """Get the last object selection, for ``<a-.>``."""
        return self._last_object

    @last_object.setter
    def last_object(self, value: str | None) -> None:
        """Set the last object selection."""
        self._last_object = value

    @property
    def last_char_find(self) -> tuple[str, str] | None:
        """Get the last ``f``/``t`` selection as ``(command, character)``."""
        return self._last_char_find

    @last_char_find.setter
    def last_char_find(self, value: tuple[str, str] | None) -> None:
        """Set the last ``f``/``t`` selection."""
        self._last_char_find = value

    @property
    def last_insert(self) -> str:
        """Get the text of the last insert-mode change, for ``.``."""
        return self._last_insert

    @last_insert.setter
    def last_insert(self, value: str) -> None:
        """Set the text of the last insert-mode change."""
        self._last_insert = value

    @property
    def recording_insert(self) -> bool:
        """Check whether insert-mode text is being captured for ``.``."""
        return self._recording_insert

    @recording_insert.setter
    def recording_insert(self, value: bool) -> None:
        """Set whether insert-mode text is being captured."""
        self._recording_insert = value

    # Helpers

    def take_register(self) -> str | None:
        """Consume and return the pending register, if any.

        Returns:
            The register name, or None when no register was selected.
        """
        register, self._pending_register = self._pending_register, None
        return register

    def clear_pending(self) -> None:
        """Clear every pending-key slot.

        Used by :kbd:`Escape`, which in Kakoune cancels whatever is pending rather
        than leaving the buffer.
        """
        self._pending_object = None
        self._pending_char = None
        self._pending_register = None
        self._waiting_for_register = False
        self._pending_replace_char = False
        self._pending_mark = None
        self._pending_mark_combine = None
        self._pending_regex_op = None
        self._pending_regex_ranges = []

    def reset(self) -> None:
        """Reset the state."""
        super().reset()
        self._mode = KakouneMode.NORMAL
        self.clear_selections()
        self._applying_multi_edit = False
        self.clear_pending()
        self._last_object = None
        self._last_char_find = None
        self._last_insert = ""
        self._recording_insert = False
        self.recording_register = None
        self.current_recording = ""


#: Per-buffer state. Weak so a state is collected with the cell it belongs to.
_STATES: WeakKeyDictionary[Buffer, KakouneState] = WeakKeyDictionary()


def get_state(buffer: Buffer) -> KakouneState:
    """Return the Kakoune state for a buffer, creating it on first use.

    Args:
        buffer: The buffer whose state is wanted.

    Returns:
        The state belonging to that buffer.
    """
    state = _STATES.get(buffer)
    if state is None:
        state = KakouneState()
        _STATES[buffer] = state
    return state
