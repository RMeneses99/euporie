############
Key Bindings
############

*************
Editing Modes
*************

The key-bindings used when editing a cell or in the console are determined by the :confval:`edit_mode` configuration variable. This can be set to ``micro``, ``emacs``, ``vi``, ``helix`` or ``kakoune`` to use key-bindings in the style of the respective text editor.

**********
Helix Mode
**********

Helix mode is modal, like Vi, but inverts the order in which commands are given. Where Vi is *verb-then-object* - ``dw`` to delete a word - Helix is **select-then-act**: ``w`` selects the next word and ``d`` then deletes whatever is selected. Because the selection is always visible before the operation runs, the effect of a command can be seen before committing to it.

Modes
=====

``i`` enters insert mode and :kbd:`Escape` returns to normal mode. ``v`` enters select mode, in which motions extend the selection rather than replacing it.

Four sub-modes are entered with a prefix key and left with :kbd:`Escape`:

.. list-table::
   :header-rows: 1
   :widths: 12 88

   * - Key
     - Sub-mode
   * - ``g``
     - **Goto** - jump to the start or end of the buffer, a line, or the top, middle or bottom of the window
   * - ``m``
     - **Match** - matching brackets, text objects, and surround operations
   * - ``z``
     - **View** - scroll the viewport without moving the cursor
   * - :kbd:`Space`
     - **Space** - open files, save, change kernel, and show the command palette
   * - :kbd:`Ctrl+w`
     - **Window** - tile, stack, focus and close tabs

Multiple selections
===================

Several ranges of text can be selected at once, and every subsequent command acts on all of them. The primary selection is highlighted differently from the others.

* ``x`` selects the current line; pressing it again extends to the next.
* ``Alt+s`` splits the selection into one selection per line.
* ``s`` selects every match of a regular expression inside the current selections, and ``S`` splits the selections on matches.
* ``C`` and ``Alt+C`` add a further selection on the line below or above.
* ``,`` reduces the selections back to the primary one, and ``Alt+,`` removes the primary selection.
* ``_`` trims surrounding whitespace from each selection, and ``&`` aligns them into a common column.

Editing commands - ``d``, ``c``, ``y``, ``p``, ``~`` and the case commands - apply to every selection. Such an edit is applied as a single change, so one press of ``u`` undoes it everywhere at once. Yanking several selections joins them with newlines, and pasting a clipboard which holds one line per selection distributes a line to each.

Text objects and surround
=========================

