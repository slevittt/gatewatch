"""The LAN relay: an HTTP CONNECT proxy that sends every tunnel through the CURRENT exit.

Design rules (each one comes from a real outage):
  * The exit lives in a file and is re-read when the file changes: switching needs no restart.
  * NO SILENT FALLBACK. If the exit is dead the client gets 502 and the guard repairs it.
    A relay that quietly takes another path makes every health check green and the app broken.
  * Only the configured client networks may use it (it is an open proxy otherwise).
"""
import asyncio
import base64
import ipaddress
import json
import os
from collections import Counter
from typing import Optional, Tuple

from .config import Config
from .log import log
from .net import Exit


def matches(host: str, suffixes) -> bool:
    h = host.lower().rstrip(".")
    return any(h == s.lower().lstrip(".") or h.endswith("." + s.lower().lstrip(".")) for s in suffixes)


def split_hostport(target: str) -> Tuple[str, int]:
    if target.startswith("["):                       # [v6]:port
        host, _, rest = target[1:].partition("]")
        return host, int(rest.lstrip(":") or 443)
    host, _, port = target.rpartition(":")
    return (host, int(port)) if host else (target, 443)


async def connect_http(up: Exit, host: str, port: int):
    r, w = await asyncio.open_connection(up.host, up.port)
    try:
        hp = "[%s]:%d" % (host, port) if ":" in host else "%s:%d" % (host, port)
        req = "CONNECT %s HTTP/1.1\r\nHost: %s\r\n" % (hp, hp)
        if up.user:
            tok = base64.b64encode(("%s:%s" % (up.user, up.password)).encode()).decode()
            req += "Proxy-Authorization: Basic %s\r\n" % tok
        w.write((req + "\r\n").encode())
        await w.drain()
        head = await r.readuntil(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0].split()
        if len(status) < 2 or status[1] != b"200":
            raise ConnectionError("upstream said %s" % head.split(b"\r\n", 1)[0].decode("latin-1"))
        return r, w
    except BaseException:
        w.close()
        raise


async def connect_socks5(up: Exit, host: str, port: int):
    r, w = await asyncio.open_connection(up.host, up.port)
    try:
        w.write(b"\x05\x02\x00\x02" if up.user else b"\x05\x01\x00")
        await w.drain()
        ver, method = await r.readexactly(2)
        if ver != 5:
            raise ConnectionError("not a SOCKS5 server")
        if method == 2:
            u, p = up.user.encode(), up.password.encode()
            w.write(b"\x01" + bytes([len(u)]) + u + bytes([len(p)]) + p)
            await w.drain()
            if (await r.readexactly(2))[1] != 0:
                raise ConnectionError("SOCKS5 authentication failed")
        elif method != 0:
            raise ConnectionError("SOCKS5: no acceptable auth method")
        try:
            ip = ipaddress.ip_address(host)
            addr = (b"\x01" if ip.version == 4 else b"\x04") + ip.packed
        except ValueError:
            hb = host.encode("idna")
            addr = b"\x03" + bytes([len(hb)]) + hb
        w.write(b"\x05\x01\x00" + addr + port.to_bytes(2, "big"))
        await w.drain()
        head = await r.readexactly(4)
        if head[1] != 0:
            raise ConnectionError("SOCKS5 reply code %d" % head[1])
        atyp = head[3]
        n = 4 if atyp == 1 else 16 if atyp == 4 else (await r.readexactly(1))[0]
        await r.readexactly(n + 2)
        return r, w
    except BaseException:
        w.close()
        raise


async def open_via(up: Exit, host: str, port: int):
    return await (connect_socks5 if up.scheme == "socks5" else connect_http)(up, host, port)


async def pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await src.read(65536)
            if not data:
                break
            dst.write(data)
            await dst.drain()
        if dst.can_write_eof():
            dst.write_eof()
    except (ConnectionError, OSError):
        dst.close()


