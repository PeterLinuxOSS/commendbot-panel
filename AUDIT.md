# CommendBot Panel — code audit (pre-open-source)

Source pulled from Google Drive `commendbot.ui/`:

| file | role | size |
|---|---|---|
| `V0.2/main.py` | GUI panel (customtkinter), MongoDB client, local TCP control server | 2028 lines |
| `run/main.py` | per-account client: launches Steam+CS:GO, auto-reconnects to servers | 364 lines |
| `V0.2/images/`, `V0.2/lib/cfg/` | assets and CS:GO cfg payload | — |
| `output/`, `tests/` | PyInstaller `dist/` output (binaries, not source) | — |

Panel version string: `2.6.3`. Both files were read in full.

---

## S — Secrets that must be rotated before anything is published

| # | where | what |
|---|---|---|
| S1 | `V0.2/main.py:206` | **Live MongoDB Atlas URI with username + password.** Full read/write on every collection: users, balances, blacklist, subscriptions, keys. |
| S2 | `V0.2/main.py:247`, `run/main.py:71-77` | Game-server hostnames + join passwords, hardcoded. |
| S3 | `V0.2/main.py:1695` | Personal SteamID64 hardcoded in a debug button. |
| S4 | `V0.2/main.py:1532`, `:1938` | Personal Discord user ID hardcoded as a limit bypass. |
| S5 | `V0.2/main.py:1524`, `:1929` | Private Discord invite link. |

S1 is in the shipped `.exe` too, so it is already exposed to every customer — rotating it is
worth doing regardless of open-sourcing.

---

## A — Real bugs (behaviour is wrong today)

### A1. `Auto-Reconnect off` never turns off — `run/main.py:191`
```python
autoreconnect = bool(edata.split("-")[1])  # bool("0") is True
```
The panel sends `autoreconnect-0` (`main.py:92`, `:1771`), the client reads it as `True`.
The checkbox has never worked in the "off" direction.

### A2. `Auto-Start` setting writes to the wrong variable — `V0.2/main.py:1773-1777`
```python
elif type == "autostart":
    regobj...set_subkey("Settings", {str(type): txt._check_state})
    global auto_start
    auto_reconnect = txt._check_state    # <-- assigns auto_reconnect, not auto_start
```
`auto_start` is never updated in the running process, and toggling Auto-Start silently
changes Auto-Reconnect instead.

### A3. Reconnect timeout can never expire — `run/main.py:194-195`
```python
finally:
   reconnect_timeout = 60
```
The `finally` runs on every loop pass, so the countdown at `:128`, `:137`, `:153` is reset
before it can reach 0. The client reconnects forever instead of giving up.

### A4. Half of the CS:GO config is never copied — `run/main.py:42-54`
`os.makedirs(ruserdata)` runs first, so `if not os.path.exists(target_folder_path)` on the
next line is always false and the `shutil.copy` nested under it never executes. The two
sibling loops (`:32-39`, `:59-66`) copy unconditionally — this one is the odd one out.

### A5. `min_commends` is never enforced — `V0.2/main.py:1492`, `:1892`
```python
if amount < 0:
    ...f"You cant use less than {slotdb['min_commends']} commends!"
```
The message names `min_commends`, the check compares against `0`.

### A6. The user-ID exemption is dead code — `V0.2/main.py:1532`, `:1938`
```python
if tdb >= 5 or tdb >= 5 and userid != <hardcoded id>:
```
`and` binds tighter than `or`, so this reduces to `tdb >= 5`. The special-cased account
gets the same limit as everyone else.

### A7. Steam-guard window check is inverted — `V0.2/main.py:148-157`
`timeout = 5` is overwritten with `-1` on the first pass, so the loop breaks immediately;
and the `while...else` branch (which runs only when the loop was *not* broken out of)
prints `retry IsWindow` and re-triggers `popen` — the retry fires on the success path.

