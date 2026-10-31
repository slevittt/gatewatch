<div align="center">

# Gatewatch

**A self-hosted PAC gateway and availability monitor for selected domains.**

[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](https://github.com/slevittt/gatewatch/blob/main/LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![Dependencies: none](https://img.shields.io/badge/dependencies-none-brightgreen.svg)
![Platform: Linux](https://img.shields.io/badge/platform-Linux-lightgrey.svg)

[Why Gatewatch](#why-gatewatch) ·
[How it works](#how-it-works) ·
[Features](#features) ·
[Quick start](#quick-start) ·
[Commands](#commands) ·
[Security](#security) ·
[Русский](https://github.com/slevittt/gatewatch/blob/main/README.ru.md)

</div>

---

## Why Gatewatch

A conventional health check answers one question: *"Is the proxy reachable?"*

It usually does not answer the question that matters:
**"Will the user actually see the page they expect?"**

A target can return HTTP 200, transfer hundreds of kilobytes, and still display an error page,
redirect, login wall, or service-unavailable notice. Meanwhile, the proxy pool reports that the
upstream is healthy and the monitoring dashboard stays green.

Gatewatch checks the result the way a browser user would see it:

```text
$ gatewatch check
service-a     STUB  stub page (not available in your country)
service-b     OK    HTTP 200, 503000 bytes
exit          OK    relay leaves through the exit (198.51.100.4)

$ echo $?
1                       # HTTP 200 was received, but the result is a failure
```

Gatewatch is a small self-hosted tool for a home network: one PAC file, one relay,
configurable targets, and automatic recovery when the selected upstream stops working.
The story behind it, and the seven reasons a green check can be wrong, is in
[docs/WHY-200-LIES.md](https://github.com/slevittt/gatewatch/blob/main/docs/WHY-200-LIES.md).

## How it works

```mermaid
flowchart LR
    B["Browsers on the home network<br/>PAC: selected domains only"] -->|CONNECT| R["Gatewatch relay"]
    R -->|reads on change| E[("exit.json")]
    R -->|"HTTP or SOCKS5"| X["Configured upstream<br/>your VPS or a proxy from a pool"]
    X --> T["Target websites"]
    W["Gatewatch guard<br/>systemd timer"] --> C["check"]
    W --> F["prune · harvest · switch"]
    F --> E
```

- The PAC file sends **only the domains you configure** to the Gatewatch relay.
- The relay forwards those requests through the current upstream.
- `guard` periodically runs a health check.
- If a target fails, Gatewatch attempts recovery: it prunes bad nodes, switches upstreams,
  and optionally discovers new candidates.
- If recovery fails, Gatewatch sends one state-change notification instead of repeating
  the same alert every few minutes.

All other traffic on the network is unaffected.

## Features

| Feature | What it provides |
|---|---|
| **Real-result checks** | `check` inspects the response text, not only the HTTP status code and response size. A stub page returned with HTTP 200 is treated as a failure. |
| **Route verification** | Compares the IP visible through the relay with the IP visible through the selected upstream. This helps detect requests that silently leave through an unexpected route. |
| **Loud failures** | An unavailable upstream returns HTTP 502 instead of silently falling back. The generated PAC does not include a hidden `DIRECT` fallback. |
| **Step-by-step recovery** | `guard` prunes the pool, switches the upstream, forces a switch, and discovers new candidates. It rechecks the target after each step. |
| **Hot upstream switching** | The current upstream is stored in a file and reloaded by the relay without a restart. A failed switch is rolled back. |
| **Configurable targets** | Define any URL and the response phrases that should be treated as failure indicators, in any language. |
| **One PAC for the network** | Configure it once for browsers and devices that support PAC files. |
| **Minimal dependencies** | Python standard library and `curl`. The codebase is intentionally small and readable. |
| **Offline tests** | 39 automated tests use local fake proxies and web servers to cover tunnels, authentication, ACLs, rollback, pool pruning, and notifications. |
| **Operational tooling** | `check --json`, hardened systemd units, a Windows helper script, and a Proxmox guest helper. |

## Quick start

Requirements: Linux, Python 3.9+, and `curl`.
Run the relay on an always-on machine in your home network: a mini PC, home server, NAS, or VM.

```bash
# 1. Install
git clone https://github.com/slevittt/gatewatch && cd gatewatch
sudo python3 -m venv /opt/gatewatch
sudo /opt/gatewatch/bin/pip install .
sudo ln -s /opt/gatewatch/bin/gatewatch /usr/local/bin/gatewatch

# 2. Create configuration
sudo useradd -r -s /usr/sbin/nologin gatewatch
sudo mkdir -p /etc/gatewatch
gatewatch init | sudo tee /etc/gatewatch/gatewatch.ini >/dev/null
sudoedit /etc/gatewatch/gatewatch.ini
#   [pac]      relay = 192.168.1.10:10813      (the relay as browsers will see it)
#              hosts = example.com             (the domains to route)
#   [targets]  example = https://example.com/  (what "working" means)

# 3. Install systemd services
sudo cp contrib/systemd/gatewatch-*.service contrib/systemd/gatewatch-guard.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gatewatch-relay gatewatch-pac gatewatch-guard.timer

# 4. Configure an upstream (run as the service user so the relay can read the file)
# A trusted VPS or private proxy is the recommended setup.
sudo -u gatewatch gatewatch -c /etc/gatewatch/gatewatch.ini switch --set socks5://user:pass@your-server.example:1080

# 5. Point browsers at the PAC file:  http://<gatewatch-host-IP>:8094/gatewatch.pac
#    Windows (PowerShell, as administrator):
#      .\contrib\windows\Set-BrowserPac.ps1 -PacUrl http://<IP>:8094/gatewatch.pac
#    Proxmox VM (from the host):
#      contrib/proxmox/set-browser-pac-via-qga.sh <vmid> http://<IP>:8094/gatewatch.pac

# 6. Verify
gatewatch -c /etc/gatewatch/gatewatch.ini check
```

After configuration, fully close and reopen the browser. In Chrome, open `chrome://policy`
and confirm that a `ProxySettings` policy is present.

## Commands

| Command | Purpose |
|---|---|
| `gatewatch check [--json]` | Check configured targets through the relay. Exit codes range from 0 to 3 ([meaning](https://github.com/slevittt/gatewatch/blob/main/docs/ARCHITECTURE.md)). |
| `gatewatch relay` | Start the HTTP CONNECT relay. |
| `gatewatch guard [--loop N]` | Run checks, recovery, and notifications. Usually launched by a systemd timer. |
| `gatewatch switch [--force] [--dry-run]` | Select a suitable upstream, verify it through the relay, and roll back on failure. |
| `gatewatch switch --set URL` | Set an upstream manually: `http://` or `socks5://`, optionally with credentials. |
| `gatewatch prune [--dry-run]` | Remove unhealthy nodes from the pool. |
| `gatewatch harvest [--add]` | Discover candidate nodes from configured public sources. |
| `gatewatch pac` / `gatewatch pac-serve` | Print or serve the PAC file. |
| `gatewatch init` | Print a default configuration template. |
| `gatewatch status` | Show the current upstream and pool size. |

## Configuration

All settings live in one INI file. See [`examples/gatewatch.ini`](https://github.com/slevittt/gatewatch/blob/main/examples/gatewatch.ini).

```ini
[relay]
allow = 127.0.0.1/32, 192.168.0.0/16

[targets]
# name = URL to check
my_service = https://example.com/

[check]
# A page smaller than this is not "the real page"
min_size = 1000
# Phrases that indicate a failure page, in any language
stub_phrases = not available in your country, access restricted

[pac]
# Relay address as seen by browsers
relay = 192.168.1.10:10813
# Domains routed through the relay
hosts = example.com, assets.example.com

[guard]
notify_cmd = sh -c 'echo "$GATEWATCH_BODY" | mail -s "$GATEWATCH_SUBJECT" you@example.com'
```

The `[targets]` section replaces the built-in default. You can monitor any web service
for which you know the URL and the text or pattern that indicates a failure.

## Security

For reliable operation, use a **trusted VPS**, home server, or other infrastructure you control
as the upstream.

Public proxies may be useful for experiments, but treat them as untrusted:

- They may log traffic, throttle it, or drop it. TLS protects content, not metadata.
- Their availability, location, and behavior are unpredictable.
- Do not use them for account logins, payments, work data, or other sensitive traffic.

The relay is a proxy: keep it inside your network, never forward its port to the internet, and keep
`[relay] allow` as narrow as you can. See [docs/SECURITY.md](https://github.com/slevittt/gatewatch/blob/main/docs/SECURITY.md).

## Project status

Gatewatch is in **beta**.

| Area | Status |
|---|---|
| Automated tests | HTTP/SOCKS5 tunnels, authentication, hot reload, HTTP 502/503 handling, ACLs, stub detection, upstream switching with rollback, pool pruning, notification hysteresis, and PAC generation. |
| End-to-end checks | The relay and `check` command are tested against local fake upstreams and web servers, including the real CLI as a subprocess. |
| Real deployment | The failure modes in [docs/WHY-200-LIES.md](https://github.com/slevittt/gatewatch/blob/main/docs/WHY-200-LIES.md) (causes 1-6) were diagnosed on the author's installation, and the guest-agent technique for the browser policy worked there. Cause 7 and the stale-tunnel note are suspected, not proven. |
| Not yet verified | This release on a clean machine against external services, the Docker files, Python 3.9 in CI, Firefox, and relay operation on macOS or Windows. |

A useful first issue report includes:

```bash
gatewatch -c /etc/gatewatch/gatewatch.ini check --json
```

Before sharing output, remove IP addresses, hostnames, credentials, cookies, tokens,
and any other private information.

## Roadmap

- JavaScript-rendered failure-page detection using a headless browser.
- Prometheus metrics endpoint.
- Optional relay authentication.
- Per-target upstream groups.
- A tested official Docker image.

## FAQ

**Is Gatewatch a VPN?**

No. Gatewatch is a small HTTP CONNECT relay plus a PAC file for selected domains.
It does not route all traffic from a device or network.

**Why not use a regular VPN client?**

A VPN client is usually configured per device, routes all traffic through one tunnel,
and may not detect when a particular website stops returning a usable result.
Gatewatch is centralized, affects only selected domains, and validates the actual result.

**Why PAC instead of a browser extension?**

A PAC file can be configured once for multiple browsers and devices. Browser extensions operate
within a profile and can conflict with system or organization-level proxy policies.

**Can I use it with other services?**

Yes. Add domains to `[pac] hosts`, a target URL to `[targets]`, and failure indicators
to `[check] stub_phrases`.

**Why does the checker use curl?**

`curl` supports HTTP and SOCKS5 proxies, performs a real TLS handshake, and makes it possible
to validate the path as a client would see it without running a full browser.

## Responsible use

Gatewatch is a general-purpose routing, monitoring, and recovery tool. What you route through it,
and through which upstream, is your decision and your responsibility.

Proxy use may be restricted by a service's terms, network policy, or local law. Ensure that
your use complies with applicable rules and regulations.

Public proxies are not trusted infrastructure. Do not use them for accounts, payments,
work-related data, or other sensitive traffic.

## Contributing and license

See [CONTRIBUTING.md](https://github.com/slevittt/gatewatch/blob/main/CONTRIBUTING.md).

Gatewatch is released under the MIT License. See [LICENSE](https://github.com/slevittt/gatewatch/blob/main/LICENSE).

If Gatewatch saved you an evening of debugging, consider giving the project a star.
