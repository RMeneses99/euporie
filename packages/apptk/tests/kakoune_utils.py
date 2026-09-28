"""Provide a two-layer test harness for Kakoune key bindings.

Two layers are offered, with different costs and different reach:

``run_kakoune``
    Layer 2. Invokes commands directly against a :py:class:`Buffer`, with no
    :py:class:`Application` event loop. Fast, and suitable for the large majority
    of tests - anything asserting on resulting text, cursor position or selections.

``feed_kakoune``
    Layer 1. Drives a real :py:class:`PromptSession` with piped key presses.
    Slow, but the only way to exercise key *dispatch*: multi-key prefixes such as
    ``<a-a>w`` or ``g g``, :kbd:`Escape` handling, and macro record/replay.

This module is deliberately not named ``test_*`` so that pytest does not collect it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import Mock

# Importing the bindings module registers every ``kakoune-*`` command.
import apptk.key_binding.bindings.kakoune  # noqa: F401
from apptk.application.application import Application
from apptk.application.current import set_app
from apptk.buffer import Buffer
from apptk.clipboard import InMemoryClipboard
from apptk.commands import get_cmd
from apptk.document import Document
from apptk.enums import EditingMode
from apptk.input.defaults import create_pipe_input
from apptk.key_binding.bindings.kakoune_selections import get_selections
from apptk.key_binding.kakoune_state import InputMode, get_state
from apptk.key_binding.key_bindings import KeyBindings
from apptk.key_binding.key_processor import KeyPress, KeyPressEvent, KeyProcessor
from apptk.keys import Keys
from apptk.output import DummyOutput
from apptk.shortcuts import PromptSession

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "assert_selections",
    "feed_kakoune",
    "make_event",
    "make_kakoune_app",
    "run_kakoune",
    "selection_ranges",
]


def make_kakoune_app(buffer: Buffer) -> Any:
    """Build a mock application exposing a real buffer and Kakoune state.

    The mock is deliberately thin: commands reach the buffer through
    ``app.current_buffer`` and mutate the per-buffer Kakoune state, so both must be
    real objects. Everything else a command might touch is left as a mock or a
    dummy so that calls are recorded but inert.

    Args:
        buffer: The buffer commands should operate on.

    Returns:
        A mock application suitable for use with :py:func:`set_app`.
    """
    app = Mock(spec=Application)
    app.current_buffer = buffer
    app.editing_mode = EditingMode.KAKOUNE
    # The real property resolves per buffer; the mock pins the one under test.
    app.kakoune_state = get_state(buffer)
    app.kakoune_state.input_mode = InputMode.NAVIGATION
    app.clipboard = InMemoryClipboard()
    # Some prompt_toolkit internals still read ``vi_state``.
    app.vi_state = app.kakoune_state
    # Commands signal "nothing to do" by ringing the bell, so this must exist.
    app.output = DummyOutput()
    app.key_processor = KeyProcessor(KeyBindings())
    return app


def make_event(app: Any, data: str = "", arg: str | None = None) -> KeyPressEvent:
    """Build a synthetic key-press event bound to the given application.

    Args:
        app: The application the event belongs to.
        data: The key data, as a command awaiting a character would read it.
        arg: The numeric argument, as a count prefix would supply it.

    Returns:
        A key-press event.
    """
    return KeyPressEvent(
        lambda: app.key_processor,
        arg=arg,
        key_sequence=[KeyPress(Keys.Any, data)],
        previous_key_sequence=[],
        is_repeat=False,
    )


def run_kakoune(
    text: str,
    commands: str | Iterable[str],
    *,
    cursor: int = 0,
    selections: list[tuple[int, int]] | None = None,
    input_mode: InputMode = InputMode.NAVIGATION,
    data: str = "",
    arg: str | None = None,
    multiline: bool = True,
) -> tuple[Buffer, Any]:
    """Run one or more commands against a buffer and return the result.

    Args:
        text: The initial buffer text.
        commands: A command name, or several to run in order.
        cursor: The initial cursor offset.
        selections: Initial selection ranges, when more than the cursor is wanted.
        input_mode: The initial input mode.
        data: The key data passed to each command.
        arg: The numeric argument passed to each command.
        multiline: Whether the buffer is multiline.

    Returns:
        The buffer and the mock application, so tests can assert on both the text
        and the resulting modal state.
    """
    buffer = Buffer(document=Document(text, cursor), multiline=multiline)
    app = make_kakoune_app(buffer)
    app.kakoune_state.input_mode = input_mode

    if isinstance(commands, str):
        commands = [commands]

    with set_app(app):
        if selections is not None:
            from apptk.key_binding.bindings.kakoune_selections import set_selections

            set_selections(buffer, selections)
        for name in commands:
            get_cmd(name).handler(make_event(app, data=data, arg=arg))

    return buffer, app


def feed_kakoune(
    text: str,
    keys: str,
    *,
    cursor: int = 0,
    multiline: bool = False,
) -> tuple[Document, Any]:
    """Drive a real prompt session with piped key presses.

    This is the only layer which exercises key *dispatch*, so it is the one to use
    for multi-key sequences and for anything where the binding's filter matters.

    Args:
        text: The initial buffer text.
        keys: The keys to feed. Must end with a carriage return so the prompt
            accepts and returns; a multiline prompt would otherwise block forever.
        cursor: The initial cursor offset.
        multiline: Whether the prompt is multiline. Left False by default because
            in a multiline prompt a carriage return inserts a newline rather than
            accepting, so the call would never return.

    Returns:
        The final document and the application, for assertions.
    """
    assert keys.endswith("\r"), "feed_kakoune keys must end with '\\r' to accept"

    with create_pipe_input() as pipe_input:
        pipe_input.send_text(keys)
        session: PromptSession = PromptSession(
            input=pipe_input,
            output=DummyOutput(),
            editing_mode=EditingMode.KAKOUNE,
            multiline=multiline,
        )

        def pre_run() -> None:
            """Seed the buffer before the first key is processed."""
            session.default_buffer.document = Document(text, cursor)

        session.prompt(pre_run=pre_run)
        return session.default_buffer.document, session.app


def selection_ranges(buffer: Buffer) -> list[tuple[int, int]]:
    """Return the active selection ranges for a buffer.

    Normalises the single- and multiple-selection representations so that tests
    read the same either way.

    Args:
        buffer: The buffer to inspect.

    Returns:
        The active ranges as ``(start, end)`` pairs in buffer order.
    """
    from apptk.key_binding.bindings.kakoune_selections import normalise

    return sorted(normalise(r) for r in get_selections(buffer))


def assert_selections(
    buffer: Buffer, expected: list[tuple[int, int]], *, text: str | None = None
) -> None:
    """Assert the active selections, reporting the selected text on failure.

    Args:
        buffer: The buffer to inspect.
        expected: The expected ranges as ``(start, end)`` pairs.
        text: The buffer text, used to render a readable failure message.
    """
    actual = selection_ranges(buffer)
    wanted = sorted(expected)
    if actual != wanted:
        source = text if text is not None else buffer.text
        rendered_actual = [source[s:e] for s, e in actual]
        rendered_wanted = [source[s:e] for s, e in wanted]
        raise AssertionError(
            f"selections {actual} != {wanted}\n"
            f"  actual text: {rendered_actual}\n"
            f"  wanted text: {rendered_wanted}"
        )
