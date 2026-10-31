"""Proxy descriptions and page fetching/judging. Fetching goes through curl on purpose:
it speaks every proxy flavour and does the same TLS as a real client."""
import ipaddress
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")


@dataclass(frozen=True)
class Exit:
    scheme: str            # "http" or "socks5"
    host: str
    port: int
    user: str = ""
    password: str = ""

    @classmethod
    def parse(cls, text: str) -> Optional["Exit"]:
        text = (text or "").strip()
        if "://" not in text:
            return None
        u = urlparse(text)
        scheme = {"http": "http", "socks5": "socks5", "socks5h": "socks5"}.get(u.scheme)
        try:
            port = u.port
        except ValueError:
            return None
        if not scheme or not u.hostname or not port:
            return None
        return cls(scheme, u.hostname, port, unquote(u.username or ""), unquote(u.password or ""))

    @property
    def key(self) -> str:
        return "%s://%s:%d" % (self.scheme, self.host, self.port)

    @property
    def url(self) -> str:
        auth = ""
        if self.user:
            auth = quote(self.user, safe="") + ":" + quote(self.password, safe="") + "@"
        return "%s://%s%s:%d" % (self.scheme, auth, self.host, self.port)

    @property
    def curl_proxy(self) -> str:
        return self.url.replace("socks5://", "socks5h://", 1)

    @property
    def display(self) -> str:
        return self.key + (" (auth)" if self.user else "")


@dataclass
class Result:
    code: int
    size: int
    url: str
    body: str
    seconds: float
    error: str = ""


def fetch(url: str, proxy: str, timeout: int = 30, lang: str = "ru", follow: bool = True,
          max_body: int = 3_000_000) -> Result:
    """GET url through proxy (a curl -x value). Always tunnels (CONNECT), even for http://."""
    fd, path = tempfile.mkstemp(prefix="gatewatch-")
    os.close(fd)
    cmd = ["curl", "-s", "-p", "--max-time", str(timeout), "-A", UA,
           "-H", "Accept-Language: " + lang, "-o", path,
           "-w", "%{http_code} %{size_download} %{url_effective}", "-x", proxy]
    if follow:
        cmd += ["-L", "--max-redirs", "3"]
    cmd.append(url)
    t0 = time.monotonic()
    code, size, eff, body, err = 0, 0, "", "", ""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10)
        parts = (p.stdout.split() + ["0", "0", ""])[:3]
        code, size, eff = int(parts[0]), int(parts[1]), parts[2]
        with open(path, "rb") as f:
            body = f.read(max_body).decode("utf-8", "replace")
        err = p.stderr.strip()
    except FileNotFoundError:
        raise RuntimeError("curl is required but was not found in PATH")
    except Exception as e:  # timeouts and the like
        err = repr(e)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return Result(code, size, eff, body, time.monotonic() - t0, err)


def judge(res: Result, min_size: int, stub_phrases: List[str]) -> Tuple[str, str]:
    """-> ("ok" | "stub" | "dead", explanation).  A stub is checked FIRST: it comes with HTTP 200."""
    haystack = (res.body + " " + res.url).lower()
    for phrase in stub_phrases:
        if phrase.lower() in haystack:
            return "stub", "stub page (%s)" % phrase
    if res.code != 200 or res.size < min_size:
        return "dead", "no real page (HTTP %d, %d bytes)" % (res.code, res.size)
    return "ok", "HTTP %d, %d bytes" % (res.code, res.size)


def as_ip(text: str) -> str:
    """First token of text if it is an IP address, else ''."""
    tok = (text or "").strip().split()
    if not tok:
        return ""
    try:
        return str(ipaddress.ip_address(tok[0]))
    except ValueError:
        return ""
