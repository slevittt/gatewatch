import json
import os
import socket
import time

from conftest import make_cfg, tunnel
from gatewatch.net import Exit
from gatewatch.state import write_exit


def test_tunnel_through_http_connect_exit(cfg, fakes, start_relay):
    echo, up = fakes.echo(), fakes.http_proxy("a")
    write_exit(cfg, Exit.parse("http://127.0.0.1:%d" % up))
    relay, port = start_relay(cfg)
    status, data = tunnel(port, "127.0.0.1", echo)
    assert " 200 " in status and data == b"hello"
    assert fakes.hits == {"a": 1}


def test_tunnel_through_socks5_exit_with_domain_and_ip_targets(cfg, fakes, start_relay):
    echo, up = fakes.echo(), fakes.socks5_proxy("s")
    write_exit(cfg, Exit.parse("socks5://127.0.0.1:%d" % up))
    relay, port = start_relay(cfg)
    assert tunnel(port, "127.0.0.1", echo)[1] == b"hello"
    assert tunnel(port, "localhost", echo)[1] == b"hello"
    assert fakes.hits["s"] == 2


def test_socks5_username_password(cfg, fakes, start_relay):
    echo = fakes.echo()
    good = fakes.socks5_proxy("g", "bob", "s3cret")
    write_exit(cfg, Exit.parse("socks5://bob:s3cret@127.0.0.1:%d" % good))
    relay, port = start_relay(cfg)
    assert tunnel(port, "127.0.0.1", echo)[1] == b"hello"
    write_exit(cfg, Exit.parse("socks5://bob:WRONG@127.0.0.1:%d" % good))
    assert " 502 " in tunnel(port, "127.0.0.1", echo)[0]


def test_exit_switch_is_picked_up_without_restart(cfg, fakes, start_relay):
    echo, a, b = fakes.echo(), fakes.http_proxy("a"), fakes.http_proxy("b")
    write_exit(cfg, Exit.parse("http://127.0.0.1:%d" % a))
    relay, port = start_relay(cfg)
    tunnel(port, "127.0.0.1", echo)
    time.sleep(0.02)
    write_exit(cfg, Exit.parse("http://127.0.0.1:%d" % b))
    os.utime(cfg.exit_file, ns=(time.time_ns(), time.time_ns() + 10_000_000))
    tunnel(port, "127.0.0.1", echo)
    assert fakes.hits == {"a": 1, "b": 1}


def test_dead_exit_gives_502_and_never_falls_back_silently(cfg, fakes, start_relay):
    echo = fakes.echo()
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    dead = s.getsockname()[1]
    s.close()
    write_exit(cfg, Exit.parse("http://127.0.0.1:%d" % dead))
    relay, port = start_relay(cfg)
    assert " 502 " in tunnel(port, "127.0.0.1", echo)[0]
    assert relay.stats["upstream_errors"] == 1


def test_upstream_refusal_is_a_502(cfg, fakes, start_relay):
    echo, up = fakes.echo(), fakes.http_proxy("r", status=403)
    write_exit(cfg, Exit.parse("http://127.0.0.1:%d" % up))
    relay, port = start_relay(cfg)
    assert " 502 " in tunnel(port, "127.0.0.1", echo)[0]


def test_no_exit_configured_gives_503(cfg, fakes, start_relay):
    relay, port = start_relay(cfg)
    assert " 503 " in tunnel(port, "127.0.0.1", fakes.echo())[0]


def test_fallback_is_used_only_for_listed_hosts(tmp_path, fakes, start_relay):
    echo, main, fb = fakes.echo(), fakes.http_proxy("main"), fakes.http_proxy("fb")
    cfg = make_cfg(tmp_path, "fallback = http://127.0.0.1:%d\nfallback_hosts = localhost\n" % fb)
    write_exit(cfg, Exit.parse("http://127.0.0.1:%d" % main))
    relay, port = start_relay(cfg)
    tunnel(port, "localhost", echo)       # listed  -> fallback
    tunnel(port, "127.0.0.1", echo)       # others  -> the exit
    assert fakes.hits == {"fb": 1, "main": 1}


def test_clients_outside_allow_list_are_refused(tmp_path, fakes, start_relay):
    cfg = make_cfg(tmp_path)
    cfg.cp.set("relay", "allow", "10.0.0.0/8")
    echo, up = fakes.echo(), fakes.http_proxy("a")
    write_exit(cfg, Exit.parse("http://127.0.0.1:%d" % up))
    relay, port = start_relay(cfg)
    try:
        status, data = tunnel(port, "127.0.0.1", echo)
    except (ConnectionError, OSError):
        status, data = "", b""
    assert data == b"" and " 200 " not in status
    assert fakes.hits == {}
    assert relay.stats["denied"] == 1


def test_status_endpoint_reports_exit(cfg, fakes, start_relay):
    write_exit(cfg, Exit.parse("socks5://user:pw@127.0.0.1:9"))
    relay, port = start_relay(cfg)
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(b"GET /status HTTP/1.1\r\nHost: x\r\n\r\n")
    raw = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        raw += chunk
    body = json.loads(raw.split(b"\r\n\r\n", 1)[1])
    assert body["ok"] is True and body["exit"] == "socks5://127.0.0.1:9 (auth)"
    assert b"pw" not in raw                     # the password never leaves the host


def test_large_transfer_survives_the_chain(cfg, fakes, start_relay):
    echo, up = fakes.echo(), fakes.socks5_proxy("s")
    write_exit(cfg, Exit.parse("socks5://127.0.0.1:%d" % up))
    relay, port = start_relay(cfg)
    s = socket.create_connection(("127.0.0.1", port), timeout=10)
    s.sendall(("CONNECT 127.0.0.1:%d HTTP/1.1\r\nHost: x\r\n\r\n" % echo).encode())
    assert b"200" in s.recv(1024)
    payload = os.urandom(2_000_000)
    s.sendall(payload)
    got = b""
    while len(got) < len(payload):
        chunk = s.recv(65536)
        if not chunk:
            break
        got += chunk
    assert got == payload
