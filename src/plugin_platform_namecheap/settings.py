"""The plugin's settings, read through the library's Login interface and nothing else (the user, 2026-11-08: "again, all
the settings are stored on a login-app db"; "but we are not integrating login-app right now"). Each setting is a pair named
by its variable (NAMECHEAP_API_KEY is the pair `namecheap-api-key`: apps.authorization.pair_name), asked of the login of the
app the plugin is attached to: the platform's EnvironmentLogin today (the platform's environment, the user's variables as
they were when it started), the login app's pairs once the platform binds it. Not attached (the command line), an
EnvironmentLogin of its own. The plugin keeps no settings file: a value is never written anywhere, never shown, and only
the names of the settings set are said."""
from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from liminal_libs.apps import EnvironmentLogin, Login
from liminal_libs.sources.keys import KeyVar

API_USER = "NAMECHEAP_API_USER"
API_KEY = "NAMECHEAP_API_KEY"
USERNAME = "NAMECHEAP_USERNAME"
CLIENT_IP = "NAMECHEAP_CLIENT_IP"
SANDBOX = "NAMECHEAP_SANDBOX"
DDNS_PASSWORD = "NAMECHEAP_DDNS_PASSWORD"
DDNS_HOSTS = "NAMECHEAP_DDNS_HOSTS"
DDNS_MINUTES = "NAMECHEAP_DDNS_MINUTES"

# what the login app's "Pairs your plugins ask for" lists, once it lists the platform's plugins
KEYS = (
    KeyVar(API_USER, label="API user", secret=False,
           hint="your Namecheap username: the API user once API access is on (Profile > Tools > Namecheap API Access)"),
    KeyVar(API_KEY, label="API key", hint="Profile > Tools > Business & Dev Tools > Namecheap API Access, once it is on"),
    KeyVar(USERNAME, label="Account acted on", secret=False,
           hint="optional: the Namecheap account the commands act on (the API user's own unless set)"),
    KeyVar(CLIENT_IP, label="Whitelisted address", secret=False,
           hint="optional: the IPv4 address whitelisted for the API (this network's public address unless set)"),
    KeyVar(SANDBOX, label="Sandbox", secret=False, hint="optional: 1 for Namecheap's sandbox (api.sandbox.namecheap.com)"),
    KeyVar(DDNS_PASSWORD, label="Dynamic DNS password",
           hint="Domain List > Manage > Advanced DNS > Dynamic DNS; for several domains: example.com=PASSWORD;example.net=PASSWORD"),
    KeyVar(DDNS_HOSTS, label="Dynamic DNS hosts", secret=False,
           hint="the hosts kept at this network's address, comma separated: home.example.com, @.example.com (the domain itself), *.example.com"),
    KeyVar(DDNS_MINUTES, label="Dynamic DNS minutes", secret=False, hint="optional: minutes between checks, 1 to 1440 (5 unless set)"),
)
NAMES = tuple(k.name for k in KEYS)

TRUE = frozenset({"1", "true", "yes", "on"})
FALSE = frozenset({"0", "false", "no", "off"})
MINUTES = (1.0, 1440.0, 5.0)  # the least, the most, unless set
HOST_LABEL = re.compile(r"^[A-Za-z0-9_](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9_])?$")
DOMAIN_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
# the suffixes of two labels a domain is registered under (a host's domain is three labels there): what a host's domain is
# taken to be when the account's own domains are not known yet
TWO_LEVEL = frozenset({
    "co.uk", "org.uk", "me.uk", "ltd.uk", "plc.uk", "net.uk", "com.au", "net.au", "org.au", "id.au", "co.nz", "net.nz",
    "org.nz", "co.jp", "co.za", "com.br", "com.mx", "com.cn", "com.tw", "com.hk", "com.sg", "co.in", "net.in", "org.in",
    "co.il", "co.kr", "com.tr", "com.ar", "com.co", "com.pe", "com.ph", "com.my", "com.ng", "co.ke", "com.ua", "com.pl",
    "com.es", "co.id", "com.vn", "com.pk", "com.ec", "com.gt", "com.sv", "com.do", "com.bo", "com.py", "com.uy"})


