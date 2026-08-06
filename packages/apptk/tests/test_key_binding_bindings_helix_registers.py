"""Test Helix named registers and macro recording.

Register storage is exercised at the command level, while macro recording and
replay need real key dispatch and so use the prompt-session harness.
"""

from __future__ import annotations

from apptk.application.current import set_app
from apptk.clipboard import ClipboardData
from apptk.commands import get_cmd
from helix_utils import feed_helix, make_event, run_helix

SELECT_REGISTER_A = ["helix-select-register", "helix-handle-register"]


# Selecting a register


def test_select_register_awaits_a_name() -> None:
    """``"`` puts the editor into the waiting-for-register state."""
    _, app = run_helix("hello", "helix-select-register", cursor=0)
    assert app.helix_state.waiting_for_register


def test_register_name_is_recorded() -> None:
    """The key after ``"`` becomes the pending register."""
    _, app = run_helix("hello", SELECT_REGISTER_A, cursor=0, data="a")
    assert app.helix_state.pending_register == "a"
    assert not app.helix_state.waiting_for_register


def test_invalid_register_name_is_rejected() -> None:
    """A non-alphanumeric register name is not accepted."""
    _, app = run_helix("hello", SELECT_REGISTER_A, cursor=0, data="!")
    assert app.helix_state.pending_register is None
    assert not app.helix_state.waiting_for_register


def test_take_register_consumes_the_pending_value() -> None:
    """A pending register is consumed by the first command which uses it."""
    _, app = run_helix("hello", SELECT_REGISTER_A, cursor=0, data="a")
    assert app.helix_state.take_register() == "a"
    assert app.helix_state.take_register() is None


# Yanking and pasting


def test_yank_without_register_uses_the_clipboard() -> None:
    """A yank with no register selected goes to the clipboard as before."""
    _, app = run_helix(
        "hello world", ["helix-extend-line-below", "helix-yank"], cursor=0
    )
    assert app.clipboard.get_data().text
    assert app.helix_state.named_registers == {}


def test_yank_with_register_bypasses_the_clipboard() -> None:
    """A yank into a register leaves the clipboard untouched."""
    _, app = run_helix(
        "hello world",
        [*SELECT_REGISTER_A, "helix-extend-line-below", "helix-yank"],
        cursor=0,
        data="a",
    )
    assert app.helix_state.named_registers["a"].text
    assert app.clipboard.get_data().text == ""


def test_delete_with_register_stores_the_cut_text() -> None:
    """A delete into a register stores what was removed."""
    buffer, app = run_helix(
        "hello world",
        [*SELECT_REGISTER_A, "helix-extend-line-below", "helix-delete-selection"],
        cursor=0,
        data="a",
    )
    assert "a" in app.helix_state.named_registers
    assert buffer.text != "hello world"


def test_paste_reads_from_the_selected_register() -> None:
    """A paste with a register selected uses that register's contents."""
    buffer, app = run_helix("abc", [], cursor=0)
    app.helix_state.named_registers["a"] = ClipboardData("XY")
    app.helix_state.pending_register = "a"
    with set_app(app):
        get_cmd("helix-paste-after").handler(make_event(app))
    assert buffer.text == "aXYbc"


def test_paste_from_an_empty_register_inserts_nothing() -> None:
    """Pasting an unwritten register does not corrupt the buffer."""
    buffer, app = run_helix("abc", [], cursor=0)
    app.helix_state.pending_register = "z"
    with set_app(app):
        get_cmd("helix-paste-after").handler(make_event(app))
    assert buffer.text == "abc"


def test_registers_are_independent() -> None:
    """Different registers hold different values."""
    _, app = run_helix("hello", [], cursor=0)
    app.helix_state.named_registers["a"] = ClipboardData("first")
    app.helix_state.named_registers["b"] = ClipboardData("second")
    assert app.helix_state.named_registers["a"].text == "first"
    assert app.helix_state.named_registers["b"].text == "second"


# Macros - these need real key dispatch


def test_macro_records_key_presses() -> None:
    """``q`` starts recording and a second ``q`` stores the macro."""
    _, app = feed_helix("one two three", "qllq\r", cursor=0)
    assert app.helix_state.named_registers["@"].text == "ll"
    assert app.helix_state.recording_register is None


def test_macro_replays_recorded_keys() -> None:
    """``Q`` replays the default macro register."""
    doc, _ = feed_helix("one two three", "qllqQ\r", cursor=0)
    # Two cursor movements while recording, then two more on replay.
    assert doc.cursor_position == 4


def test_macro_records_into_a_named_register() -> None:
    """``"a`` before ``q`` records the macro into register ``a``."""
    _, app = feed_helix("one two three", '"aqllq\r', cursor=0)
    assert app.helix_state.named_registers["a"].text == "ll"


def test_macro_replays_from_a_named_register() -> None:
    """``"aQ`` replays the macro held in register ``a``."""
    doc, _ = feed_helix("one two three", '"aqllq"aQ\r', cursor=0)
    assert doc.cursor_position == 4


def test_recording_excludes_the_start_and_stop_keys() -> None:
    """The ``q`` keys which delimit a macro are not part of it."""
    _, app = feed_helix("one two three", "qwwq\r", cursor=0)
    assert app.helix_state.named_registers["@"].text == "ww"


def test_replaying_an_empty_register_is_harmless() -> None:
    """``Q`` with nothing recorded leaves the buffer unchanged."""
    doc, _ = feed_helix("abc", "Q\r", cursor=0)
    assert doc.text == "abc"


def test_macro_state_is_cleared_on_reset() -> None:
    """Resetting the Helix state discards register and recording state."""
    _, app = run_helix("hello", SELECT_REGISTER_A, cursor=0, data="a")
    app.helix_state.recording_register = "a"
    app.helix_state.reset()
    assert app.helix_state.pending_register is None
    assert not app.helix_state.waiting_for_register


def test_vi_macros_are_unaffected() -> None:
    """Vi macro recording still works alongside the Helix implementation.

    Helix records macros through an override of ``KeyProcessor._call_handler``,
    so this guards against that override disturbing the upstream Vi path.
    """
    from apptk.document import Document
    from apptk.enums import EditingMode
    from apptk.input.defaults import create_pipe_input
    from apptk.key_binding.vi_state import InputMode
    from apptk.output import DummyOutput
    from apptk.shortcuts import PromptSession

    with create_pipe_input() as inp:
        inp.send_text("qwllq\r")
        session: PromptSession = PromptSession(
            input=inp, output=DummyOutput(), editing_mode=EditingMode.VI
        )

        def seed() -> None:
            """Seed the buffer and enter Vi navigation mode."""
            session.default_buffer.set_document(
                Document("one two three four", 0), bypass_readonly=True
            )
            session.app.vi_state.input_mode = InputMode.NAVIGATION

        session.prompt(pre_run=seed)
        assert session.app.vi_state.named_registers["w"].text == "ll"
