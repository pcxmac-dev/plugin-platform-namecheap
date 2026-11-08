"""Namecheap's XML API, as its documentation (https://www.namecheap.com/support/api/intro/, read 2026-11-08) gives it: a
service URL per environment (production; the sandbox), every request carrying ApiUser, ApiKey, UserName, Command and
ClientIp (an IPv4 address whitelisted under Profile > Tools > Namecheap API Access), the answer an
<ApiResponse Status="OK|ERROR"> with its <Errors><Error Number="...">. The documentation's examples differ in their namespace
(http and https) and the live API writes <host> in lowercase, so an answer is read by its elements' local names in any
case. Reads go by GET; setHosts by POST (recommended above ten hosts), its hosts in the form and the global parameters in
the query, as the clients in use send it. Namecheap's limits, as reported (20 or 50 a minute, 700 an hour, 8,000 a day
per key), are kept at the lower. Only what the plugin uses is here, and nothing that spends: no domain is registered,
renewed, reactivated or transferred from it, and no nameserver changed."""
from __future__ import annotations

import http.client
import re
import ssl
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from collections import deque
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

PRODUCTION = "https://api.namecheap.com/xml.response"
SANDBOX = "https://api.sandbox.namecheap.com/xml.response"
TIMEOUT_S = 30.0
MAX_BODY = 4 * 2**20  # an answer larger than this is not one of the API's
USER_AGENT = "plugin-platform-namecheap (Liminal)"
IPV4_ANY = ("0.0.0.0", 0)  # a connection's own address: IPv4, so the whitelist (IPv4 alone) and Dynamic DNS see this network's
PAGE_SIZE = 100  # domains.getList's most a page
MAX_PAGES = 20
CHECK_MAX = 50  # domains.check's most at once
TTL_MIN, TTL_MAX, TTL_DEFAULT = 60, 60000, 1800
WINDOWS = ((60.0, 20), (3600.0, 700), (86400.0, 8000))  # (seconds, requests): Namecheap's limits as reported, the lower kept
MAX_WAIT_S = 30.0  # the longest a request waits for room in them

# the global errors (and the methods' own the plugin meets) in words of what to do; Namecheap's own words follow them
WORDS = {
    "1011150": "this network's address is not whitelisted for the API: Profile > Tools > Namecheap API Access > Whitelisted IPs (IPv4 only)",
    "1017150": "the requesting address is disabled or locked at Namecheap",
    "1017105": "the client IP is disabled or locked at Namecheap",
    "1017101": "the API user is disabled or locked at Namecheap",
    "1016103": "the user name is not authorized: NAMECHEAP_USERNAME names an account the API user may act on",
    "1019103": "the user name is not available",
    "1017103": "the user name is disabled or locked",
    "1010101": "the API user is missing (NAMECHEAP_API_USER)",
    "1010102": "the API key is missing or refused: NAMECHEAP_API_KEY, with API access on (Profile > Tools > Namecheap API Access)",
    "1011102": "the API key is missing or refused: NAMECHEAP_API_KEY, with API access on (Profile > Tools > Namecheap API Access)",
    "1010105": "the client IP is missing",
    "1011105": "the client IP is missing",
    "1050900": "Namecheap could not check the API user",
    "1017410": "too many declined payments on the account",
    "1017411": "too many login attempts: Namecheap has locked the API user for a while",
    "2019166": "the domain is not found",
    "2016166": "the domain is not in this account",
    "2030166": "the domain cannot be edited from this account",
    "2030288": "the domain is not on Namecheap's DNS",
    "3013288": "too many records",
    "4013288": "too many records",
    "4022288": "Namecheap could not read the domain's nameservers",
    "2011169": "at most 50 domains are checked at once",
    "4022312": "the balance is not available",
}
REFUSALS = frozenset({"1011150", "1017150", "1017105", "1017101", "1016103", "1019103", "1017103", "1010101", "1010102",
                      "1011102", "1010105", "1011105", "1017411"})  # the account's refusals: no passing trouble
DOMAIN = re.compile(r"^(?=.{3,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")
SECRET_PARAMS = re.compile(r"(?i)\b(apikey|password)=[^&\s\"'<>]+")


