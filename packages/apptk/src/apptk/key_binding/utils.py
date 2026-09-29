"""Utility functions for formatting key-bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

from apptk.key_binding.key_bindings import _parse_key
from apptk.keys import Keys

if TYPE_CHECKING:
    from apptk.application.application import Application
    from apptk.key_binding import KeyPressEvent
    from apptk.key_binding.vi_state import InputMode
    from apptk.keys import AnyKeys


KEY_ALIASES: dict[str | Keys, str] = {
    Keys.ControlH: "backspace",
    Keys.ControlM: "enter",
    Keys.ControlI: "tab",
    Keys.ControlUnderscore: "c-/",
    Keys.ControlAt: "c-space",
}


def if_no_repeat(event: KeyPressEvent) -> bool:
    """Return True when the previous event was delivered to another handler."""
    return not event.is_repeat


def parse_keys(keys: AnyKeys) -> list[tuple[str | Keys, ...]]:
    """Parse a list of keys."""
    # Use dict keys as ordered set
    output: dict[tuple[str | Keys, ...], None] = {}
    if not isinstance(keys, list):
        keys = [keys]
    for key in keys:
        if isinstance(key, Keys):
            output[(key,)] = None
        elif isinstance(key, tuple):
            output[tuple(_parse_key(k) for k in key)] = None
        elif " " in key:
            output[tuple(_parse_key(k) for k in key.split())] = None
        else:
            output[(_parse_key(key),)] = None
    return list(output.keys())


def _format_key_str(key: str) -> str:
    if key:
        key = key.replace("c-", "Ctrl+").replace("s-", "Shift+").replace("A-", "Alt+")
        parts = key.split("+")
        if parts[-1].isupper():
            parts.insert(-1, "Shift")
            key = "+".join(parts)
    return key.title()


def format_keys(keys: list[tuple[str | Keys, ...]]) -> list[str]:
    """Convert a list of tuples of keys to a string."""
    s: list[str] = []

    # Add duplicate key aliases to the list
    keys_: list[tuple[str | Keys, ...]] = []
    for key in keys:
        if len(key) == 1 and key[0] in KEY_ALIASES:
            keys_.append((KEY_ALIASES[key[0]],))
        keys_.append(key)

    # Format the key text
    for key in keys_:
        if isinstance(key, tuple):
            s.append(
                ", ".join([_format_key_str(k) for k in key])
                .replace("Escape, ", "Alt+")
                .replace("Alt+Ctrl+m", "Ctrl+Alt+Enter")
            )
        elif isinstance(key, str):
            s.append(_format_key_str(key))
        else:
            s.append(_format_key_str(key.value))

    # Remove duplicate entries but keep the order
    keys_ = list(dict(zip(keys, range(len(keys)))).keys())

    return s


def set_modal_input_mode(app: Application, mode: InputMode) -> None:
    """Set the input mode on every modal editing state the application holds.

    The Vi, Helix and Kakoune modes each keep their own state object, so a widget
    which takes or releases focus has to reset all of them rather than guess which
    is active. Collecting that here keeps the call sites to one line and stops a
    newly added mode being forgotten at one of them.

    Args:
        app: The application whose modal states should be updated.
        mode: The input mode to set.
    """
    # ``micro_state`` is excluded: it uses its own enum rather than ``InputMode``.
    for attribute in ("vi_state", "helix_state", "kakoune_state"):
        state = getattr(app, attribute, None)
        if state is not None:
            state.input_mode = mode