@dataclass(frozen=True)
class DdnsHost:
    """A host kept at this network's address: `host` as Namecheap names it (@ the domain itself, * every name not
    otherwise set, home, a.b), `domain` as it was typed (Namecheap asks for the dashboard's own letter case)."""

    host: str
    domain: str

    @property
    def fqdn(self) -> str:
        return self.domain if self.host == "@" else f"{self.host}.{self.domain}"


def split_host(text: str, known: Iterable[str] = ()) -> DdnsHost:
    """A host as typed (home.example.com, @.example.com, *.example.com, example.com) as its host and its domain: the
    longest of the account's domains (`known`) it ends with, else its last two labels (three under a suffix of two:
    example.co.uk). ValueError when it is no host name."""
    name = str(text or "").strip().rstrip(".")
    labels = name.split(".") if name else []
    at = bool(labels) and labels[0] == "@"
    rest = labels[1:] if at else labels
    if len(rest) < 2 or not all(DOMAIN_LABEL.match(x) or HOST_LABEL.match(x) or (i == 0 and x == "*")
                                for i, x in enumerate(rest)):
        raise ValueError(f"{text.strip()!r} is not a host: home.example.com, @.example.com or *.example.com")
    lower = [x.lower() for x in rest]
    size = None
    for d in sorted((str(k).lower().strip(".") for k in known if k), key=lambda d: -len(d)):
        parts = d.split(".")
        if len(parts) <= len(lower) and lower[-len(parts):] == parts:
            size = len(parts)
            break
    if size is None:
        size = 3 if len(lower) >= 3 and ".".join(lower[-2:]) in TWO_LEVEL else 2
    domain, host = rest[-size:], rest[:-size]
    if at and host:
        raise ValueError(f"{text.strip()!r}: @ stands for the domain itself (@.example.com)")
    if not all(DOMAIN_LABEL.match(x) for x in domain):
        raise ValueError(f"{text.strip()!r} is not a host: its domain {'.'.join(domain)!r} is no domain name")
    return DdnsHost(".".join(host) or "@", ".".join(domain))


def parse_passwords(value: str) -> tuple[tuple[str, str], ...]:
    """The Dynamic DNS passwords as typed: one password for every domain (("", password),), or example.com=PASSWORD pairs
    separated by ; or , (each domain's own: Namecheap gives each domain a password of its own). ValueError otherwise."""
    parts = [p.strip() for p in re.split(r"[;,]", str(value or "")) if p.strip()]
    if not parts:
        return ()
    if len(parts) == 1 and "=" not in parts[0]:
        return (("", parts[0]),)
    out = []
    for p in parts:
        domain, eq, password = p.partition("=")
        domain, password = domain.strip().lower().rstrip("."), password.strip()
        if not eq or not domain or not password or "." not in domain:
            raise ValueError(f"{DDNS_PASSWORD} is one password, or example.com=PASSWORD pairs separated by ;")
        out.append((domain, password))
    return tuple(out)


