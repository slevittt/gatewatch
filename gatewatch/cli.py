import argparse
import os
import sys

from . import __version__
from .config import DEFAULT_INI, DEFAULT_PAC_HOSTS, Config
from .log import setup as log_setup


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="gatewatch", description="Keep region-locked AI web apps reachable for a LAN.")
    ap.add_argument("-c", "--config", help="path to gatewatch.ini")
    ap.add_argument("--version", action="version", version="gatewatch " + __version__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("check", help="check the targets through the relay (detects stub pages)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--quiet", action="store_true", help="exit code only")
    sub.add_parser("relay", help="run the LAN relay")
    p = sub.add_parser("switch", help="pick the best exit from the pool")
    p.add_argument("--force", action="store_true", help="change even if the current exit looks fine")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--set", metavar="URL", help="set the exit by hand (http:// or socks5://), e.g. your own VPS")
    p = sub.add_parser("prune", help="drop unusable nodes from the pool")
    p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("harvest", help="find usable nodes in public lists")
    p.add_argument("--add", action="store_true", help="add the usable ones to the pool")
    p = sub.add_parser("guard", help="check + repair + notify (run from a timer)")
    p.add_argument("--loop", type=int, default=0, metavar="SECONDS", help="repeat forever (for containers)")
    sub.add_parser("pac", help="print the PAC file")
    p = sub.add_parser("pac-serve", help="serve the PAC file over HTTP")
    p.add_argument("--port", type=int, default=8094)
    sub.add_parser("init", help="print a default gatewatch.ini")
    sub.add_parser("status", help="show the current exit and the pool")

    args = ap.parse_args(argv)
    if args.cmd == "init":
        print(DEFAULT_INI.replace("{pac_hosts}", DEFAULT_PAC_HOSTS), end="")
        return 0
    cfg = Config(Config.find(args.config))
    log_setup(cfg.get("paths", "log_file"))

    from . import check, guard, harvest, pac, pool, relay, switch
    from .state import read_exit
    if args.cmd == "check":
        return check.run(cfg, as_json=args.json, quiet=args.quiet, color=sys.stdout.isatty())
    if args.cmd == "relay":
        relay.serve(cfg)
        return 0
    if args.cmd == "switch":
        return switch.set_exit(cfg, args.set) if args.set else switch.run(cfg, args.force, args.dry_run)
    if args.cmd == "prune":
        return pool.prune(cfg, args.dry_run)
    if args.cmd == "harvest":
        good = harvest.harvest_into_pool(cfg) if args.add else harvest.harvest(cfg)
        pool.print_verdicts(good)
        print("%d usable nodes%s" % (len(good), " added to the pool" if args.add else ""))
        return 0 if good else 1
    if args.cmd == "guard":
        return guard.run(cfg, args.loop)
    if args.cmd == "pac":
        print(pac.build(cfg), end="")
        return 0
    if args.cmd == "pac-serve":
        pac.serve(cfg, args.port)
        return 0
    if args.cmd == "status":
        ex = read_exit(cfg)
        print("exit: %s" % (ex.display if ex else "not set"))
        print("pool: %d nodes (%s)" % (len(pool.load(cfg)), cfg.pool_file))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
