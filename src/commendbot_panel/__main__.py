"""Entry point for the panel: ``python -m commendbot_panel``."""

from __future__ import annotations

import logging
import sys

from .config import ConfigError, load_settings


def main(argv: list[str] | None = None) -> int:
    """Start the GUI. Returns a process exit code.

    Configuration errors are reported on the console *and* in a dialog, because
    the usual way to start this program is by double-clicking it, where nobody
    ever sees stderr.
    """
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    try:
        settings = load_settings()
    except ConfigError as exc:
        _report_startup_failure(str(exc))
        return 2

    # Imported here so a configuration error is reported before Tk is touched —
    # on a headless machine importing the UI is itself a failure.
    from .ui import PanelApp  # noqa: PLC0415 - deliberate late import

    app = PanelApp(settings)
    app.mainloop()
    return 0


def _report_startup_failure(message: str) -> None:
    """Show the reason we cannot start, on the console and in a dialog."""
    print(f"commendbot-panel: {message}", file=sys.stderr)
    try:
        from tkinter import messagebox  # noqa: PLC0415 - optional on headless hosts

        messagebox.showerror("CommendBot Panel", message)
    except Exception:
        pass


if __name__ == "__main__":
    sys.exit(main())