class NamecheapError(Exception):
    """Namecheap refused or could not answer, in words that hold no key: `number` its error's number (or "network",
    "answer", "limit", "ip"), `command` the command asked."""

    def __init__(self, message: str, number: str = "", command: str = ""):
        super().__init__(message)
        self.number = str(number or "")
        self.command = command

    @property
    def refused(self) -> bool:
        """The account refused (the key, the address, the user): not a passing trouble."""
        return self.number in REFUSALS


def scrub(text: str, secrets: Iterable[str] = ()) -> str:
    """`text` without the secrets in it, nor an ApiKey= or password= value."""
    out = str(text)
    for s in sorted({str(s) for s in secrets if s and len(str(s)) >= 4}, key=len, reverse=True):
        out = out.replace(s, "***")
    return SECRET_PARAMS.sub(lambda m: f"{m.group(1)}=***", out)


def shorten(text: str, most: int = 200) -> str:
    t = " ".join(str(text).split())
    return t if len(t) <= most else t[: most - 1] + "…"


def decoded(body: bytes) -> str:
    return body.decode("utf-8", errors="replace") if isinstance(body, (bytes, bytearray)) else str(body)


# -- the answers, read by their local names in any case ---------------------------------------------------------------
def local(tag) -> str:
    return str(tag).rsplit("}", 1)[-1].lower()


def attr(el, name: str, default: str = "") -> str:
    """An attribute of `el` by its name in any case."""
    if el is None:
        return default
    want = name.lower()
    for k, v in el.attrib.items():
        if local(k) == want:
            return v
    return default


def descendants(el, name: str) -> list:
    """`el` and the elements under it whose local name is `name`, in any case."""
    want = name.lower()
    return [] if el is None else [e for e in el.iter() if local(e.tag) == want]


def first(el, name: str):
    found = descendants(el, name)
    return found[0] if found else None


def text_of(el, name: str) -> str:
    e = first(el, name)
    return " ".join((e.text or "").split()) if e is not None else ""


def flag(value) -> bool | None:
    v = str(value or "").strip().lower()
    return True if v == "true" else False if v == "false" else None


def number(value, default: int) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def answer_of(body: bytes, status: int, command: str, secrets: Iterable[str] = ()):
    """The <ApiResponse> of an answer (an Element), or NamecheapError with Namecheap's words and the plugin's."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        raise NamecheapError(scrub(f"Namecheap answered {command} with HTTP {status} and no XML: {shorten(decoded(body))}",
                                   secrets), "answer", command) from None
    if local(root.tag) != "apiresponse":
        raise NamecheapError(f"Namecheap answered {command} with <{local(root.tag)}>, no ApiResponse", "answer", command)
    if attr(root, "Status").upper() != "OK":
        errors = [(attr(e, "Number"), " ".join((e.text or "").split())) for e in descendants(root, "Error")]
        if errors:
            raise error_of(errors, command, secrets)
        raise NamecheapError(f"Namecheap answered {command} with status {attr(root, 'Status') or 'none'} and no error",
                             "answer", command)
    return root


def error_of(errors: Sequence[tuple[str, str]], command: str, secrets: Iterable[str] = ()) -> NamecheapError:
    num, said = errors[0]
    words = WORDS.get(num)
    text = f"{words} (Namecheap {num}: {said})" if words else f"Namecheap {num or 'error'}: {said or 'no words given'}"
    if len(errors) > 1:
        text += "; and " + "; ".join(f"{n}: {s}" for n, s in errors[1:4])
    return NamecheapError(scrub(text, secrets), num, command)


# -- a domain's records -----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Record:
    """A host record as getHosts gives it (and setHosts takes it back: name, type, address, MX preference, TTL)."""

    name: str
    type: str
    address: str
    ttl: int = TTL_DEFAULT
    mxpref: int = 10
    host_id: str = ""
    active: bool | None = None  # IsActive, when the answer says
    ddns: bool | None = None  # IsDDNSEnabled: an "A + Dynamic DNS Record"
    friendly: str = ""
    app: str = ""  # AssociatedAppTitle

    def as_dict(self) -> dict:
        return {"name": self.name, "type": self.type, "address": self.address, "ttl": self.ttl, "mxpref": self.mxpref,
                "hostId": self.host_id, "active": self.active, "ddns": self.ddns, "friendlyName": self.friendly, "app": self.app}

    @classmethod
    def from_dict(cls, d: Mapping) -> "Record":
        return cls(name=str(d["name"]), type=str(d["type"]).upper(), address=str(d["address"]), ttl=number(d.get("ttl"), TTL_DEFAULT),
                   mxpref=number(d.get("mxpref"), 10), host_id=str(d.get("hostId") or ""), active=d.get("active"),
                   ddns=d.get("ddns"), friendly=str(d.get("friendlyName") or ""), app=str(d.get("app") or ""))


@dataclass(frozen=True)
class Zone:
    """A domain's records as read: `email_type` its mail setting (None when the answer did not say), `using_our_dns`
    whether it is on Namecheap's DNS."""

    domain: str
    email_type: str | None
    using_our_dns: bool | None
    records: tuple[Record, ...]
    read_at: float = 0.0

    def as_dict(self) -> dict:
        return {"domain": self.domain, "emailType": self.email_type, "usingOurDns": self.using_our_dns, "readAt": self.read_at,
                "records": [r.as_dict() for r in self.records]}


