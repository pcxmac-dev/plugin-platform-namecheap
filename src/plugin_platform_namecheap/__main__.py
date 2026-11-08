"""`python -m plugin_platform_namecheap ...`: the plugin from the command line, its settings read from the environment
(an EnvironmentLogin: the variables as this shell has them).

    ip                                       this network's public IPv4 address, as the plugin finds it (to whitelist)
    status                                   the account read, then the plugin's status (JSON)
    domains                                  the account's domains
    hosts DOMAIN                             a domain's records and its mail setting
    set DOMAIN HOST TYPE ADDRESS [--ttl N] [--mx N] [--accept-ddns-reset]
                                             a record set, every other record kept (a backup first, a check after)
    remove DOMAIN HOST TYPE [ADDRESS] [--accept-ddns-reset]
                                             a record removed, the rest kept
    restore DOMAIN FILE [--accept-ddns-reset]
                                             a backup put back
    backups [DOMAIN]                         the backups kept, the newest first
    check NAME...                            whether names are free to register (nothing is bought)
    balance                                  the account's funds
    ddns [--now]                             a Dynamic DNS pass: an update where a host differs (--now: for every host)

--json prints the answer as JSON."""
from __future__ import annotations

import argparse
import json
import sys

from . import MACHINE, MAIL, when
from . import zone as zones
from .api import NamecheapError


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m plugin_platform_namecheap", description="Namecheap for Liminal: domains, records, Dynamic DNS")
    p.add_argument("--json", action="store_true", help="print the answer as JSON")
    sub = p.add_subparsers(dest="what")
    sub.add_parser("ip", help="this network's public IPv4 address, as the plugin finds it")
    sub.add_parser("status", help="the account read, then the plugin's status")
    sub.add_parser("domains", help="the account's domains")
    h = sub.add_parser("hosts", help="a domain's records")
    h.add_argument("domain")
    s = sub.add_parser("set", help="a record set, every other record kept")
    for a in ("domain", "host", "type", "address"):
        s.add_argument(a)
    s.add_argument("--ttl", type=int)
    s.add_argument("--mx", type=int, help="an MX record's preference")
    s.add_argument("--accept-ddns-reset", action="store_true", help="write even when the zone has Dynamic DNS hosts")
    r = sub.add_parser("remove", help="a record removed, the rest kept")
    for a in ("domain", "host", "type"):
        r.add_argument(a)
    r.add_argument("address", nargs="?")
    r.add_argument("--accept-ddns-reset", action="store_true")
    b = sub.add_parser("restore", help="a backup put back")
    b.add_argument("domain")
    b.add_argument("file")
    b.add_argument("--accept-ddns-reset", action="store_true")
    k = sub.add_parser("backups", help="the backups kept")
    k.add_argument("domain", nargs="?")
    c = sub.add_parser("check", help="whether names are free to register")
    c.add_argument("names", nargs="+")
    sub.add_parser("balance", help="the account's funds")
    d = sub.add_parser("ddns", help="a Dynamic DNS pass")
    d.add_argument("--now", action="store_true", help="an update for every host, whether it differs or not")
    return p


def report_lines(rep: dict) -> list[str]:
    """A write's report in words."""
    out = [f"{rep['domain']}: {rep['said']}"]
    if not rep.get("changed"):
        return out
    out.append(f"  backup: {rep['backup']}")
    if rep.get("success") is False:
        out.append("  Namecheap said the write did not succeed")
    if rep.get("ok"):
        out.append(f"  read back: every record as written ({rep['records']}); mail setting {rep.get('emailType')} kept")
    for what, label in (("missing", "missing after the write"), ("unexpected", "there but not written"), ("ttl", "TTL"),
                        ("dropped", "made since the backup and dropped")):
        for item in rep.get(what) or []:
            out.append(f"  {label}: {item}")
    if rep.get("emailChanged"):
        out.append(f"  the mail setting is now {rep.get('emailType')}")
    if rep.get("ddnsLost"):
        out.append(f"  Dynamic DNS turned off on {', '.join(rep['ddnsLost'])}: turn it on again in Namecheap's dashboard "
                   "(Advanced DNS: the host's record, A + Dynamic DNS Record)")
    if not rep.get("ok"):
        out.append(f"  to put the zone back as it was: {rep['restore']}")
    return out


