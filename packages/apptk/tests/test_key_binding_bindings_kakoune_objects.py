"""Test text objects, matching-pair motions and character search in Kakoune mode.

Kakoune's object type keys differ from Helix's - ``B`` is the curly block where
Helix uses ``c``, and ``Q``/``q``/``g`` distinguish the three quote kinds - and
Kakoune has objects Helix lacks: sentences, indentation blocks, numbers and
arguments. ``m`` is a motion here, not a sub-mode prefix.
"""

from __future__ import annotations

import pytest
from kakoune_utils import make_event, make_kakoune_app, run_kakoune, selection_ranges

from apptk.application.current import set_app
from apptk.buffer import Buffer
from apptk.commands import get_cmd
from apptk.document import Document


def _object(
    text: str, entry: str, type_key: str, cursor: int, *, arg: str | None = None
) -> list[str]:
    """Apply an object-entry command followed by a type key, returning the text."""
    buffer = Buffer(document=Document(text, cursor), multiline=True)
    app = make_kakoune_app(buffer)
    with set_app(app):
        get_cmd(entry).handler(make_event(app))
        get_cmd("kakoune-handle-object").handler(
            make_event(app, data=type_key, arg=arg)
        )
    return [text[s:e] for s, e in selection_ranges(buffer)]


CODE = 'call(a, "str", [1,2])'


# Object selection


@pytest.mark.parametrize(
    ("type_key", "cursor", "expected"),
    [
        ("b", 6, 'a, "str", [1,2]'),
        ("r", 16, "1,2"),
        ("Q", 10, "str"),
        ("w", 1, "call"),
    ],
)
def test_inner_object_selection(type_key: str, cursor: int, expected: str) -> None:
    """``<a-i>`` selects inside the named object."""
    assert _object(CODE, "kakoune-object-select-inner", type_key, cursor) == [expected]


def test_whole_object_includes_the_delimiters() -> None:
    """``<a-a>`` includes the surrounding characters."""
    assert _object(CODE, "kakoune-object-select-whole", "b", 6) == ['(a, "str", [1,2])']


def test_curly_block_uses_capital_b() -> None:
    """``B`` is the curly block.

    NOTE: Helix spells this ``c``, so the two tables are not interchangeable.
    """
    assert _object("if x { y }", "kakoune-object-select-inner", "B", 7) == [" y "]


@pytest.mark.parametrize(
    ("type_key", "text", "cursor", "expected"),
    [
        ("q", "a 'b c' d", 4, "b c"),
        ("g", "a `b c` d", 4, "b c"),
    ],
)
def test_quote_kinds_are_distinguished(
    type_key: str, text: str, cursor: int, expected: str
) -> None:
    """``Q``, ``q`` and ``g`` select double, single and grave quotes."""
    assert _object(text, "kakoune-object-select-inner", type_key, cursor) == [expected]


def test_sentence_object() -> None:
    """``s`` selects a sentence, which Helix's implementation lacks."""
    text = "He went home. She left! Third one?"
    assert _object(text, "kakoune-object-select-inner", "s", 16) == ["She left!"]


def test_indent_object_selects_a_python_suite() -> None:
    """``i`` selects the indentation block - the object that matters for Python."""
    code = "def f():\n    if x:\n        a = 1\n        b = 2\n    c = 3\n"
    assert _object(code, "kakoune-object-select-inner", "i", code.index("a = 1")) == [
        "        a = 1\n        b = 2"
    ]


def test_indent_object_whole_includes_the_introducing_line() -> None:
    """``<a-a>i`` takes in the line which opens the block."""
    code = "def f():\n    if x:\n        a = 1\n    c = 3\n"
    selected = _object(code, "kakoune-object-select-whole", "i", code.index("a = 1"))
    assert selected == ["    if x:\n        a = 1"]


@pytest.mark.parametrize(
    ("cursor", "expected"),
    [(6, "a"), (9, "b=2")],
)
def test_argument_object(cursor: int, expected: str) -> None:
    """``u`` selects one comma-separated argument."""
    assert _object("def f(a, b=2):", "kakoune-object-select-inner", "u", cursor) == [
        expected
    ]


def test_number_object() -> None:
    """``n`` selects the number under the cursor, including a decimal point."""
    assert _object("v = 3.14", "kakoune-object-select-inner", "n", 6) == ["3.14"]


def test_punctuation_acts_as_its_own_delimiter() -> None:
    """Any punctuation type key delimits the object.

    Kakoune's own example: with the cursor inside ``/home/bar``, ``<a-a>/``
    selects ``/home/``.
    """
    assert _object("/home/bar", "kakoune-object-select-whole", "/", 2) == ["/home/"]


