"""CommendBot Panel — a desktop controller for CS:GO commend jobs.

The package is split into four layers:

* :mod:`commendbot_panel.database`  — MongoDB access
* :mod:`commendbot_panel.ipc`       — the loopback control channel to the runners
* :mod:`commendbot_panel.steam`     — Steam IDs, credentials and process launching
* :mod:`commendbot_panel.ui`        — the CustomTkinter front-end

Everything outside ``ui`` is import-safe on any platform, so the business logic
can be unit-tested without Windows, Steam or a database.
"""

__version__ = "3.0.0"
__all__ = ["__version__"]