@dataclass(frozen=True)
class Config:
    """The settings as read (`present`: the names of those set; `problems`: what was set but could not be taken, in words
    that never hold a secret)."""

    api_user: str = ""
    api_key: str = field(default="", repr=False)
    username: str = ""
    client_ip: str = ""
    sandbox: bool = False
    passwords: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    hosts: tuple[str, ...] = ()  # the hosts as typed (split against the account's domains when they are known)
    minutes: float = MINUTES[2]
    present: frozenset = frozenset()
    problems: tuple[str, ...] = ()

    @property
    def api_ready(self) -> bool:
        return bool(self.api_user and self.api_key)

    @property
    def ddns_ready(self) -> bool:
        return bool(self.hosts and self.passwords)

    @property
    def incomplete(self) -> tuple[str, ...]:
        """What a part set halfway lacks, in words."""
        out = []
        if bool(self.api_user) != bool(self.api_key):
            out.append(f"{API_KEY if self.api_user else API_USER} is not set (the API needs both)")
        if bool(self.hosts) != bool(self.passwords):
            out.append(f"{DDNS_PASSWORD if self.hosts else DDNS_HOSTS} is not set (Dynamic DNS needs both)")
        return tuple(out)

    def ddns_hosts(self, known: Iterable[str] = ()) -> tuple[list[DdnsHost], list[str]]:
        """The Dynamic DNS hosts (their domains found among the account's, `known`, when given), and the entries that are
        no host, in words."""
        found, wrong = [], []
        for text in self.hosts:
            try:
                h = split_host(text, known)
            except ValueError as e:
                wrong.append(str(e))
                continue
            if h.fqdn.lower() not in {x.fqdn.lower() for x in found}:
                found.append(h)
        return found, wrong

    def password_for(self, domain: str) -> str | None:
        """The Dynamic DNS password of `domain`: its own, else the one for every domain; None when there is none."""
        d = str(domain or "").lower().rstrip(".")
        own = dict(self.passwords)
        return own.get(d) or own.get("") or None

    @property
    def secrets(self) -> tuple[str, ...]:
        """The values scrubbed from every message the plugin gives."""
        return tuple(v for v in (self.api_key, *(p for _, p in self.passwords)) if v)

    def print_of(self, *names: str) -> str:
        """A fingerprint of these settings' values (kept in memory to notice a change; never shown nor written)."""
        values = {API_USER: self.api_user, API_KEY: self.api_key, USERNAME: self.username, CLIENT_IP: self.client_ip,
                  SANDBOX: str(self.sandbox), DDNS_PASSWORD: repr(self.passwords), DDNS_HOSTS: repr(self.hosts),
                  DDNS_MINUTES: str(self.minutes)}
        return hashlib.sha256("\0".join(f"{n}={values[n]}" for n in names).encode("utf-8")).hexdigest()

    @property
    def api_print(self) -> str:
        return self.print_of(API_USER, API_KEY, USERNAME, CLIENT_IP, SANDBOX)

    @property
    def ddns_print(self) -> str:
        return self.print_of(DDNS_PASSWORD, DDNS_HOSTS)


def parse(values: Mapping[str, str]) -> Config:
    """The settings from their values by variable (those not set left out or empty)."""
    v = {n: str(values.get(n) or "").strip() for n in NAMES}
    present = frozenset(n for n in NAMES if v[n])
    problems: list[str] = []
    client_ip = v[CLIENT_IP]
    if client_ip:
        try:
            client_ip = str(ipaddress.IPv4Address(client_ip))
        except ValueError:
            problems.append(f"{CLIENT_IP} is not an IPv4 address (Namecheap whitelists IPv4 alone): this network's is used")
            client_ip = ""
    sandbox = v[SANDBOX].lower()
    if sandbox and sandbox not in TRUE | FALSE:
        problems.append(f"{SANDBOX} is 1 or 0: production is used")
    passwords: tuple[tuple[str, str], ...] = ()
    try:
        passwords = parse_passwords(v[DDNS_PASSWORD])
    except ValueError as e:
        problems.append(str(e))
    minutes = MINUTES[2]
    if v[DDNS_MINUTES]:
        try:
            minutes = min(max(float(v[DDNS_MINUTES]), MINUTES[0]), MINUTES[1])
        except ValueError:
            problems.append(f"{DDNS_MINUTES} is not a number of minutes: {MINUTES[2]:g} is used")
    hosts = tuple(h.strip() for h in re.split(r"[,;\s]+", v[DDNS_HOSTS]) if h.strip())
    return Config(api_user=v[API_USER], api_key=v[API_KEY], username=v[USERNAME], client_ip=client_ip,
                  sandbox=sandbox in TRUE, passwords=passwords, hosts=hosts, minutes=minutes, present=present,
                  problems=tuple(problems))


def read(login: Login | None = None) -> Config:
    """The settings as `login` furnishes them (the login of the app the plugin is attached to), else an EnvironmentLogin's:
    the variables set, by their pairs' names; a login that cannot be asked furnishes none, and says so."""
    asked = login if login is not None else EnvironmentLogin()
    try:
        values = asked.variables(NAMES)
    except Exception as e:  # noqa: BLE001 - a login that cannot be asked: nothing set, and why
        return Config(problems=(f"the settings could not be read from the login: {type(e).__name__}",))
    return parse(values)
