"""A domain's records changed the only way Namecheap's setHosts allows: the whole zone written at once, every record it is
not given deleted. So a change is a read, a change and a write of everything (the user's domain hypokrites.me keeps its mail
at Proton: a write must never lose its MX or TXT records):

- a fresh getHosts, then refused, with nothing sent, when what was read cannot be written back as it is: no mail setting
  (EmailType) in the answer, a record type setHosts cannot take back (CAA until its Flag and Tag are verified, SRV), a
  record turned off, a domain not on Namecheap's DNS, a zone read back empty, Dynamic DNS hosts (setHosts has no record
  type for them) unless the caller accepts that they may turn into plain A records;
- every other record and the mail setting kept as read;
- the zone as read saved to a JSON backup before the write (`restore` puts one back);
- written by POST, read again and compared with what was written: a record missing or one not written, the mail setting
  changed, a Dynamic DNS host turned plain, each reported."""
from __future__ import annotations

import ipaddress
import json
import os
import re
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from .api import TTL_DEFAULT, TTL_MAX, TTL_MIN, NamecheapApi, Record, Zone, valid_domain

ROUND_TRIP = frozenset({"A", "AAAA", "ALIAS", "CNAME", "MX", "MXE", "NS", "TXT", "URL", "URL301", "FRAME"})  # sent back as read
WRITABLE = ROUND_TRIP  # what a record set here may be (not CAA: its Flag and Tag are not verified to come back whole)
SINGLE = frozenset({"A", "AAAA", "ALIAS", "CNAME", "MXE", "URL", "URL301", "FRAME"})  # set: the host's records of the type replaced
NAMED = frozenset({"CNAME", "ALIAS", "NS", "MX"})  # an address that is a host name
REDIRECTS = frozenset({"URL", "URL301", "FRAME"})
MAX_TEXT = 2048
LABEL = re.compile(r"^[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?$")
TARGET_LABEL = re.compile(r"^[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?$")


class Refusal(ValueError):
    """A write not made, and why: nothing was sent to Namecheap."""


# -- what is written -----------------------------------------------------------------------------------------------------
def record_type(value: str) -> str:
    t = str(value or "").strip().upper()
    if t == "CAA":
        raise Refusal("CAA records are not written by this release: their Flag and Tag are not verified to come back whole")
    if t not in WRITABLE:
        raise ValueError(f"{value!r} is no record type here: {', '.join(sorted(WRITABLE))}")
    return t


def host_name(name: str, domain: str) -> str:
    """A host as Namecheap names it in `domain`: @ (the domain itself), www, home, *, _dmarc, a.b; the domain's own name
    given in full is taken off (home.example.com is home)."""
    n = str(name or "").strip().lower().rstrip(".")
    d = domain.lower().rstrip(".")
    if n == d:
        return "@"
    if n.endswith("." + d):
        n = n[: -len(d) - 1]
    if n == "@":
        return "@"
    labels = n.split(".") if n else []
    if not labels or len(n) > 253 or not all(LABEL.match(x) or (i == 0 and x == "*") for i, x in enumerate(labels)):
        raise ValueError(f"{str(name).strip()!r} is not a host: @, www, home, *, _dmarc")
    return n


def address_for(rtype: str, address: str) -> str:
    """The address of a record of `rtype` as written; ValueError when it is none."""
    a = str(address or "").strip()
    if not a:
        raise ValueError("no address given")
    if rtype in ("A", "MXE"):
        try:
            return str(ipaddress.IPv4Address(a))
        except ValueError:
            raise ValueError(f"{a!r} is not an IPv4 address (a {rtype} record's)") from None
    if rtype == "AAAA":
        try:
            return str(ipaddress.IPv6Address(a))
        except ValueError:
            raise ValueError(f"{a!r} is not an IPv6 address (an AAAA record's)") from None
    if rtype in NAMED:
        n = a.lower()
        labels = n.rstrip(".").split(".")
        if len(n) > 254 or len(labels) < 2 or not all(TARGET_LABEL.match(x) for x in labels):
            raise ValueError(f"{a!r} is not a host name (a {rtype} record's)")
        return n
    if rtype in REDIRECTS:
        if not re.match(r"^https?://[^\s]+$", a, flags=re.IGNORECASE) or len(a) > MAX_TEXT:
            raise ValueError(f"{a!r} is not an http or https address (a {rtype} record's)")
        return a
    if len(a) > MAX_TEXT or any(ord(c) < 32 or ord(c) == 127 for c in a):  # TXT
        raise ValueError(f"a TXT record's text is one line of at most {MAX_TEXT} characters")
    return a


