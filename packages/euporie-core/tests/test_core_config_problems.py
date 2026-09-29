"""Test reporting of configuration values which fail validation.

An invalid value is discarded and the setting falls back to its default, so without
a report a mistyped setting is indistinguishable from one which was never written.
The log message alone does not reach the user: the standard output log handler
defaults to ``critical``, so a warning goes only to the in-application log tab -
which is of little use for a problem occurring before the interface exists.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import pytest

from euporie.core.config._config import Config

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point euporie's configuration directory at a temporary one."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    directory = tmp_path / "euporie"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _load(config_dir: Path, toml: str, args: list[str] | None = None) -> Config:
    """Write a configuration file and load it.

    Only the settings these tests touch are registered, keeping the store small and
    independent of which settings an app happens to define.
    """
    from euporie.core import settings as core_settings

    (config_dir / "config.toml").write_text(toml)
    config = Config(
        app="notebook",
        settings=[
            core_settings.tab_size,
            core_settings.edit_mode,
            core_settings.quiet_config,
            # Read by ``setup_logs`` while loading.
            core_settings.log_file,
            core_settings.log_level,
            core_settings.log_level_stdout,
            core_settings.log_config,
            core_settings.syntax_theme,
        ],
    )
    config.load(args=args or [])
    return config


# Collection


def test_invalid_value_is_recorded(config_dir: Path) -> None:
    """A value rejected by the schema is collected as a problem."""
    config = _load(config_dir, 'tab_size = "not a number"\n')
    assert len(config.problems) == 1
    problem = config.problems[0]
    assert problem.name == "tab_size"
    assert problem.value == "not a number"
    assert "integer" in problem.message


def test_problem_names_its_source_file(config_dir: Path) -> None:
    """The problem records which file the value came from.

    With both a TOML and a legacy JSON file in play, naming the layer class is not
    enough to find the offending line.
    """
    config = _load(config_dir, 'tab_size = "not a number"\n')
    assert config.problems[0].source == str(config_dir / "config.toml")


def test_valid_config_records_nothing(config_dir: Path) -> None:
    """A configuration which validates produces no problems."""
    config = _load(config_dir, "tab_size = 2\n")
    assert config.problems == []


def test_an_unknown_key_is_not_reported(config_dir: Path) -> None:
    """A key which is not a setting of this store is not treated as a problem.

    A store holds only the settings applicable to its own app, so valid keys -
    state such as ``recent_files``, or another app's settings - reach that branch
    routinely. Reporting them would be noise about a correct file.
    """
    config = _load(config_dir, "some_other_apps_setting = 1\n")
    assert config.problems == []


def test_problems_are_cleared_between_loads(config_dir: Path) -> None:
    """Reloading does not accumulate problems from a previous load."""
    config = _load(config_dir, 'tab_size = "not a number"\n')
    assert len(config.problems) == 1
    (config_dir / "config.toml").write_text("tab_size = 2\n")
    config.load(args=[])
    assert config.problems == []


# Reporting


def test_report_goes_to_stderr(
    config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The report is written to stderr, leaving stdout untouched.

    stdout carries the interface and the ``--log-file -`` output, so mixing the
    report into it would interleave badly.
    """
    _load(config_dir, 'tab_size = "not a number"\n')
    captured = capsys.readouterr()
    assert "tab_size" in captured.err
    assert "tab_size" not in captured.out


def test_report_names_the_file_and_the_reason(
    config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The report is actionable: which file, which setting, and why."""
    _load(config_dir, 'tab_size = "not a number"\n')
    err = capsys.readouterr().err
    assert str(config_dir / "config.toml") in err
    assert "tab_size" in err
    assert "integer" in err


def test_valid_config_reports_nothing(
    config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A configuration which validates produces no output."""
    _load(config_dir, "tab_size = 2\n")
    assert capsys.readouterr().err == ""


def test_quiet_config_suppresses_the_report(
    config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--quiet-config`` silences the report but still records the problems."""
    config = _load(config_dir, 'tab_size = "not a number"\n', args=["--quiet-config"])
    assert capsys.readouterr().err == ""
    assert len(config.problems) == 1


def test_a_long_value_is_truncated(
    config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A rejected value is abbreviated, so each problem stays on one line."""
    long_value = "x" * 500
    _load(config_dir, f'tab_size = "{long_value}"\n')
    err = capsys.readouterr().err
    assert "..." in err
    assert long_value not in err
    # One line for the heading, one for the setting, one for the reason.
    assert len(err.strip().splitlines()) == 3


def test_several_problems_are_grouped_by_file(
    config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Problems from one file are reported under a single heading."""
    _load(config_dir, 'tab_size = "no"\nedit_mode = "not-an-editor"\n')
    err = capsys.readouterr().err
    assert err.count("invalid settings in") == 1
    assert "2 invalid settings" in err
    assert "tab_size" in err
    assert "edit_mode" in err


def test_report_is_written_before_the_interface_starts(
    config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reporting happens during ``load``, which runs before the app is built.

    That window is the only one in which writing to the terminal is safe.
    """
    _load(config_dir, 'tab_size = "not a number"\n')
    # The report is already present once ``load`` has returned.
    assert "tab_size" in capsys.readouterr().err


def test_stderr_is_used_even_when_not_a_tty(
    config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The report is not suppressed merely because stderr is redirected.

    A user piping stderr to a file is usually doing so in order to read it.
    """
    assert not sys.stderr.isatty()
    _load(config_dir, 'tab_size = "not a number"\n')
    assert "tab_size" in capsys.readouterr().err


# Notices
#
# Messages about the configuration itself rather than about a specific value. These
# share the visibility problem: they are logged, but the log reaches only the
# in-application log tab.


def test_legacy_json_file_is_reported(
    config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A leftover JSON configuration file is reported, so it can be migrated.

    A value set in both files silently takes the TOML one, which is an easy way to
    be confused about why a setting appears not to change.
    """
    (config_dir / "config.json").write_text("{}")
    _load(config_dir, "tab_size = 2\n")
    err = capsys.readouterr().err
    assert "Legacy JSON" in err
    assert str(config_dir / "config.json") in err


def test_no_notice_without_a_legacy_file(
    config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A configuration with no JSON file produces no notice."""
    _load(config_dir, "tab_size = 2\n")
    assert capsys.readouterr().err == ""


def test_quiet_config_suppresses_notices_too(
    config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--quiet-config`` silences notices as well as invalid values."""
    (config_dir / "config.json").write_text("{}")
    _load(config_dir, "tab_size = 2\n", args=["--quiet-config"])
    assert capsys.readouterr().err == ""
