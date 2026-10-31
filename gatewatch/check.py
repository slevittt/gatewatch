"""Health check that cannot be fooled by a stub page.

Exit codes: 0 all good | 1 a target answers with a stub page | 2 a target is unreachable
            3 the relay is not leaving through the recorded exit (or there is no exit)
"""
import json
from dataclasses import dataclass, field
from typing import Dict, Optional

from .config import Config
from .net import as_ip, fetch, judge
from .state import read_exit


@dataclass
class Report:
    code: int = 0
    targets: Dict[str, dict] = field(default_factory=dict)
    exit: Optional[dict] = None


def evaluate(cfg: Config) -> Report:
    rep = Report()
    relay = "http://" + cfg.get("check", "relay")
    timeout = cfg.int("check", "timeout") or 30
    lang = cfg.get("check", "accept_language") or "ru"
    min_size, phrases = cfg.int("check", "min_size"), cfg.lst("check", "stub_phrases")
    rank = {"ok": 0, "stub": 1, "dead": 2}
    for name, url in cfg.items("targets"):
        res = fetch(url, relay, timeout=timeout, lang=lang)
        status, msg = judge(res, min_size, phrases)
        rep.targets[name] = {"status": status, "message": msg, "http": res.code, "bytes": res.size}
        rep.code = max(rep.code, rank[status])

    ex = read_exit(cfg)
    ip_url = cfg.get("check", "ip_url")
    if ex is None:
        rep.exit = {"status": "missing", "message": "no exit is set (gatewatch switch / harvest)"}
        rep.code = 3
    elif ip_url:
        via_relay = as_ip(fetch(ip_url, relay, timeout=timeout, lang=lang).body)
        direct = as_ip(fetch(ip_url, ex.curl_proxy, timeout=timeout, lang=lang).body)
        same = bool(via_relay) and via_relay == direct
        rep.exit = {"status": "ok" if same else "mismatch", "exit": ex.display,
                    "ip_via_relay": via_relay or None, "ip_via_exit": direct or None,
                    "message": ("relay leaves through the exit (%s)" % via_relay) if same else
                    "relay IP %s != exit IP %s: the relay is not using the recorded exit" %
                    (via_relay or "?", direct or "?")}
        if not same:
            rep.code = 3
    else:
        rep.exit = {"status": "skipped", "exit": ex.display, "message": "ip_url is empty"}
    return rep


def render(rep: Report, color: bool) -> str:
    def paint(txt: str, status: str) -> str:
        if not color:
            return txt
        c = {"ok": "32", "skipped": "33", "stub": "31", "dead": "31", "mismatch": "31", "missing": "31"}[status]
        return "\033[%sm%s\033[0m" % (c, txt)
    lines = []
    for name, t in rep.targets.items():
        lines.append("%-12s %s  %s" % (name, paint("%-4s" % t["status"].upper(), t["status"]), t["message"]))
    if rep.exit:
        lines.append("%-12s %s  %s" % ("exit", paint("%-4s" % rep.exit["status"].upper()[:4], rep.exit["status"]),
                                       rep.exit["message"]))
    return "\n".join(lines)


def run(cfg: Config, as_json: bool = False, quiet: bool = False, color: bool = False) -> int:
    rep = evaluate(cfg)
    if not quiet:
        if as_json:
            print(json.dumps({"code": rep.code, "targets": rep.targets, "exit": rep.exit}, indent=1))
        else:
            print(render(rep, color))
    return rep.code
