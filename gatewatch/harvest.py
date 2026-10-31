"""Find new exits in public proxy lists. They are free, slow, and not trustworthy:
gatewatch only ever sends them requests for the pages it checks (always through a TLS tunnel)."""
import random
import re
import urllib.request
from typing import List

from .config import Config
from .log import log
from .net import Exit, UA
from .pool import Verdict, load, save, test_many

_ADDR = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})")


def _download(url: str, timeout: int = 20) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read(8_000_000).decode("utf-8", "replace")
    except Exception as e:
        log("harvest: cannot download %s: %s" % (url, e))
        return ""


def candidates(cfg: Config) -> List[Exit]:
    found = {"http": set(), "socks5": set()}
    for kind, key in (("http", "http_sources"), ("socks5", "socks5_sources")):
        for url in cfg.lst("harvest", key):
            for m in _ADDR.finditer(_download(url)):
                found[kind].add("%s:%s" % (m.group(1), m.group(2)))
    out: List[Exit] = []
    for kind, limit in (("http", cfg.int("harvest", "max_http")), ("socks5", cfg.int("harvest", "max_socks5"))):
        pick = random.sample(sorted(found[kind]), min(limit, len(found[kind])))
        out += [Exit.parse("%s://%s" % (kind, p)) for p in pick]
        log("harvest: %d %s candidates, testing %d" % (len(found[kind]), kind, len(pick)))
    return [e for e in out if e]


def harvest(cfg: Config) -> List[Verdict]:
    """Test fresh candidates, return the usable ones, fastest first."""
    verdicts = test_many(cfg, candidates(cfg), cfg.int("harvest", "workers") or 60)
    good = sorted((v for v in verdicts if v.status == "ok"), key=lambda v: v.seconds)
    log("harvest: %d usable nodes found" % len(good))
    return good


def harvest_into_pool(cfg: Config) -> List[Verdict]:
    good = harvest(cfg)
    known = {e.key for e in load(cfg)}
    save(cfg, load(cfg) + [v.exit for v in good if v.exit.key not in known])
    return good
