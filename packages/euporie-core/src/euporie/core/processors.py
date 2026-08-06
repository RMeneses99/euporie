"""Buffer processors."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from apptk.layout.processors import (
    HighlightSelectionProcessor,
    Processor,
    Transformation,
)
from apptk.layout.utils import explode_text_fragments

if TYPE_CHECKING:
    from collections.abc import Callable

    from apptk.formatted_text.base import StyleAndTextTuples
    from apptk.layout.processors import TransformationInput

    from euporie.core.diagnostics import Report


log = logging.getLogger(__name__)


def _helix_selections() -> list[tuple[int, int]]:
    """Return the active Helix selection ranges, if there are several.

    Returns:
        The additional selection ranges, or an empty list when a single selection
        is active or Helix mode is not in use.
    """
    from apptk.application.current import get_app
    from apptk.enums import EditingMode

    try:
        app = get_app()
    except Exception:
        return []
    if app.editing_mode != EditingMode.HELIX:
        return []
    return list(getattr(app.helix_state, "selections", []) or [])


class HelixSelectionProcessor(HighlightSelectionProcessor):
    """Highlight every Helix selection, not just the primary one.

    The upstream processor reads ``document.selection_range_at_line``, which knows
    only about the buffer's single selection. When several Helix selections are
    active the secondary ones are highlighted here, using a distinct style so that
    the primary selection remains identifiable.
    """

    def apply_transformation(
        self, transformation_input: TransformationInput
    ) -> Transformation:
        """Apply selection highlighting to one line.

        Args:
            transformation_input: The line being rendered.

        Returns:
            The transformed line.
        """
        selections = _helix_selections()
        if len(selections) < 2:
            # Single selection: the upstream implementation is correct and cheaper.
            return super().apply_transformation(transformation_input)

        (
            _buffer_control,
            document,
            lineno,
            source_to_display,
            fragments,
            _,
            _,
        ) = transformation_input.unpack()

        line_start = document.translate_row_col_to_index(lineno, 0)
        line_end = line_start + len(document.lines[lineno])

        primary = super().apply_transformation(transformation_input)
        fragments = explode_text_fragments(primary.fragments)

        for anchor, head in selections:
            start, end = (anchor, head) if anchor <= head else (head, anchor)
            # Clip the range to this line.
            start = max(start, line_start)
            end = min(end, line_end)
            if start >= end:
                continue
            from_ = source_to_display(start - line_start)
            to = source_to_display(end - line_start)
            for index in range(from_, to):
                if index < len(fragments):
                    style, text, *_ = fragments[index]
                    if "class:selected" not in style:
                        fragments[index] = (
                            style + " class:selected.secondary",
                            text,
                        )
                elif index == len(fragments):
                    fragments.append((" class:selected.secondary ", " "))

        return Transformation(fragments)


class HelixMultipleCursors(Processor):
    """Display a cursor at the head of every Helix selection.

    The upstream ``DisplayMultipleCursors`` is gated on Vi block-insert mode, so
    it never fires for Helix. This applies the same styling under Helix's own
    condition instead.
    """

    def apply_transformation(
        self, transformation_input: TransformationInput
    ) -> Transformation:
        """Mark each secondary cursor position on one line.

        Args:
            transformation_input: The line being rendered.

        Returns:
            The transformed line.
        """
        (
            buffer_control,
            document,
            lineno,
            source_to_display,
            fragments,
            _,
            _,
        ) = transformation_input.unpack()

        if len(_helix_selections()) < 2:
            return Transformation(fragments)

        positions = buffer_control.buffer.multiple_cursor_positions
        if not positions:
            return Transformation(fragments)

        fragments = explode_text_fragments(fragments)
        line_start = document.translate_row_col_to_index(lineno, 0)
        line_end = line_start + len(document.lines[lineno])

        for position in positions:
            if line_start <= position <= line_end:
                column = source_to_display(position - line_start)
                try:
                    style, text, *_ = fragments[column]
                except IndexError:
                    fragments.append((" class:multiple-cursors", " "))
                else:
                    fragments[column] = (style + " class:multiple-cursors", text)

        return Transformation(fragments)


class DiagnosticProcessor(Processor):
    """Highlight diagnostics."""

    def __init__(
        self,
        report: Report | Callable[[], Report],
        style: str = "underline",
    ) -> None:
        """Create a new processor instance."""
        self._report = report
        self.style = style

    @property
    def report(self) -> Report:
        """Return the current diagnostics report."""
        if callable(self._report):
            return self._report()
        return self._report

    def apply_transformation(self, ti: TransformationInput) -> Transformation:
        """Underline the text ranges relating to diagnostics in the report."""
        line = ti.lineno
        fragments = ti.fragments
        self_style = self.style
        for item in self.report:
            if item.lines.start < line < item.lines.stop - 1:
                fragments = cast(
                    "StyleAndTextTuples",
                    [
                        (f"{style} {self.style}", text, *rest)
                        for style, text, *rest in fragments
                    ],
                )
            elif line == item.lines.start or line == item.lines.stop - 1:
                fragments = explode_text_fragments(fragments)
                start = item.chars.start if line == item.lines.start else 0
                end = (
                    item.chars.stop - 1
                    if line == item.lines.stop - 1
                    else len(fragments)
                )
                for i in range(start, min(len(fragments), end)):
                    fragments[i] = (
                        f"{fragments[i][0]} {self_style}",
                        *fragments[i][1:],
                    )

        return Transformation(fragments)
