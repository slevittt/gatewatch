"""End to end: real curl -> relay -> fake exit -> local web server."""
import os
import threading

import pytest

from conftest import make_cfg
from gatewatch import check, guard, pac, pool, switch
from gatewatch.net import Exit
from gatewatch.state import load_guard_state, read_exit, write_exit

BIG = b"x" * 5000
STUB = b"<html>This service is not available in your country.</html>" + b"x" * 5000


def flow_cfg(tmp_path, relay_port, web_port, extra=""):
    return make_cfg(tmp_path,
                    "%s\n[check]\nrelay = 127.0.0.1:%d\nmin_size = 1000\ntimeout = 10\n"
                    "ip_url = http://127.0.0.1:%d/ip\n[targets]\nsite = http://127.0.0.1:%d/page\n"
                    "[pool]\ntest_url = http://127.0.0.1:%d/page\ntest_timeout = 10\n"
                    % (extra, relay_port, web_port, web_port, web_port))


@pytest.fixture(autouse=True)
def no_network_harvest(monkeypatch):
    """Tests must never download public proxy lists."""
    monkeypatch.setattr(guard.harvest_mod, "harvest_into_pool", lambda c: [])


@pytest.fixture
def chain(tmp_path, fakes, start_relay, web):
    web_port, pages = web
    pages["/page"], pages["/ip"] = BIG, b"198.51.100.4\n"
    up = fakes.http_proxy("exit1")
    base = make_cfg(tmp_path)
    write_exit(base, Exit.parse("http://127.0.0.1:%d" % up))
    relay, rport = start_relay(base)
    cfg = flow_cfg(tmp_path, rport, web_port)
    return cfg, pages, fakes, up


def test_check_is_green_when_everything_works(chain):
    cfg, pages, fakes, up = chain
    rep = check.evaluate(cfg)
    assert rep.code == 0, rep
    assert rep.targets["site"]["status"] == "ok" and rep.exit["status"] == "ok"


def test_check_catches_a_stub_page_served_with_http_200(chain):
    cfg, pages, *_ = chain
    pages["/page"] = STUB
    rep = check.evaluate(cfg)
    assert rep.code == 1 and rep.targets["site"]["status"] == "stub"


def test_check_catches_an_unreachable_target(chain):
    cfg, pages, *_ = chain
    del pages["/page"]                      # the site now answers 404
    assert check.evaluate(cfg).code == 2


def test_check_flags_a_relay_that_does_not_use_the_recorded_exit(chain):
    cfg, pages, fakes, up = chain
    # record an exit the relay is NOT using: the IP seen through it cannot be proven
    s = __import__("socket").socket()
    s.bind(("127.0.0.1", 0))
    dead = s.getsockname()[1]
    s.close()
    other = Exit.parse("http://127.0.0.1:%d" % dead)
    # the relay has already cached the old exit; rewrite the file WITHOUT bumping mtime
    st = os.stat(cfg.exit_file)
    write_exit(cfg, other)
    os.utime(cfg.exit_file, ns=(st.st_atime_ns, st.st_mtime_ns))
    rep = check.evaluate(cfg)
    assert rep.code == 3 and rep.exit["status"] == "mismatch"


def test_check_without_an_exit_is_code_3(tmp_path, web, start_relay):
    port, pages = web
    pages["/page"] = BIG
    relay, rport = start_relay(make_cfg(tmp_path))
    rep = check.evaluate(flow_cfg(tmp_path, rport, port))
    assert rep.code == 3 and rep.exit["status"] == "missing"


def test_switch_prefers_the_fastest_usable_node_and_keeps_a_good_current_one(chain, monkeypatch):
    cfg, pages, fakes, up = chain
    a, b = fakes.http_proxy("a"), fakes.http_proxy("b")
    pool.save(cfg, [Exit.parse("http://127.0.0.1:%d" % p) for p in (a, b)])
    assert switch.run(cfg) == 0 and read_exit(cfg).port == up      # current is fine: untouched
    assert switch.run(cfg, force=True) == 0 and read_exit(cfg).port in (a, b)


