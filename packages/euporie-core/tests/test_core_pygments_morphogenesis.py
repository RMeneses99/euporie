"""Test the Morphogenesis pygments style against its specification.

Morphogenesis ranks syntax tokens by *brightness* rather than hue, and defines each
tier by a measured contrast ratio against a fixed base. That makes the port
checkable rather than subjective: the relative luminance of every colour assigned
can be computed and the tier ordering asserted, so a mapping which puts a token at
the wrong brightness fails here rather than merely looking wrong.

The specification is ``MORPHOGENESIS-SYNTAX.md`` in the repository root.
"""

from __future__ import annotations

import pytest
from pygments.styles import get_all_styles, get_style_by_name
from pygments.token import (
    Comment,
    Error,
    Generic,
    Keyword,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Text,
)

from euporie.core.pygments import MORPHOGENESIS_RAMP, MorphogenesisStyle

#: The base the specification measures every contrast ratio against.
BASE = "#0d1b2a"

#: Surfaces, at 1.5:1 and 1.6:1. Legitimate for a selection background or a
#: whitespace marker, where position carries the meaning; never for text.
SURFACES_ONLY = {"#1a3a5c", "#2a3f54"}


def _channel(value: int) -> float:
    """Linearise one sRGB channel, per the WCAG definition."""
    fraction = value / 255
    if fraction <= 0.03928:
        return fraction / 12.92
    return ((fraction + 0.055) / 1.055) ** 2.4