def norm_address(rtype: str, address: str) -> str:
    a = str(address or "").strip()
    if rtype in NAMED:
        return a.lower().rstrip(".")
    if rtype in ("A", "AAAA", "MXE"):
        try:
            return str(ipaddress.ip_address(a))
        except ValueError:
            return a
    return a


def key(r: Record) -> tuple[str, str, str]:
    """What makes a record the same record: its host, its type, its address."""
    t = r.type.strip().upper()
    return (r.name.strip().lower().rstrip(".") or "@", t, norm_address(t, r.address))


def said(r: Record) -> str:
    short = r.address if len(r.address) <= 60 else r.address[:59] + "…"
    return f"{r.name} {r.type} {short}" + (f" (pref {r.mxpref})" if r.type == "MX" else "")


def same(a: Sequence[Record], b: Sequence[Record]) -> bool:
    """Whether two zones hold the same records, their TTLs and preferences too."""
    def full(rs):
        return sorted((*key(r), r.ttl, r.mxpref if r.type.upper() == "MX" else 0) for r in rs)
    return full(a) == full(b)


def ttl_of(value) -> int:
    try:
        t = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"the TTL is a number of seconds, {TTL_MIN} to {TTL_MAX}") from None
    if not TTL_MIN <= t <= TTL_MAX:
        raise ValueError(f"the TTL is {TTL_MIN} to {TTL_MAX} seconds (Namecheap's range)")
    return t


def pref_of(value) -> int:
    try:
        p = int(value)
    except (TypeError, ValueError):
        raise ValueError("an MX preference is a number, 0 to 65535") from None
    if not 0 <= p <= 65535:
        raise ValueError("an MX preference is 0 to 65535")
    return p


# -- what may be written over --------------------------------------------------------------------------------------------
def check_writable(zone: Zone, accept_ddns_reset: bool = False) -> None:
    """Refusal when a write could lose what the zone holds."""
    d = zone.domain
    if zone.using_our_dns is False:
        raise Refusal(f"{d} is not on Namecheap's DNS: its records are wherever its nameservers are")
    if not zone.email_type:
        raise Refusal(f"Namecheap's answer did not say {d}'s mail setting (EmailType): a write could reset its mail, so none is made")
    if not zone.records:
        raise Refusal(f"{d}'s records read back empty: no write is made over what may be a misreading "
                      "(the first records of an empty zone are added in Namecheap's dashboard)")
    odd = sorted({r.type or "(no type)" for r in zone.records if r.type.upper() not in ROUND_TRIP})
    if odd:
        raise Refusal(f"{d} holds {', '.join(odd)} records, which setHosts cannot take back as they are: "
                      "a write would lose them, so none is made (change them in Namecheap's dashboard)")
    off = sorted({r.name for r in zone.records if r.active is False})
    if off:
        raise Refusal(f"{d} holds records turned off ({', '.join(off)}): a write would turn them on or lose them, so none is made")
    ddns = sorted({r.name for r in zone.records if r.ddns})
    if ddns and not accept_ddns_reset:
        raise Refusal(f"{d} has Dynamic DNS hosts ({', '.join(ddns)}): setHosts has no record type for them, so a write may "
                      "turn them into plain A records that Dynamic DNS no longer updates; write anyway with accept_ddns_reset "
                      "(the command line's --accept-ddns-reset): the result says whether they kept it, and the dashboard "
                      "turns it back on (Advanced DNS: the host's record, A + Dynamic DNS Record)")