def record_of(h) -> Record:
    return Record(name=attr(h, "Name") or "@", type=attr(h, "Type").upper(), address=attr(h, "Address"),
                  ttl=number(attr(h, "TTL"), TTL_DEFAULT), mxpref=number(attr(h, "MXPref"), 10), host_id=attr(h, "HostId"),
                  active=flag(attr(h, "IsActive")), ddns=flag(attr(h, "IsDDNSEnabled")), friendly=attr(h, "FriendlyName"),
                  app=attr(h, "AssociatedAppTitle"))


def valid_domain(name: str) -> str:
    """A registered domain's name, lowercase without a trailing dot; ValueError when it is none."""
    d = str(name or "").strip().lower().rstrip(".")
    if not DOMAIN.match(d):
        raise ValueError(f"{str(name).strip()!r} is not a domain name")
    return d


def split_domain(name: str) -> tuple[str, str]:
    """A domain as Namecheap asks for it: its SLD (the label registered) and its TLD (com, me, co.uk)."""
    sld, _, tld = valid_domain(name).partition(".")
    return sld, tld


# -- the connection: HTTPS over IPv4 --------------------------------------------------------------------------------------
def https(method: str, url: str, query: Mapping[str, str] | None, form: Mapping[str, str] | None,
          timeout: float = TIMEOUT_S) -> tuple[int, bytes]:
    """One request over HTTPS from this machine's IPv4 address (Namecheap whitelists IPv4 alone, and Dynamic DNS keeps A
    records): GET with `query`, POST with `form` as well; the answer's status and its body."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"not an https address: {parts.scheme}://{parts.hostname}")
    target = (parts.path or "/") + ("?" + urllib.parse.urlencode(query) if query else "")
    body = urllib.parse.urlencode(form).encode("ascii") if form is not None else None
    headers = {"User-Agent": USER_AGENT, "Accept": "text/xml, application/xml, */*"}
    if body is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    conn = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=timeout, context=ssl.create_default_context(),
                                       source_address=IPV4_ANY)
    try:
        conn.request(method, target, body=body, headers=headers)
        r = conn.getresponse()
        data = r.read(MAX_BODY + 1)
        status = r.status
    finally:
        conn.close()
    if len(data) > MAX_BODY:
        raise OSError(f"an answer over {MAX_BODY // 2**20} MB")
    return status, data


class Limiter:
    """The requests of the last minute, hour and day kept under Namecheap's limits (`windows`): a request waits for room,
    at most `max_wait` seconds, else NamecheapError("limit"). One for the process: every copy of the plugin, the command
    line's included, counts against the same key."""

    def __init__(self, windows=WINDOWS, clock=time.monotonic, sleep=time.sleep, max_wait: float = MAX_WAIT_S):
        self.windows = tuple(windows)
        self.clock, self.sleep, self.max_wait = clock, sleep, max_wait
        self._times: deque = deque()
        self._lock = threading.Lock()

    def wait_for(self, now: float) -> float:
        """The seconds until a request may go (the requests past the longest window forgotten)."""
        longest = max(span for span, _ in self.windows)
        while self._times and now - self._times[0] >= longest:
            self._times.popleft()
        wait = 0.0
        for span, most in self.windows:
            recent = [t for t in self._times if now - t < span]
            if len(recent) >= most:
                wait = max(wait, recent[-most] + span - now)
        return wait

    def acquire(self) -> None:
        """Room for one request, waited for (outside the lock: the status reads `used` meanwhile)."""
        while True:
            with self._lock:
                now = self.clock()
                wait = self.wait_for(now)
                if wait <= 0:
                    self._times.append(now)
                    return
            if wait > self.max_wait:
                raise NamecheapError(f"Namecheap's limits ({self.describe()}): the next request may go in {wait:.0f} s", "limit")
            self.sleep(wait)

    def used(self) -> list[tuple[float, int, int]]:
        """(window, requests in it, its most) for each window."""
        with self._lock:
            now = self.clock()
            return [(span, sum(1 for t in self._times if now - t < span), most) for span, most in self.windows]

    def describe(self) -> str:
        names = {60.0: "a minute", 3600.0: "an hour", 86400.0: "a day"}
        return ", ".join(f"{most:,} {names.get(span, f'{span:g} s')}" for span, most in self.windows)


