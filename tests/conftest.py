"""Stand-ins for Namecheap and DNS: the tests never reach Namecheap, a resolver or the network. `FakeNamecheap` is the
API and the Dynamic DNS update as a transport (an account's domains and zones in memory, its answers laid out as the live
API's: the namespace, <host> in lowercase, EmailType on getHosts); `FakeDns` is nslookup's output for the lookups the
plugin makes; `Pairs` is a Login holding pairs by name."""
from __future__ import annotations

from xml.sax.saxutils import escape

import pytest

import plugin_platform_namecheap.api as api_mod
import plugin_platform_namecheap.ddns as ddns_mod
from liminal_libs.apps import Login, Unauthorized, pair_name
from plugin_platform_namecheap import NamecheapPlugin
from plugin_platform_namecheap.api import Limiter
from plugin_platform_namecheap.settings import NAMES

NS = "http://api.namecheap.com/xml.response"
KEY = "0123456789abcdef0123456789abcdef"  # a stand-in key (no account's)
DDNS_PASSWORD = "fedcba9876543210fedcba9876543210"
HOME = "93.184.216.34"  # this network's public address in the tests (a global one: the private ranges are refused)
CALLER = "93.184.216.99"  # the address an update without ip= is taken from


def q(v) -> str:
    return escape(str(v), {'"': "&quot;"})


def api_xml(command: str, inner: str, ns: str = NS) -> bytes:
    return (f'<?xml version="1.0" encoding="utf-8"?>\r\n<ApiResponse Status="OK" xmlns="{ns}"><Errors /><Warnings />'
            f'<RequestedCommand>{command.lower()}</RequestedCommand><CommandResponse Type="{command}">{inner}</CommandResponse>'
            '<Server>PHX01API</Server><GMTTimeDifference>--5:00</GMTTimeDifference><ExecutionTime>0.02</ExecutionTime>'
            '</ApiResponse>').encode()


def error_xml(number: str, text: str) -> bytes:
    return (f'<?xml version="1.0" encoding="utf-8"?>\r\n<ApiResponse Status="ERROR" xmlns="{NS}"><Errors>'
            f'<Error Number="{number}">{q(text)}</Error></Errors><Warnings /><RequestedCommand /></ApiResponse>').encode()


def ddns_ok(ip: str) -> bytes:
    return ('<?xml version="1.0" encoding="utf-16"?>\r\n<interface-response><Command>SETDNSHOST</Command><Language>eng'
            f'</Language><IP>{ip}</IP><ErrCount>0</ErrCount><errors /><ResponseCount>0</ResponseCount><responses />'
            '<Done>true</Done><debug><![CDATA[]]></debug></interface-response>').encode()


def ddns_error(words: str) -> bytes:
    return ('<?xml version="1.0" encoding="utf-16"?>\r\n<interface-response><Command>SETDNSHOST</Command><Language>eng'
            f'</Language><ErrCount>1</ErrCount><errors><Err1>{q(words)}</Err1></errors><ResponseCount>1</ResponseCount>'
            '<responses><response><ResponseNumber>304156</ResponseNumber><ResponseString>Validation error</ResponseString>'
            '</response></responses><Done>true</Done><debug><![CDATA[]]></debug></interface-response>').encode()


def proton_zone() -> list[dict]:
    """hypokrites.me as the user keeps it: mail at Proton (MX, SPF, DKIM, DMARC, the verification), a Dynamic DNS host."""
    return [{"name": "@", "type": "MX", "address": "mail.protonmail.ch.", "mxpref": 10},
            {"name": "@", "type": "MX", "address": "mailsec.protonmail.ch.", "mxpref": 20},
            {"name": "@", "type": "TXT", "address": "v=spf1 include:_spf.protonmail.ch ~all"},
            {"name": "@", "type": "TXT", "address": "protonmail-verification=0123456789abcdef"},
            {"name": "_dmarc", "type": "TXT", "address": "v=DMARC1; p=quarantine"},
            {"name": "protonmail._domainkey", "type": "CNAME", "address": "protonmail.domainkey.dabc.domains.proton.ch."},
            {"name": "www", "type": "CNAME", "address": "parkingpage.namecheap.com."}]


