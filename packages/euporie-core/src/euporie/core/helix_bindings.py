"""Bind euporie commands into the Helix space and window sub-modes.

:py:mod:`apptk` provides the Helix ``space`` and ``window`` sub-modes but not the
actions reached through them: which pickers and window operations exist is an
application concern. This module attaches euporie's own commands to keys within
those modes.

Existing commands are re-bound rather than reimplemented, so a Helix user reaches
exactly the same behaviour as the corresponding menu item or default key binding.
Bindings are picked up automatically by ``load_helix_bindings``, which scans the
command registry.
"""

from __future__ import annotations

import logging

from apptk.commands import get_cmd
from apptk.filters.modes import helix_space_mode, helix_window_mode

log = logging.getLogger(__name__)

__all__ = ["register_helix_app_bindings"]

#: Commands reached through the Helix ``space`` sub-mode, keyed by their key.
SPACE_MODE_BINDINGS: dict[str, str] = {
    "f": "open-file",
    "w": "save-file",
    "k": "change-kernel",
    "?": "show-command-palette",
}

#: Commands reached through the Helix ``window`` sub-mode, keyed by their key.
WINDOW_MODE_BINDINGS: dict[str, str] = {
    "v": "tile-tabs",
    "s": "stack-tabs",
    "w": "focus-next",
    "p": "focus-previous",
    "q": "close-tab",
    "n": "next-tab",
}


def register_helix_app_bindings() -> None:
    """Bind euporie commands into the Helix space and window sub-modes.

    Commands which are not registered - because the relevant application package
    is not installed - are skipped, so that this is safe to call from any app.
    """
    for filter_, bindings in (
        (helix_space_mode, SPACE_MODE_BINDINGS),
        (helix_window_mode, WINDOW_MODE_BINDINGS),
    ):
        for key, name in bindings.items():
            try:
                command = get_cmd(name)
            except KeyError:
                log.debug("Helix sub-mode command %r is not registered", name)
                continue
            command.add_keys(keys=[key], filter=filter_)
