# Changelog

## 3.0.0 — open-source release

The first published version. The code it descends from was two scripts —
a 2 028-line `main.py` and a 364-line `run/main.py` — reorganised into a package
without changing what the program is meant to do. Audit ids in brackets refer to
[AUDIT.md](AUDIT.md).

### Removed from the source

* The MongoDB Atlas username and password, previously a literal in `main.py`
  and therefore inside every distributed `.exe` [S1]. The URI now comes from
  `COMMENDBOT_MONGO_URI` and there is no default.
* Server host names and join passwords, hard-coded in two places that had
  already drifted apart on the port numbers [S2]. They live in a JSON file now.
* A personal SteamID64 in a debug button [S3], a personal Discord user ID used
  as a limit bypass [S4], and a private Discord invite [S5].
* The panel password is no longer written to the registry in clear text [B5].
  Only the login name is remembered.

### Fixed

* **Auto-Reconnect could not be switched off.** The flag travelled as the string
  `"0"` and was read with `bool()`, which is `True` [A1].
* **Auto-Start wrote to the wrong variable.** Its handler declared
  `global auto_start` and then assigned to `auto_reconnect` [A2].
* **The reconnect budget never expired.** A `finally` reset the countdown on
  every pass, so a runner whose panel had exited retried forever [A3].
* **One of three configuration copies never ran.** Its `shutil.copy` was nested
  under a directory check that the two preceding lines had already satisfied
  [A4].
* **`min_commends` was never enforced** — the message named it, the comparison
  used `0` [A5].
* **A limit exemption was dead code.** `a >= 5 or a >= 5 and user != X` reduces
  to `a >= 5` [A6].
* **The Steam Guard retry fired on success**, because a `while…else` was read as
  if `else` ran on `break` [A7].
* **A dict was mutated while being iterated** over pending accounts [A8], and
  those accounts were keyed by `random.randint(0, 100)`, so two could collide
  and one would vanish [A9].
* **Every stored timestamp was the moment the panel started.** `datetime.now()`
  was evaluated once at import and reused in every document [A10].
* **Minute 9 rendered as `14:9`** [A11].
* **The change-stream watcher recursed instead of looping**, growing the stack
  for the lifetime of the session [A12].
* `raise "disconnected"` — a `TypeError` that happened to land in the bare
  `except` below it [A13].
* **The stalled-connection retry was unreachable**, because the branch above it
  matched in exactly the states the retry was meant for [A14].
* **The "paused" branch never matched**: the stored value is `stoped`, one
  comparison used `stopped` [A15].
* Unguarded `find_one()` results, a `KeyError` when a client disconnected before
  identifying itself, an `UnboundLocalError` in the navigation code, and a
  document read after it had been deleted [A16–A19].
* **The control channel had no message framing.** Two messages sent close
  together arrived as one `recv` buffer and matched nothing [A20].

### Changed

* **The control channel is authenticated.** Previously any local process could
  connect to `127.0.0.1:11569` and close every running game [B3].
* **Slot budget is spent with one conditional update** instead of read-then-write,
  closing a double-spend the original author had marked with a comment [B6].
* **Steam credentials no longer appear on the runner's command line**; they are
  sent over the control channel after the handshake [B1].
* **`subprocess.Popen` no longer uses `shell=True` with an argument list**, which
  on Windows silently dropped everything after the first element as soon as a
  path contained a space [B2].
* **Widgets are only touched from the Tk thread.** Background work marshals
  through `after()` [B9].
* **The machine ID no longer depends on `wmic`**, removed in Windows 11 24H2. It
  reads `MachineGuid`, falls back to a CIM query, then to a hashed MAC [B8].
* `os.system("shutdown /s /t 1")` became a 60-second delay, long enough to
  cancel [B10].
* Bare `except:` clauses that swallowed `KeyboardInterrupt` were narrowed [B7].

### Added

* A test-suite over the pure logic, with regression tests named after the audit
  entries above.
* `pyproject.toml`, ruff configuration, GitHub Actions CI, `.env.example`,
  `servers.example.json`, MIT licence, this changelog and `AUDIT.md`.

### Known limitations

* CS:GO only; CS2 is not supported and would need the runner rewritten.
* Windows only for real use.
* The MongoDB backend and the Discord bot that share the database are not part
  of this repository.
* The original icon assets are not redistributed.