class FakeNamecheap:
    """The API and the Dynamic DNS update in memory; every request kept (`requests`)."""

    def __init__(self, user: str = "tester", key: str = KEY):
        self.user, self.key = user, key
        self.requests: list[dict] = []
        self.domains = [
            {"ID": "11", "Name": "hypokrites.me", "User": user, "Created": "05/01/2024", "Expires": "05/01/2027",
             "IsExpired": "false", "IsLocked": "false", "AutoRenew": "true", "WhoisGuard": "ENABLED", "IsPremium": "false",
             "IsOurDNS": "true"},
            {"ID": "12", "Name": "example.net", "User": user, "Created": "01/02/2020", "Expires": "01/02/2026",
             "IsExpired": "true", "IsLocked": "true", "AutoRenew": "false", "WhoisGuard": "NOTPRESENT", "IsPremium": "false",
             "IsOurDNS": "false"}]
        self.zones = {"hypokrites.me": {"email": "MX", "hosts": proton_zone()}}
        self.error: tuple[str, str] | None = None  # every API call answered with it
        self.keep_ddns = True  # a write keeps a Dynamic DNS host's flag (False: it turns plain)
        self.drop_on_write: str | None = None  # a record's address a write loses (a fault of Namecheap's, for the check)
        self.ddns_password = DDNS_PASSWORD
        self.ddns_records: dict[str, str] = {}  # fqdn -> the A record's address at the nameserver
        self.ddns_answer: bytes | None = None  # an update answered with this instead
        self.balance = {"Currency": "USD", "AvailableBalance": "12.34", "AccountBalance": "12.34", "EarnedAmount": "0.00",
                        "WithdrawableAmount": "0.00", "FundsRequiredForAutoRenew": "0.00"}
        self.lowercase_hosts = True  # the live API writes <host>; the documentation <Host>
        self.namespace = NS

    def commands(self) -> list[str]:
        return [r["params"].get("Command") for r in self.requests if "Command" in r["params"]]

    def __call__(self, method, url, query, form, timeout):
        params = {**(query or {}), **(form or {})}
        self.requests.append({"method": method, "url": url, "query": dict(query or {}), "form": dict(form or {}), "params": params})
        if url.startswith("https://dynamicdns.park-your-domain.com/"):
            return self.update(method, params)
        assert url in (api_mod.PRODUCTION, api_mod.SANDBOX), url
        if self.error:
            return 200, error_xml(*self.error)
        if params.get("ApiUser") != self.user or params.get("ApiKey") != self.key:
            return 200, error_xml("1011102", "API Key is invalid or API access has not been enabled")
        if not params.get("ClientIp"):
            return 200, error_xml("1011105", "Parameter ClientIP is missing")
        command = params["Command"]
        if command == "namecheap.domains.getList":
            size, page = int(params.get("PageSize", 20)), int(params.get("Page", 1))
            shown = self.domains[(page - 1) * size: page * size]
            inner = ("<DomainGetListResult>" + "".join("<Domain " + " ".join(f'{k}="{q(v)}"' for k, v in d.items()) + " />" for d in shown)
                     + f"</DomainGetListResult><Paging><TotalItems>{len(self.domains)}</TotalItems><CurrentPage>{page}</CurrentPage>"
                     f"<PageSize>{size}</PageSize></Paging>")
            return 200, api_xml(command, inner, self.namespace)
        if command == "namecheap.domains.dns.getHosts":
            domain = f"{params['SLD']}.{params['TLD']}"
            z = self.zones.get(domain)
            if z is None:
                return 200, error_xml("2030288", "Cannot complete this command as this domain is not using proper DNS servers")
            tag = "host" if self.lowercase_hosts else "Host"
            hosts = "".join(f'<{tag} HostId="{i}" Name="{q(h["name"])}" Type="{h["type"]}" Address="{q(h["address"])}" '
                            f'MXPref="{h.get("mxpref", 10)}" TTL="{h.get("ttl", 1799)}" AssociatedAppTitle="" FriendlyName="" '
                            f'IsActive="{str(h.get("active", True)).lower()}" IsDDNSEnabled="{str(h.get("ddns", False)).lower()}" />'
                            for i, h in enumerate(z["hosts"], 100))
            email = f' EmailType="{z["email"]}"' if z.get("email") is not None else ""
            return 200, api_xml(command, f'<DomainDNSGetHostsResult Domain="{domain}"{email} IsUsingOurDNS="true">{hosts}'
                                         "</DomainDNSGetHostsResult>", self.namespace)
        if command == "namecheap.domains.dns.setHosts":
            assert method == "POST" and "HostName1" in form and "ApiKey" not in form, "setHosts: by POST, its hosts in the form"
            domain = f"{params['SLD']}.{params['TLD']}"
            before = {(h["name"].lower(), h["type"]): h for h in self.zones[domain]["hosts"]}
            hosts, i = [], 1
            while f"HostName{i}" in form:
                h = {"name": form[f"HostName{i}"], "type": form[f"RecordType{i}"], "address": form[f"Address{i}"],
                     "mxpref": int(form[f"MXPref{i}"]), "ttl": int(form[f"TTL{i}"])}
                was = before.get((h["name"].lower(), h["type"]))
                if self.keep_ddns and was is not None and was.get("ddns"):
                    h["ddns"] = True
                if h["address"] != self.drop_on_write:
                    hosts.append(h)
                i += 1
            self.zones[domain] = {"email": form.get("EmailType"), "hosts": hosts}
            return 200, api_xml(command, f'<DomainDNSSetHostsResult Domain="{domain}" IsSuccess="true" />', self.namespace)
        if command == "namecheap.users.getBalances":
            return 200, api_xml(command, "<UserGetBalancesResult " + " ".join(f'{k}="{v}"' for k, v in self.balance.items()) + " />")
        if command == "namecheap.domains.check":
            out = "".join(f'<DomainCheckResult Domain="{d}" Available="{str(d.startswith("free")).lower()}" ErrorNo="0" '
                          f'Description="" IsPremiumName="{str(d.startswith("free-premium")).lower()}" '
                          f'PremiumRegistrationPrice="{"13000.0000" if d.startswith("free-premium") else "0"}" />'
                          for d in params["DomainList"].split(","))
            return 200, api_xml(command, out)
        return 200, error_xml("2011166", f"unknown command {command}")

    def update(self, method, params) -> tuple[int, bytes]:
        assert method == "GET", "Dynamic DNS takes GET alone"
        if self.ddns_answer is not None:
            return 200, self.ddns_answer
        if params.get("password") != self.ddns_password:
            return 200, ddns_error("Passwords do not match")
        host, domain = params["host"], params["domain"]
        fqdn = domain if host == "@" else f"{host}.{domain}"
        ip = params.get("ip") or CALLER
        self.ddns_records[fqdn.lower()] = ip
        return 200, ddns_ok(ip)


