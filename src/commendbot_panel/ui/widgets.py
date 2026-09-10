"""Reusable widgets and the asset loader.

The original built the same scrolled frame, the same little bordered "stat tile"
and the same icon button inline, several times each, and reached into
CustomTkinter privates (``._text``, ``._image``, ``._update_image()``) to read
them back. Those attributes are not API and change between releases, so the
widgets here keep their own state instead.
"""

from __future__ import annotations

import logging
from pathlib import Path

import customtkinter as ctk
from PIL import Image

log = logging.getLogger(__name__)


class AssetLoader:
    """Loads icons from a directory, tolerating the ones that are absent.

    The image files are not redistributed with the source (see
    ``assets/images/README.md``). A missing icon must not stop the panel from
    starting, so this returns ``None`` and the caller falls back to a text
    label.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._cache: dict[tuple[str, int], ctk.CTkImage] = {}

    def icon(self, name: str, size: int = 20) -> ctk.CTkImage | None:
        """Return a square icon, or ``None`` when the file is not there."""
        key = (name, size)
        if key in self._cache:
            return self._cache[key]

        path = self.directory / name
        if not path.is_file():
            log.debug("asset %s is missing", path)
            return None

        try:
            image = ctk.CTkImage(Image.open(path), size=(size, size))
        except OSError:
            log.warning("asset %s could not be read", path)
            return None

        self._cache[key] = image
        return image

    def raw(self, name: str) -> Image.Image | None:
        """Return a PIL image, used by the on-screen template matching."""
        path = self.directory / name
        if not path.is_file():
            return None
        try:
            return Image.open(path)
        except OSError:
            return None

    def icon_path(self, name: str) -> str | None:
        """Path to a ``.ico``, for ``iconbitmap``; ``None`` when absent."""
        path = self.directory / name
        return str(path) if path.is_file() else None


class ScrollableFrame(ctk.CTkFrame):
    """A frame whose contents scroll vertically.

    CustomTkinter grew ``CTkScrollableFrame`` after this program was written, so
    this is now a thin wrapper: the surrounding code keeps one name to use and
    the hand-rolled canvas plumbing is gone.
    """

    def __init__(self, master: ctk.CTkBaseClass, **kwargs) -> None:
        super().__init__(master, fg_color="transparent")
        self.inner = ctk.CTkScrollableFrame(self, **kwargs)
        self.inner.pack(fill="both", expand=True)

    def clear(self) -> None:
        """Destroy every child, e.g. before repopulating a list."""
        for child in self.inner.winfo_children():
            child.destroy()


class StatTile(ctk.CTkFrame):
    """A bordered box with a caption and a value, used across the stats panel."""

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        caption: str,
        value: str = "0",
        *,
        width: int = 75,
        height: int = 55,
    ) -> None:
        super().__init__(master, width=width, height=height, border_width=2)
        self.pack_propagate(False)

        ctk.CTkLabel(self, text=caption, font=("Roboto", 15, "bold")).pack(pady=(3, 0))
        self._value = ctk.CTkLabel(self, text=value, font=("Roboto", 14, "bold"))
        self._value.pack(pady=(0, 3))
        self._current = value

    @property
    def value(self) -> str:
        """The text currently displayed."""
        return self._current

    def set(self, value: str) -> None:
        """Update the value, skipping the redraw when nothing changed."""
        if value == self._current:
            return
        self._current = value
        self._value.configure(text=value)


class NavButton(ctk.CTkButton):
    """One entry in the left-hand navigation rail.

    Holds its own active/inactive icons rather than reading them back off the
    widget, which is what the original did through private attributes.
    """

    def __init__(
        self,
        master: ctk.CTkBaseClass,
        *,
        active_icon: ctk.CTkImage | None,
        inactive_icon: ctk.CTkImage | None,
        fallback_text: str,
        command,
    ) -> None:
        super().__init__(
            master,
            image=inactive_icon,
            text="" if inactive_icon else fallback_text,
            width=25,
            height=25,
            command=command,
            hover_color="#add8e6",
            fg_color="transparent",
        )
        self._active_icon = active_icon
        self._inactive_icon = inactive_icon
        self._fallback_text = fallback_text

    def set_active(self, active: bool) -> None:
        """Swap to the highlighted icon and stop hovering while selected."""
        icon = self._active_icon if active else self._inactive_icon
        self.configure(
            image=icon,
            text="" if icon else self._fallback_text,
            hover=not active,
        )


def format_clock(hour: int, minute: int) -> str:
    """Format a wall-clock time as ``HH:MM``.

    The original wrote ``if 9 > dt.minute`` and so rendered minute 9 as ``14:9``
    (AUDIT.md A11). Kept as a function purely so the boundary is covered by a
    test.
    """
    return f"{hour:02d}:{minute:02d}"
