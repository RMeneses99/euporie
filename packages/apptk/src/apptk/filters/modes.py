"""Define common filters."""

from __future__ import annotations

from apptk.enums import EditingMode
from apptk.filters.app import (
    emacs_insert_mode,
    emacs_mode,
    vi_insert_mode,
    vi_mode,
    vi_navigation_mode,
    vi_replace_mode,
)
from apptk.filters.base import Condition
from apptk.key_binding.helix_state import InputMode as HelixInputMode
from apptk.key_binding.kakoune_state import InputMode as KakouneInputMode
from apptk.key_binding.kakoune_state import KakouneMode
from apptk.key_binding.micro_state import MicroInputMode

__all__ = [
    "helix_goto_mode",
    "helix_insert_mode",
    "helix_match_mode",
    "helix_mode",
    "helix_navigation_mode",
    "helix_normal_mode",
    "helix_replace_mode",
    "helix_select_mode",
    "helix_space_mode",
    "helix_view_mode",
    "helix_window_mode",
    "insert_mode",
    "kakoune_goto_mode",
    "kakoune_insert_mode",
    "kakoune_mode",
    "kakoune_navigation_mode",
    "kakoune_normal_mode",
    "kakoune_replace_mode",
    "kakoune_user_mode",
    "kakoune_view_mode",
    "micro_insert_mode",
    "micro_mode",
    "micro_recording_macro",
    "micro_replace_mode",
    "navigation_mode",
    "replace_mode",
]


@Condition
def helix_mode() -> bool:
    """When the helix key-bindings are active."""
    from apptk.application.current import get_app

    return get_app().editing_mode == EditingMode.HELIX


@Condition
def helix_insert_mode() -> bool:
    """Determine if the editor is in helix insert mode."""
    from apptk.application.current import get_app

    app = get_app()
    if app.editing_mode != EditingMode.HELIX:
        return False
    return app.helix_state.input_mode == HelixInputMode.INSERT


@Condition
def helix_navigation_mode() -> bool:
    """Determine if the editor is in helix navigation mode."""
    from apptk.application.current import get_app

    app = get_app()
    if app.editing_mode != EditingMode.HELIX:
        return False
    return app.helix_state.input_mode == HelixInputMode.NAVIGATION


@Condition
def helix_replace_mode() -> bool:
    """Determine if the editor is in helix replace mode."""
    from apptk.application.current import get_app

    app = get_app()
    if app.editing_mode != EditingMode.HELIX:
        return False
    return app.helix_state.input_mode in (
        HelixInputMode.REPLACE,
        HelixInputMode.REPLACE_SINGLE,
    )


@Condition
def helix_normal_mode() -> bool:
    """Determine if in helix normal mode: navigation, without explicit select mode."""
    from apptk.application.current import get_app

    app = get_app()
    if app.editing_mode != EditingMode.HELIX:
        return False
    return (
        app.helix_state.input_mode == HelixInputMode.NAVIGATION
        and not app.helix_state.select_mode
    )


@Condition
def helix_select_mode() -> bool:
    """Determine if in helix select/extend mode, entered via ``v``."""
    from apptk.application.current import get_app

    app = get_app()
    if app.editing_mode != EditingMode.HELIX:
        return False
    return (
        app.helix_state.input_mode == HelixInputMode.NAVIGATION
        and app.helix_state.select_mode
    )


@Condition
def helix_goto_mode() -> bool:
    """Determine if the helix goto sub-mode is active."""
    from apptk.application.current import get_app

    app = get_app()
    if app.editing_mode != EditingMode.HELIX:
        return False
    return app.helix_state.goto_mode


@Condition
def helix_match_mode() -> bool:
    """Determine if the helix match sub-mode is active."""
    from apptk.application.current import get_app

    app = get_app()
    if app.editing_mode != EditingMode.HELIX:
        return False
    return app.helix_state.match_mode


@Condition
def helix_view_mode() -> bool:
    """Determine if the helix view sub-mode is active."""
    from apptk.application.current import get_app

    app = get_app()
    if app.editing_mode != EditingMode.HELIX:
        return False
    return app.helix_state.view_mode


@Condition
def helix_window_mode() -> bool:
    """Determine if the helix window sub-mode is active."""
    from apptk.application.current import get_app

    app = get_app()
    if app.editing_mode != EditingMode.HELIX:
        return False
    return app.helix_state.window_mode


@Condition
def helix_space_mode() -> bool:
    """Determine if the helix space sub-mode is active."""
    from apptk.application.current import get_app

    app = get_app()
    if app.editing_mode != EditingMode.HELIX:
        return False
    return app.helix_state.space_mode


@Condition
def kakoune_mode() -> bool:
    """When the kakoune key-bindings are active."""
    from apptk.application.current import get_app

    return get_app().editing_mode == EditingMode.KAKOUNE