class FakeDns:
    """nslookup's output (as Windows prints it) for this network's address and the hosts' A records at their nameserver."""

    def __init__(self, fake: FakeNamecheap, public: str | None = HOME, google: bool = False):
        self.fake, self.public, self.google = fake, public, google
        self.calls: list[tuple] = []

    def __call__(self, name, rtype, server=None):
        self.calls.append((name, rtype, server))
        if (name, rtype) == ("myip.opendns.com", "A"):
            if not self.public or self.google:
                return "Server:  UnKnown\nAddress:  208.67.222.222\n\n*** UnKnown can't find myip.opendns.com: Non-existent domain\n"
            return f"Server:  resolver1.opendns.com\nAddress:  208.67.222.222\n\nName:    myip.opendns.com\nAddress:  {self.public}\n\n"
        if (name, rtype) == ("o-o.myaddr.l.google.com", "TXT"):
            if not self.public:
                return "Server:  UnKnown\nAddress:  216.239.32.10\n\nDNS request timed out.\n"
            return f'Server:  ns1.google.com\nAddress:  216.239.32.10\n\no-o.myaddr.l.google.com\ttext =\n\n\t"{self.public}"\n'
        if rtype == "NS":
            return (f"Server:  router.home\nAddress:  192.168.1.1\n\nNon-authoritative answer:\n{name}\tnameserver = "
                    f"dns1.registrar-servers.com\n{name}\tnameserver = dns2.registrar-servers.com\n")
        if rtype == "A":
            ip = self.fake.ddns_records.get(name.lower())
            if ip is None:
                return f"Server:  {server}\nAddress:  156.154.132.200\n\n*** {server} can't find {name}: Non-existent domain\n"
            return f"Server:  {server}\nAddress:  156.154.132.200\n\nName:    {name}\nAddress:  {ip}\n\n"
        return None


