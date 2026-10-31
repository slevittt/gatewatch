# Security and responsibility

## Free public proxies are untrusted
`harvest` pulls candidates from public lists. The operator of such a proxy can see **which hosts you
connect to and how much you transfer**, can drop or slow your traffic, and may log it. Content is
protected by TLS (the relay opens a CONNECT tunnel; gatewatch never terminates TLS), but metadata is not.

- Do not sign in to accounts you care about through a pool of free proxies.
- Prefer **your own exit**: a small VPS you control, running an HTTP or SOCKS5 proxy with
  authentication. `gatewatch switch --set socks5://user:pass@host:port`. The pool then becomes a spare.
- The target service sees the exit's IP address. Using a proxy may conflict with that service's terms,
  a network policy, or local law. You are responsible for your use.

## The relay is a proxy: keep it inside your LAN
- `allow` in `[relay]` lists the client networks (default: loopback and private ranges). Everything else is dropped.
- Do **not** forward the relay port to the internet. It has no authentication of its own.
- `/status` is served only to allowed clients and never prints credentials.

## Secrets
- `exit.json` and `pool.txt` are written with mode 0600 (they can contain proxy credentials).
- No API keys are used anywhere. The pool test is a plain page fetch.
- The PAC file is public inside the LAN by design. It contains the relay address and the domain list only.

## Reporting a vulnerability
Open a private security advisory on GitHub, or an issue without exploit details if advisories are off.
