# commendbot-panel

Serverový ovládací panel systému **CommendBot**. Riadi klientske agenty (`commendbot-client`), dispečuje im úlohy a spúšťa ich automaticky (aj skompilovaný `client.exe`).

## Súčasti
- panel backend + UI
- komunikácia s klientmi cez socket

## Rodina CommendBot
- **commendbot** — jadro bota (commend logika)
- **commendbot-panel** — serverový ovládací panel (spúšťa a riadi klientov)
- **commendbot-client** — klientský agent bežiaci na stroji (ovláda Steam/CS2)
- **commendbot-slots** — slotový systém inštancií
- **shopmanager** — predajný/objednávkový Discord bot (kľúče, licencie)

_Súčasť ekosystému služby gameboosting._
