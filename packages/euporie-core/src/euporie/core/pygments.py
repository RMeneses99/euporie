"""Contain lexers for pygments."""

from __future__ import annotations

from typing import ClassVar

from pygments.lexer import RegexLexer
from pygments.style import Style
from pygments.token import (
    Comment,
    Error,
    Generic,
    Keyword,
    Literal,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Text,
    Token,
    _TokenType,
)


class ArgparseLexer(RegexLexer):
    """A pygments lexer for agrparse help text."""

    name = "argparse"
    aliases: ClassVar[list[str]] = ["argparse"]
    filenames: ClassVar[list[str]] = []

    tokens: ClassVar[
        dict[str, list[tuple[str, _TokenType] | tuple[str, _TokenType, str]]]
    ] = {
        "root": [
            (r"(?<=usage: )[^\s]+", Name.Namespace),
            (r"\{", Operator, "options"),
            (r"[\[\{\|\}\]]", Operator),
            (r"((?<=\s)|(?<=\[))(--[a-zA-Z0-9-]+|-[a-zA-Z0-9-])", Keyword),
            (r"^(\w+\s)?\w+:", Generic.Heading),
            (r"\b(str|int|bool|UPath|loads)\b", Name.Builtin),
            (r"\b[A-Z]+_[A-Z]*\b", Name.Variable),
            (r"'.*?'", Literal.String),
            (r".", Text),
        ],
        "options": [
            (r"\d+", Literal.Number),
            (r",", Text),
            (r"[^\}]", Literal.String),
            (r"\}", Operator, "#pop"),
        ],
    }


class EuporiePygmentsStyle(Style):
    """ANSI color only pygments style.

    This is loosely based on Pygments' "native" style, modified to use ANSI colors
    instead of RGB. This adapts better to light/dark mode, because the built-in themes
    from a terminal are typically designed for whatever background is used.
    """

    styles: ClassVar[dict[_TokenType, str]] = {
        Comment: "italic ansibrightblack",
        Comment.Preproc: "noitalic bold ansired",
        Comment.Special: "noitalic bold ansired",
        Keyword: "bold ansigreen",
        Keyword.Pseudo: "nobold",
        Keyword.Constant: "nobold ansired",
        Operator.Word: "bold ansigreen",
        Literal.Date: "ansicyan",
        Literal.String: "ansiyellow",
        Literal.String.Other: "ansiyellow",
        Literal.Number: "ansibrightblue",
        Name.Builtin: "ansicyan",
        Name.Variable: "ansicyan",
        Name.Constant: "ansicyan",
        Name.Class: "underline ansibrightblue",
        Name.Function: "ansibrightblue",
        Name.Namespace: "underline ansibrightblue",
        Name.Exception: "noinherit bold",
        Name.Tag: "bold ansigreen",
        Name.Attribute: "noinherit",
        Name.Decorator: "ansiyellow",
        Generic.Heading: "bold",
        Generic.Subheading: "underline",
        Generic.Deleted: "ansired",
        Generic.Inserted: "ansigreen",
        Generic.Error: "ansired",
        Generic.Emph: "italic",
        Generic.Strong: "bold",
        Generic.Traceback: "ansired",
        Error: "bold ansired",
    }


#: The Morphogenesis brightness ramp. Tokens are ranked by *luminance*, not hue, so
#: the eye can tell what matters without learning arbitrary colour-to-concept
#: mappings. Contrast is measured against the ``#0d1b2a`` base; the descent is
#: monotonic, which is what makes the mapping checkable rather than a matter of
#: taste. See ``MORPHOGENESIS-SYNTAX.md``.
MORPHOGENESIS_RAMP: dict[str, str] = {
    "plain": "#e8f0fe",  # 15.2:1 - body text, unclassified tokens
    "light": "#a8d4ff",  # 11.2:1 - variables, identifiers, labels, tags
    "accent": "#00d4ff",  # 9.8:1 - functions, types, constructors, namespaces
    "mid": "#7eb8f7",  # 8.4:1 - strings, constants, escapes, attributes
    "dim": "#8ab4d4",  # 7.9:1 - comments
    "muted": "#5a9fe0",  # 6.2:1 - keywords, imports, storage
    "dimmest": "#6c8aa8",  # 4.8:1 - punctuation, operators, delimiters
    "error": "#ff6b6b",  # 6.3:1 - errors
    "warning": "#ffd93d",  # 12.6:1 - warnings, deprecated
    "added": "#69ff94",  # diff added
    "moved": "#c792ea",  # diff moved, secondary
}