Within match mode, ``mi`` selects *inside* a text object and ``ma`` selects *around* it. The object is named by the following key: ``w`` for a word, ``W`` for a WORD, ``p`` for a paragraph, a quote character, or a bracket - ``(``, ``[``, ``{`` or ``<``, with ``b``, ``r``, ``c`` and ``a`` as aliases. Nested brackets resolve to the innermost enclosing pair of the requested type.

Also within match mode, ``ms`` surrounds the selection with a pair of characters, ``md`` removes the surrounding pair, and ``mr`` replaces one pair with another.

Registers and macros
====================

``"`` followed by a letter or digit selects a register for the next yank, paste or delete; without one, the system clipboard is used.

``q`` starts recording a macro and a second ``q`` stops it, storing the recording in the selected register or in ``@`` by default. ``Q`` replays it.

Other commands
==============

``Ctrl+a`` and ``Ctrl+x`` increment and decrement the number at or after the cursor, including negative numbers.

Differences from upstream Helix
===============================

Helix's language-server-backed pickers and workspace navigation have no equivalent in euporie, so the space sub-mode is bound to euporie's own file, kernel and command-palette actions instead. Window commands operate on euporie's tabs rather than on editor splits.

************
Kakoune Mode
************

Kakoune mode is modal and **selection-first**: every command acts on the set of currently selected ranges, and several ranges can be selected at once. Helix descends from Kakoune, so the two share that philosophy - but they do not share a keymap, and a number of keys mean different things in each. Where they differ, euporie follows Kakoune.

Selections are never empty
==========================

In Kakoune a bare cursor *is* a one-character selection. This is why ``d`` deletes a character when nothing appears to be selected: the character under the cursor is the selection. There is consequently no separate "delete character" command - every editing command simply acts on whatever is selected.

Modes
=====

``i`` and ``a`` enter insert mode before and after each selection, and :kbd:`Escape` returns to normal mode. There is **no select mode**: motions with :kbd:`Shift` extend the selection instead, so ``H``, ``J``, ``K``, ``L`` extend where ``h``, ``j``, ``k``, ``l`` replace.

Three sub-modes are entered with a prefix key and left with :kbd:`Escape`:

.. list-table::
   :header-rows: 1
   :widths: 12 88

   * - Key
     - Sub-mode
   * - ``g``
     - **Goto** - line start and end, first non-blank, first and last line, end of buffer. ``G`` does the same while extending the selection.
   * - ``v``
     - **View** - scroll the viewport without moving the selection. ``V`` locks view mode until :kbd:`Escape`.
   * - :kbd:`Space`
     - **User** - open files, save, change kernel, switch tabs and show the command palette.

Multiple selections
===================

Several ranges can be selected at once, and every subsequent command acts on all of them. The primary selection is highlighted differently from the others.

* ``x`` expands each selection to whole lines; pressing it again takes in the next line. ``Alt+x`` trims to whole lines.
* ``s`` selects every match of a regular expression within the selections, and ``S`` splits the selections on matches. ``Alt+s`` splits on line boundaries.
* ``Alt+k`` and ``Alt+K`` keep and drop selections matching a pattern.
* ``C`` and ``Alt+C`` add a selection on the line below or above; ``+`` duplicates each selection.
* ``,`` reduces to the main selection and ``Alt+,`` removes it. ``)`` and ``(`` change which selection is main.
* ``Alt+_`` merges touching selections and ``Alt++`` merges overlapping ones.
* ``_`` trims surrounding whitespace, ``&`` aligns the selections into a common column, and ``Alt+S`` reduces each to its first and last characters.
* ``Alt+)`` and ``Alt+(`` rotate the *contents* between selections, leaving the selections in place.

Editing commands apply to every selection as a single change, so one press of ``u`` undoes it everywhere at once. Yanking several selections joins them with newlines, and pasting a register which holds one line per selection distributes a line to each.

Insert mode works across all selections too: ``c`` on five selections leaves five insertion points, and everything typed afterwards is inserted at all five.

Text objects
============

``Alt+a`` selects a whole object and ``Alt+i`` the inner one, followed by a key naming the object:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Key
     - Object
   * - ``w`` / ``Alt+w``
     - word / WORD
   * - ``b`` ``(`` ``)``
     - parenthesis block
   * - ``B`` ``{`` ``}``
     - brace block
   * - ``r`` ``[`` ``]``
     - bracket block
   * - ``a`` ``<`` ``>``
     - angle block
   * - ``Q`` ``"`` / ``q`` ``'`` / ``g``
     - double-, single- and grave-quoted string (``g`` also accepts a backtick)
   * - ``s`` / ``p``
     - sentence / paragraph
   * - ``i``
     - indentation block - the Python suite at the cursor
   * - ``n`` / ``u``
     - number / argument
   * - :kbd:`Space`
     - run of whitespace

Any other punctuation acts as its own delimiter, so with the cursor inside ``/home/bar``, ``Alt+a`` then ``/`` selects ``/home/``. A count selects an outer nesting level: ``2`` then ``Alt+a`` then ``b`` takes the second enclosing parenthesis pair.

``[`` and ``]`` select from the cursor to the object's start or end, ``{`` and ``}`` extend to them, and the ``Alt+`` forms of those four do the same for the inner object. ``Alt+.`` repeats the last object or character selection.

Matching pairs, registers, macros and marks
===========================================

``m`` selects to the next sequence enclosed by matching characters, ``M`` extends to it, and ``Alt+m`` and ``Alt+M`` do the same backwards. Kakoune has no match sub-mode - ``m`` is a motion.

``"`` followed by a character selects the register used by the next yank, paste, delete or macro operation. The default text register is mapped onto the system clipboard.

``Q`` starts recording a macro and a second ``Q`` stops it; ``q`` replays it.

``Z`` saves the current selections to a register and ``z`` restores them. ``Alt+z`` and ``Alt+Z`` combine saved and current selections, then wait for ``a`` (append), ``u`` (union), ``i`` (intersection), ``<`` or ``>`` (leftmost or rightmost), or ``+`` or ``-`` (longest or shortest).

Differences from Helix mode
===========================

Several keys are spelled the same in both editors but do different things. If you use both, these are the ones to know:

.. list-table::
   :header-rows: 1
   :widths: 16 42 42

   * - Key
     - Kakoune
     - Helix
   * - ``x``
     - expand selections to whole lines
     - extend selection down one line
   * - ``~``
     - to upper case
     - swap case
   * - ``Alt+```
     - swap case
     - to upper case
   * - ``m``
     - matching-pair motion
     - enter match sub-mode
   * - ``v``
     - enter view sub-mode
     - enter select mode
   * - ``z`` / ``Z``
     - restore / save selections
     - enter view sub-mode
   * - ``Q`` / ``q``
     - record / replay macro
     - replay / record macro
   * - ``N``
     - add a selection at the next match
     - search backwards
   * - ``Alt+j``
     - join lines
     - (``J`` joins)
   * - ``Alt+a`` / ``Alt+i``
     - whole / inner text object
     - (``ma`` / ``mi``)
   * - ``Alt+h`` / ``Alt+l``
     - select to line start / end
     - (``gh`` / ``gl``)

Differences from upstream Kakoune
=================================

:kbd:`Escape` behaves as it does in Kakoune - it returns to normal mode or cancels whatever is pending, and never leaves the buffer. Because a notebook cell still has to be left somehow, **pressing** :kbd:`Escape` **twice** exits the cell.

Kakoune's shell filters (``|``, ``Alt+|``, ``!``, ``Alt+!`` and ``$``) are not bound. In a notebook the kernel is a better tool for transforming text than an external process, so these keys are left unbound rather than approximated. Tab conversion (``@`` and ``Alt+@``) and hook-disabling (``\``) are likewise absent.

Kakoune's user mode is empty by default, for the user's own configuration. Here it is populated with euporie's file, kernel and tab actions. ``:`` opens euporie's command bar rather than Kakoune's command prompt, and the jump list operates within the cell.

Editing state is kept **per cell**, so each cell remembers its own mode, selections and marks: leaving one cell in insert mode does not affect any other.

*******************
Custom Key Bindings
*******************

Key bindings can be customized by setting the :confval:`key_bindings` configuration parameter.

This parameter takes the form of a mapping where the keys are command names and the values are lists of keys to bind to those commands. You can also use the ``add``, ``remove``, and ``replace`` keys for finer control over how your bindings interact with the defaults.

Using the simple list form will entirely over-ride the default bindings for a command, so if you want to add an additional binding for a command while retaining the defaults, use the ``add`` key instead.

Below is an example :ref:`pages/configuration:Configuration File` showing how the key-bindings can be set:

.. code-block:: toml
   :emphasize-lines: 5-7

   [notebook]
   autoformat = false
   expand = true

   [notebook.key_bindings]
   quit = ["c-q", "c-p"]
   new-notebook = []

This example sets two key-bindings in the :doc:`Notebook <../packages/notebook>` app for the :option:`quit` command: :kbd:`Ctrl+Q` and :kbd:`Ctrl+P`. It also unsets any key-bindings for the :option:`new-notebook` command.

To add bindings while keeping the defaults, use the ``add`` key:

.. code-block:: toml

   [notebook.key_bindings.quit]
   add = ["c-q", "c-p"]

Custom key-binding configuration can also be passed on the command line in the form of a JSON string:

.. code-block:: console

   $ euporie-notebook --key-bindings='{"new-notebook": [], "quit": ["c-q", "c-p"]}'

Command names are listed in the `Default Key Bindings Reference`_ below. You
can also discover them using the :term:`command palette` (press
:kbd:`Ctrl+Space`) or the :term:`command bar` (press :kbd:`:` or
:kbd:`Alt+:`), via the :menuselection:`Help --> Keyboard Shortcuts` menu item in :doc:`euporie-notebook <../packages/notebook>`,
or you can view all available command on the :doc:`All Commands <../_inc/commands>` documentation page.


***********************************
The Command Palette and Command Bar
***********************************

There are two keyboard-driven ways to find and run a :term:`command` by name.

The :term:`command palette` is a searchable popup, summoned with
:kbd:`Ctrl+Space`. It lists every command available in the current context
alongside its description and key binding. Type to fuzzy-search, move between
matches with the arrow keys, and run the highlighted command with
:kbd:`Enter`.

The :term:`command bar` is a modal, single-line input shown at the bottom of
the screen, inspired by the vim and helix command line. Summon it with
:kbd:`:` or :kbd:`Alt+:`, then type a command name and press :kbd:`Enter` to
run it. The command bar offers:

* **Tab-completion** of command names as you type.
* **Validation** -- unrecognised commands are rejected before they run.
* A **persistent history** of previously entered commands, searchable with
  the up and down arrow keys.

Prefix your input with ``!`` -- or summon the bar directly with :kbd:`Alt+!`
-- to run a system shell command instead of a euporie command. Close the
command bar without running anything by pressing :kbd:`Escape` or
:kbd:`Ctrl+C`.

The activation key bindings are themselves configurable commands
(:option:`activate-command-bar`, :option:`activate-command-bar-shell` and
:option:`deactivate-command-bar`), so they can be rebound like any other
binding using the :confval:`key_bindings` option described above.


*************
Running Cells
*************

Cells can be run using :kbd:`Ctrl+Enter`, or :kbd:`Shift+Enter` to run and select the next cell, as is the case in `JupyterLab <https://jupyter.org/>`_.

However, most terminals do not distinguish between :kbd:`Enter`, :kbd:`Ctrl+Enter` & :kbd:`Shift+Enter` by default, meaning that you have to use alternative key-bindings in euporie to run cells.

Fortunately it is possible to configure many terminals such that these key-bindings can be used, as outlined below.

.. note::
   There are two commonly used formats of escape sequences which can be used to distinguish these key-bindings: **FK-27** and **CSI-u**. The instructions below implement the CSI-u style, but euporie will recognise either.

WezTerm
=======

Update your :file:`$HOME/.config/wezterm/wezterm.lua` file to include the following:

.. code-block:: lua

    local wezterm = require 'wezterm';

    return {
      -- ...

      keys = {
        {key="Enter", mods="CTRL", action=wezterm.action{SendString="\x1b[13;5u"}},
        {key="Enter", mods="SHIFT", action=wezterm.action{SendString="\x1b[13;2u"}},
      },
    }

Kitty
=====

Add the following to your :file:`$HOME/.config/kitty/kitty.conf` file:

.. code-block::

   map ctrl+enter send_text normal,application \x1b[13;5u
   map shift+enter send_text normal,application \x1b[13;2u


Foot
====

Foot supports XTerm's `K27 format <https://invisible-island.net/xterm/modified-keys.html>`_, so does not require any additional configuration.

XTerm
=====

You can add the following lines to your :file:`$HOME/.Xresources` file, which enables **CSI-u** escape sequences.

.. code-block::

   *vt100.modifyOtherKeys: 1
   *vt100.formatOtherKeys: 1


Windows Terminal
================

You can add the key-bindings to your :file:`settings.json` file:

.. code-block:: javascript

   {
     // ...

     "keybindings":
     [
       { "command": { "action": "sendInput", "input": "\u001b[13;5u" }, "keys": "ctrl+enter" },
       { "command": { "action": "sendInput", "input": "\u001b[13;2u" }, "keys": "shift+enter" }
     ]
   }


Alacritty
=========

You can define the key-binding in your :file:`$HOME/.config/alacritty/alacritty.yml` file as follows:

.. code-block:: yaml

    key_bindings:
      - { key: Return, mods: Control, chars: "\x1b[13;5u" }
      - { key: Return, mods: Shift,   chars: "\x1b[13;2u" }

Konsole
=======

In the menu, navigate to :menuselection:`Settings --> Edit Current Profile`, then select :menuselection:`Keyboard --> Edit`.

Change the existing entry for `Return+Shift` to `Return+Shift+Ctrl` (or whatever you prefer), then add the following entries:

+-----------------+---------------+
| Key combination | Output        |
+=================+===============+
| Return+Ctrl     | ``E\[13;5u``  |
+-----------------+---------------+
| Return+Shift    | ``\E\[13;2u`` |
+-----------------+---------------+

******************************
Default Key Bindings Reference
******************************

The following lists outline the default key-bindings used in euporie:

.. include:: ../_inc/default_key_bindings.rst
   :start-after: .. start-key-bindings-reference
   :end-before: .. end-key-bindings-reference

----

Default Key-binding configuration
=================================

The following lists all of the default key-bindings used in euporie in the format required for custom key-bindings in the configuration file. The ``[key_bindings]`` table below should be placed under the relevant app section in your configuration (e.g. ``[notebook.key_bindings]``).

.. include:: ../_inc/default_key_bindings.rst
   :start-after: .. start-key-bindings-config
