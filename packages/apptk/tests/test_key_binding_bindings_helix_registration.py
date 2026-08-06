"""Test that Helix key-binding registration stays in step with the command registry."""

from __future__ import annotations

from apptk.commands import COMMANDS
from apptk.key_binding.bindings.helix import (
    HELIX_SEARCH_COMMANDS,
    load_helix_bindings,
    load_helix_search_bindings,
)


def _binding_pairs(key_bindings: object) -> list[tuple[str, str]]:
    """Return each binding as a comparable ``(keys, handler name)`` pair.

    Args:
        key_bindings: The key bindings to describe.

    Returns:
        One pair per binding.
    """
    return [
        (
            ",".join(str(key) for key in binding.keys),
            getattr(binding.handler, "__name__", "?"),
        )
        for binding in key_bindings.bindings  # type: ignore[attr-defined]
    ]


def test_every_helix_command_is_bound() -> None:
    """Every ``helix-*`` command in the registry is bound by the loader.

    This is the property the registry scan buys: a command cannot be added with
    ``@add_cmd`` and then silently left unbound.
    """
    bound_handlers = {handler for _, handler in _binding_pairs(load_helix_bindings())}

    seen: set[int] = set()
    for name, command in COMMANDS.items():
        if not name.startswith("helix-") or id(command) in seen:
            continue
        seen.add(id(command))
        if not command.bindings:
            # A command with no keys of its own contributes no bindings.
            continue
        assert command.handler.__name__ in bound_handlers, (
            f"{name} is registered but not bound"
        )


def test_no_duplicate_bindings() -> None:
    """No binding is registered twice, as would happen if aliases were not guarded."""
    pairs = _binding_pairs(load_helix_bindings())
    duplicates = {pair for pair in pairs if pairs.count(pair) > 1}
    assert not duplicates, f"duplicate bindings: {duplicates}"


def test_aliased_command_bound_once_per_key() -> None:
    """``helix-toggle-comments`` is an alias and must not be bound twice per key.

    It aliases ``toggle-comments``, so an unguarded scan over ``COMMANDS`` would
    visit the same ``Command`` twice and bind every one of its keys twice. The
    command legitimately has several distinct keys, so the property to check is
    that each key appears once - not that there is only one binding.
    """
    pairs = _binding_pairs(load_helix_bindings())
    keys = [key for key, handler in pairs if handler == "toggle_comments"]
    assert keys, "toggle-comments is not bound at all"
    assert len(keys) == len(set(keys)), f"toggle-comments keys bound twice: {keys}"


def test_search_bindings_are_an_explicit_subset() -> None:
    """Search bindings cover exactly the declared search commands."""
    pairs = _binding_pairs(load_helix_search_bindings())
    assert len(pairs) == len(HELIX_SEARCH_COMMANDS)


def test_search_command_names_all_resolve() -> None:
    """Every declared search command name exists in the registry."""
    for name in HELIX_SEARCH_COMMANDS:
        assert name in COMMANDS, f"{name} is not a registered command"


def test_no_command_is_bound_to_a_private_helper() -> None:
    """No ``helix-`` command resolves to a private helper function.

    An ``@add_cmd`` decorator separated from its intended function by a helper
    definition silently attaches to the helper instead. That mistake is invisible
    until the command is invoked, so it is checked here by convention: command
    handlers are public, helpers are underscore-prefixed.
    """
    seen: set[int] = set()
    misbound: list[tuple[str, str]] = []
    for name, command in COMMANDS.items():
        if not name.startswith("helix-") or id(command) in seen:
            continue
        seen.add(id(command))
        handler_name = command.handler.__name__
        # ``_arg`` handlers are generated in a loop and are legitimately private.
        if handler_name.startswith("_") and not handler_name.startswith("_arg"):
            misbound.append((name, handler_name))
    assert not misbound, f"commands bound to private helpers: {misbound}"