def reply(code: int, text: str, body: bytes = b"", ctype: str = "text/plain") -> bytes:
    return ("HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %d\r\nConnection: close\r\n\r\n"
            % (code, text, ctype, len(body))).encode() + body


class Relay:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.allow = [ipaddress.ip_network(x, strict=False) for x in cfg.lst("relay", "allow")]
        self.fallback: Optional[Exit] = Exit.parse(cfg.get("relay", "fallback"))
        self.fallback_hosts = cfg.lst("relay", "fallback_hosts")
        self.timeout = cfg.int("relay", "connect_timeout") or 15
        self.stats: Counter = Counter()
        self._exit: Optional[Exit] = None
        self._mtime: Optional[int] = None

    # -- state ----------------------------------------------------------
    def current_exit(self) -> Optional[Exit]:
        path = self.cfg.exit_file
        try:
            mtime = os.stat(path).st_mtime_ns
        except FileNotFoundError:
            self._exit, self._mtime = None, None
            return None
        if mtime != self._mtime:
            try:
                with open(path, encoding="utf-8") as f:
                    self._exit = Exit.parse(json.load(f)["url"])
                log("relay: exit is now %s" % (self._exit.display if self._exit else "invalid"))
            except (OSError, ValueError, KeyError):
                self._exit = None
                log("relay: exit file unreadable")
            self._mtime = mtime
        return self._exit

    def allowed(self, ip: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        return any(addr in net for net in self.allow)

    # -- connections ----------------------------------------------------
    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = (writer.get_extra_info("peername") or ("?", 0))[0]
        try:
            if not self.allowed(peer):
                self.stats["denied"] += 1
                return
            head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 15)
            parts = head.split(b"\r\n", 1)[0].decode("latin-1").split()
            if len(parts) < 2:
                return
            method, target = parts[0].upper(), parts[1]
            if method == "CONNECT":
                await self.tunnel(reader, writer, target)
            elif method == "GET" and target.split("?")[0] in ("/status", "/health"):
                ex = self.current_exit()
                body = json.dumps({"ok": ex is not None, "exit": ex.display if ex else None,
                                   "stats": dict(self.stats)}).encode()
                writer.write(reply(200, "OK", body, "application/json"))
            else:
                writer.write(reply(405, "Method Not Allowed", b"gatewatch relay: CONNECT only\n"))
            await writer.drain()
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError,
                ConnectionError, OSError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def tunnel(self, reader, writer, target: str) -> None:
        try:
            host, port = split_hostport(target)
        except ValueError:
            writer.write(reply(400, "Bad Request"))
            return
        if self.fallback and matches(host, self.fallback_hosts):
            up, via = self.fallback, "fallback"
        else:
            up, via = self.current_exit(), "exit"
        if up is None:
            self.stats["no_exit"] += 1
            writer.write(reply(503, "No exit configured", b"gatewatch: no exit configured\n"))
            return
        try:
            ur, uw = await asyncio.wait_for(open_via(up, host, port), self.timeout)
        except Exception as e:
            self.stats["upstream_errors"] += 1
            log("relay: %s %s failed via %s: %s" % (via, target, up.display, e or type(e).__name__))
            writer.write(reply(502, "Bad Gateway", b"gatewatch: exit unreachable\n"))
            return
        self.stats["tunnels_" + via] += 1
        writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        await writer.drain()
        try:
            await asyncio.gather(pipe(reader, uw), pipe(ur, writer))
        finally:
            uw.close()

    async def start(self, host: Optional[str] = None, port: Optional[int] = None):
        h, p = self.cfg.hostport("relay", "listen")
        return await asyncio.start_server(self.handle, host or h, p if port is None else port)


def serve(cfg: Config) -> None:
    async def main():
        srv = await Relay(cfg).start()
        log("relay: listening on %s" % ", ".join(str(s.getsockname()[:2]) for s in srv.sockets))
        async with srv:
            await srv.serve_forever()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