# -- the changes -------------------------------------------------------------------------------------------------------------
def plan_set(zone: Zone, name: str, rtype: str, address: str, ttl=None, mx=None) -> tuple[tuple[Record, ...], str]:
    """The zone's records with a record set, and what that does in words: an A, AAAA, ALIAS, CNAME, MXE or redirect
    replaces the host's records of its type; a TXT, MX or NS is added beside the others (or its TTL changed when it is
    there already)."""
    t = record_type(rtype)
    host = host_name(name, zone.domain)
    addr = address_for(t, address)
    if t == "MX" and zone.email_type != "MX":
        raise Refusal(f"{zone.domain}'s mail setting is {zone.email_type}: MX records are its mail only with Custom MX "
                      "(EmailType MX), chosen in Namecheap's dashboard (Domain List > Manage > Mail Settings)")
    if t == "MXE" and zone.email_type != "MXE":
        raise Refusal(f"{zone.domain}'s mail setting is {zone.email_type}: an MXE record needs the MXE mail setting, chosen in "
                      "Namecheap's dashboard")
    if mx is not None and t != "MX":
        raise ValueError("an MX preference is an MX record's alone")
    if t == "CNAME" and host == "@":
        raise Refusal("a CNAME cannot stand for the domain itself (@): an ALIAS or a URL record does")
    at_host = [r for r in zone.records if key(r)[0] == host]
    if t == "CNAME" and any(r.type.upper() != "CNAME" for r in at_host):
        raise Refusal(f"{host} holds other records ({', '.join(sorted({r.type for r in at_host}))}): a CNAME stands alone")
    if t != "CNAME" and any(r.type.upper() == "CNAME" for r in at_host):
        raise Refusal(f"{host} is a CNAME: it holds no {t} record beside it")
    new_key = (host, t, norm_address(t, addr))
    out: list[Record] = []
    was: list[Record] = []
    placed = False
    for r in zone.records:
        k = key(r)
        if k == new_key or (t in SINGLE and k[0] == host and k[1] == t):
            was.append(r)
            if not placed:
                out.append(None)  # its place, filled below
                placed = True
            continue
        out.append(r)
    base = next((r for r in was if key(r) == new_key), was[0] if was else None)
    record = Record(name=host, type=t, address=addr, ttl=ttl_of(ttl) if ttl is not None else (base.ttl if base else TTL_DEFAULT),
                    mxpref=pref_of(mx) if mx is not None else (base.mxpref if base else 10))
    records = tuple(record if r is None else r for r in out) if placed else (*out, record)
    gone = [r for r in was if key(r) != new_key]
    if any(key(r) == new_key for r in was):
        words = f"{said(record)} is there already" + ("" if not gone else f"; {', '.join(said(r) for r in gone)} replaced")
        if base and (base.ttl != record.ttl or base.mxpref != record.mxpref):
            words += f"; TTL {record.ttl}" + (f", preference {record.mxpref}" if t == "MX" else "")
    elif gone:
        words = f"set {said(record)} (it was {', '.join(r.address for r in gone)})"
    else:
        words = f"added {said(record)}"
    return records, words


def plan_remove(zone: Zone, name: str, rtype: str, address: str | None = None) -> tuple[tuple[Record, ...], str]:
    """The zone's records without a record: the host's records of the type, the one with `address` when given (needed when
    the host has several, as a domain's TXT records are)."""
    t = str(rtype or "").strip().upper()
    if t not in ROUND_TRIP:
        raise ValueError(f"{rtype!r} is no record type here: {', '.join(sorted(ROUND_TRIP))}")
    host = host_name(name, zone.domain)
    want = norm_address(t, address) if address not in (None, "") else None
    matches = [r for r in zone.records if key(r)[:2] == (host, t) and (want is None or key(r)[2] == want)]
    if not matches:
        raise Refusal(f"{zone.domain} has no {t} record at {host}" + (f" holding {address}" if want is not None else ""))
    if want is None and len(matches) > 1:
        raise Refusal(f"{zone.domain} has {len(matches)} {t} records at {host}: name the one to remove by its address")
    gone = {id(r) for r in matches}
    rest = tuple(r for r in zone.records if id(r) not in gone)
    if not rest:
        raise Refusal(f"removing it would leave {zone.domain} with no records at all: that is done in Namecheap's dashboard")
    return rest, "removed " + ", ".join(said(r) for r in matches)


# -- the check after a write ----------------------------------------------------------------------------------------------
def verify(before: Zone, written: Sequence[Record], after: Zone) -> dict:
    """What the zone read after a write holds against what was written: every record written there (`missing` those not),
    nothing else (`unexpected`), the mail setting kept, the TTLs, and the Dynamic DNS hosts that turned plain."""
    want = {key(r): r for r in written}
    got = {key(r): r for r in after.records}
    missing = [said(want[k]) for k in want if k not in got]
    unexpected = [said(got[k]) for k in got if k not in want]
    ttl = [f"{k[0]} {k[1]}: TTL {want[k].ttl} written, {got[k].ttl} read" for k in want if k in got and want[k].ttl != got[k].ttl]
    still = {k[0] for k in want}
    lost = sorted({r.name.lower() for r in before.records if r.ddns} - {r.name.lower() for r in after.records if r.ddns})
    lost = [n for n in lost if n in still]
    mail_changed = (after.email_type or None) != (before.email_type or None)
    return {"ok": not missing and not unexpected and not mail_changed, "missing": missing, "unexpected": unexpected,
            "ttl": ttl, "ddnsLost": lost, "emailType": after.email_type, "emailChanged": mail_changed,
            "records": len(after.records)}


# -- backups ---------------------------------------------------------------------------------------------------------------
def backup_name(domain: str) -> str:
    return re.sub(r"[^a-z0-9.-]", "_", domain.lower())


