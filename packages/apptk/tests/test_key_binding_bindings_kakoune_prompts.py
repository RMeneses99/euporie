"""Test Kakoune's integration with Escape and with the host's prompts.

These cover the seam between the mode's own keymap and the application's, which is
where four faults hid: the mode must release :kbd:`Escape` in normal mode, and must
carry its own accept bindings for single-line prompts and for the search prompt.

``feed_kakoune`` cannot reach any of this - a ``PromptSession`` has no notebook pane,
no command bar and no search prompt - so these assert on filters and command handlers
directly.
"""

from __future__ import annotations

import pytest
from apptk.application.application import Application
from apptk.application.current import set_app
from apptk.buffer import Buffer
from apptk.commands import get_cmd
from apptk.document import Document
from apptk.enums import EditingMode
from apptk.filters.modes import exitable_mode
from apptk.key_binding.kakoune_state import InputMode, get_state
from apptk.layout import Layout, Window
from apptk.layout.controls import BufferControl
from kakoune_utils import make_event, make_kakoune_app


def _focused_app(editing_mode: EditingMode = EditingMode.KAKOUNE) -> Application:
    """Build an application with a real focused buffer."""
    window = Window(BufferControl(Buffer(name="cell", multiline=True)))
    return Application(
        layout=Layout(window, focused_element=window), editing_mode=editing_mode
    )


# Escape: the handoff protocol
#
# ``exitable_mode`` decides whether a mode still wants Escape. euporie's
# ``_exit_edit_mode`` is filtered on ``~exitable_mode``, so a mode which claims Escape
# unconditionally can never be left. Kakoune leaves Escape unbound in normal mode, so
# it must release the key there.


@pytest.mark.parametrize(
    ("input_mode", "claims_escape"),
    [
        (InputMode.NAVIGATION, False),
        (InputMode.INSERT, True),
        (InputMode.REPLACE, True),
    ],
)
def test_kakoune_releases_escape_in_normal_mode(
    input_mode: InputMode, claims_escape: bool
) -> None:
    """Kakoune claims Escape only while it has state to unwind.

    False in navigation mode is what lets the host leave a notebook cell; True in
    insert mode is what keeps Escape inside the cell.
    """
    app = _focused_app()
    app.kakoune_state.input_mode = input_mode
    with set_app(app):
        assert exitable_mode() is claims_escape


def test_kakoune_matches_the_other_modes_escape_convention() -> None:
    """Kakoune's clause behaves like Helix's, rather than claiming Escape always.

    This is the regression guard for the original fault, where the clause was written
    as a bare ``| kakoune_mode``.
    """
    for mode, attribute in (
        (EditingMode.KAKOUNE, "kakoune_state"),
        (EditingMode.HELIX, "helix_state"),
    ):
        app = _focused_app(mode)
        state = getattr(app, attribute)
        with set_app(app):
            state.input_mode = InputMode.NAVIGATION
            assert not exitable_mode(), f"{mode} should release Escape"
            state.input_mode = InputMode.INSERT
            assert exitable_mode(), f"{mode} should claim Escape"


def test_leave_insert_mode_returns_to_navigation() -> None:
    """Escape in insert mode returns to normal mode.

    Escape is the only way out of insert mode in Kakoune; ``<a-;>`` is a different
    command which returns to insert mode after one normal-mode command.
    """
    buffer = Buffer(document=Document("hello", 3), multiline=True)
    app = make_kakoune_app(buffer)
    app.kakoune_state.input_mode = InputMode.INSERT
    with set_app(app):
        get_cmd("kakoune-leave-insert-mode").handler(make_event(app))
    assert app.kakoune_state.input_mode == InputMode.NAVIGATION


def test_leave_insert_mode_is_not_bound_in_normal_mode() -> None:
    """The insert-mode Escape must not match in navigation mode.

    If it did, it would shadow the host's cell exit and reintroduce the fault.
    """
    from apptk.filters.modes import kakoune_insert_mode

    app = _focused_app()
    app.kakoune_state.input_mode = InputMode.NAVIGATION
    with set_app(app):
        assert not kakoune_insert_mode()


