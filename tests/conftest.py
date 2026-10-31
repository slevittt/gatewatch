"""Test doubles: an echo server, a fake HTTP-CONNECT proxy, a fake SOCKS5 proxy and a tiny web server,
all on localhost, so the whole chain can be exercised without internet access."""
import asyncio
import http.server
import socket
import threading

import pytest

from gatewatch.config import Config
from gatewatch.relay import Relay, connect_http


class Loop:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.t = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.t.start()

    def run(self, coro, timeout=10):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout)

    def stop(self):
        async def _shutdown():
            for t in asyncio.all_tasks():
                if t is not asyncio.current_task():
                    t.cancel()
            await asyncio.sleep(0.1)
        try:
            self.run(_shutdown())
        except Exception:
            pass
        self.loop.call_soon_threadsafe(self.loop.stop)


@pytest.fixture
def loop():
    lp = Loop()
    yield lp
    lp.stop()


async def _pipe(r, w):
    try:
        while True:
            d = await r.read(65536)
            if not d:
                break
            w.write(d)
            await w.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            w.close()
        except Exception:
            pass


class Fakes:
    """Counts connections so a test can see WHICH upstream carried a tunnel."""
    def __init__(self, lp):
        self.lp = lp
        self.hits = {}

    def echo(self):
        async def h(r, w):
            await _pipe(r, w)
        srv = self.lp.run(asyncio.start_server(h, "127.0.0.1", 0))
        return srv.sockets[0].getsockname()[1]

    def http_proxy(self, name, status=200):
        async def h(r, w):
            head = await r.readuntil(b"\r\n\r\n")
            self.hits[name] = self.hits.get(name, 0) + 1
            if status != 200:
                w.write(b"HTTP/1.1 %d Nope\r\n\r\n" % status)
                w.close()
                return
            host, _, port = head.split()[1].decode().rpartition(":")
            ur, uw = await asyncio.open_connection(host, int(port))
            w.write(b"HTTP/1.1 200 OK\r\n\r\n")
            await asyncio.gather(_pipe(r, uw), _pipe(ur, w))
        srv = self.lp.run(asyncio.start_server(h, "127.0.0.1", 0))
        return srv.sockets[0].getsockname()[1]

    def socks5_proxy(self, name, user=None, password=None):
        async def h(r, w):
            await r.readexactly(1)
            n = (await r.readexactly(1))[0]
            methods = await r.readexactly(n)
            if user is not None:
                assert 2 in methods
                w.write(b"\x05\x02")
                await r.readexactly(1)
                ul = (await r.readexactly(1))[0]
                u = await r.readexactly(ul)
                pl = (await r.readexactly(1))[0]
                p = await r.readexactly(pl)
                ok = (u.decode(), p.decode()) == (user, password)
                w.write(b"\x01\x00" if ok else b"\x01\x01")
                if not ok:
                    w.close()
                    return
            else:
                w.write(b"\x05\x00")
            await r.readexactly(3)
            atyp = (await r.readexactly(1))[0]
            if atyp == 3:
                ln = (await r.readexactly(1))[0]
                host = (await r.readexactly(ln)).decode()
            elif atyp == 1:
                host = socket.inet_ntoa(await r.readexactly(4))
            else:
                host = socket.inet_ntop(socket.AF_INET6, await r.readexactly(16))
            port = int.from_bytes(await r.readexactly(2), "big")
            self.hits[name] = self.hits.get(name, 0) + 1
            ur, uw = await asyncio.open_connection(host, port)
            w.write(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")
            await asyncio.gather(_pipe(r, uw), _pipe(ur, w))
        srv = self.lp.run(asyncio.start_server(h, "127.0.0.1", 0))
        return srv.sockets[0].getsockname()[1]


@pytest.fixture
def fakes(loop):
    return Fakes(loop)


def make_cfg(tmp_path, extra=""):
    ini = tmp_path / "gatewatch.ini"
    ini.write_text("[paths]\nstate_dir = %s\n[relay]\nlisten = 127.0.0.1:0\nallow = 127.0.0.1/32\n"
                   "connect_timeout = 3\n%s" % (tmp_path, extra))
    return Config(str(ini))


@pytest.fixture
def cfg(tmp_path):
    return make_cfg(tmp_path)


@pytest.fixture
def start_relay(loop):
    def _start(cfg_):
        relay = Relay(cfg_)
        srv = loop.run(relay.start())
        return relay, srv.sockets[0].getsockname()[1]
    return _start


def tunnel(relay_port, host, port, payload=b"hello", timeout=5):
    """Open CONNECT host:port through the relay; return (status line, echoed bytes)."""
    s = socket.create_connection(("127.0.0.1", relay_port), timeout=timeout)
    s.sendall(("CONNECT %s:%d HTTP/1.1\r\nHost: x\r\n\r\n" % (host, port)).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
    status = buf.split(b"\r\n", 1)[0].decode()
    echoed = b""
    if " 200 " in status:
        s.sendall(payload)
        echoed = s.recv(4096)
    s.close()
    return status, echoed


class Web(http.server.BaseHTTPRequestHandler):
    pages = {}

    def do_GET(self):
        body = self.pages.get(self.path.split("?")[0])
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def web():
    Web.pages = {}
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Web)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv.server_address[1], Web.pages
    srv.shutdown()
