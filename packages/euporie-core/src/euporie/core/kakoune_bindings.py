"""Bind euporie commands into the Kakoune user mode.

:py:mod:`apptk` provides Kakoune's ``user mode`` - reached with :kbd:`Space` - but
not the actions within it. In Kakoune that mode is deliberately empty, for the user
to fill through their own configuration; here it is populated with euporie's own
file, kernel and command-palette actions so that the key is useful out of the box.

Existing commands are re-bound rather than reimplemented, so a Kakoune user reaches
exactly the same behaviour as the corresponding menu item. Bindings are picked up
automatically by ``load_kakoune_bindings``, which scans the command registry.
"""

from __future__ import annotations

import logging

from apptk.commands import get_cmd
from apptk.filters.modes import kakoune_user_mode

log = logging.getLogger(__name__)

__all__ = ["register_kakoune_app_bindings"]

#: Commands reached through Kakoune's user mode, keyed by their key.
#:
#: Kakoune leaves this mode empty by default, so there is no upstream keymap to
#: match; these follow the Helix space-mode choices so that a euporie user moving
#: between the two modes finds the same keys.
USER_MODE_BINDINGS: dict[str, str] = {
    "f": "open-file",
    "w": "save-file",
    "k": "change-kernel",
    "?": "show-command-palette",
    "q": "close-tab",
    "n": "next-tab",
    "p": "previous-tab",
}


def register_kakoune_app_bindings() -> None:
    """Bind euporie commands into the Kakoune user mode.

    Commands which are not registered - because the relevant application package is
    not installed - are skipped, so this is safe to call from any app.
    """
    for key, name in USER_MODE_BINDINGS.items():
        try:
            command = get_cmd(name)
        except KeyError:
            log.debug("Kakoune user-mode command %r is not registered", name)
            continue
        command.add_keys(keys=[key], filter=kakoune_user_mode)