def _luminance(hex_colour: str) -> float:
    """Return the WCAG relative luminance of a hex colour."""
    text = hex_colour.lstrip("#")
    red, green, blue = (int(text[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def _contrast(first: str, second: str) -> float:
    """Return the WCAG contrast ratio between two hex colours."""
    light, dark = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _colour_of(token: object) -> str | None:
    """Return the hex colour the style assigns a token, if any."""
    for word in str(MorphogenesisStyle.styles.get(token, "")).split():
        if word.startswith("#"):
            return word
    return None


# Registration


def test_style_is_discoverable() -> None:
    """The style is registered through the ``pygments.styles`` entry point.

    Without the entry point the style exists but cannot be selected by name, which
    is how ``syntax_theme`` refers to it.
    """
    assert "morphogenesis" in set(get_all_styles())
    assert get_style_by_name("morphogenesis") is MorphogenesisStyle


def test_style_name_validates_against_the_setting() -> None:
    """``syntax_theme = "morphogenesis"`` passes schema validation.

    The enum was previously built from Pygments' built-ins only, so an entry-point
    style was rejected and the setting silently fell back to its default.
    """
    import fastjsonschema

    from euporie.core.settings import syntax_theme

    fastjsonschema.compile(syntax_theme.schema)("morphogenesis")


def test_base_matches_the_specification() -> None:
    """The style's background is the base every ratio is measured against."""
    assert MorphogenesisStyle.background_color == BASE


# The brightness ramp


def test_the_descent_is_monotonic() -> None:
    """Each tier is dimmer than the one above it.

    This is the property the whole theme rests on. A tier out of order means the
    brightness no longer communicates rank, which is the theme's entire mechanism.
    """
    order = ["plain", "light", "accent", "mid", "dim", "muted", "dimmest"]
    luminances = [_luminance(MORPHOGENESIS_RAMP[tier]) for tier in order]
    assert luminances == sorted(luminances, reverse=True), dict(zip(order, luminances))


@pytest.mark.parametrize(
    ("tier", "expected"),
    [
        ("plain", 15.2),
        ("light", 11.2),
        ("accent", 9.8),
        ("mid", 8.4),
        ("dim", 7.9),
        ("muted", 6.2),
        ("dimmest", 4.8),
    ],
)
def test_contrast_matches_the_specification(tier: str, expected: float) -> None:
    """Each tier's contrast against the base is what the specification states."""
    actual = _contrast(MORPHOGENESIS_RAMP[tier], BASE)
    assert actual == pytest.approx(expected, abs=0.1), f"{tier} is {actual:.1f}:1"


def test_accent_is_not_the_brightest_tier() -> None:
    """Cyan stands out by saturation, not by being the lightest thing on screen.

    The specification calls this out explicitly: plain text and identifiers outrank
    the accent numerically.
    """
    assert _luminance(MORPHOGENESIS_RAMP["accent"]) < _luminance(
        MORPHOGENESIS_RAMP["light"]
    )
    assert _luminance(MORPHOGENESIS_RAMP["accent"]) < _luminance(
        MORPHOGENESIS_RAMP["plain"]
    )


# Token placement


def test_punctuation_is_the_dimmest_thing_on_screen() -> None:
    """Punctuation and operators sit at the bottom of the ramp.

    They are the most frequent tokens in most languages and carry almost no
    information once the language is known, so anything bright there is tiring.
    """
    dimmest = _luminance(MORPHOGENESIS_RAMP["dimmest"])
    for token in (Punctuation, Operator):
        colour = _colour_of(token)
        assert colour is not None
        assert _luminance(colour) == pytest.approx(dimmest)


def test_keywords_are_muted_and_not_bold() -> None:
    """A keyword is legible and obviously a keyword without shouting."""
    assert _colour_of(Keyword) == MORPHOGENESIS_RAMP["muted"]
    assert "bold" not in MorphogenesisStyle.styles[Keyword]


def test_definitions_get_the_accent() -> None:
    """Functions, classes and types are what the eye should find fast."""
    for token in (Name.Function, Name.Class, Name.Namespace, Keyword.Type):
        assert _colour_of(token) == MORPHOGENESIS_RAMP["accent"], token


def test_comments_are_italic() -> None:
    """Comments are dim and italic, per the specification."""
    assert _colour_of(Comment) == MORPHOGENESIS_RAMP["dim"]
    assert "italic" in MorphogenesisStyle.styles[Comment]


def test_keywords_are_dimmer_than_definitions() -> None:
    """The ordering that matters most in practice.

    Keywords are frequent; definitions are what you scan for. If a keyword outranks
    a function name, the file reads as noise.
    """
    assert _luminance(MORPHOGENESIS_RAMP["muted"]) < _luminance(
        MORPHOGENESIS_RAMP["accent"]
    )


@pytest.mark.parametrize(
    ("token", "tier"),
    [
        (Text, "plain"),
        (Name, "light"),
        (String, "mid"),
        (Number, "mid"),
    ],
)
def test_tier_assignments(token: object, tier: str) -> None:
    """Representative tokens sit in the tier the specification assigns them."""
    assert _colour_of(token) == MORPHOGENESIS_RAMP[tier]


# Outliers


def test_warm_colours_are_reserved_for_outliers() -> None:
    """Errors are warm and bold; nothing in ordinary code is warm.

    The specification's stated acceptance criterion is that a correct file shows no
    warm colour at all.
    """
    assert _colour_of(Error) == MORPHOGENESIS_RAMP["error"]
    assert "bold" in MorphogenesisStyle.styles[Error]

    ordinary = (Text, Name, String, Number, Keyword, Comment, Punctuation, Operator)
    warm = {MORPHOGENESIS_RAMP["error"], MORPHOGENESIS_RAMP["warning"]}
    for token in ordinary:
        assert _colour_of(token) not in warm, token


def test_diff_roles_keep_their_meaning() -> None:
    """Added and removed use the palette's semantic green and red."""
    assert _colour_of(Generic.Inserted) == MORPHOGENESIS_RAMP["added"]
    assert _colour_of(Generic.Deleted) == MORPHOGENESIS_RAMP["error"]


# Contrast floors


def test_every_text_colour_clears_wcag_aa() -> None:
    """No token is assigned a colour too dim to read against the base."""
    for token in MorphogenesisStyle.styles:
        colour = _colour_of(token)
        if colour is None:
            continue
        ratio = _contrast(colour, BASE)
        assert ratio >= 4.5, f"{token} at {colour} is only {ratio:.1f}:1"


def test_surfaces_are_never_used_for_text() -> None:
    """The specification's most-warned-about trap.

    ``#1a3a5c`` and ``#2a3f54`` are legitimate as a selection background or a
    whitespace marker, where position carries the meaning and the colour only has
    to be perceptible. As text they fail badly, at 1.5:1 and 1.6:1.
    """
    for surface in SURFACES_ONLY:
        assert _contrast(surface, BASE) < 2.0, "guard assumption"

    for token in MorphogenesisStyle.styles:
        assert _colour_of(token) not in SURFACES_ONLY, token
