"""Test the ``custom_styles`` configuration option.

The setting is the documented route for overriding individual style keys, which
matters because euporie otherwise *derives* every style arithmetically from the
colour palette - so a theme needing specific colours cannot express them any other
way. It was defined, documented with a worked example and registered on the app, but
read nowhere, so it silently did nothing.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from euporie.core.app.app import _custom_style

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_overrides_become_style_rules() -> None:
    """Each configured entry becomes a style rule."""
    style = _custom_style({"cell input prompt": "fg:#ff00ff", "status": "bg:#1a3a5c"})
    assert style.style_rules == [
        ("cell input prompt", "fg:#ff00ff"),
        ("status", "bg:#1a3a5c"),
    ]


def test_no_overrides_gives_an_empty_style() -> None:
    """An unset option contributes nothing, rather than failing."""
    assert _custom_style({}).style_rules == []


def test_order_is_preserved() -> None:
    """Rules keep their configured order.

    prompt_toolkit resolves later rules over earlier ones, so a user listing two
    rules for overlapping selectors gets the one they wrote last.
    """
    style = _custom_style({"a": "fg:#111111", "b": "fg:#222222", "c": "fg:#333333"})
    assert [name for name, _ in style.style_rules] == ["a", "b", "c"]


def test_overrides_reach_the_application_style(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configured override is present in the application's merged style.

    This is the regression test for the original fault: the value loaded correctly
    from configuration but never reached the style merge.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config_dir = tmp_path / "euporie"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.toml").write_text(
        '[custom_styles]\n"cell input prompt" = "fg:#ff00ff"\n'
    )

    from euporie.notebook.app import NotebookApp

    NotebookApp.config.load(args=[])
    app = NotebookApp()

    def rules(style: object) -> list[tuple[str, str]]:
        """Collect style rules from a merged style tree.

        Recurses rather than calling ``style_rules`` on the root, because the
        palette-derived styles need a live terminal to resolve ANSI colours.
        """
        found: list[tuple[str, str]] = []
        for child in getattr(style, "styles", []) or []:
            found += rules(child)
        # A palette-derived style raises here without a live terminal, which is
        # fine: only the user's own rules are being looked for.
        with contextlib.suppress(Exception):
            found += list(style.style_rules)  # type: ignore[attr-defined]
        return found

    assert ("cell input prompt", "fg:#ff00ff") in rules(app.style)
