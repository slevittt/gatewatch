"""The pool of candidate exits (one URL per line) and how a node is judged."""
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Optional

from .config import Config
from .net import Exit, fetch, judge
from .state import _atomic_write


@dataclass
class Verdict:
    exit: Exit
    status: str          # ok | stub | dead
    msg: str
    seconds: float


def load(cfg: Config) -> List[Exit]:
    try:
        with open(cfg.pool_file, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    seen, out = set(), []
    for line in lines:
        ex = Exit.parse(line.strip()) if line.strip() and not line.lstrip().startswith("#") else None
        if ex and ex.key not in seen:
            seen.add(ex.key)
            out.append(ex)
    return out


def save(cfg: Config, exits: List[Exit]) -> None:
    _atomic_write(cfg.pool_file, "".join(e.url + "\n" for e in exits), 0o600)


def test_node(cfg: Config, ex: Exit) -> Verdict:
    res = fetch(cfg.get("pool", "test_url"), ex.curl_proxy, timeout=cfg.int("pool", "test_timeout") or 20,
                lang=cfg.get("check", "accept_language") or "ru")
    status, msg = judge(res, cfg.int("check", "min_size"), cfg.lst("check", "stub_phrases"))
    return Verdict(ex, status, msg, res.seconds)


def test_many(cfg: Config, exits: List[Exit], workers: Optional[int] = None) -> List[Verdict]:
    if not exits:
        return []
    with ThreadPoolExecutor(max_workers=workers or cfg.int("pool", "workers") or 8) as pool:
        return list(pool.map(lambda e: test_node(cfg, e), exits))


def print_verdicts(verdicts: List[Verdict], current: Optional[Exit] = None) -> None:
    for v in verdicts:
        mark = {"ok": "OK  ", "stub": "STUB", "dead": "DEAD"}[v.status]
        cur = "   <- current exit" if current and v.exit.key == current.key else ""
        print("%s %-34s %5.1fs  %s%s" % (mark, v.exit.display, v.seconds, v.msg, cur))


def prune(cfg: Config, dry_run: bool = False) -> int:
    exits = load(cfg)
    if not exits:
        print("pool is empty (%s)" % cfg.pool_file)
        return 1
    verdicts = test_many(cfg, exits)
    print_verdicts(verdicts)
    keep = [v.exit for v in verdicts if v.status == "ok"]
    print("usable: %d of %d" % (len(keep), len(exits)))
    if not dry_run and len(keep) != len(exits):
        if os.path.exists(cfg.pool_file):
            os.replace(cfg.pool_file, cfg.pool_file + ".bak")
        save(cfg, keep)
        print("pool rewritten (backup: %s.bak)" % cfg.pool_file)
    return 0 if keep else 1