def _kakoune_state() -> object | None:
    """Return the current buffer's Kakoune state, or None outside Kakoune mode.

    Every filter below re-checks the editing mode first: all modes' bindings are
    loaded into one merged set, so a filter which trusted stale state would let
    Kakoune bindings fire while another mode is active.

    Returns:
        The state for the focused buffer, or None when Kakoune is not active.
    """
    from apptk.application.current import get_app

    app = get_app()
    if app.editing_mode != EditingMode.KAKOUNE:
        return None
    return app.kakoune_state


@Condition
def kakoune_insert_mode() -> bool:
    """Determine if the editor is in kakoune insert mode."""
    state = _kakoune_state()
    return state is not None and state.input_mode == KakouneInputMode.INSERT


@Condition
def kakoune_navigation_mode() -> bool:
    """Determine if the editor is in kakoune normal (navigation) mode."""
    state = _kakoune_state()
    return state is not None and state.input_mode == KakouneInputMode.NAVIGATION


@Condition
def kakoune_replace_mode() -> bool:
    """Determine if the editor is in kakoune replace mode."""
    state = _kakoune_state()
    return state is not None and state.input_mode in (
        KakouneInputMode.REPLACE,
        KakouneInputMode.REPLACE_SINGLE,
    )


@Condition
def kakoune_normal_mode() -> bool:
    """Determine if in kakoune normal mode, with no sub-mode active.

    Kakoune has no select mode - Shift extends selections instead - so unlike the
    Helix equivalent this is simply navigation mode outside any sub-mode.
    """
    state = _kakoune_state()
    return (
        state is not None
        and state.input_mode == KakouneInputMode.NAVIGATION
        and state.mode == KakouneMode.NORMAL
    )


@Condition
def kakoune_goto_mode() -> bool:
    """Determine if a kakoune goto sub-mode is active (``g`` or ``G``)."""
    state = _kakoune_state()
    return state is not None and state.mode in (
        KakouneMode.GOTO,
        KakouneMode.GOTO_EXTEND,
    )


@Condition
def kakoune_view_mode() -> bool:
    """Determine if a kakoune view sub-mode is active (``v`` or locked ``V``)."""
    state = _kakoune_state()
    return state is not None and state.mode in (
        KakouneMode.VIEW,
        KakouneMode.VIEW_LOCKED,
    )


@Condition
def kakoune_user_mode() -> bool:
    """Determine if the kakoune user sub-mode is active (:kbd:`Space`)."""
    state = _kakoune_state()
    return state is not None and state.mode == KakouneMode.USER


@Condition
def micro_mode() -> bool:
    """When the micro key-bindings are active."""
    from apptk.application.current import get_app

    return get_app().editing_mode == EditingMode.MICRO


@Condition
def micro_replace_mode() -> bool:
    """Determine if the editor is in overwrite mode."""
    from apptk.application.current import get_app

    app = get_app()
    return app.micro_state.input_mode == MicroInputMode.REPLACE


@Condition
def micro_insert_mode() -> bool:
    """Determine if the editor is in insert mode."""
    from apptk.application.current import get_app

    app = get_app()
    return app.micro_state.input_mode == MicroInputMode.INSERT


@Condition
def micro_recording_macro() -> bool:
    """Determine if a micro macro is being recorded."""
    from apptk.application.current import get_app

    return get_app().micro_state.current_recording is not None


"""Determine if any binding style is in insert mode."""
insert_mode = (
    (vi_mode & vi_insert_mode)
    | (emacs_mode & emacs_insert_mode)
    | (micro_mode & micro_insert_mode)
    | helix_insert_mode
    | kakoune_insert_mode
)

"""Determine if any binding style is in replace mode."""
replace_mode = (
    (micro_mode & micro_replace_mode)
    | (vi_mode & vi_replace_mode)
    | helix_replace_mode
    | kakoune_replace_mode
)

"""Determine if any binding style is in navigation mode."""
navigation_mode = (
    (vi_mode & vi_navigation_mode) | helix_navigation_mode | kakoune_navigation_mode
)

"""Determine if the current editing mode is exitable."""
exitable_mode = (
    (vi_mode & ~vi_navigation_mode)
    | (helix_mode & ~helix_navigation_mode)
    # Gated on *not* being in navigation mode, exactly as the other modes are: a
    # mode claims Escape while it still has state to unwind, and releases it in
    # navigation mode so the host can use it. Kakoune leaves Escape unbound in
    # normal mode, so euporie's ``_exit_edit_mode`` gets it and leaves the cell.
    | (kakoune_mode & ~kakoune_navigation_mode)
    | (micro_mode & ~micro_insert_mode)
    | (emacs_mode & ~emacs_insert_mode)
)
