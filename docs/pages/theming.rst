#######
Theming
#######

Euporie's appearance is controlled by two independent settings:

* the :term:`colour scheme <Color scheme>` - which sets the application's overall foreground and background colours and selects an appropriate palette for menus, borders, status bars and so on, and
* the **syntax theme** - which sets the colours used for syntax-highlighting source code inside cells.

This guide describes how to switch between them and how to configure your own.

***********************
Built-in colour schemes
***********************

Built-in schemes include:

* ``default`` - terminal default (uses your terminal's foreground/background)
* ``dark`` - dark grey background with light foreground
* ``light`` - light background with dark foreground
* ``black`` - pure-black background
* ``white`` - pure-white background
* ``inverse`` - swaps the terminal's foreground and background
* ``custom`` - uses :confval:`custom_foreground_color` and :confval:`custom_background_color`

Switch from inside the :term:`app` via :menuselection:`Settings --> Color Scheme`, or set the :confval:`color_scheme` configuration option.

A custom scheme:

.. code-block:: toml

   color_scheme = "custom"
   custom_foreground_color = "#dcd7ba"
   custom_background_color = "#1f1f28"

*****************
Syntax themes
*****************

Syntax themes come from :doc:`Pygments <pygments:styles>` and include hundreds of options - try ``monokai``, ``dracula``, ``solarized-dark``, ``nord``, ``gruvbox-dark``, ``one-dark`` etc.

Switch from inside the :term:`app` via :menuselection:`Settings --> Syntax Theme`, or set :confval:`syntax_theme`.

*************
Morphogenesis
*************

Euporie ships the ``morphogenesis`` syntax theme: a dark blue scheme which ranks tokens by **brightness rather than hue**, so the eye can tell what matters without learning a colour-to-concept mapping. Functions and types are the only saturated colour, keywords are muted rather than bold, punctuation is the dimmest thing on screen, and warm colours are reserved for errors — so a correct file shows none.

The syntax theme works on its own:

.. code-block:: toml

   syntax_theme = "morphogenesis"

To match the application chrome to it as well, the theme expects the terminal to be running the same palette. Inheriting the base rather than restating it keeps the two in agreement, and is also the only :confval:`color_scheme` value which leaves the cell background unpainted — so a terminal background image shows through:

.. code-block:: toml

   syntax_theme = "morphogenesis"
   color_scheme = "default"
   accent_color = "#00d4ff"

   [notebook]
   background_pattern = 0

   [custom_styles]
   "status" = "fg:#e8f0fe bg:#1a3a5c"
   "menu" = "fg:#e8f0fe bg:#1a3a5c"
   "app tab-bar tab active" = "bold fg:#e8f0fe bg:#2a6fb5"
   "app tab-bar tab inactive" = "fg:#8ab4d4 bg:#1a3a5c"
   "line-number" = "fg:#2a3f54"
   "line-number.current" = "bold fg:#00d4ff"
   "matching-bracket.cursor" = "bold fg:#00d4ff"
   "matching-bracket.other" = "bold fg:#00d4ff"
   "selected.secondary" = "bg:#1a3a5c"

If your terminal is *not* using the Morphogenesis palette, set the base explicitly instead of inheriting it. This looks the same anywhere — over SSH, in a multiplexer — but paints a solid background, so any terminal background image is covered:

.. code-block:: toml

   color_scheme = "custom"
   custom_background_color = "#0d1b2a"
   custom_foreground_color = "#e8f0fe"

.. warning::

   ``#1a3a5c`` and ``#2a3f54`` are surfaces, not text colours. At 1.5:1 and 1.6:1 against the background they are correct for a selection background, a border or a whitespace marker — where position carries the meaning and the colour only has to be perceptible — but unreadable as text. When a dim foreground is wanted, use ``#6c8aa8`` (4.8:1).

**************
Custom styles
**************

Individual style keys can be overridden with :confval:`custom_styles`, a mapping of style names to :doc:`prompt-toolkit <prompt_toolkit:index>` style strings. This is the only way to set an exact colour: euporie otherwise *derives* every style from the foreground, background and accent colours, so a theme specifying particular values cannot express them any other way.

.. code-block:: toml

   [custom_styles]
   "cell input prompt" = "fg:purple"
   "cell output prompt" = "fg:green"

Overrides are applied after the derived styles, so they win. The available key names are those used in :py:func:`euporie.core.style.build_style`.

*****************
Per-app overrides
*****************

Both options can be overridden per :term:`app`. For example, to use a light scheme in the notebook editor but a dark one in the console:

.. code-block:: toml

   color_scheme = "light"
   syntax_theme = "default"

   [console]
   color_scheme = "dark"
   syntax_theme = "dracula"

See :doc:`configuration` for the full configuration mechanism.

**********************************
Borders, cell visuals and tab bars
**********************************

A handful of related settings control the visual density of the UI:

* :confval:`show_cell_borders` - draw a coloured border around each :term:`cell`.
* :confval:`always_show_tab_bar` - keep the :term:`tab` bar visible even when only one tab is open.
* :confval:`expand` - let cells expand to fill the available width instead of using a fixed maximum.
* :confval:`show_status_bar` - hide or show the bottom status bar.

These can be tweaked alongside the colour/syntax options to get a layout that suits you, and can also be toggled from inside the :term:`app` via the :menuselection:`Settings --> UI Elements` menu.