def test_object_count_selects_an_outer_level() -> None:
    """A count picks which enclosing pair to select, for nestable objects."""
    assert _object("f(g(h(x)))", "kakoune-object-select-whole", "b", 6, arg="2") == [
        "(h(x))"
    ]


def test_bracket_goes_to_the_object_start() -> None:
    """``[`` selects from the cursor back to the object's start."""
    selected = _object(CODE, "kakoune-object-to-start-whole", "b", 10)
    assert selected == ['(a, "s']


def test_brace_goes_to_the_object_end() -> None:
    """``]`` selects from the cursor forward to the object's end."""
    selected = _object(CODE, "kakoune-object-to-end-whole", "b", 10)
    assert selected == ['tr", [1,2])']


def test_unresolvable_object_leaves_selections_alone() -> None:
    """An object which cannot be found rings the bell instead of raising."""
    buffer = Buffer(document=Document("plain text", 0), multiline=True)
    app = make_kakoune_app(buffer)
    with set_app(app):
        get_cmd("kakoune-object-select-inner").handler(make_event(app))
        get_cmd("kakoune-handle-object").handler(make_event(app, data="b"))
    assert buffer.text == "plain text"


# Matching pairs - motions, not a sub-mode


MATCH_TEXT = "f(g(x)) end"


@pytest.mark.parametrize(
    ("command", "cursor", "expected"),
    [
        ("kakoune-match-next", 0, "(g(x))"),
        ("kakoune-match-next", 2, "(x)"),
        ("kakoune-match-prev", 6, "(g(x))"),
    ],
)
def test_matching_pair_motions(command: str, cursor: int, expected: str) -> None:
    """``m`` and ``<a-m>`` select to the next or previous matching pair.

    NOTE: Helix uses ``m`` to enter match mode. Kakoune has no match mode; ``m``
    is a motion, which is the largest structural difference between the keymaps.
    """
    buffer, _ = run_kakoune(MATCH_TEXT, command, cursor=cursor)
    assert [MATCH_TEXT[s:e] for s, e in selection_ranges(buffer)] == [expected]


def test_match_extend_keeps_the_anchor() -> None:
    """``M`` extends to the matching pair rather than replacing the selection."""
    buffer, _ = run_kakoune(MATCH_TEXT, "kakoune-match-next-extend", cursor=0)
    ranges = selection_ranges(buffer)
    assert ranges[0][0] == 0


def test_no_matching_pair_rings_the_bell() -> None:
    """With nothing to match the selection is left alone."""
    buffer, _ = run_kakoune("no pairs here", "kakoune-match-next", cursor=0)
    assert selection_ranges(buffer) == [(0, 1)]


# Character search


def _char_search(command: str, char: str, cursor: int, text: str) -> list[str]:
    """Apply a character-search command followed by its character."""
    buffer = Buffer(document=Document(text, cursor), multiline=True)
    app = make_kakoune_app(buffer)
    with set_app(app):
        get_cmd(command).handler(make_event(app))
        get_cmd("kakoune-handle-char").handler(make_event(app, data=char))
    return [text[s:e] for s, e in selection_ranges(buffer)]


@pytest.mark.parametrize(
    ("command", "char", "cursor", "expected"),
    [
        ("kakoune-find-char", "t", 0, "one t"),
        ("kakoune-find-till-char", "t", 0, "one "),
        ("kakoune-find-char-backward", "o", 6, "one two"),
    ],
)
def test_character_search(command: str, char: str, cursor: int, expected: str) -> None:
    """``f`` and ``t`` select to and until a character.

    NOTE: Kakoune reverses direction with Alt (``<a-f>``), where Helix uses
    Shift (``F``). Shift here is the extending form.
    """
    assert _char_search(command, char, cursor, "one two three") == [expected]


def test_character_search_records_for_repeat() -> None:
    """``f`` stores its target so ``<a-.>`` can repeat it."""
    buffer = Buffer(document=Document("a.b.c", 0), multiline=True)
    app = make_kakoune_app(buffer)
    with set_app(app):
        get_cmd("kakoune-find-char").handler(make_event(app))
        get_cmd("kakoune-handle-char").handler(make_event(app, data="."))
        assert app.kakoune_state.last_char_find == ("f", ".")


def test_missing_character_rings_the_bell() -> None:
    """Searching for an absent character leaves the selection alone."""
    assert _char_search("kakoune-find-char", "z", 0, "one two") == ["o"]
