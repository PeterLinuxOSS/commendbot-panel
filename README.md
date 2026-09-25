# commendbot-panel

Server-side control panel for the **CommendBot** system. It manages the client agents (`commendbot-client`), dispatches tasks to them and launches them automatically (including the compiled `client.exe`).

## Overview
- Panel backend + UI
- Socket-based communication with clients

## CommendBot family
- **commendbot** — core bot (commend logic)
- **commendbot-panel** — server-side control panel (dispatches & manages clients)
- **commendbot-client** — client agent running on the machine (drives Steam/CS2)
- **commendbot-slots** — slot-based instance manager
- **shopmanager** — Discord sales/order bot (keys, licenses)

_Part of the gameboosting service ecosystem._
