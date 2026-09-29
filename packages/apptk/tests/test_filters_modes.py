"""Test editing-mode filters are correctly scoped to their editing mode."""

from __future__ import annotations

import pytest
from apptk.application.application import Application
from apptk.application.current import set_app
from apptk.enums import EditingMode
from apptk.filters.modes import (
    helix_goto_mode,
    helix_insert_mode,
    helix_match_mode,
    helix_mode,
    helix_navigation_mode,
    helix_normal_mode,
    helix_replace_mode,
    helix_select_mode,
    helix_space_mode,
    helix_view_mode,
    helix_window_mode,
    insert_mode,
    kakoune_goto_mode,
    kakoune_insert_mode,
    kakoune_mode,
    kakoune_navigation_mode,
    kakoune_normal_mode,
    kakoune_replace_mode,
    kakoune_user_mode,
    kakoune_view_mode,
    micro_insert_mode,
    micro_mode,
    micro_replace_mode,
    navigation_mode,
    replace_mode,
)
from apptk.key_binding.helix_state import HelixMode, InputMode
from apptk.key_binding.kakoune_state import KakouneMode

HELIX_FILTERS = [
    helix_goto_mode,
    helix_insert_mode,
    helix_match_mode,
    helix_mode,
    helix_navigation_mode,
    helix_normal_mode,
    helix_replace_mode,
    helix_select_mode,
    helix_space_mode,
    helix_view_mode,
    helix_window_mode,
]

NON_HELIX_MODES = [
    EditingMode.VI,
    EditingMode.EMACS,
    EditingMode.MICRO,
    EditingMode.KAKOUNE,
]

KAKOUNE_FILTERS = [
    kakoune_goto_mode,
    kakoune_insert_mode,
    kakoune_mode,
    kakoune_navigation_mode,
    kakoune_normal_mode,
    kakoune_replace_mode,
    kakoune_user_mode,
    kakoune_view_mode,
]

NON_KAKOUNE_MODES = [
    EditingMode.VI,
    EditingMode.EMACS,
    EditingMode.MICRO,
    EditingMode.HELIX,
]


@pytest.mark.parametrize("editing_mode", NON_HELIX_MODES)
@pytest.mark.parametrize("helix_filter", HELIX_FILTERS)
def test_helix_filters_false_outside_helix_mode(
    editing_mode: EditingMode, helix_filter: object
) -> None:
    """Helix filters are False in other editing modes, whatever the helix state."""
    app = Application(editing_mode=editing_mode)
    # Leave stale helix state behind, as a runtime edit-mode switch would.
    app.helix_state.input_mode = InputMode.INSERT
    app.helix_state.select_mode = True
    app.helix_state.mode = HelixMode.GOTO
    with set_app(app):
        assert not helix_filter()  # type: ignore[operator]


@pytest.mark.parametrize("editing_mode", NON_HELIX_MODES)
def test_stale_helix_insert_state_does_not_leak_into_composites(
    editing_mode: EditingMode,
) -> None:
    """A stale helix INSERT state does not make composite filters report insert mode."""
    app = Application(editing_mode=editing_mode)
    app.helix_state.input_mode = InputMode.INSERT
    with set_app(app):
        if editing_mode is EditingMode.MICRO:
            # Micro genuinely is in insert mode by default.
            assert insert_mode()
        else:
            assert not replace_mode()


def test_stale_helix_navigation_state_does_not_leak_into_navigation_mode() -> None:
    """Micro mode is not reported as navigation mode via stale helix state.

    Regression test: ``navigation_mode`` is used bare in ``apptk.widgets.toolbars``
    to gate the command bar, so a leak here would misgate the ``:`` binding.
    """
    app = Application(editing_mode=EditingMode.MICRO)
    app.helix_state.input_mode = InputMode.NAVIGATION
    with set_app(app):
        assert not navigation_mode()


def test_helix_filters_true_in_helix_mode() -> None:
    """Helix filters report correctly when helix is the active editing mode."""
    app = Application(editing_mode=EditingMode.HELIX)
    app.helix_state.input_mode = InputMode.NAVIGATION
    app.helix_state.select_mode = False
    with set_app(app):
        assert helix_mode()
        assert helix_navigation_mode()
        assert helix_normal_mode()
        assert navigation_mode()
        assert not helix_insert_mode()
        assert not helix_select_mode()


def test_helix_select_mode_distinguished_from_normal_mode() -> None:
    """Select mode and normal mode are mutually exclusive."""
    app = Application(editing_mode=EditingMode.HELIX)
    app.helix_state.input_mode = InputMode.NAVIGATION
    app.helix_state.select_mode = True
    with set_app(app):
        assert helix_select_mode()
        assert not helix_normal_mode()


def test_helix_insert_mode_feeds_composite_insert_mode() -> None:
    """Helix insert mode enables the composite insert filter used for self-insert."""
    app = Application(editing_mode=EditingMode.HELIX)
    app.helix_state.input_mode = InputMode.INSERT
    with set_app(app):
        assert helix_insert_mode()
        assert insert_mode()


