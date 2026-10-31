"""The watchdog: check, repair, tell a human only when it matters (state changes, not every run)."""
import fcntl
import os
import shlex
import subprocess
import time

from . import check as check_mod
from . import harvest as harvest_mod
from . import pool as pool_mod
from . import switch as switch_mod
from .config import Config
from .log import log
from .state import load_guard_state, save_guard_state

MEANING = {1: "stub page", 2: "unreachable", 3: "relay/exit inconsistent"}


def notify(cfg: Config, subject: str, body: str) -> None:
    cmd = cfg.get("guard", "notify_cmd")
    if not cmd:
        return
    env = dict(os.environ, GATEWATCH_SUBJECT=subject, GATEWATCH_BODY=body)
    try:
        subprocess.run(shlex.split(cmd), env=env, timeout=60, capture_output=True)
    except Exception as e:
        log("guard: notify_cmd failed: %r" % e)


def _quiet(fn, *a, **kw):
    """Run a command-style function without its console output."""
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        return fn(*a, **kw)


def repair(cfg: Config) -> int:
    """Escalating repair; returns the final check code."""
    _quiet(pool_mod.prune, cfg)
    _quiet(switch_mod.run, cfg)
    code = check_mod.evaluate(cfg).code
    if code == 0:
        return 0
    # the node may look fine from here and still fail through the relay: take another one
    _quiet(switch_mod.run, cfg, force=True)
    code = check_mod.evaluate(cfg).code
    if code == 0:
        return 0
    if len(pool_mod.load(cfg)) < max(1, cfg.int("guard", "harvest_below")) or code != 3:
        log("guard: harvesting new public proxies")
        harvest_mod.harvest_into_pool(cfg)
        _quiet(switch_mod.run, cfg, force=True)
        code = check_mod.evaluate(cfg).code
    return code


def run_once(cfg: Config) -> int:
    os.makedirs(cfg.state_dir, exist_ok=True)
    lock = open(cfg.state_path("guard.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("guard: another run is in progress")
        return 0
    st = load_guard_state(cfg)
    code = check_mod.evaluate(cfg).code
    if code != 0:
        log("guard: check failed (%d: %s) - repairing" % (code, MEANING.get(code, "?")))
        code = repair(cfg)
    if code == 0:
        if st.get("status") == "failed":
            log("guard: recovered")
            notify(cfg, "gatewatch: recovered", "The targets are reachable again.")
        save_guard_state(cfg, {"status": "ok", "since": time.time()})
        return 0
    log("guard: STILL FAILING (%d: %s)" % (code, MEANING.get(code, "?")))
    if st.get("status") != "failed":
        notify(cfg, "gatewatch: targets unreachable",
               "check code %d (%s); automatic repair did not help." % (code, MEANING.get(code, "?")))
        st = {"status": "failed", "since": time.time()}
    save_guard_state(cfg, st)
    return 1


def run(cfg: Config, loop: int = 0) -> int:
    if not loop:
        return run_once(cfg)
    while True:
        run_once(cfg)
        time.sleep(loop)