### A8. Dict mutated while iterating — `V0.2/main.py:1859-1860`
```python
for id, data in check_verify.items():
    del check_verify[id]
```
`RuntimeError: dictionary changed size during iteration` as soon as there is more than one
pending account. Today it survives only because the code elsewhere refuses to queue a second.

### A9. Random dict keys collide — `V0.2/main.py:826`, `:833`, `:1437`
`check_verify[random.randint(0, 100)]` — a repeated key silently drops a pending account.

### A10. Every timestamp is the app start time — `V0.2/main.py:35-36`
`datetime_utc` is evaluated once at import and then written into every record
(`:364`, `:430`, `:682`, `:690`, `:1580`). Error logs and job records are all stamped with
when the panel was launched, not when the event happened.

### A11. Clock display drops a digit at minute 9 — `V0.2/main.py:1267`
`if 9 > dt.minute` — minute 9 renders as `14:9`. Should be `dt.minute < 10`.
Also shadows the builtin `min`.

### A12. `watch_mongodb` recurses instead of looping — `V0.2/main.py:1198-1200`
The change-stream watcher calls itself after each crash; stack depth grows for the lifetime
of the session and eventually hits `RecursionError`.

### A13. `raise` on a string — `run/main.py:133`
`raise "dissconnected"` is a `TypeError`. It happens to land in the bare `except` below, so
the reconnect path works by accident, not by design.

### A14. Retry branch is unreachable — `run/main.py:336-342`, `:345-351`
`elif not started or trecconect: timer += 20` precedes `elif timer >= 100`, so the retry
only ever fires when `started and not trecconect` — exactly the state where no retry is
wanted.

### A15. Status string typo makes a branch dead — `V0.2/main.py:1312`, `:1318`, `:1383`
The stored status value is `"stoped"` (one `p`). `select_profile:1383` compares against
`"stopped"`, so the "paused" case never re-enables the buttons.

### A16. Unguarded `None` from MongoDB
`find_one()` results are indexed without a null check: `:1361`→`:1377` (`serverdb["status"]`),
`:1488` (`slotdb["enable"]`), `:1510`/`:1913` (`balancedb["amount"]`), `:668`
(`servercheck["slot_id"]`). Any of these raises `TypeError` when the document is missing.

### A17. `KeyError` on client disconnect — `V0.2/main.py:173`
`del clients[steamid]` with `steamid` still `0` when a client disconnects before sending
`id-...`; the statement is outside the `try`.

### A18. `UnboundLocalError` in `clear_all` — `V0.2/main.py:589-638`
`img` is only assigned inside the four `else` branches. If `stay` is not one of the four
nav buttons, `stay.configure(image=img)` at `:637` raises.

### A19. `reason` read after the document is deleted — `V0.2/main.py:1132` → `:1154`
`delete_one` runs first, then the error path formats `idb['reason']`, which is not
guaranteed to be present on the in-memory copy.

### A20. The control channel has no message framing
Both ends do `data = sock.recv(1024)` and then compare the whole buffer with
`==` (`V0.2/main.py:84-94`, `run/main.py:131-158`). TCP is a byte stream: two
messages sent close together arrive in one buffer and match nothing, and a long
message can arrive split. The panel sends `autoreconnect-…` immediately after
the identification handshake, so this is reachable, not theoretical.

---

## B — Security / robustness