@pytest.mark.parametrize(
    ("sub_mode", "sub_filter"),
    [
        (HelixMode.GOTO, helix_goto_mode),
        (HelixMode.MATCH, helix_match_mode),
        (HelixMode.VIEW, helix_view_mode),
        (HelixMode.WINDOW, helix_window_mode),
        (HelixMode.SPACE, helix_space_mode),
    ],
)
def test_helix_sub_mode_filters(sub_mode: HelixMode, sub_filter: object) -> None:
    """Each helix sub-mode filter matches only its own sub-mode."""
    app = Application(editing_mode=EditingMode.HELIX)
    app.helix_state.mode = sub_mode
    with set_app(app):
        assert sub_filter()  # type: ignore[operator]
    app.helix_state.mode = HelixMode.NORMAL
    with set_app(app):
        assert not sub_filter()  # type: ignore[operator]


def test_micro_filters_unaffected_by_helix_guards() -> None:
    """Micro filters still work after the helix guard changes."""
    app = Application(editing_mode=EditingMode.MICRO)
    with set_app(app):
        assert micro_mode()
        assert micro_insert_mode()
        assert not micro_replace_mode()


def _focused_app(editing_mode: EditingMode = EditingMode.KAKOUNE) -> Application:
    """Build an application with a real focused buffer.

    Kakoune state is resolved per buffer, and a bare ``Application`` has no
    focused ``BufferControl`` - ``current_buffer`` then fabricates a throwaway
    buffer per access, so a write and a subsequent read would land on different
    states. Tests which mutate the state need a real one to resolve to.

    Args:
        editing_mode: The editing mode to start in.

    Returns:
        An application whose ``kakoune_state`` is stable across accesses.
    """
    from apptk.buffer import Buffer
    from apptk.layout import Layout, Window
    from apptk.layout.controls import BufferControl

    window = Window(BufferControl(Buffer(name="test-buffer")))
    layout = Layout(window, focused_element=window)
    return Application(layout=layout, editing_mode=editing_mode)


@pytest.mark.parametrize("editing_mode", NON_KAKOUNE_MODES)
@pytest.mark.parametrize("kakoune_filter", KAKOUNE_FILTERS)
def test_kakoune_filters_false_outside_kakoune_mode(
    editing_mode: EditingMode, kakoune_filter: object
) -> None:
    """Kakoune filters are False in other editing modes, whatever the state.

    All modes' bindings are loaded into one merged set, so a filter which trusted
    stale state would let Kakoune bindings fire while another mode was active.
    """
    app = _focused_app(editing_mode)
    # Leave stale Kakoune state behind, as a runtime edit-mode switch would.
    app.kakoune_state.input_mode = InputMode.INSERT
    app.kakoune_state.mode = KakouneMode.GOTO
    with set_app(app):
        assert not kakoune_filter()


@pytest.mark.parametrize("kakoune_filter", KAKOUNE_FILTERS)
def test_helix_and_kakoune_filters_are_mutually_exclusive(
    kakoune_filter: object,
) -> None:
    """No Kakoune filter fires while Helix is the active mode.

    The two modes share a great deal of behaviour, so this pins the one thing that
    keeps their bindings apart.
    """
    app = _focused_app(EditingMode.HELIX)
    app.helix_state.input_mode = InputMode.NAVIGATION
    app.kakoune_state.input_mode = InputMode.NAVIGATION
    with set_app(app):
        assert not kakoune_filter()


def test_kakoune_normal_mode_requires_no_sub_mode() -> None:
    """``kakoune_normal_mode`` is False while a sub-mode is active."""
    app = _focused_app()
    with set_app(app):
        app.kakoune_state.input_mode = InputMode.NAVIGATION
        app.kakoune_state.mode = KakouneMode.NORMAL
        assert kakoune_normal_mode()

        app.kakoune_state.mode = KakouneMode.GOTO
        assert not kakoune_normal_mode()
        assert kakoune_goto_mode()


def test_kakoune_insert_mode_joins_the_composite_filter() -> None:
    """Kakoune insert mode is visible to the shared ``insert_mode`` filter.

    That composite drives the cursor shape and the autopair bindings, so a mode
    missing from it would show the wrong cursor while inserting.
    """
    app = _focused_app()
    with set_app(app):
        app.kakoune_state.input_mode = InputMode.INSERT
        assert insert_mode()

        app.kakoune_state.input_mode = InputMode.NAVIGATION
        assert not insert_mode()
        assert navigation_mode()


def test_kakoune_replace_mode_joins_the_composite_filter() -> None:
    """Kakoune replace mode is visible to the shared ``replace_mode`` filter."""
    app = _focused_app()
    with set_app(app):
        app.kakoune_state.input_mode = InputMode.REPLACE
        assert replace_mode()


def test_kakoune_state_is_per_buffer() -> None:
    """Each buffer has its own Kakoune state, so cells do not share a mode."""
    from apptk.buffer import Buffer
    from apptk.layout import Layout, Window
    from apptk.layout.containers import HSplit
    from apptk.layout.controls import BufferControl

    first, second = Buffer(name="cell-a"), Buffer(name="cell-b")
    window_a = Window(BufferControl(first))
    window_b = Window(BufferControl(second))
    layout = Layout(HSplit([window_a, window_b]), focused_element=window_a)
    app = Application(layout=layout, editing_mode=EditingMode.KAKOUNE)

    app.kakoune_state.input_mode = InputMode.INSERT
    layout.focus(window_b)
    assert app.kakoune_state.input_mode == InputMode.NAVIGATION

    layout.focus(window_a)
    assert app.kakoune_state.input_mode == InputMode.INSERT
