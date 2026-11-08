"""Dynamic DNS (the user, 2026-11-08: "a namecheap platform plugin that utilizes the API to create a dynamic DNS method"),
as Namecheap's knowledge base gives it: a GET of https://dynamicdns.park-your-domain.com/update with the host (@ the domain
itself, * the wildcard, www, home), the domain (in the dashboard's letter case), the domain's Dynamic DNS password (not the
account's) and the address (`ip`; without it, the address the request comes from). IPv4 alone (A records); Dynamic DNS must
be on for the domain (Advanced DNS > Dynamic DNS), the host an "A + Dynamic DNS Record", the domain on Namecheap's DNS. No
API command turns it on or reads its password: the dashboard does.

Every few minutes (NAMECHEAP_DDNS_MINUTES) this network's public IPv4 address is asked of DNS (myip.opendns.com of
OpenDNS's resolver, else Google's o-o.myaddr.l.google.com, each asked by its IPv4 address so the answer is the IPv4 one) and
each host's A record of the domain's own nameserver (not a resolver's copy, which lags by its TTL); an update is sent only
when they differ. When the address cannot be found, an update without it, at most every half hour; a failed update is
tried again after half an hour. The answer's layout is not documented: it is read for an error count, the errors' words,
the address and Done, and shown shortened (without the password) when it cannot be."""
from __future__ import annotations

import ipaddress
import os
import re
import subprocess
import threading
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from dataclasses import dataclass, replace

from .api import decoded, first, flag, https, scrub, shorten, text_of
from .settings import Config, DdnsHost

UPDATE_URL = "https://dynamicdns.park-your-domain.com/update"
MYIP = ("myip.opendns.com", "A", "208.67.222.222")  # resolver1.opendns.com by its address: this network's IPv4 address
MYIP_TXT = ("o-o.myaddr.l.google.com", "TXT", "216.239.32.10")  # ns1.google.com by its address: the same, as text
FALLBACK_NS = "dns1.registrar-servers.com"  # Namecheap BasicDNS's, when the domain's own cannot be read
RETRY_S = 1800.0  # an update without the address, or a failed one, at most this often
NS_KEEP_S = 86400.0
LOOKUP_S = 15.0
UPDATE_S = 30.0
CREATE_NO_WINDOW = 0x08000000
HINTS = (("password", " (NAMECHEAP_DDNS_PASSWORD is the domain's Dynamic DNS password, not the account's)"),
         ("not found", " (the host must be an A + Dynamic DNS Record: Advanced DNS > Host records)"),
         ("not active", " (Dynamic DNS must be on for the domain: Advanced DNS > Dynamic DNS)"),
         ("invalid domain", " (the domain as the dashboard writes it, in its letter case)"))


