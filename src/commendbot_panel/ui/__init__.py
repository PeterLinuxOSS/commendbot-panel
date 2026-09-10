"""The CustomTkinter front-end.

Importing this package pulls in ``customtkinter``, so nothing outside ``ui``
should import from it — that is what keeps the rest of the code testable on a
machine with no display.
"""

from .app import PanelApp

__all__ = ["PanelApp"]
