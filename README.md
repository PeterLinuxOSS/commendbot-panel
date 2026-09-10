# CommendBot Panel

A Windows desktop controller that drove CS:GO commend jobs: it signed Steam
accounts in, kept their game clients on a set of community servers, and tracked
progress against the same MongoDB the rest of the service used.

It was the operator-facing half of a paid commend service run under the **r4p
Services** brand (gameboosting.top) from November 2019 to January 2025. The
service has been retired; this repository is an archive, published for
reference. All credentials have been removed and rotated.

**This is an archive release.** CS:GO was replaced by Counter-Strike 2 in
September 2023. The runner works by patching `csgo/gameinfo.txt` and tailing
`csgo/console.log`, neither of which applies to CS2, so the tool does not
function against a current install. It is published for the code, not the
capability — see [AUDIT.md](AUDIT.md) for a full account of what was wrong with
the original and what was changed.

> Automating commends is against the Steam Subscriber Agreement. Running this
> risks the accounts involved. It is here as a record of a finished project.

## Where this fits

Four repositories, one retired service. They talk to each other exclusively
through MongoDB collections — one component records a request, another acts on
it and writes progress back.

| repository | role |
|---|---|
| [commendbot](https://github.com/PeterLinuxOSS/commendbot) | Discord bot: the management and commerce layer — balances, tickets, resellers |
| [commendbot-slots](https://github.com/PeterLinuxOSS/commendbot-slots) | the worker processes that actually delivered the commends |
| **commendbot-panel** (this repo) | the desktop client an operator ran on the machine hosting the game clients |
| [shopmanager](https://github.com/PeterLinuxOSS/shopmanager) | the storefront bot that sold the commends in the first place |

The panel writes to `serverusers` and `waitinglist` and reads `commendbotstatus`,
`balancesdb`, `usersdb` and `blacklistdb`; `commendbot` is the other end of every
one of those. Neither repository ships the database, so each is readable on its
own but neither runs alone.

## Demo

A walkthrough of the panel in use, recorded while CS:GO was still the live game:

[![CommendBot Panel — overview](https://img.youtube.com/vi/eW5n4UGVCA8/maxresdefault.jpg)](https://youtu.be/eW5n4UGVCA8)

---

## What is in the box

```
src/commendbot_panel/
├── config.py        settings: environment for secrets, registry/JSON for prefs
├── constants.py     every value that used to be a magic number
├── database.py      MongoDB access, one typed method per operation
├── jobs.py          the rules for whether an order may be placed — pure
├── servers.py       the server pool and least-busy selection — pure
├── windows.py       registry, window handles, process control; no-ops elsewhere
├── ipc/             the loopback control channel (framed, authenticated)
├── steam/           IDs, loginusers.vdf, Steam Guard, gameinfo, launching
├── runner/          the per-account process that babysits one game client
└── ui/              CustomTkinter front-end, the only place that touches Tk
```

Two processes. The **panel** is the window; it owns the database connection and
listens on `127.0.0.1:11569`. One **runner** is started per account; it launches
Steam, keeps the client on a server, and reports back over that channel.

Everything outside `ui/` imports cleanly on Linux with no Steam, no Windows and
no database, which is what makes the test-suite possible.

## Requirements

* Windows 10/11 for actual use — Steam, `pywin32` and screen automation.
* Python 3.11+.
* A MongoDB deployment with the collections the panel expects (`usersdb`,
  `balancesdb`, `commendbotstatus`, `serverusers`, `waitinglist`, `blacklistdb`,
  `errors`). Those documents are created and consumed by
  [commendbot](https://github.com/PeterLinuxOSS/commendbot) — without it running
  against the same database, a fresh clone is a client with nothing to talk to.

## Setup

```bash
git clone https://github.com/PeterLinuxOSS/commendbot-panel
cd commendbot-panel
python -m venv .venv && .venv\Scripts\activate
pip install -e .

copy .env.example .env          # then fill in COMMENDBOT_MONGO_URI
copy servers.example.json servers.json
```

Run it:

```bash
commendbot-panel
```

There is deliberately no default connection string. The original had a live
MongoDB Atlas user and password as a literal in the source — and therefore in
every distributed `.exe`. If `COMMENDBOT_MONGO_URI` is unset the panel says so
and exits.

The icon and PNG assets are not redistributed; see
[`assets/images/README.md`](assets/images/README.md). Without them the panel
still runs, with text labels instead of icons.

## Development

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check .
pytest -q
```

The tests cover the parts that carry the logic: order validation, the wire
protocol, server selection, Steam ID parsing, the VDF reader and the settings
round-trip. Several are named after entries in `AUDIT.md` and exist to keep a
specific historical bug from coming back.

## Configuration

| Variable | Required | Meaning |
|---|---|---|
| `COMMENDBOT_MONGO_URI` | yes | MongoDB connection string |
| `COMMENDBOT_IPC_TOKEN` | no | shared secret for the control channel; generated per run when unset |
| `COMMENDBOT_SERVERS_FILE` | no | path to the server pool JSON |

Paths, launch options and the two automation switches are edited in the
Settings screen and stored under `HKCU\Software\CommendBotPR\Settings`.

## Security notes

Three things are worth knowing before running this anywhere real.

**Steam passwords reach a command line.** Steam accepts credentials only as
`steam.exe -login <user> <pass>`, so they are briefly visible in the process
list. The panel no longer *also* puts them on the runner's command line — the
runner receives them over the authenticated control channel — but the exposure
to `steam.exe` itself is not avoidable.

**Steam Guard shared secrets are credentials.** Anyone holding one can sign into
that account indefinitely. Supplying them is optional throughout.

**The control channel is loopback-only and token-authenticated.** In the
original anything running on the machine could connect to port 11569 and shut
down every game client.

## Licence

MIT — see [LICENSE](LICENSE).
