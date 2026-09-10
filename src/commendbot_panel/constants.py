"""Fixed values shared across the package.

Anything that used to be a magic number in the original single-file script lives
here, so that a reader can see the whole vocabulary of the program in one place.
"""

from __future__ import annotations

# --- Steam ----------------------------------------------------------------

# Offset between a 64-bit Steam ID and the 32-bit account ID used in folder names.
STEAM_ID64_BASE = 76561197960265728

# A SteamID64 rendered as decimal is always 17 digits.
STEAM_ID64_LENGTH = 17

CSGO_APP_ID = 730

# Title of the Steam Guard prompt the runner has to bring to the foreground.
STEAM_SIGN_IN_WINDOW_TITLE = "Steam Sign In"

# --- Local control channel ------------------------------------------------

# The panel listens here; runners started by the panel connect back to it.
# Loopback only — this channel is never meant to leave the machine.
IPC_HOST = "127.0.0.1"
IPC_PORT = 11569

# Messages are newline-delimited UTF-8. The original protocol had no framing at
# all, so two messages sent in quick succession arrived as one blob and matched
# nothing (see AUDIT.md A20).
IPC_ENCODING = "utf-8"
IPC_TERMINATOR = "\n"
IPC_READ_SIZE = 4096

# --- Runner timing --------------------------------------------------------

# How long the runner waits between console.log polls.
CONSOLE_POLL_SECONDS = 20

# Grace period after Steam is launched before the first server connect attempt.
FIRST_CONNECT_DELAY_SECONDS = 35

# Total budget for re-establishing the control connection before giving up.
RECONNECT_BUDGET_SECONDS = 120
RECONNECT_STEP_SECONDS = 10

# Idle time on a server before the runner re-issues a connect.
STALLED_CONNECT_SECONDS = 100

# --- CS:GO console lines the runner reacts to -----------------------------

DISCONNECT_MESSAGES = (
    "Disconnect: Server shutting down.",
    "Disconnect: Relog to continue.",
    "Server connection timed out.",
)
CONNECTED_MESSAGE = "Connected to "

# --- Job status values as stored in MongoDB -------------------------------
#
# These strings are the on-disk contract with the Discord bot that shares the
# database, so the historical misspelling of "stopped" is preserved on purpose.
# The original panel compared against both spellings in different places, which
# made the paused branch unreachable (AUDIT.md A15).

STATUS_WAITING_CONNECT = "w8connect"
STATUS_CONFIRMED = "confirmed"
STATUS_STOPPED = "stoped"  # noqa: S105 - historical DB value, not a password
STATUS_DONE = "done"
STATUS_ERROR = "error"

STATUS_LABELS = {
    STATUS_WAITING_CONNECT: "Connecting",
    STATUS_CONFIRMED: "Commending",
    STATUS_STOPPED: "Paused",
    STATUS_DONE: "Finished",
    STATUS_ERROR: "Error",
}

# --- CS:GO launch options -------------------------------------------------

# Stripped-down launch options: no sound, no video, smallest possible window.
# Kept as one string because it is user-editable in the settings screen.
DEFAULT_LAUNCH_ARGUMENTS = (
    "-no-browser -noreactlogin -nodircheck -noconsole -skipinitialbootstrap "
    "-silent -noverifyfiles -norepairfiles -single_core -worldwide "
    "-language english -applaunch 730 -port 27020 -swapcores -noqueuedload "
    "-d3d9ex -disable_d3d9_hacks -dxlevel 90 -vrdisable -windowed -nopreload "
    "-limitvsconst -softparticlesdefaultoff -nohltv -noaafonts -nosound -novid "
    "-nojoy +violence_hblood 0 +sethdmodels 0 +mat_disable_fancy_blending 1 "
    "+r_dynamic 0 +exec autoexec.cfg -w 640 -h 480 -nomouse"
)

# Horizontal offset between consecutive game windows, in pixels.
WINDOW_TILE_STEP = 383

# --- Limits ---------------------------------------------------------------

# Maximum number of accounts one machine may commend for at the same time.
MAX_CONCURRENT_JOBS = 5

# Above this count only resellers may queue further accounts.
RESELLER_ONLY_JOBS = 3