def main(argv: list[str] | None = None, plugin=None, out=None, err=None) -> int:
    p = plugin if plugin is not None else MACHINE
    say = out or (lambda s: print(s))
    tell = err or (lambda s: print(s, file=sys.stderr))
    args = parser().parse_args(sys.argv[1:] if argv is None else argv)
    what = args.what or "status"
    try:
        if what == "ip":
            found = p.updater().address(fresh_s=0.0)
            if not found:
                tell("this network's public IPv4 address could not be found (OpenDNS and Google's DNS asked)")
                return 1
            say(json.dumps({"ip": found}) if args.json else found)
            return 0
        if what == "status":
            if p.config().api_ready:
                try:
                    p.refresh()
                except NamecheapError:
                    pass  # the status says it
            answer = p.status()
            say(json.dumps(answer, indent=1))
            return 0
        if what == "domains":
            answer = p.domains()
            lines = [f"{d['name']:<32} expires {d['expires'] or '–':<10}  auto-renew {'on' if d['autoRenew'] else 'off':<3}  "
                     f"{'Namecheap DNS' if d['ourDns'] else 'DNS elsewhere'}{'  locked' if d['locked'] else ''}" for d in answer]
            lines = lines or ["no domains in this account"]
        elif what == "hosts":
            answer = p.hosts(args.domain)
            lines = [f"{answer['domain']} · mail: {MAIL.get(answer['emailType'] or '', answer['emailType'] or 'not said')} · "
                     f"{'Namecheap DNS' if answer['usingOurDns'] else 'DNS elsewhere' if answer['usingOurDns'] is False else 'DNS not said'}"]
            lines += [f"  {r['name']:<24} {r['type']:<6} {r['address']}  ttl {r['ttl']}" + (f"  pref {r['mxpref']}" if r["type"] == "MX" else "")
                      + ("  [Dynamic DNS]" if r["ddns"] else "") for r in answer["records"]]
        elif what == "set":
            answer = p.set_record(args.domain, args.host, args.type, args.address, ttl=args.ttl, mx=args.mx,
                                  accept_ddns_reset=args.accept_ddns_reset)
            lines = report_lines(answer)
        elif what == "remove":
            answer = p.remove_record(args.domain, args.host, args.type, args.address, accept_ddns_reset=args.accept_ddns_reset)
            lines = report_lines(answer)
        elif what == "restore":
            answer = p.restore(args.domain, args.file, accept_ddns_reset=args.accept_ddns_reset)
            lines = report_lines(answer)
        elif what == "backups":
            found = zones.backups(p.folder, args.domain)
            answer = [str(f) for f in found]
            lines = answer or [f"no backups in {p.folder}"]
        elif what == "check":
            answer = p.availability(*args.names)
            lines = [f"{a['domain']:<32} {'free' if a['available'] else 'taken'}" + (f"  premium: {a['premiumPrice']}" if a["premium"] else "")
                     for a in answer]
        elif what == "balance":
            answer = p.balance()
            lines = [f"{answer['available']} {answer['currency']} available" + (f"; {answer['autoRenew']} needed for the auto-renewals due"
                                                                               if answer.get("autoRenew") not in (None, "", "0", "0.00") else "")]
        else:  # ddns
            answer = p.ddns_update(force=args.now)
            lines = [f"{h['host']:<32} {h['address'] or '–':<16} {h['result']} (checked {when(h['checkedAt'])})" for h in answer]
    except NamecheapError as e:
        tell(f"namecheap: {e}")
        return 1
    except (ValueError, RuntimeError) as e:  # a refusal (zone.Refusal), a setting not set, a pass under way
        tell(f"refused: {e}")
        return 1
    if args.json:
        say(json.dumps(answer, indent=1))
    else:
        for line in lines:
            say(line)
    if what in ("set", "remove", "restore") and answer.get("changed") and not answer.get("ok"):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
