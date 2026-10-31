"""Choose the exit. The relay re-reads the exit file, so switching never restarts anything."""
import socket
from typing import Optional

from .config import Config
from .log import log
from .net import Exit, fetch, judge
from .pool import load, print_verdicts, test_many
from .state import read_exit, restore_exit_backup, write_exit


def relay_reachable(cfg: Config) -> bool:
    host, port = cfg.hostport("check", "relay")
    try:
        with socket.create_connection((host, port), timeout=2):
            return True
    except OSError:
        return False


def verify_via_relay(cfg: Config) -> Optional[bool]:
    """True/False after fetching the test page through the relay, None when the relay is not running here."""
    if not relay_reachable(cfg):
        return None
    res = fetch(cfg.get("pool", "test_url"), "http://" + cfg.get("check", "relay"),
                timeout=cfg.int("check", "timeout") or 30, lang=cfg.get("check", "accept_language") or "ru")
    return judge(res, cfg.int("check", "min_size"), cfg.lst("check", "stub_phrases"))[0] == "ok"


def set_exit(cfg: Config, url: str) -> int:
    ex = Exit.parse(url)
    if not ex:
        print("not a valid proxy URL: %s (use http://host:port or socks5://host:port)" % url)
        return 2
    write_exit(cfg, ex, "set manually")
    print("exit set to %s" % ex.display)
    return 0


def run(cfg: Config, force: bool = False, dry_run: bool = False) -> int:
    cur = read_exit(cfg)
    cands = load(cfg)
    if cur and cur.key not in {c.key for c in cands}:
        cands.append(cur)
    if not cands:
        print("no candidates: the pool is empty and no exit is set (try: gatewatch harvest --add)")
        return 2
    verdicts = test_many(cfg, cands)
    print_verdicts(verdicts, cur)
    good = sorted((v for v in verdicts if v.status == "ok"), key=lambda v: v.seconds)
    if not good:
        print("no usable node right now")
        return 2
    cur_ok = bool(cur) and any(v.exit.key == cur.key for v in good)
    if cur_ok and not force:
        print("current exit is fine, nothing to change")
        return 0
    others = [v for v in good if not cur or v.exit.key != cur.key]
    if not others:
        print("current exit is the only usable node, nothing to change")
        return 0
    pick = others[0]
    print("picked: %s" % pick.exit.display)
    if dry_run:
        return 0
    write_exit(cfg, pick.exit, "switch --force" if force else "switch")
    log("exit switched to %s" % pick.exit.display)
    if verify_via_relay(cfg) is False:
        restore_exit_backup(cfg)
        print("the page does not open through the relay with the new exit - rolled back")
        return 4
    print("done")
    return 0
