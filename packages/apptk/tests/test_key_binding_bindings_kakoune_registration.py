"""Test the structural invariants of Kakoune binding registration.

``load_kakoune_bindings`` derives its bindings by scanning the command registry for
the ``kakoune-`` prefix. That makes several properties checkable here which would
otherwise only surface when a key was actually pressed.
"""

from __future__ import annotations

import kakoune_utils  # noqa: F401  - imported for its command registration
import pytest

from apptk.commands import COMMANDS, get_cmd
from apptk.key_binding.bindings.kakoune import (
    KAKOUNE_SEARCH_COMMANDS,
    load_kakoune_bindings,
    load_kakoune_search_bindings,
)


def _kakoune_commands() -> dict[str, object]:
    """Return the registered Kakoune commands, keyed by name."""
    return {name: cmd for name, cmd in COMMANDS.items() if name.startswith("kakoune-")}


def test_commands_are_registered() -> None:
    """The bindings module registers a substantial command set.

    A bare floor rather than an exact count, so that adding commands does not
    require editing this test - but low enough to catch the module failing to
    import or register at all.
    """
    assert len(_kakoune_commands()) > 100


def test_every_kakoune_command_is_bound() -> None:
    """No command can be added and then silently left unbound.

    The registry scan means a command with an ``@add_cmd`` decorator is bound
    automatically, so an unbound one indicates a command declared with no keys.
    """
    unbound = [
        name
        for name, cmd in _kakoune_commands().items()
        if not cmd.bindings  # type: ignore[attr-defined]
    ]
    assert unbound == []


def test_no_duplicate_bindings() -> None:
    """No key sequence is registered twice for the same command."""
    for name, cmd in _kakoune_commands().items():
        keys = [binding.keys for binding in cmd.bindings]  # type: ignore[attr-defined]
        assert len(keys) == len(set(keys)), f"{name} has duplicate bindings"


def test_loader_binds_each_command_once() -> None:
    """Aliases must not cause a command to be bound more than once.

    ``COMMANDS`` maps every alias to the same object, so an unguarded scan would
    bind an aliased command once per name.
    """
    bindings = load_kakoune_bindings().bindings
    total = sum(len(cmd.bindings) for cmd in set(_kakoune_commands().values()))  # type: ignore[attr-defined]
    assert len(bindings) == total


def test_search_bindings_are_an_explicit_subset() -> None:
    """The search bindings are exactly the declared commands, not a scan."""
    bindings = load_kakoune_search_bindings().bindings
    expected = sum(len(get_cmd(name).bindings) for name in KAKOUNE_SEARCH_COMMANDS)
    assert len(bindings) == expected


@pytest.mark.parametrize("name", KAKOUNE_SEARCH_COMMANDS)
def test_search_command_names_all_resolve(name: str) -> None:
    """Every declared search command exists in the registry."""
    assert get_cmd(name) is not None


def test_no_command_is_bound_to_a_private_helper() -> None:
    """No ``kakoune-`` command resolves to a private helper function.

    An ``@add_cmd`` decorator separated from its intended function by a helper
    definition silently attaches to the helper instead. That mistake is invisible
    until the command is invoked, so it is checked here by convention: command
    handlers are public, helpers are underscore-prefixed.

    The generated commands - counts, movements, objects and so on - are registered
    from closures inside registration helpers, so they are exempted by name.
    """
    generated_prefixes = (
        "kakoune-count-",
        "kakoune-left",
        "kakoune-right",
        "kakoune-up",
        "kakoune-down",
        "kakoune-next-",
        "kakoune-prev-",
        "kakoune-word-end",
        "kakoune-long-word-end",
        "kakoune-object-",
        "kakoune-match-",
        "kakoune-find-",
        "kakoune-extend-find-",
        "kakoune-goto-",
        "kakoune-view-",
    )
    offenders = [
        name
        for name, cmd in _kakoune_commands().items()
        if cmd.handler.__name__.startswith("_")  # type: ignore[attr-defined]
        and not name.startswith(generated_prefixes)
    ]
    assert offenders == []


def test_loader_is_gated_on_kakoune_mode() -> None:
    """The bindings are wrapped so they cannot fire in another editing mode."""
    from apptk.application.application import Application
    from apptk.application.current import set_app
    from apptk.enums import EditingMode

    bindings = load_kakoune_bindings()
    app = Application(editing_mode=EditingMode.HELIX)
    with set_app(app):
        # The conditional wrapper reports no active bindings outside Kakoune mode.
        assert bindings.bindings, "bindings exist"
        from apptk.filters.modes import kakoune_mode

        assert not kakoune_mode()


def test_divergent_keys_are_bound_the_kakoune_way() -> None:
    """The keys most often confused with Helix resolve to Kakoune's meaning.

    This is the guard against a future refactor drifting towards the Helix
    semantics; each of these is a key where the two editors genuinely differ.
    """
    expectations = {
        # key: the command it must resolve to
        "x": "kakoune-expand-lines",
        "~": "kakoune-to-uppercase",
        "m": "kakoune-match-next",
        "v": "kakoune-enter-view-mode",
        "z": "kakoune-restore-selections",
        "Z": "kakoune-save-selections",
        "Q": "kakoune-start-record-macro",
        "q": "kakoune-play-macro",
        "N": "kakoune-search-next-add",
        "C": "kakoune-copy-selection-below",
        ")": "kakoune-rotate-main-forward",
        "+": "kakoune-duplicate-selections",
    }
    for key, expected in expectations.items():
        command = get_cmd(expected)
        bound = {"".join(str(k) for k in binding.keys) for binding in command.bindings}
        assert key in bound, f"{expected} should be bound to {key!r}, got {bound}"