| # | where | issue |
|---|---|---|
| B1 | `V0.2/main.py:1970`, `run/main.py:287` | Steam **password passed as a command-line argument** — visible to any process listing on the machine. |
| B2 | `run/main.py:289` | `subprocess.Popen(list, shell=True)` — `shell=True` with a list is wrong on Windows and breaks on paths containing spaces. It is not needed here. |
| B3 | `V0.2/main.py:44-72` | The local control socket on `127.0.0.1:11569` has **no authentication**. Any local process can send `close`, `open`, `hwnd-...`. |
| B4 | `V0.2/main.py:117`, `:786` | The Steam `shared_secret` is held in a plain global dict and is also read from a plaintext `login:pass:amount:secret` text file. |
| B5 | `V0.2/main.py:473-479` | Panel login **and password are written to the registry in plaintext** (`HKCU\Software\CommendBotPR`), re-written on every login. |
| B6 | `V0.2/main.py:1503`/`1510`, `:1905`/`1913` | Check-then-act on slot currency and user balance. The author's own comment marks it: the balance is read, `newamount` computed — and then thrown away. Two jobs started quickly both pass the check. |
| B7 | both files | ~20 bare `except:` clauses swallow `KeyboardInterrupt` and `SystemExit` along with real errors. |
| B8 | `V0.2/main.py:242` | `wmic csproduct get uuid` for the HWID — `wmic` is deprecated and absent from Windows 11 24H2+. The parsing (`find("\\n")+2`, `[:-15]`) is brittle string surgery on `str(bytes)`. |
| B9 | `V0.2/main.py` (threads) | `configure()` / `messagebox` are called from `watch_mongodb`, `do_stuff` and socket threads. Tk is not thread-safe; widget updates must be marshalled to the main loop via `after()`. |
| B10 | `V0.2/main.py:1165` | `os.system("shutdown /s /t 1")` on a code path reachable from a database change event. |

---

## C — Structure / style (the "make it look professional" part)

- **One 2028-line module.** No packages, no separation between UI, data access, networking
  and process control.
- `from customtkinter import *` **plus** `from tkinter import Button, Frame, ...` — wildcard
  import colliding with explicit ones; `Frame`, `Button`, `CENTER`, `END` are ambiguous.
- Imports scattered through the file (`:3-32`, `import time` at `:20` after executable code).
- `class db()` is declared **inside** `connect()` inside a `try/else`. If the connection
  fails the name `db` never exists and every later reference is a `NameError`.
- `home_screen`, `commend_screen`, `balance_screen`, `settings_screen` are classes used as
  namespaces with unbound `def init()` — they should be modules or plain functions.
- ~30 module-level globals mutated from several threads (`current_account`, `accounts`,
  `clients`, `logs`, `wincounter`, `auto_reconnect`, ...).
- Private CustomTkinter attributes used as API: `._text`, `._image`, `._check_state`,
  `._update_image()`, `window._hWnd`. These break on library upgrades.
- Dead code: `premium`, `loopcount`, `csgo_started`, `event`, `sleep_sec`, `start_msg`,
  `region` (`run/main.py:186`), the commented-out block at `:2005-2007`, ~200 lines of
  blank filler (e.g. `:262-280`, `:1446-1468`).
- `run/main.py` is tab-indented, the panel is space-indented.
- Two Slovak comments left in the code (`run/main.py:292`, `#idk reseller` at
  `V0.2/main.py:1528`).
- Typos carried into identifiers: `beststerver`, `trecconect`, `dissconnected`, `stoped`.
- No `requirements.txt`, no `pyproject.toml`, no `.gitignore`, no licence, no README, no
  tests, no CI.

---

## D — Context that shapes the plan

- The target game is **CS:GO**, replaced by CS2 in September 2023. `csgo.exe`, the
  `-applaunch 730` argument set, `gameinfo.txt` patching and `console.log` scraping do not
  apply to CS2. The panel cannot be made to work again without rewriting the client.
- The panel is a thin client over a MongoDB that also backs a Discord bot (collections
  `guildsetting`, `privatechannels`, `commendbotstatus`, `sub`, `keysdb`, ...). That backend
  is not in *this* source tree — it is
  [commendbot](https://github.com/PeterLinuxOSS/commendbot), archived separately — so this
  repository is readable on its own but not runnable on its own.
- Windows-only by construction: `regobj`, `win32gui`, `wmic`, `pyautogui` screen matching,
  `steam.exe`.