def test_switch_rolls_back_when_the_page_fails_through_the_relay(chain, monkeypatch):
    cfg, pages, fakes, up = chain
    bad = fakes.http_proxy("bad", status=403)
    pool.save(cfg, [Exit.parse("http://127.0.0.1:%d" % bad)])
    # the pool test says "ok" for every node, so only the verification through the relay can catch the bad one
    monkeypatch.setattr(switch, "test_many", lambda c, ex, w=None: [pool.Verdict(e, "ok", "fake", 0.1 if e.port == bad else 9)
                                                                  for e in ex])
    assert switch.run(cfg, force=True) == 4
    assert read_exit(cfg).port == up                                 # rolled back


def test_set_exit_by_hand(cfg):
    assert switch.set_exit(cfg, "socks5://u:p@203.0.113.9:1080") == 0
    assert read_exit(cfg).host == "203.0.113.9"
    assert switch.set_exit(cfg, "garbage") == 2


def test_prune_removes_dead_nodes(chain):
    cfg, pages, fakes, up = chain
    good = fakes.http_proxy("g")
    dead = fakes.http_proxy("d", status=403)
    pool.save(cfg, [Exit.parse("http://127.0.0.1:%d" % p) for p in (good, dead)])
    assert pool.prune(cfg) == 0
    assert [e.port for e in pool.load(cfg)] == [good]


def test_guard_repairs_notifies_only_on_state_changes(chain, monkeypatch, tmp_path):
    cfg, pages, fakes, up = chain
    sent = []
    monkeypatch.setattr(guard, "notify", lambda c, s, b: sent.append(s))
    pages["/page"] = STUB                                    # everything breaks, nothing can fix a stub target
    assert guard.run_once(cfg) == 1 and guard.run_once(cfg) == 1
    assert sent == ["gatewatch: targets unreachable"]          # one alert, not two
    assert load_guard_state(cfg)["status"] == "failed"
    pages["/page"] = BIG
    assert guard.run_once(cfg) == 0
    assert sent[-1] == "gatewatch: recovered" and len(sent) == 2
    assert guard.run_once(cfg) == 0 and len(sent) == 2      # healthy runs stay silent


def test_guard_switches_to_a_working_node_when_the_exit_dies(chain, monkeypatch):
    cfg, pages, fakes, up = chain
    monkeypatch.setattr(guard.harvest_mod, "harvest_into_pool", lambda c: [])
    good = fakes.http_proxy("good")
    pool.save(cfg, [Exit.parse("http://127.0.0.1:%d" % good)])
    s = __import__("socket").socket()
    s.bind(("127.0.0.1", 0))
    dead = s.getsockname()[1]
    s.close()
    st = os.stat(cfg.exit_file)
    write_exit(cfg, Exit.parse("http://127.0.0.1:%d" % dead))
    os.utime(cfg.exit_file, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))
    assert guard.run_once(cfg) == 0
    assert read_exit(cfg).port == good


def test_pac_fails_closed_and_lists_domains(cfg):
    cfg.cp.set("pac", "relay", "192.168.1.10:10813")
    cfg.cp.set("pac", "hosts", "app.example.com, .Example.org")
    text = pac.build(cfg)
    assert '"app.example.com", "example.org"' in text
    assert 'return "PROXY 192.168.1.10:10813";' in text
    assert "10813; DIRECT" not in text


def test_custom_stub_phrase_in_any_language(chain):
    cfg, pages, *_ = chain
    cfg.cp.set("check", "stub_phrases", "сервис недоступен")
    pages["/page"] = "<html>Этот сервис недоступен</html>".encode() + b"x" * 5000
    assert check.evaluate(cfg).code == 1


def test_the_default_targets_are_neutral(tmp_path):
    from gatewatch.config import Config
    c = Config()
    assert c.items("targets") == [("example", "https://example.com/")]
    assert "google" not in c.get("pac", "hosts")