class Pairs(Login):
    """A login holding pairs by name (the login app's store, as the Login interface asks it)."""

    NAMESPACE = "test"

    def __init__(self, values: dict[str, str]):
        self.pairs = {pair_name(k): v for k, v in values.items()}
        self.asked: list[str] = []

    def user(self) -> dict:
        return {"name": "tester"}

    def vector(self, name: str) -> str:
        self.asked.append(name)
        if name not in self.pairs:
            raise Unauthorized(f"no {name}", 404)
        return self.pairs[name]

    def names(self) -> set[str]:
        return set(self.pairs)


def settings_of(api: bool = True, ddns: bool = False, **more) -> dict[str, str]:
    out = {}
    if api:
        out.update({"NAMECHEAP_API_USER": "tester", "NAMECHEAP_API_KEY": KEY})
    if ddns:
        out.update({"NAMECHEAP_DDNS_HOSTS": "home.hypokrites.me", "NAMECHEAP_DDNS_PASSWORD": DDNS_PASSWORD})
    out.update(more)
    return out


@pytest.fixture(autouse=True)
def _no_namecheap_no_network(monkeypatch, tmp_path):
    """No test reaches Namecheap, a resolver or this machine's settings: the HTTPS and nslookup are refused, every
    NAMECHEAP_ variable cleared, the platform's folder the test's own."""
    def refused(*a, **k):
        raise AssertionError("a test reached for the network")
    monkeypatch.setattr(api_mod, "https", refused)
    monkeypatch.setattr(ddns_mod, "https", refused)
    monkeypatch.setattr(ddns_mod, "nslookup", refused)
    for n in NAMES:
        monkeypatch.delenv(n, raising=False)
    monkeypatch.setenv("LIMINAL_PLATFORM_DIR", str(tmp_path / "platform"))


@pytest.fixture
def env(monkeypatch):
    """Sets the plugin's variables (the EnvironmentLogin's: what the platform reads today)."""
    def put(values: dict[str, str]):
        for k, v in values.items():
            monkeypatch.setenv(k, v)
    return put


@pytest.fixture
def made(tmp_path):
    """A plugin over the stand-ins: (plugin, fake Namecheap, fake DNS)."""
    def make(fake: FakeNamecheap | None = None, dns: FakeDns | None = None):
        fake = fake or FakeNamecheap()
        dns = dns or FakeDns(fake)
        p = NamecheapPlugin(transport=fake, run=dns, folder=tmp_path / "backups", limiter=Limiter(windows=((60.0, 100_000),)))
        return p, fake, dns
    return make
