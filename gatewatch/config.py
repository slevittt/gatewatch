"""Configuration: one INI file, every key has a default."""
import configparser
import os
from typing import List, Optional

DEFAULT_PAC_HOSTS = "example.com"

DEFAULT_INI = """\
# gatewatch configuration. Full-line comments only (no trailing comments).

[paths]
state_dir = /var/lib/gatewatch
# optional extra log file; empty = stderr/journald only
log_file =

[relay]
# address the LAN relay listens on (this is the host:port that goes into the PAC file)
listen = 0.0.0.0:10813
# only these client networks may use the relay or read /status
allow = 127.0.0.1/32, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16
connect_timeout = 15
# optional second exit used ONLY for the hosts listed in fallback_hosts
# example: fallback = http://user:pass@proxy.example.net:3128
fallback =
fallback_hosts =

[targets]
# name = URL checked through the relay. A target is "ok" only if the page is large enough
# and contains none of the stub phrases.
example = https://example.com/

[check]
# the relay as seen from the machine running gatewatch
relay = 127.0.0.1:10813
timeout = 30
# a page smaller than this is treated as "not the real page"; raise it for big sites
min_size = 1000
# phrases that mean "this is a stub / error page" even if the status is 200 and the size looks fine.
# Add the exact wording your service uses, in any language.
stub_phrases = not available in your country, not available in your region, location=unsupported
# used to prove that the relay really leaves through the recorded exit; empty = skip
ip_url = https://ifconfig.me/ip
accept_language = en

[pool]
# a node is usable only if this page opens through it
test_url = https://example.com/
test_timeout = 20
workers = 8

[harvest]
# public lists of free proxies (third-party, untrusted - see docs/SECURITY.md)
http_sources = https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt,
    https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt,
    https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/http/data.txt
socks5_sources = https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt,
    https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/socks5.txt,
    https://raw.githubusercontent.com/proxifly/free-proxy-list/main/proxies/protocols/socks5/data.txt
max_http = 400
max_socks5 = 200
workers = 60

[guard]
# run when the state changes to failed or back to ok. Environment: GATEWATCH_SUBJECT, GATEWATCH_BODY
# example: notify_cmd = sh -c 'echo "$GATEWATCH_BODY" | mail -s "$GATEWATCH_SUBJECT" you@example.com'
notify_cmd =
# harvest new public proxies if fewer than this many usable nodes remain
harvest_below = 1

[pac]
# the address of the relay as the BROWSER sees it
relay = 192.168.1.10:10813
# domain suffixes sent through the relay; everything else stays DIRECT
hosts = {pac_hosts}
"""


class Config:
    def __init__(self, path: Optional[str] = None):
        self.cp = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=None)
        self.cp.read_string(DEFAULT_INI.replace("{pac_hosts}", DEFAULT_PAC_HOSTS))
        self.path = path
        if path:
            if not os.path.exists(path):
                raise FileNotFoundError("config not found: %s" % path)
            user = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=None)
            user.read(path, encoding="utf-8")
            # [targets] is a list, not a set of overrides: if the user defines it, the defaults go away
            if user.has_section("targets"):
                self.cp.remove_section("targets")
            self.cp.read(path, encoding="utf-8")

    @staticmethod
    def find(explicit: Optional[str] = None) -> Optional[str]:
        for cand in (explicit, os.environ.get("GATEWATCH_CONFIG"), "./gatewatch.ini", "/etc/gatewatch/gatewatch.ini"):
            if cand and os.path.exists(cand):
                return cand
        return explicit

    def get(self, section: str, key: str) -> str:
        return self.cp.get(section, key, fallback="").strip()

    def int(self, section: str, key: str) -> int:
        return int(self.get(section, key) or 0)

    def lst(self, section: str, key: str) -> List[str]:
        raw = self.get(section, key).replace("\n", ",")
        return [x.strip() for x in raw.split(",") if x.strip()]

    def items(self, section: str):
        return [(k, v.strip()) for k, v in self.cp.items(section)]

    # derived paths -----------------------------------------------------
    @property
    def state_dir(self) -> str:
        return self.get("paths", "state_dir")

    def state_path(self, name: str) -> str:
        return os.path.join(self.state_dir, name)

    @property
    def exit_file(self) -> str:
        return self.state_path("exit.json")

    @property
    def pool_file(self) -> str:
        return self.state_path("pool.txt")

    def hostport(self, section: str, key: str):
        host, _, port = self.get(section, key).rpartition(":")
        return host or "127.0.0.1", int(port)
