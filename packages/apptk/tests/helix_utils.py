"""Provide a two-layer test harness for Helix key bindings.

Two layers are offered, with different costs and different reach:

``run_helix``
    Layer 2. Invokes commands directly against a :py:class:`Buffer`, with no
    :py:class:`Application` event loop. Fast, and suitable for the large majority
    of tests - anything asserting on resulting text, cursor position or selection.

``feed_helix``
    Layer 1. Drives a real :py:class:`PromptSession` with piped key presses.
    Slow, but the only way to exercise key *dispatch*: multi-key prefixes such as
    ``g g`` or ``m i w``, and macro record/replay.

This module is deliberately not named ``test_*`` so that pytest does not collect it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

from apptk.application.application import Application
from apptk.application.current import set_app
from apptk.buffer import Buffer
from apptk.commands import get_cmd
from apptk.document import Document
from apptk.enums import EditingMode
from apptk.input.defaults import create_pipe_input
from apptk.key_binding.helix_state import HelixState, InputMode
from apptk.key_binding.key_processor import KeyPressEvent
from apptk.output import DummyOutput
from apptk.shortcuts import PromptSession

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "assert_selection",
    "feed_helix",
    "make_event",
    "make_helix_app",
    "run_helix",
    "selection_range",
]


def make_helix_app(buffer: Buffer) -> Any:
    """Build a mock application exposing a real buffer and helix state.

    The mock is deliberately thin: commands reach the buffer through
    ``app.current_buffer`` and mutate ``app.helix_state``, so both must be real
    objects rather than mocks. Everything else a command might touch (``output``,
    ``clipboard``) is left as a mock so that calls are recorded but inert.

    Args:
        buffer: The buffer commands should operate on.

    Returns:
        A mock application suitable for use with :py:func:`set_app`.
    """
    from apptk.clipboard import InMemoryClipboard
    from apptk.output import DummyOutput

    app = Mock(spec=Application)
    app.current_buffer = buffer
    app.editing_mode = EditingMode.HELIX
    app.helix_state = HelixState()
    app.helix_state.input_mode = InputMode.NAVIGATION
    app.clipboard = InMemoryClipboard()
    app.vi_state = app.helix_state
    # Commands signal "nothing to do" by ringing the bell, so this must exist.
    app.output = DummyOutput()
    return app


def make_event(app: Any, data: str = "", arg: str | None = None) -> KeyPressEvent:
    """Build a synthetic key-press event bound to the given application.

    Args:
        app: The application the event should report.
        data: The literal key data, for commands which read ``event.data``.
        arg: A numeric argument prefix, as a string, or None.

    Returns:
        A key-press event usable as a command handler argument.
    """
    from apptk.key_binding.key_processor import KeyPress
    from apptk.keys import Keys

    with set_app(app):
        event = KeyPressEvent(
            key_processor_ref=Mock(),
            arg=arg,
            key_sequence=[KeyPress(Keys.Any, data)] if data else [],
            previous_key_sequence=[],
            is_repeat=False,
        )
    return event


def run_helix(
    text: str,
    commands: str | Iterable[str],
    *,
    cursor: int = 0,
    select_mode: bool = False,
    input_mode: InputMode = InputMode.NAVIGATION,
    data: str = "",
    arg: str | None = None,
) -> tuple[Buffer, Any]:
    """Run Helix commands by name against a buffer, without an application loop.

    Args:
        text: Initial buffer contents.
        commands: A command name, or an iterable of names run in order.
        cursor: Initial cursor position.
        select_mode: Whether to start in Helix select mode.
        input_mode: The Helix input mode to start in.
        data: Key data made available to the commands as ``event.data``.
        arg: A numeric argument prefix, as a string.

    Returns:
        A tuple of the resulting buffer and the mock application, so that tests may
        assert on ``app.helix_state`` as well as on buffer contents.
    """
    if isinstance(commands, str):
        commands = [commands]

    buffer = Buffer(document=Document(text, cursor))
    app = make_helix_app(buffer)
    app.helix_state.input_mode = input_mode
    app.helix_state.select_mode = select_mode

    with set_app(app):
        for name in commands:
            event = make_event(app, data=data, arg=arg)
            get_cmd(name).handler(event)

    return buffer, app


def feed_helix(
    text: str,
    keys: str,
    *,
    cursor: int = 0,
    multiline: bool = False,
) -> tuple[Document, Any]:
    r"""Feed key presses to a real prompt session in Helix mode.

    Use this only where key *dispatch* is the thing under test - multi-key prefixes,
    or macro replay. For everything else prefer :py:func:`run_helix`, which is far
    faster.

    Multiline buffers may still be passed as ``text``; only the prompt's own
    ``multiline`` behaviour is disabled by default.

    Args:
        text: Initial buffer contents, seeded before keys are fed.
        keys: The key presses to feed. Must end with ``\r`` so the prompt returns.
        cursor: Initial cursor position.
        multiline: Whether the prompt should be multiline. Defaults to False:
            in a multiline prompt ``\r`` inserts a newline rather than accepting
            the input, so the prompt never returns and the call blocks forever.
            Only pass True when testing newline handling, and then terminate the
            key sequence with an explicit accept binding instead.

    Returns:
        A tuple of the resulting document and the application, so that tests may
        assert on ``app.helix_state``.

    Raises:
        AssertionError: If ``keys`` does not end with a carriage return.
    """
    assert keys.endswith("\r"), "key sequence must end with '\\r' to finish the prompt"

    with create_pipe_input() as inp:
        inp.send_text(keys)
        session: PromptSession = PromptSession(
            input=inp,
            output=DummyOutput(),
            editing_mode=EditingMode.HELIX,
            multiline=multiline,
        )

        def seed() -> None:
            """Seed the buffer and enter navigation mode before keys are processed."""
            session.default_buffer.set_document(
                Document(text, cursor), bypass_readonly=True
            )
            session.app.helix_state.input_mode = InputMode.NAVIGATION

        session.prompt(pre_run=seed)

        return session.default_buffer.document, session.app


def selection_range(buffer: Buffer) -> tuple[int, int] | None:
    """Return the buffer's selection as a sorted ``(start, end)`` pair.

    Args:
        buffer: The buffer to inspect.

    Returns:
        The sorted selection bounds, or None when nothing is selected.
    """
    state = buffer.selection_state
    if state is None:
        return None
    anchor = state.original_cursor_position
    head = buffer.cursor_position
    return (anchor, head) if anchor <= head else (head, anchor)


def assert_selection(
    buffer: Buffer, app: Any, expected: list[tuple[int, int]] | tuple[int, int] | None
) -> None:
    """Assert the current selection, whether single or multiple.

    Normalises the two representations so that single- and multi-selection tests
    read identically: a single selection lives on ``buffer.selection_state``, while
    multiple selections live on ``app.helix_state``.

    Args:
        buffer: The buffer to inspect.
        app: The application holding the Helix state.
        expected: The expected ranges, a single expected range, or None for no
            selection.

    Raises:
        AssertionError: If the actual selection does not match.
    """
    selections = list(getattr(app.helix_state, "selections", []) or [])
    if selections:
        actual: list[tuple[int, int]] | None = [
            (a, h) if a <= h else (h, a) for a, h in selections
        ]
    else:
        single = selection_range(buffer)
        actual = None if single is None else [single]

    if expected is None:
        assert actual is None, f"expected no selection, got {actual}"
        return

    if isinstance(expected, tuple):
        expected = [expected]

    assert actual == expected, f"expected selection {expected}, got {actual}"