# -- DNS, asked with nslookup (windowless) -------------------------------------------------------------------------------
def nslookup(name: str, rtype: str, server: str | None = None) -> str | None:
    """nslookup's answer for `name` of `rtype`, asked of `server` (the machine's resolver when None); None when it could
    not run."""
    argv = ["nslookup", f"-type={rtype}", name] + ([server] if server else [])
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=LOOKUP_S,
                           stdin=subprocess.DEVNULL, **({"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}))
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout or "") + (r.stderr or "")


def answer_addresses(out: str) -> list[str]:
    """The addresses of nslookup's answer: those after its first "Name:" line (the ones before are the server's own)."""
    found, named = [], False
    for line in str(out or "").splitlines():
        s = line.strip()
        if s.lower().startswith("name:"):
            named = True
            continue
        if not named or not s:
            continue
        if ":" in s and s.split(":", 1)[0].lower() in ("address", "addresses"):
            s = s.split(":", 1)[1]
        for token in s.replace(",", " ").split():
            try:
                found.append(str(ipaddress.ip_address(token)))
            except ValueError:
                continue
    return found


def ipv4s(addresses: Iterable[str]) -> list[str]:
    out = []
    for a in addresses:
        try:
            if isinstance(ipaddress.ip_address(a), ipaddress.IPv4Address):
                out.append(a)
        except ValueError:
            continue
    return out


def nameservers_in(out: str) -> list[str]:
    return [n.lower().rstrip(".") for n in re.findall(r"nameserver\s*=\s*([A-Za-z0-9.-]+)", str(out or ""))]


def public_ipv4(run=None) -> str | None:
    """This network's public IPv4 address, asked of DNS (OpenDNS, else Google); None when neither says."""
    run = run or nslookup
    for a in ipv4s(answer_addresses(run(*MYIP) or "")):
        if ipaddress.IPv4Address(a).is_global:
            return a
    for text in re.findall(r'"([^"]*)"', run(*MYIP_TXT) or ""):
        for a in ipv4s([text.strip()]):
            if ipaddress.IPv4Address(a).is_global:
                return a
    return None


# -- the update's answer -------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Answer:
    ok: bool
    ip: str | None
    said: str


def hint(words: str) -> str:
    low = words.lower()
    return next((h for k, h in HINTS if k in low), "")


def parse_update(body: bytes, status: int, secrets: Iterable[str] = ()) -> Answer:
    """Namecheap's answer to an update, read for its error count, its errors, the address and Done (its layout is not
    documented: an XML interface-response, often declared utf-16 while sent as utf-8)."""
    text = decoded(body).lstrip("﻿")
    bare = re.sub(r"^\s*<\?xml[^>]*\?>", "", text)
    count, errors, ip, done = None, [], None, None
    try:
        root = ET.fromstring(bare)
        n = text_of(root, "ErrCount")
        count = int(n) if n.isdigit() else None
        box = first(root, "errors")
        errors = [" ".join((e.text or "").split()) for e in (list(box) if box is not None else []) if (e.text or "").strip()]
        ip = text_of(root, "IP") or None
        done = flag(text_of(root, "Done"))
    except ET.ParseError:
        m = re.search(r"<ErrCount>\s*(\d+)\s*</ErrCount>", text, flags=re.IGNORECASE)
        count = int(m.group(1)) if m else None
        errors = [" ".join(e.split()) for e in re.findall(r"<Err\d+>(.*?)</Err\d+>", text, flags=re.IGNORECASE | re.DOTALL)]
        m = re.search(r"<IP>\s*([0-9.]+)\s*</IP>", text, flags=re.IGNORECASE)
        ip = m.group(1) if m else None
    if count is None and not errors:
        return Answer(False, None, scrub(f"an answer it could not read (HTTP {status}): {shorten(text)}", secrets))
    if not errors and not count and done is not False and status < 400:
        return Answer(True, ip, f"updated to {ip}" if ip else "updated")
    words = "; ".join(errors) or f"{count} errors, no words given"
    return Answer(False, ip, scrub(words + hint(words), secrets))


# -- the hosts kept --------------------------------------------------------------------------------------------------------
@dataclass
class HostState:
    host: str
    domain: str
    fqdn: str
    address: str | None = None  # what its record holds (read of its nameserver), or was set to
    checked_at: float | None = None
    updated_at: float | None = None
    result: str = "not checked yet"
    ok: bool | None = None
    sent: str | None = None  # the address last sent
    tried_at: float | None = None  # the last update sent, whatever came of it
    failed: bool = False

    def describe(self) -> dict:
        return {"host": self.fqdn, "address": self.address, "checkedAt": self.checked_at, "updatedAt": self.updated_at,
                "result": self.result, "ok": self.ok}


class Updater:
    """The Dynamic DNS hosts' state and their passes (one at a time); `transport` and `run` a test's stand-ins for the
    update's HTTPS and nslookup."""

    def __init__(self, transport=None, run=None, clock=time.time):
        self.transport = transport or https
        self.run = run or nslookup
        self.clock = clock
        self.public: str | None = None
        self.public_at: float | None = None
        self._hosts: dict[str, HostState] = {}
        self._ns: dict[str, tuple[float, str]] = {}
        self._lock = threading.Lock()  # the state, held only to read or write it
        self._passing = threading.Lock()  # a pass under way

    def states(self) -> list[HostState]:
        with self._lock:
            return [replace(s) for s in self._hosts.values()]

    def address(self, fresh_s: float = 600.0) -> str | None:
        """This network's public IPv4 address: the last pass's when fresh, else asked now."""
        with self._lock:
            ip, at = self.public, self.public_at
        now = self.clock()
        if ip and at is not None and now - at < fresh_s:
            return ip
        ip = public_ipv4(self.run)
        with self._lock:
            self.public, self.public_at = ip, now
        return ip

    def nameserver(self, domain: str) -> str:
        """The domain's first nameserver (read of DNS, kept a day), else Namecheap BasicDNS's."""
        d = domain.lower()
        now = self.clock()
        with self._lock:
            kept = self._ns.get(d)
        if kept and now - kept[0] < NS_KEEP_S:
            return kept[1]
        found = nameservers_in(self.run(d, "NS", None) or "")
        ns = found[0] if found else FALLBACK_NS
        with self._lock:
            self._ns[d] = (now, ns)
        return ns

    def record(self, h: DdnsHost) -> list[str] | None:
        """The IPv4 addresses `h`'s A record holds at its domain's nameserver ([] none), None when it could not be asked."""
        out = self.run(h.fqdn, "A", self.nameserver(h.domain))
        return None if out is None else ipv4s(answer_addresses(out))

    def send(self, h: DdnsHost, password: str, ip: str | None) -> Answer:
        query = {"host": h.host, "domain": h.domain, "password": password}
        if ip:
            query["ip"] = ip
        try:
            status, body = self.transport("GET", UPDATE_URL, query, None, UPDATE_S)
        except Exception as e:  # noqa: BLE001 - its words, without the password
            return Answer(False, None, scrub(f"Dynamic DNS could not be reached: {type(e).__name__}: {e}", (password,)))
        return parse_update(body, status, (password,))

    def run_pass(self, config: Config, known: Iterable[str] = (), force: bool = False, wait: float = 120.0) -> list[dict]:
        """A pass over the hosts set: each one's record read, an update sent where it differs from this network's address
        (`force`: sent for every host). What each host's state is after it."""
        if not self._passing.acquire(timeout=wait):
            raise RuntimeError("a Dynamic DNS pass is under way")
        try:
            self._pass(config, known, force)
        finally:
            self._passing.release()
        return [s.describe() for s in self.states()]

    def _pass(self, config: Config, known: Iterable[str], force: bool) -> None:
        hosts, _ = config.ddns_hosts(known)  # the entries that are no host: said by the status
        public = public_ipv4(self.run)
        now = self.clock()
        with self._lock:
            self.public, self.public_at = public, now
            wanted = {h.fqdn.lower() for h in hosts}
            for gone in [k for k in self._hosts if k not in wanted]:
                del self._hosts[gone]
            for h in hosts:
                self._hosts.setdefault(h.fqdn.lower(), HostState(h.host, h.domain, h.fqdn))
        for h in hosts:
            with self._lock:
                st = replace(self._hosts[h.fqdn.lower()])
            self._one(st, h, config, public, force)
            with self._lock:
                if h.fqdn.lower() in self._hosts:
                    self._hosts[h.fqdn.lower()] = st

    def _one(self, st: HostState, h: DdnsHost, config: Config, public: str | None, force: bool) -> None:
        now = self.clock()
        password = config.password_for(h.domain)
        st.checked_at = now
        if not password:
            st.ok, st.result = False, f"no Dynamic DNS password for {h.domain} (NAMECHEAP_DDNS_PASSWORD)"
            return
        current = self.record(h)
        if current:
            st.address = ", ".join(current)
        recent = st.tried_at is not None and now - st.tried_at < RETRY_S
        if not force:
            if public and current is not None and public in current:
                st.ok, st.result, st.address, st.failed = True, "unchanged", public, False
                return
            if public and recent and st.sent == public and (current is None or st.failed):
                st.result = (f"{public} sent at {clock_words(st.tried_at)}; its record could not be read since"
                             if not st.failed else f"{st.result.split(' · ')[0]} · tried again after {clock_words(st.tried_at + RETRY_S)}")
                return
            if not public and recent:
                st.result = (f"this network's address could not be found: an update without it was sent at "
                             f"{clock_words(st.tried_at)}, the next after half an hour")
                return
        answer = self.send(h, password, public)
        st.sent, st.tried_at, st.failed, st.ok = public, now, not answer.ok, answer.ok
        if answer.ok:
            st.updated_at = now
            st.address = answer.ip or public or st.address
            st.result = answer.said if public else f"{answer.said} (the address the request came from)"
        else:
            st.result = f"failed: {answer.said}"


def clock_words(t: float | None) -> str:
    return "–" if t is None else time.strftime("%H:%M", time.localtime(t))