def save_backup(folder: Path, zone: Zone, clock=time.time) -> Path:
    """The zone as read, saved before a write: `<domain>-<UTC time>.json` in `folder`."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{backup_name(zone.domain)}-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime(clock()))}"
    path, n = folder / f"{stem}.json", 1
    while path.exists():
        path, n = folder / f"{stem}-{n}.json", n + 1
    data = {"kind": "namecheap-zone", "format": 1, "domain": zone.domain, "readAt": zone.read_at,
            "emailType": zone.email_type, "usingOurDns": zone.using_our_dns, "records": [r.as_dict() for r in zone.records]}
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(data, indent=1), encoding="utf-8")
    os.replace(part, path)
    return path


def load_backup(path) -> Zone:
    """A backup of this plugin's (save_backup) as the zone it saved; ValueError when the file is none."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("kind") != "namecheap-zone":
            raise ValueError("not a zone backup")
        records = tuple(Record.from_dict(d) for d in data["records"])
        return Zone(domain=str(data["domain"]), email_type=data.get("emailType") or None,
                    using_our_dns=data.get("usingOurDns"), records=records, read_at=float(data.get("readAt") or 0.0))
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise ValueError(f"{path} is not a zone backup of this plugin's ({type(e).__name__}: {e})") from None


def backups(folder: Path, domain: str | None = None) -> list[Path]:
    """The backups kept, the newest first (`domain`: its own)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    stem = f"{backup_name(domain)}-" if domain else ""

    def newest(p: Path):  # by its time, then its count within the same second (name-20270115T080000Z-1.json)
        m = re.match(r"^.*-(\d{8}T\d{6}Z)(?:-(\d+))?\.json$", p.name)
        return (m.group(1), int(m.group(2) or 0)) if m else ("", 0)
    return sorted((p for p in folder.glob("*.json") if p.name.startswith(stem)), key=newest, reverse=True)


# -- a write ----------------------------------------------------------------------------------------------------------------
Plan = Callable[[Zone], tuple[tuple[Record, ...], str]]


def write(api: NamecheapApi, domain: str, plan: Plan, folder: Path, accept_ddns_reset: bool = False,
          email_type: str | None = None, clock=time.time) -> tuple[dict, Zone]:
    """A change written: the zone read fresh, refused when it cannot be written back whole, changed by `plan`, backed up,
    written, read again and checked. (The report, the zone read after it; the one read before when nothing was written.)"""
    zone = api.hosts(valid_domain(domain))
    check_writable(zone, accept_ddns_reset)
    records, words = plan(zone)
    mail = email_type or zone.email_type
    if same(zone.records, records) and mail == zone.email_type:
        return {"domain": zone.domain, "changed": False, "said": words + ": nothing written"}, zone
    backup = save_backup(folder, zone, clock)
    success = api.set_hosts(zone.domain, records, mail)
    after = api.hosts(zone.domain)
    report = verify(zone, records, after)
    report.update({"domain": zone.domain, "changed": True, "said": words, "success": success, "backup": str(backup),
                   "restore": f'python -m plugin_platform_namecheap restore {zone.domain} "{backup}"'})
    if mail != zone.email_type:  # a restore putting the mail setting back: changed by asking, so not a fault
        report["emailChanged"] = (after.email_type or None) != (mail or None)
        report["ok"] = not report["missing"] and not report["unexpected"] and not report["emailChanged"]
    return report, after


def restore(api: NamecheapApi, domain: str, path, folder: Path, accept_ddns_reset: bool = False,
            clock=time.time) -> tuple[dict, Zone]:
    """A backup put back: the zone as it was saved (its mail setting too), the zone as it is now backed up first."""
    d = valid_domain(domain)
    saved = load_backup(path)
    if saved.domain.lower().rstrip(".") != d:
        raise Refusal(f"{path} is a backup of {saved.domain}, not of {d}")
    check_writable(saved, accept_ddns_reset=True)  # what it puts back must itself come back whole
    now: dict = {}

    def plan(zone: Zone):
        now["dropped"] = [said(r) for r in zone.records if key(r) not in {key(s) for s in saved.records}]
        when = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(saved.read_at)) if saved.read_at else "its backup"
        return saved.records, f"put back the {len(saved.records)} records of {when}"
    report, after = write(api, d, plan, folder, accept_ddns_reset=accept_ddns_reset, email_type=saved.email_type, clock=clock)
    if report.get("changed"):
        if now.get("dropped"):
            report["dropped"] = now["dropped"]
        # the hosts that were Dynamic DNS hosts in the backup and are plain now (setHosts has no type for them)
        report["ddnsLost"] = sorted({r.name.lower() for r in saved.records if r.ddns} - {r.name.lower() for r in after.records if r.ddns})
    return report, after
