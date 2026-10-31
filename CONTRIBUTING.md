# Contributing

Bug reports with a **`gatewatch check --json`** output and the relevant `journalctl -u gatewatch-relay` lines are the most useful thing you can send.

```
git clone https://github.com/slevittt/gatewatch && cd gatewatch
python3 -m pytest        # the tests run offline: they use local fake proxies and a local web server
```

Rules of the road
- Standard library only. `curl` is the one external tool, on purpose.
- Every behaviour that came from a real outage has a test and a line in `docs/WHY-200-LIES.md`. Keep it that way.
- New check ideas (headless-browser stub detection, other targets) are very welcome: open an issue first.
