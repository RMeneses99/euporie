"""Config subclass - user-editable configuration."""

from __future__ import annotations

import logging
import sys
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from platformdirs import user_config_dir

from euporie.core import __app_name__, __copyright__
from euporie.core.config._layers import (
    CliLayer,
    EnvironmentLayer,
    JsonFileLayer,
    TomlFileLayer,
)
from euporie.core.config._store import ConfigProblem, SettingStore

if TYPE_CHECKING:
    from euporie.core.config._layers import Layer
    from euporie.core.config._setting import Setting as Setting

log = logging.getLogger(__name__)


class Config(SettingStore):
    """User-editable configuration stored in user_config_dir.

    Resolution order (lowest to highest priority):
        1. Defaults
        2. Global config file (top-level values in config.toml)
        3. App config file section ([notebook] in config.toml)
        4. Global environment variables (EUPORIE_*)
        5. App environment variables (EUPORIE_NOTEBOOK_*)
        6. CLI arguments
        7. Programmatic overrides

    Attributes:
        parser: The argument parser for CLI arguments.
    """

    def __init__(
        self,
        app: str | None = None,
        *,
        settings: list[Setting] | None = None,
        _help: str = "",
        **kwargs: Any,
    ) -> None:
        """Create a new Config instance.

        Args:
            app: The application name.
            settings: The list of settings this config manages.
            _help: Help text for the argument parser.
            **kwargs: Initial override values.
        """
        app = app or kwargs.pop("app", None) or "euporie"
        self._help = _help

        config_dir = Path(user_config_dir(__app_name__, appauthor=None))
        config_dir.mkdir(exist_ok=True, parents=True)
        self._config_path = config_dir / "config.toml"
        self._json_config_path = config_dir / "config.json"
        #: Non-fatal messages about the configuration itself, reported at startup.
        self._notices: list[str] = []

        # Add read-only JSON layers for legacy config if JSON exists
        # but TOML has not yet been created
        layers: list[Layer] = [
            JsonFileLayer(self._json_config_path),
            JsonFileLayer(self._json_config_path, namespace=app),
            TomlFileLayer(self._config_path),
            TomlFileLayer(self._config_path, namespace=app, persistable=True),
            EnvironmentLayer(__app_name__),
            EnvironmentLayer(__app_name__, namespace=app),
            CliLayer(
                validate=partial(self._validate, source="Command line"),
                description=_help,
                epilog=__copyright__,
                syntax_theme=partial(getattr, self, "syntax_theme"),
            ),
        ]

        super().__init__(
            app=app,
            settings=settings or [],
            layers=layers,
            overrides=kwargs,
        )

    def load(self, args: list[str] | None = None) -> None:
        """Load configuration.

        Args:
            args: Explicit CLI argument list. When provided, the CLI
                layer parses from this list instead of ``sys.argv``.
        """
        from euporie.core.log import BufferedLogs, setup_logs

        self._notices: list[str] = []

        with BufferedLogs(logger=logging.getLogger("euporie")):
            try:
                super().load(args=args)
            finally:
                setup_logs(self)

        if self._json_config_path.exists():
            message = (
                f"Legacy JSON configuration file found at "
                f"'{self._json_config_path}'. Please migrate your settings to "
                f"'{self._config_path}' and remove the JSON file."
            )
            log.warning("%s", message)
            self._notices.append(message)

        self._report_problems()

    def _report_problems(self) -> None:
        """Print rejected configuration values to the standard error stream.

        Invalid values are discarded and the setting falls back to its default, so
        without this a mistyped setting is indistinguishable from one which was
        never written. The log message alone is not enough: the standard output log
        handler defaults to ``critical`` - correctly, since stray output would
        corrupt the interface once it is drawing - so a warning reaches only the
        in-application log tab, which is of little use for a problem occurring
        before the interface exists.

        This runs in the window after configuration is loaded and before the
        interface starts, where writing to the terminal is still safe.
        """
        if self.quiet_config or not (self.problems or self._notices):
            return

        for notice in self._notices:
            print(f"euporie: {notice}", file=sys.stderr)  # noqa: T201

        if not self.problems:
            return

        # Group by source file, since a value may come from any of several.
        by_source: dict[str, list[ConfigProblem]] = {}
        for problem in self.problems:
            by_source.setdefault(problem.source, []).append(problem)

        for source, problems in by_source.items():
            count = len(problems)
            print(  # noqa: T201
                f"euporie: {count} invalid setting{'s' if count > 1 else ''}"
                f" in {source}",
                file=sys.stderr,
            )
            for problem in problems:
                value = repr(problem.value)
                # Keep the report to one line per problem: a rejected value may be
                # arbitrarily long, such as a list of paths.
                if len(value) > 60:
                    value = f"{value[:57]}..."
                print(  # noqa: T201
                    f"  {problem.name} = {value}\n    {problem.message}",
                    file=sys.stderr,
                )