LIMITER = Limiter()


class NamecheapApi:
    """The account's API: its domains, a domain's records read and written whole, a name's availability, the balance."""

    def __init__(self, api_user: str, api_key: str, username: str = "", client_ip: str = "", sandbox: bool = False,
                 transport=None, limiter: Limiter | None = None, ip_of=None, secrets: Iterable[str] = (), clock=time.time):
        if not api_user or not api_key:
            raise ValueError("the API needs NAMECHEAP_API_USER and NAMECHEAP_API_KEY")
        self.api_user, self.api_key, self.username = api_user, api_key, username or api_user
        self.client_ip, self.sandbox = client_ip, sandbox
        self.transport = transport or https
        self.limiter = limiter or LIMITER
        self.ip_of = ip_of  # () -> this network's public IPv4 address, or None
        self.secrets = tuple(s for s in (api_key, *secrets) if s)
        self.clock = clock

    def __repr__(self) -> str:
        return f"<NamecheapApi {self.api_user!r} {'sandbox' if self.sandbox else 'production'}>"

    @property
    def url(self) -> str:
        return SANDBOX if self.sandbox else PRODUCTION

    def client_address(self) -> str:
        """The ClientIp sent: NAMECHEAP_CLIENT_IP, else this network's public IPv4 address."""
        if self.client_ip:
            return self.client_ip
        found = self.ip_of() if self.ip_of is not None else None
        if not found:
            raise NamecheapError("this network's public IPv4 address could not be found for the API's ClientIp: set "
                                 "NAMECHEAP_CLIENT_IP to the address whitelisted for the API", "ip")
        return found

    def request(self, command: str, params: Mapping | None = None, post: bool = False):
        """A command asked: (its <ApiResponse>, the answer's bytes)."""
        query = {"ApiUser": self.api_user, "ApiKey": self.api_key, "UserName": self.username, "Command": command,
                 "ClientIp": self.client_address()}
        more = {k: str(v) for k, v in (params or {}).items()}
        self.limiter.acquire()
        try:
            status, body = self.transport("POST" if post else "GET", self.url, query if post else {**query, **more},
                                          more if post else None, TIMEOUT_S)
        except NamecheapError:
            raise
        except Exception as e:  # noqa: BLE001 - a network's trouble, in words without the key
            raise NamecheapError(scrub(f"Namecheap's API could not be reached: {type(e).__name__}: {e}", self.secrets),
                                 "network", command) from None
        return answer_of(body, status, command, self.secrets), body

    def domains(self) -> list[dict]:
        """Every domain of the account (getList, a hundred a page), by name."""
        out: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            root, _ = self.request("namecheap.domains.getList", {"ListType": "ALL", "Page": page, "PageSize": PAGE_SIZE,
                                                                  "SortBy": "NAME"})
            found = [domain_of(d) for d in descendants(root, "Domain")]
            out += found
            total = number(text_of(first(root, "Paging"), "TotalItems"), len(out))
            if not found or len(out) >= total:
                break
        return out

    def hosts(self, domain: str) -> Zone:
        """A domain's records (getHosts) and its mail setting. A <host> the reading missed (an answer laid out otherwise)
        is NamecheapError: a zone misread as empty must never be written over."""
        sld, tld = split_domain(domain)
        root, body = self.request("namecheap.domains.dns.getHosts", {"SLD": sld, "TLD": tld})
        result = first(root, "DomainDNSGetHostsResult")
        if result is None:
            raise NamecheapError("getHosts answered no DomainDNSGetHostsResult", "answer", "namecheap.domains.dns.getHosts")
        records = tuple(record_of(h) for h in descendants(result, "host"))
        seen = len(re.findall(rb"<(?:[\w.-]+:)?host\b", body, flags=re.IGNORECASE))
        if seen != len(records):
            raise NamecheapError(f"getHosts answered {seen} host elements and {len(records)} were read: the answer is not "
                                 "laid out as expected, so nothing is taken from it", "answer", "namecheap.domains.dns.getHosts")
        email = attr(result, "EmailType").strip().upper() or None
        return Zone(domain=attr(result, "Domain") or f"{sld}.{tld}", email_type=email,
                    using_our_dns=flag(attr(result, "IsUsingOurDNS")), records=records, read_at=self.clock())

    def set_hosts(self, domain: str, records: Sequence[Record], email_type: str) -> bool:
        """The domain's records written whole (setHosts, by POST): every record not given is deleted by Namecheap, so the
        caller gives them all (zone.write). Whether Namecheap said it succeeded."""
        if not records:
            raise ValueError("setHosts with no records would empty the zone")
        if not email_type:
            raise ValueError("setHosts without the mail setting (EmailType) could reset the domain's mail")
        sld, tld = split_domain(domain)
        form: dict[str, str] = {"SLD": sld, "TLD": tld, "EmailType": email_type}
        for i, r in enumerate(records, 1):
            form.update({f"HostName{i}": r.name, f"RecordType{i}": r.type, f"Address{i}": r.address,
                         f"MXPref{i}": str(r.mxpref), f"TTL{i}": str(r.ttl)})
        root, _ = self.request("namecheap.domains.dns.setHosts", form, post=True)
        return bool(flag(attr(first(root, "DomainDNSSetHostsResult"), "IsSuccess")))

    def availability(self, names: Iterable[str]) -> list[dict]:
        """Whether names are free to register (domains.check, at most 50 at once): read only, nothing is bought."""
        wanted = [valid_domain(n) for n in names]
        if not wanted:
            raise ValueError("name a domain to check")
        if len(wanted) > CHECK_MAX:
            raise ValueError(f"at most {CHECK_MAX} domains are checked at once")
        root, _ = self.request("namecheap.domains.check", {"DomainList": ",".join(wanted)})
        return [{"domain": attr(r, "Domain"), "available": flag(attr(r, "Available")), "premium": flag(attr(r, "IsPremiumName")),
                 "premiumPrice": attr(r, "PremiumRegistrationPrice"), "note": attr(r, "Description")}
                for r in descendants(root, "DomainCheckResult")]

    def balances(self) -> dict:
        """The account's funds (users.getBalances)."""
        root, _ = self.request("namecheap.users.getBalances")
        r = first(root, "UserGetBalancesResult")
        if r is None:
            raise NamecheapError("getBalances answered no UserGetBalancesResult", "answer", "namecheap.users.getBalances")
        return {"currency": attr(r, "Currency"), "available": attr(r, "AvailableBalance"), "account": attr(r, "AccountBalance"),
                "autoRenew": attr(r, "FundsRequiredForAutoRenew"), "earned": attr(r, "EarnedAmount"),
                "withdrawable": attr(r, "WithdrawableAmount")}


def domain_of(d) -> dict:
    """A domain of getList's answer."""
    return {"id": attr(d, "ID"), "name": attr(d, "Name"), "user": attr(d, "User"), "created": attr(d, "Created"),
            "expires": attr(d, "Expires"), "expired": flag(attr(d, "IsExpired")), "locked": flag(attr(d, "IsLocked")),
            "autoRenew": flag(attr(d, "AutoRenew")), "privacy": attr(d, "WhoisGuard"), "premium": flag(attr(d, "IsPremium")),
            "ourDns": flag(attr(d, "IsOurDNS"))}
