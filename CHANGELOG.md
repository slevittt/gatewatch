# Changelog

## 0.1.0 - first public version
- Relay (HTTP CONNECT) with hot-reloaded exit file, HTTP and SOCKS5 upstreams (with credentials), client allow-list, optional per-host fallback. No silent fallback.
- `check`: detects stub pages served with HTTP 200 and proves the relay leaves through the recorded exit.
- `harvest`, `prune`, `switch` (with verification and rollback), `guard` (escalating repair, alerts on state changes only).
- PAC generator/server (fails closed, neutral defaults), Chrome/Edge policy installers for Windows and Proxmox guests, systemd units.
- 39 automated tests that run offline.