class MorphogenesisStyle(Style):
    """A dark blue pygments style which ranks tokens by brightness, not hue.

    Unlike :py:class:`EuporiePygmentsStyle`, which uses ANSI colour names so that it
    adapts to whatever scheme the terminal provides, this style uses explicit hex
    values: the point of it is a specific, measured brightness ladder, which named
    ANSI colours cannot express.

    Two placements are deliberate and easily got wrong:

    Punctuation is the dimmest thing on screen. Brackets, commas and semicolons are
    the most frequent tokens in most languages and carry almost no information once
    the language is known, so anything bright there is tiring to read.

    Keywords are muted rather than bold. They are frequent enough that emphasising
    them competes with the definitions actually being scanned for.

    Warm colours are reserved for genuine outliers, so a correct file shows none.
    """

    name = "morphogenesis"

    background_color = "#0d1b2a"
    highlight_color = "#1a3a5c"
    line_number_color = "#2a3f54"
    line_number_special_color = "#00d4ff"

    styles: ClassVar[dict[_TokenType, str]] = {
        # Plain text
        Token: MORPHOGENESIS_RAMP["plain"],
        Text: MORPHOGENESIS_RAMP["plain"],
        # ``Whitespace`` is deliberately unset. A foreground on a token which
        # renders nothing is pointless, and visible whitespace markers are the
        # application's own chrome - the specification gives them ``#2a3f54``,
        # a surface colour which must never be used for text.
        # Structural noise - deliberately the dimmest tier
        Punctuation: MORPHOGENESIS_RAMP["dimmest"],
        Operator: MORPHOGENESIS_RAMP["dimmest"],
        # Comments
        Comment: f"italic {MORPHOGENESIS_RAMP['dim']}",
        Comment.Preproc: f"noitalic {MORPHOGENESIS_RAMP['muted']}",
        Comment.PreprocFile: f"noitalic {MORPHOGENESIS_RAMP['mid']}",
        # Identifiers
        Name: MORPHOGENESIS_RAMP["light"],
        Name.Variable: MORPHOGENESIS_RAMP["light"],
        Name.Label: MORPHOGENESIS_RAMP["light"],
        Name.Tag: MORPHOGENESIS_RAMP["light"],
        Name.Property: MORPHOGENESIS_RAMP["light"],
        # Definitions - the only saturated hue in the blues
        Name.Function: MORPHOGENESIS_RAMP["accent"],
        Name.Function.Magic: MORPHOGENESIS_RAMP["accent"],
        Name.Class: MORPHOGENESIS_RAMP["accent"],
        Name.Namespace: MORPHOGENESIS_RAMP["accent"],
        Name.Builtin: MORPHOGENESIS_RAMP["accent"],
        Name.Builtin.Pseudo: MORPHOGENESIS_RAMP["accent"],
        Name.Exception: MORPHOGENESIS_RAMP["accent"],
        Name.Entity: MORPHOGENESIS_RAMP["accent"],
        # Supporting detail
        String: MORPHOGENESIS_RAMP["mid"],
        String.Escape: MORPHOGENESIS_RAMP["mid"],
        String.Regex: MORPHOGENESIS_RAMP["mid"],
        String.Interpol: MORPHOGENESIS_RAMP["mid"],
        String.Affix: MORPHOGENESIS_RAMP["muted"],
        Number: MORPHOGENESIS_RAMP["mid"],
        Literal: MORPHOGENESIS_RAMP["mid"],
        Name.Constant: MORPHOGENESIS_RAMP["mid"],
        Name.Attribute: MORPHOGENESIS_RAMP["mid"],
        Name.Decorator: MORPHOGENESIS_RAMP["mid"],
        # Keywords - muted, not bold
        Keyword: MORPHOGENESIS_RAMP["muted"],
        Keyword.Constant: MORPHOGENESIS_RAMP["mid"],
        Keyword.Namespace: MORPHOGENESIS_RAMP["muted"],
        Keyword.Pseudo: MORPHOGENESIS_RAMP["muted"],
        Keyword.Reserved: MORPHOGENESIS_RAMP["muted"],
        # A type is a definition, not a keyword
        Keyword.Type: MORPHOGENESIS_RAMP["accent"],
        Operator.Word: MORPHOGENESIS_RAMP["muted"],
        # Markup
        Generic.Heading: f"bold {MORPHOGENESIS_RAMP['accent']}",
        Generic.Subheading: f"bold {MORPHOGENESIS_RAMP['accent']}",
        Generic.Strong: f"bold {MORPHOGENESIS_RAMP['light']}",
        Generic.Emph: f"italic {MORPHOGENESIS_RAMP['light']}",
        Generic.Output: MORPHOGENESIS_RAMP["plain"],
        Generic.Prompt: MORPHOGENESIS_RAMP["dimmest"],
        # Diff
        Generic.Inserted: MORPHOGENESIS_RAMP["added"],
        Generic.Deleted: MORPHOGENESIS_RAMP["error"],
        # Outliers - warm, so a healthy file shows none
        Generic.Error: f"bold {MORPHOGENESIS_RAMP['error']}",
        Generic.Traceback: MORPHOGENESIS_RAMP["error"],
        Error: f"bold {MORPHOGENESIS_RAMP['error']}",
        Comment.Special: f"bold {MORPHOGENESIS_RAMP['warning']}",
    }
