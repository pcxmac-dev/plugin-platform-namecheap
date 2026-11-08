"""Namecheap for Liminal (the user, 2026-11-08: "lets create a namecheap platform plugin that utilizes the API to create a
dynamic DNS method, as well as manage domains"): the account's domains through Namecheap's API (their expiry, renewal,
lock, DNS and privacy; the balance; each domain's records on Namecheap's DNS, set and removed with every other record and
the mail setting kept, a backup before each write and a check after it; whether names are free), and Dynamic DNS keeping
hosts at this network's public IPv4 address. Nothing that spends: no domain is registered, renewed or transferred here.

Its settings are pairs asked of the login of the app it is attached to (settings.py: NAMECHEAP_API_USER, NAMECHEAP_API_KEY,
NAMECHEAP_DDNS_HOSTS, NAMECHEAP_DDNS_PASSWORD ...), never a file of its own. While attached to the platform app it reads
the account every quarter of an hour and checks the Dynamic DNS hosts every few minutes in a thread of its own; detached,
nothing of it runs. Its status is what was read last (no request is made to answer it): the platform's page draws its
tables and its actions (Refresh, Update DNS now).

    python -m plugin_platform_namecheap ip | status | domains | hosts DOMAIN | set DOMAIN HOST TYPE ADDRESS [--ttl N] [--mx N]
        | remove DOMAIN HOST TYPE [ADDRESS] | restore DOMAIN FILE | backups [DOMAIN] | check NAME... | balance | ddns [--now]
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from liminal_libs.machines.plugin import MachinePlugin

from . import ddns
from . import settings as settings_mod
from . import zone as zones
from .api import LIMITER, NamecheapApi, NamecheapError, Zone, shorten
from .settings import API_KEY, API_USER, DDNS_HOSTS, DDNS_PASSWORD, KEYS, NAMES, Config

__version__ = "0.1.0"
REFRESH_S = 900.0  # the account read again at most this often while attached (or by Refresh)
CONFIG_S = 30.0  # the settings asked of the login again after this long
RETRY_S = 900.0  # a part that failed is taken as untried after this long while detached: attached again, it is tried again
ZONES_MAX = 12  # the zones read by a refresh (the rest: `hosts DOMAIN`), under Namecheap's 20 requests a minute
DIR_VAR = "LIMINAL_PLATFORM_DIR"  # the platform's own folder (its app's variable): the backups go under it
NOT_SET = (f"not set up: {API_USER} and {API_KEY} for the API (domains and records), or {DDNS_HOSTS} and {DDNS_PASSWORD} "
           "for Dynamic DNS")
MAIL = {"MX": "custom MX", "MXE": "MXE", "FWD": "Namecheap's email forwarding", "OX": "Namecheap Private Email",
        "NONE": "no email service", "GMAIL": "Gmail"}
PRIVACY = {"ENABLED": "on", "DISABLED": "off", "NOTPRESENT": "none"}


def backups_dir() -> Path:
    """Where the zones are saved before a write: the platform's folder's namecheap/backups (LIMINAL_PLATFORM_DIR, else
    the data folder's platform/)."""
    named = (os.environ.get(DIR_VAR) or "").strip()
    if named:
        return Path(named).expanduser() / "namecheap" / "backups"
    from liminal_libs import layout

    return layout.data_dir() / "platform" / "namecheap" / "backups"


def when(t: float | None) -> str:
    return "–" if not t else time.strftime("%b %d %H:%M", time.localtime(t))


def plural(n: int, word: str) -> str:
    return f"{n:,} {word}{'' if n == 1 else 's'}"


def cell(text, sub: str | None = None):
    return {"text": text, "sub": sub} if sub else text


def yes(v) -> str:
    return "on" if v else "off" if v is False else "–"


class _Runtime:
    """What the plugin read and holds, shared by its copies (the registry's with_ makes them)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.config: tuple[float, Config] | None = None
        self.api: tuple[str, NamecheapApi] | None = None
        self.domains: list[dict] | None = None
        self.balance: dict | None = None
        self.zones: dict[str, Zone | str] = {}  # by domain: its zone as read, or why it was not
        self.refreshed_at: float | None = None
        self.api_ok: bool | None = None  # the last refresh's outcome (None: none yet)
        self.api_error = ""
        self.api_error_at: float | None = None
        self.api_print = ""  # the settings that outcome is of
        self.ddns_print = ""
        self.ddns_at: float | None = None
        self.updater: ddns.Updater | None = None
        self.worker: threading.Thread | None = None
        self.stop: threading.Event | None = None
        self.wake = threading.Event()
        self.refreshing = threading.Lock()


class NamecheapPlugin(MachinePlugin):
    """Namecheap: the account's domains and records through its API, and Dynamic DNS; reading in the background while attached."""

    name = "namecheap"
    title = "Namecheap"
    about = ("Your Namecheap domains through Namecheap's API, their records set and removed with every other record and the "
             "mail setting kept, and Dynamic DNS keeping hosts at this network's address")
    api = "2.1"
    order = 740
    ICON = "globe"
    HOOKS = (*MachinePlugin.HOOKS, "refresh", "domains", "hosts", "set_record", "remove_record", "availability",
             "ddns_update", "balance")
    keys = KEYS
    signup = "https://www.namecheap.com/support/api/intro/"
    limits = ("Namecheap's API: about 20 requests a minute, 700 an hour and 8,000 a day per key (the lower kept); "
              "Dynamic DNS: IPv4 only")

    def __init__(self, transport=None, run=None, folder: Path | None = None, clock=None, limiter=None):
        self._transport = transport  # (method, url, query, form, timeout) -> (status, body): a test's; else HTTPS over IPv4
        self._run = run  # (name, type, server) -> nslookup's output: a test's; else nslookup, windowless
        self._folder = Path(folder) if folder is not None else None
        self._clock = clock or time.time
        self._limiter = limiter or LIMITER
        self._rt = _Runtime()

    # -- the settings, the API, the updater --------------------------------------------------------------------------------
    def config(self, fresh: bool = False) -> Config:
        """The settings, asked of the login (the attached app's, else the environment's); kept CONFIG_S."""
        now = time.monotonic()
        with self._rt.lock:
            kept = self._rt.config
        if kept is not None and not fresh and now - kept[0] < CONFIG_S:
            return kept[1]
        cfg = settings_mod.read(self.login)
        with self._rt.lock:
            self._rt.config = (now, cfg)
        return cfg

    @property
    def folder(self) -> Path:
        return self._folder if self._folder is not None else backups_dir()

    def updater(self) -> ddns.Updater:
        with self._rt.lock:
            if self._rt.updater is None:
                self._rt.updater = ddns.Updater(transport=self._transport, run=self._run, clock=self._clock)
            return self._rt.updater

    def client(self) -> NamecheapApi:
        """The API with the settings as they are (ValueError when they are not set)."""
        cfg = self.config()
        if not cfg.api_ready:
            raise ValueError("the API is not set up: " + ("; ".join(cfg.incomplete) or f"{API_USER} and {API_KEY} are not set"))
        with self._rt.lock:
            held = self._rt.api
        if held is not None and held[0] == cfg.api_print:
            return held[1]
        made = NamecheapApi(cfg.api_user, cfg.api_key, cfg.username, cfg.client_ip, cfg.sandbox, transport=self._transport,
                            limiter=self._limiter, ip_of=self.updater().address, secrets=cfg.secrets, clock=self._clock)
        with self._rt.lock:
            self._rt.api = (cfg.api_print, made)
        return made

    def known(self) -> list[str]:
        """The account's domains by name, as last read."""
        with self._rt.lock:
            return [d["name"] for d in (self._rt.domains or []) if d.get("name")]

    # -- the hooks --------------------------------------------------------------------------------------------------------
    def present(self) -> bool:
        """Whether anything of it is set (the API, Dynamic DNS)."""
        return bool(self.config().present)

    def refresh(self) -> dict:
        """The account read again now: its domains, its balance and the records of its domains on Namecheap's DNS (at most
        ZONES_MAX); what the status shows until the next."""
        cfg = self.config(fresh=True)
        if not cfg.api_ready:
            raise ValueError("the API is not set up: " + ("; ".join(cfg.incomplete) or f"{API_USER} and {API_KEY} are not set"))
        if not self._rt.refreshing.acquire(timeout=120):
            raise RuntimeError("a refresh is under way")
        try:
            return self._refresh(cfg)
        finally:
            self._rt.refreshing.release()

    def _refresh(self, cfg: Config) -> dict:
        now = self._clock()
        try:
            api = self.client()
            found = api.domains()
            try:
                balance = api.balances()
            except NamecheapError as e:
                balance = {"error": str(e)}
            ours = [d for d in found if d.get("ourDns")]
            read: dict[str, Zone | str] = {}
            for d in ours[:ZONES_MAX]:
                try:
                    read[d["name"].lower()] = api.hosts(d["name"])
                except (NamecheapError, ValueError) as e:
                    read[d["name"].lower()] = str(e)
            for d in ours[ZONES_MAX:]:
                read[d["name"].lower()] = f"not read with the rest (more than {ZONES_MAX} domains): hosts {d['name']}"
        except (NamecheapError, ValueError) as e:
            with self._rt.lock:
                self._rt.api_ok, self._rt.api_error, self._rt.api_error_at, self._rt.api_print = False, str(e), now, cfg.api_print
            raise
        with self._rt.lock:
            self._rt.domains, self._rt.balance, self._rt.zones, self._rt.refreshed_at = found, balance, read, now
            self._rt.api_ok, self._rt.api_error, self._rt.api_error_at, self._rt.api_print = True, "", None, cfg.api_print
        return {"domains": len(found), "zones": sum(1 for z in read.values() if isinstance(z, Zone)), "refreshedAt": when(now)}

    def domains(self) -> list[dict]:
        """The account's domains, read now."""
        found = self.client().domains()
        with self._rt.lock:
            self._rt.domains = found
        return found

    def hosts(self, domain: str) -> dict:
        """A domain's records and mail setting, read now."""
        z = self.client().hosts(domain)
        with self._rt.lock:
            self._rt.zones[z.domain.lower()] = z
        return z.as_dict()

    def set_record(self, domain: str, host: str, rtype: str, address: str, ttl=None, mx=None, accept_ddns_reset=False) -> dict:
        """A record set in `domain` (zone.plan_set), every other record and the mail setting kept; backed up before and
        checked after."""
        return self._write(domain, lambda z: zones.plan_set(z, host, rtype, address, ttl=ttl, mx=mx), accept_ddns_reset)

    def remove_record(self, domain: str, host: str, rtype: str, address: str | None = None, accept_ddns_reset=False) -> dict:
        """A record removed from `domain` (zone.plan_remove; `address` names it among several), the rest kept."""
        return self._write(domain, lambda z: zones.plan_remove(z, host, rtype, address), accept_ddns_reset)

    def restore(self, domain: str, path, accept_ddns_reset=False) -> dict:
        """A backup put back (zone.restore), the zone as it is now backed up first."""
        report, after = zones.restore(self.client(), domain, path, self.folder, accept_ddns_reset=bool(accept_ddns_reset),
                                      clock=self._clock)
        self._keep(after)
        return report

    def _write(self, domain: str, plan, accept_ddns_reset) -> dict:
        report, after = zones.write(self.client(), domain, plan, self.folder, accept_ddns_reset=bool(accept_ddns_reset),
                                    clock=self._clock)
        self._keep(after)
        return report

    def _keep(self, z: Zone) -> None:
        with self._rt.lock:
            self._rt.zones[z.domain.lower()] = z

    def availability(self, *names: str) -> list[dict]:
        """Whether names are free to register (read only: nothing is bought)."""
        return self.client().availability(names)

    def balance(self) -> dict:
        """The account's funds, read now."""
        found = self.client().balances()
        with self._rt.lock:
            self._rt.balance = found
        return found

    def ddns_update(self, force: bool = True) -> list[dict]:
        """A Dynamic DNS pass now (the page's Update DNS now: `force`, an update sent for every host whether its record
        differs or not; the command line's `ddns` without --now sends only where it differs)."""
        cfg = self.config(fresh=True)
        if not cfg.ddns_ready:
            raise ValueError("Dynamic DNS is not set up: " + ("; ".join(cfg.incomplete) or f"{DDNS_HOSTS} and {DDNS_PASSWORD} are not set"))
        out = self.updater().run_pass(cfg, known=self.known(), force=bool(force))
        with self._rt.lock:
            self._rt.ddns_print, self._rt.ddns_at = cfg.ddns_print, self._clock()
        return out

    # -- attached: the reading in the background ------------------------------------------------------------------------------
    def attach(self, app, login=None) -> dict:
        """Attached by the platform: its settings asked of the platform's login from now on; the account read and the
        Dynamic DNS hosts checked in the background."""
        interface = super().attach(app, login)
        with self._rt.lock:
            self._rt.config = None
        self._start()
        return interface

    def detach(self) -> None:
        """Detached (the platform ending, the plugin disabled or not valid): the background reading ends."""
        self._stop()
        super().detach()
        with self._rt.lock:
            self._rt.config = None

    @property
    def working(self) -> bool:
        with self._rt.lock:
            t = self._rt.worker
        return t is not None and t.is_alive()

    def _start(self) -> None:
        with self._rt.lock:
            if self._rt.worker is not None and self._rt.worker.is_alive():
                return
            stop = threading.Event()
            t = threading.Thread(target=self._work, args=(stop,), name="namecheap", daemon=True)
            self._rt.worker, self._rt.stop = t, stop
            self._rt.wake.clear()
        t.start()

    def _stop(self) -> None:
        with self._rt.lock:
            t, stop = self._rt.worker, self._rt.stop
            self._rt.worker = self._rt.stop = None
        if stop is not None:
            stop.set()
            self._rt.wake.set()
        if t is not None and t is not threading.current_thread():
            t.join(timeout=10)

    def _work(self, stop: threading.Event) -> None:
        """The background: the account read every REFRESH_S, the Dynamic DNS hosts checked every NAMECHEAP_DDNS_MINUTES;
        nothing done for what is not set."""
        next_api = next_ddns = 0.0
        while not stop.is_set():
            now = time.monotonic()
            cfg = None
            try:
                cfg = self.config()
                if cfg.api_ready and now >= next_api:
                    next_api = now + REFRESH_S
                    if self._rt.refreshing.acquire(blocking=False):  # Refresh asked meanwhile: that one is enough
                        try:
                            self._refresh(cfg)
                        except Exception:  # noqa: BLE001 - kept as its outcome (api_error), shown by the status
                            pass
                        finally:
                            self._rt.refreshing.release()
                if cfg.ddns_ready and now >= next_ddns:
                    next_ddns = now + cfg.minutes * 60.0
                    try:
                        self.updater().run_pass(cfg, known=self.known(), force=False, wait=0.5)
                        with self._rt.lock:
                            self._rt.ddns_print, self._rt.ddns_at = cfg.ddns_print, self._clock()
                    except Exception:  # noqa: BLE001 - a pass under way (Update DNS now), or its trouble kept by the hosts
                        pass
            except Exception:  # noqa: BLE001 - the background never ends on a trouble; the status says it
                pass
            due = [t for t, on in ((next_api, cfg is not None and cfg.api_ready), (next_ddns, cfg is not None and cfg.ddns_ready)) if on]
            wait = min([60.0, *(t - time.monotonic() for t in due)])
            self._rt.wake.wait(max(1.0, wait))
            self._rt.wake.clear()

    # -- what the platform's page shows ------------------------------------------------------------------------------------
    def status(self) -> dict:
        """What was read last, asking nothing of Namecheap: the settings set (by name), the summary, valid (some part set up
        that works or is untried) and why not, the tables (Dynamic DNS, the domains, each zone read) and the actions."""
        cfg = self.config()
        if not cfg.present:
            return {"present": False, "valid": False, "why": NOT_SET, "summary": "not set up", "settingsNotSet": ", ".join(NAMES),
                    "tables": [], "actions": []}
        rt, now, attached = self._rt, self._clock(), self.app is not None
        with rt.lock:
            domains, balance, read = list(rt.domains or []), rt.balance, dict(rt.zones)
            refreshed_at, api_ok, api_error, api_error_at = rt.refreshed_at, rt.api_ok, rt.api_error, rt.api_error_at
            api_print, ddns_print, updater = rt.api_print, rt.ddns_print, rt.updater
        hosts, wrong = cfg.ddns_hosts(self.known())
        states = {s.fqdn.lower(): s for s in (updater.states() if updater is not None else [])}
        parts: list[tuple[str, bool | None, str]] = []  # (part, works: None untried, its trouble)
        if cfg.api_ready:
            works = api_ok if api_print == cfg.api_print else None
            if works is False and not attached and api_error_at is not None and now - api_error_at >= RETRY_S:
                works = None  # tried again once the platform attaches it
            parts.append(("api", works, api_error))
        if cfg.ddns_ready:
            tried = [states[h.fqdn.lower()] for h in hosts if h.fqdn.lower() in states and states[h.fqdn.lower()].ok is not None]
            works = None if ddns_print != cfg.ddns_print or not tried else any(s.ok for s in tried)
            last = max((s.checked_at or 0.0 for s in tried), default=0.0)
            if works is False and not attached and now - last >= RETRY_S:
                works = None
            parts.append(("ddns", works, "; ".join(f"{s.fqdn}: {s.result}" for s in tried if s.ok is False)))
        troubles = [f"{'the API' if p == 'api' else 'Dynamic DNS'}: {t}" for p, w, t in parts if w is False]
        notes = [*cfg.incomplete, *cfg.problems, *wrong]
        valid = any(w is not False for _, w, _ in parts)
        out: dict = {"present": True, "valid": valid, "summary": self._summary(cfg, parts, domains, balance, hosts, states, attached)}
        if not valid:
            out["why"] = "; ".join(troubles or notes) or NOT_SET
        elif troubles or notes:
            out["problem"] = "; ".join([*troubles, *notes])
        out["api"] = ("Namecheap's sandbox" if cfg.sandbox else "production") if cfg.api_ready else "not set up"
        out["settingsSet"] = ", ".join(n for n in NAMES if n in cfg.present)
        missing = [n for n in NAMES if n not in cfg.present]
        if missing:
            out["settingsNotSet"] = ", ".join(missing)
        public = updater.public if updater is not None else None
        if cfg.api_ready:
            out["clientIp"] = ("as set (NAMECHEAP_CLIENT_IP)" if cfg.client_ip else
                               f"{public}, this network's" if public else "this network's address, once found")
        if balance and not balance.get("error"):
            out["balance"] = f"{balance.get('available')} {balance.get('currency')}".strip()
            try:
                if float(balance.get("autoRenew") or 0) > 0:
                    out["balance"] += f" · {balance['autoRenew']} needed for the auto-renewals due"
            except ValueError:
                pass
        if refreshed_at:
            out["readAt"] = when(refreshed_at)
        used = self._limiter.used()
        out["apiRequests"] = " · ".join(f"{n} of {most:,} {span}" for (_, n, most), span in zip(used, ("this minute", "this hour", "today")))
        if cfg.ddns_ready:
            out["ddnsEvery"] = f"every {cfg.minutes:g} min" + ("" if attached else ", once attached")
        out["backups"] = str(self.folder)
        out["tables"] = self._tables(cfg, domains, read, hosts, states, public)
        out["actions"] = ([{"hook": "refresh", "args": [], "title": "Refresh",
                            "note": "the domains, the balance and the records read again now (a few requests)"}] if cfg.api_ready else []) + \
                         ([{"hook": "ddns_update", "args": [], "title": "Update DNS now",
                            "note": "an update sent now for every Dynamic DNS host, with this network's address"}] if cfg.ddns_ready else [])
        return out

    def _summary(self, cfg, parts, domains, balance, hosts, states, attached) -> str:
        works = dict((p, w) for p, w, _ in parts)
        errors = dict((p, t) for p, _, t in parts)
        bits = []
        if cfg.api_ready:
            if works.get("api") is True:
                money = f"{balance.get('available')} {balance.get('currency')}" if balance and not balance.get("error") else ""
                bits.append(plural(len(domains), "domain") + (f" · {money}" if money else ""))
            elif works.get("api") is None:
                bits.append("reading the account…" if attached else "the account is read once attached")
            else:
                bits.append(f"the API: {shorten(errors.get('api') or 'failed', 100)}")
        if cfg.ddns_ready:
            mine = [states[h.fqdn.lower()] for h in hosts if h.fqdn.lower() in states]
            if len(hosts) == 1 and mine and mine[0].ok:
                bits.append(f"{mine[0].fqdn} at {mine[0].address}")
            elif any(s.ok is not None for s in mine):
                bits.append(f"Dynamic DNS: {sum(1 for s in mine if s.ok)} of {plural(len(hosts), 'host')} current")
            else:
                bits.append("Dynamic DNS: the first check is under way" if attached else "Dynamic DNS: checked once attached")
        return " · ".join(bits) or "set up halfway"

    def _tables(self, cfg, domains, read, hosts, states, public) -> list[dict]:
        out = []
        if cfg.ddns_ready:
            rows = []
            for h in hosts:
                s = states.get(h.fqdn.lower())
                rows.append([h.fqdn, (s.address if s else None) or "–", when(s.checked_at if s else None),
                             when(s.updated_at if s else None), s.result if s else "not checked yet"])
            out.append({"title": "Dynamic DNS", "note": f"every {cfg.minutes:g} min · this network's address: {public or 'not found yet'}",
                        "columns": [{"title": "Host"}, {"title": "Address"}, {"title": "Checked"}, {"title": "Updated"},
                                    {"title": "Result"}], "rows": rows, "empty": "No host could be read in NAMECHEAP_DDNS_HOSTS."})
        if cfg.api_ready and domains:
            out.append({"title": "Domains", "columns": [{"title": "Domain"}, {"title": "Expires"}, {"title": "Auto-renew"},
                                                        {"title": "Lock"}, {"title": "DNS"}, {"title": "Privacy"}],
                        "rows": [[cell(d["name"], " · ".join(x for x in ("expired" if d.get("expired") else "",
                                                                          "premium" if d.get("premium") else "") if x) or None),
                                  d.get("expires") or "–", yes(d.get("autoRenew")), "locked" if d.get("locked") else "–",
                                  "Namecheap" if d.get("ourDns") else "elsewhere",
                                  PRIVACY.get(str(d.get("privacy") or "").upper(), str(d.get("privacy") or "–").lower())]
                                 for d in domains]})
        for name in sorted(read):
            z = read[name]
            if not isinstance(z, Zone):
                out.append({"title": f"{name} records", "note": z, "columns": [{"title": "Host"}], "rows": [],
                            "empty": "Not read."})
                continue
            rows = [[r.name, r.type, cell(r.address if len(r.address) <= 64 else r.address[:63] + "…"), str(r.ttl),
                     str(r.mxpref) if r.type == "MX" else "", "yes" if r.ddns else ""]
                    for r in sorted(z.records, key=lambda r: (r.name != "@", r.name.lower(), r.type))]
            out.append({"title": f"{z.domain} records",
                        "note": f"mail: {MAIL.get(z.email_type or '', z.email_type or 'not said')} · read {when(z.read_at)} · "
                                "set and removed from the command line (python -m plugin_platform_namecheap set | remove)",
                        "columns": [{"title": "Host"}, {"title": "Type"}, {"title": "Address"}, {"title": "TTL", "num": True},
                                    {"title": "MX", "num": True}, {"title": "Dynamic DNS"}],
                        "rows": rows, "empty": "No records."})
        return out


MACHINE = NamecheapPlugin()
