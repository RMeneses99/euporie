###################
Language servers
###################

Euporie includes a `Language Server Protocol <https://microsoft.github.io/language-server-protocol/>`_ client, which gives you completion, diagnostics, hover information and document formatting from any standard :term:`language server`.

This guide describes how to configure a language server and what to expect when one is running.

Language server support must first be enabled by setting the :confval:`enable_language_servers` configuration option to ``true``, which can be done using the :menuselection:`Settings --> Code Tools --> Language Servers` menu.

***************
Default servers
***************

Euporie ships sensible defaults for the most common languages. If a :term:`kernel` is using a language for which a default server is configured, and the relevant server binary is on your :envvar:`PATH`, euporie will start it automatically.

The defaults can be inspected and overridden through the :confval:`language_servers` configuration option.

*****************************
Configuring a language server
*****************************

To override the defaults or add a new server, set the :confval:`language_servers` option in your config file:

.. code-block:: toml

   [language_servers.ruff]
   command = ["ruff", "server"]
   languages = ["python"]

   [language_servers.pyright]
   command = ["pyright-langserver", "--stdio"]
   languages = ["python"]

Each entry is keyed by a name (used for logs/UI) and contains:

* ``command`` - argv used to start the server.
* ``languages`` - list of language identifiers the server should activate for. These are matched against the running :term:`kernel`'s language.
* (Optional) ``settings`` - server-specific settings forwarded as the initialisation options.

If multiple servers are configured for the same language, they are all started concurrently and their results are merged.

**************
Common servers
**************

Python
======

Euporie starts ``ty``, ``ruff``, ``jedi`` and ``pylsp`` for Python by default, using whichever of them are installed.

* `ty <https://github.com/astral-sh/ty>`_ - a fast static type checker. Run as ``ty server``.
* `ruff <https://docs.astral.sh/ruff/>`_ - the recommended option for fast linting and formatting, run as ``ruff server`` (note: the older ``ruff-lsp`` project is deprecated).
* `jedi <https://github.com/pappasam/jedi-language-server>`_ - completion and navigation.
* `pylsp <https://github.com/python-lsp/python-lsp-server>`_ - a community LSP wrapping ``pylint``/``flake8``/``rope``/``yapf`` and friends.
* `pyright <https://github.com/microsoft/pyright>`_ - high-quality static type checker. In the registry but not started by default; add a :confval:`language_servers` entry to enable it.

``ty`` and ``ruff`` complement each other - one reports type errors, the other lint violations - and their diagnostics are merged. A minimal, fast setup which turns the other two off:

.. code-block:: toml

   enable_language_servers = true

   [language_servers.ruff]
   command = ["ruff", "server"]
   languages = ["python"]

   [language_servers.ty]
   command = ["ty", "server"]
   languages = ["python"]

   # An empty table disables a server which would otherwise start by default.
   [language_servers.jedi]
   [language_servers.pylsp]

.. note::

   Servers are launched as subprocesses which inherit euporie's environment, so they are found via :envvar:`PATH`. To use servers installed in a project's virtual environment, launch euporie from that environment - for example with :program:`uv run` or an activated venv. A server whose executable cannot be found is skipped with a message in the log rather than being treated as an error.

R
=

* `languageserver <https://github.com/REditorSupport/languageserver>`_ - install via ``install.packages("languageserver")``.

Other languages
===============

Any standard LSP server works - including :program:`rust-analyzer`, :program:`typescript-language-server`, :program:`gopls` and :program:`clangd`. Just add an entry to :confval:`language_servers` pointing at the right command.

***********
Formatting
***********

Cells can be formatted two ways, and both can be active at once - euporie applies each configured formatter in turn.

**Through a language server.** If a configured server advertises document-formatting capability, its formatter is used. ``ruff server`` does, so enabling it is enough.

**Through a command-line formatter.** A :term:`formatter` is an external command which reads code on standard input and writes it back on standard output. This needs no language server, so it is the lighter option if formatting is all you want. Python ships with no default formatter, so add one:

.. code-block:: toml

   [formatters.ruff-format]
   command = ["ruff", "format", "-"]
   languages = ["python"]

Note that :confval:`formatters` is a table *keyed by formatter name*, not a list. A list is rejected by validation and the option is ignored, which euporie reports at startup - see :ref:`troubleshooting <config-option-not-recognised>`.

To format, use one of:

.. list-table::
   :header-rows: 1
   :widths: 24 20 56

   * - Command
     - Default key
     - Scope
   * - :option:`reformat-cells`
     - ``f``
     - The selected cells, from notebook navigation mode
   * - :option:`reformat-notebook`
     - ``F``
     - Every code cell in the notebook
   * - :option:`reformat-input`
     - *unbound*
     - The cell being edited. Bind it with :confval:`key_bindings` to format without leaving the cell.

``f`` and ``F`` apply while a cell is selected but not being edited, so they do not shadow keys used by the modal editing modes. To format automatically whenever a cell is run, enable :confval:`autoformat`.

***********
Disabling
***********

To turn off LSP entirely, set the :confval:`enable_language_servers` option to ``false``:

.. code-block:: toml

   enable_language_servers = false

Or simply ensure that none of the relevant server binaries are on :envvar:`PATH`.