# Accept bindings for the host's prompts


def test_accept_line_validates_a_returnable_buffer() -> None:
    r"""``enter`` accepts a single-line buffer which has an accept handler.

    This is what executes euporie's command bar, so that ``:q!`` works. Without it the
    only surviving ``enter`` binding is the ``<any>`` self-insert, which drops the key
    because ``"\r".isprintable()`` is False.
    """
    accepted: list[str] = []
    buffer = Buffer(
        document=Document("q!", 2),
        multiline=False,
        accept_handler=lambda buf: accepted.append(buf.text) or False,
    )
    app = make_kakoune_app(buffer)
    app.kakoune_state.input_mode = InputMode.INSERT
    with set_app(app):
        get_cmd("kakoune-accept-line").handler(make_event(app))
    assert accepted == ["q!"]


def test_accept_line_filter_requires_a_single_line_returnable_buffer() -> None:
    """The filter excludes multiline buffers and those with no accept handler."""
    from apptk.filters.app import is_multiline
    from apptk.filters.buffer import is_returnable

    # A notebook cell: multiline, no accept handler.
    cell = Window(BufferControl(Buffer(name="cell", multiline=True)))
    app = Application(
        layout=Layout(cell, focused_element=cell), editing_mode=EditingMode.KAKOUNE
    )
    with set_app(app):
        assert is_multiline()
        assert not is_returnable()


def test_stop_search_discards_a_pending_regex_operation() -> None:
    """Aborting the prompt clears the operation, so it cannot fire later.

    Without this an abandoned ``s`` would leave the operation armed, to be applied
    against an unrelated later search.
    """
    target = Buffer(document=Document("alpha beta", 0), multiline=True)
    state = get_state(target)
    state.pending_regex_op = "select"
    state.pending_regex_ranges = [(0, 10)]

    window = Window(BufferControl(target))
    app = Application(
        layout=Layout(window, focused_element=window), editing_mode=EditingMode.KAKOUNE
    )
    with set_app(app):
        get_cmd("kakoune-stop-search").handler(make_event(app))

    assert state.pending_regex_op is None
    assert state.pending_regex_ranges == []


def test_apply_pending_regex_is_reachable_from_accept_search() -> None:
    """``apply_pending_regex`` has a caller.

    It was dead code: only Helix called its own copy, so every Kakoune regex prompt
    silently discarded the operation on :kbd:`Enter`.
    """
    import inspect

    from apptk.key_binding.bindings import kakoune

    source = inspect.getsource(kakoune.kakoune_accept_search)
    assert "apply_pending_regex" in source


# Registration


@pytest.mark.parametrize(
    "name",
    [
        "kakoune-accept-line",
        "kakoune-accept-search",
        "kakoune-stop-search",
        "kakoune-leave-insert-mode",
    ],
)
def test_prompt_commands_are_registered_and_bound(name: str) -> None:
    """Each prompt command exists and carries at least one binding."""
    command = get_cmd(name)
    assert command.bindings, f"{name} is registered but bound to nothing"


@pytest.mark.parametrize("name", ["kakoune-accept-search", "kakoune-stop-search"])
def test_search_commands_are_in_the_search_binding_set(name: str) -> None:
    """The search accept and stop commands are loaded with the search bindings."""
    from apptk.key_binding.bindings.kakoune import KAKOUNE_SEARCH_COMMANDS

    assert name in KAKOUNE_SEARCH_COMMANDS


def test_catch_all_no_longer_excludes_application_keys() -> None:
    """The misdiagnosed ``:``/``!`` exclusion is gone.

    Diagnosis showed the ``:`` fault was the missing accept-line, and that
    ``_default_bindings`` is the lowest-priority layer - so the catch-all never
    shadowed the command bar.
    """
    from apptk.key_binding.bindings import kakoune

    assert not hasattr(kakoune, "_APPLICATION_KEYS")
    assert not hasattr(kakoune, "_not_an_application_key")
