# Troubleshooting

Start with `gatewatch check`. Then use the table.

| You see | Likely cause | What to do |
|---|---|---|
| `STUB` on a target | The upstream is served a different page than you expect (for example because of its location), or it is not the upstream you think | `gatewatch switch --force`; try an upstream you control: `gatewatch switch --set socks5://...` |
| `DEAD` on every target | Relay down, or exit dead | `systemctl status gatewatch-relay`; `gatewatch status`; `gatewatch guard` |
| `exit  MISM`: relay IP != exit IP | The relay is not using the recorded exit (stale process, wrong state dir, file unreadable) | Run the relay and the CLI with the **same config and the same user**; `journalctl -u gatewatch-relay` |
| `exit  MISS` | No exit is set | `gatewatch switch --set URL` or `gatewatch harvest --add && gatewatch switch` |
| Check is green, browser shows the stub | The browser is not going through the relay, or an old tunnel is still open | `chrome://policy` shows `ProxySettings`? Disable proxy extensions. Close the browser completely and retry in an incognito window |
| `chrome://policy` has no `ProxySettings` | Policy not written, or written as invalid JSON | Re-run `Set-BrowserPac.ps1` (or the Proxmox helper); the output must show quotes: `{"ProxyMode":"pac_script",...}` |
| Everything loads slowly | Free public proxies are slow | Use your own exit. See `docs/SECURITY.md` |
| Relay logs `exit unreachable` | The exit died | `gatewatch guard` repairs it; the timer does it every 5 minutes |
| `gatewatch switch --set` works but the relay ignores it | The file is owned by another user (mode 0600) | Run gatewatch commands as the service user: `sudo -u gatewatch gatewatch switch --set ...` |
| Alerts never arrive | `notify_cmd` empty or failing | Test: `GATEWATCH_SUBJECT=x GATEWATCH_BODY=y sh -c '<your notify_cmd>'` |

## Useful one-liners

```
gatewatch check --json | python3 -m json.tool
curl -s http://127.0.0.1:10813/status
journalctl -u gatewatch-relay -f
journalctl -u gatewatch-guard --since "1 hour ago"
```
