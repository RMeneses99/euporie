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
    micro_insert_mode,
    micro_mode,
    micro_replace_mode,
    navigation_mode,
    replace_mode,
)
from apptk.key_binding.helix_state import HelixMode, InputMode

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

NON_HELIX_MODES = [EditingMode.VI, EditingMode.EMACS, EditingMode.MICRO]


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
