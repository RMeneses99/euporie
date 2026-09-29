"""Test module for euporie.core.lsp."""

from __future__ import annotations

import sys
from functools import partial
from unittest.mock import Mock, patch

from euporie.core.lsp import range_to_slice


def test_range_to_slice_single_line() -> None:
    """A range within a single line maps to character positions."""
    text = "hello world"
    result = range_to_slice(0, 0, 0, 5, text)
    assert result == slice(0, 5)
    assert text[result] == "hello"


def test_range_to_slice_multi_line() -> None:
    """A range spanning multiple lines accounts for newline characters."""
    text = "abc\ndef\nghi"
    result = range_to_slice(1, 0, 2, 3, text)
    assert text[result] == "def\nghi"


def test_range_to_slice_partial_lines() -> None:
    """A range with character offsets on start and end lines."""
    text = "abc\ndef\nghi"
    result = range_to_slice(0, 1, 2, 1, text)
    assert text[result] == "bc\ndef\ng"


def test_range_to_slice_empty_range() -> None:
    """A zero-width range produces an empty slice."""
    text = "abc\ndef"
    result = range_to_slice(1, 1, 1, 1, text)
    assert text[result] == ""


# Server launch gating
#
# Several language servers are configured by default for a given language - Python
# defaults to ty, ruff, jedi and pylsp - so an absent executable is the normal case
# rather than an error. ``_create_lsp_client`` checks before launching, which keeps
# a missing server out of the exception path.


def _app_stub(configs: dict) -> object:
    """Build the minimum object ``_create_lsp_client`` needs."""
    from euporie.core.app.app import BaseApp

    stub = Mock()
    stub.lsp_server_configs = configs
    # Call the real method against the stub.
    stub._create_lsp_client = partial(BaseApp._create_lsp_client, stub)
    return stub


def test_create_lsp_client_skips_a_missing_executable() -> None:
    """A server whose command is not installed is skipped, not launched."""
    app = _app_stub({"nope": {"command": ["definitely-not-a-real-language-server"]}})
    with patch("euporie.core.lsp.LspClient") as client_cls:
        assert app._create_lsp_client("nope") is None
    client_cls.assert_not_called()


def test_create_lsp_client_skips_an_unknown_name() -> None:
    """A name with no configuration is skipped."""
    app = _app_stub({})
    assert app._create_lsp_client("unconfigured") is None


def test_create_lsp_client_skips_a_config_without_a_command() -> None:
    """A configuration with no command is skipped."""
    app = _app_stub({"broken": {}})
    assert app._create_lsp_client("broken") is None


def test_create_lsp_client_starts_an_installed_server() -> None:
    """A server whose command exists is constructed and started."""
    # ``sys.executable`` is guaranteed to be on disk, so this exercises the
    # success path without depending on a language server being installed.
    app = _app_stub({"real": {"command": [sys.executable, "-c", ""]}})
    with patch("euporie.core.lsp.LspClient") as client_cls:
        result = app._create_lsp_client("real")
    client_cls.assert_called_once()
    assert result is client_cls.return_value
    client_cls.return_value.start.assert_called_once()
