"""The platform's page sets and removes records through the plugin's forms (0.2.0; liminal-platform 0.6.0 draws status.forms):
a record set in each zone shown and a Remove on each of its records, the fields the hooks' arguments in order, each write
confirmed by the user with the exact change named and the backup said; a zone with Dynamic DNS hosts written only once the
user has accepted that too, a second confirmation offered when the write is refused for them. Over the stand-ins alone."""
from __future__ import annotations

import inspect

import pytest

from conftest import HOME, FakeNamecheap, settings_of
from plugin_platform_namecheap import ACCEPT, TYPES
from plugin_platform_namecheap import zone as zones
from plugin_platform_namecheap.api import NamecheapError
from plugin_platform_namecheap.zone import Refusal


def page_args(form: dict, values: dict, accepted=()) -> list:
    """What the platform's page sends for a form (platform.js argsOf): the fields' values in order, a field whose `when` is
    unmet or left empty null (the hook's default), a number as a number, an accept field true only once accepted."""
    now = {**{x["name"]: x.get("value") for x in form["fields"]}, **values}
    out = []
    for x in form["fields"]:
        if x["type"] == "accept":
            out.append(x["name"] in accepted)
            continue
        shown = all(str(now.get(k) or "") in [str(v) for v in vs] for k, vs in (x.get("when") or {}).items())
        v = now.get(x["name"])
        out.append(None if not shown or v in (None, "") else int(v) if x["type"] == "number" else v)
    return out


def records(fake, domain="hypokrites.me") -> list[tuple]:
    return [(h["name"], h["type"], h["address"]) for h in fake.zones[domain]["hosts"]]


def zone_table(status: dict, domain="hypokrites.me") -> dict:
    return next(t for t in status["tables"] if t["title"] == f"{domain} records")


def forms_of(status: dict) -> dict:
    return {f["id"]: f for f in status["forms"]}


def test_each_zone_shown_has_a_set_form_and_a_remove_on_each_record(made, env):
    env(settings_of())
    p, fake, _ = made()
    assert p.status()["forms"] == []  # nothing read yet: nothing to write over
    p.refresh()
    st = p.status()
    forms = forms_of(st)
    assert list(forms) == ["set:hypokrites.me", "remove:hypokrites.me"]  # example.net is not on Namecheap's DNS: not read
    hooks = p.interface()["hooks"]
    for f in forms.values():
        assert f["hook"] in hooks
        assert [x["name"] for x in f["fields"]] == list(inspect.signature(getattr(p, f["hook"])).parameters)  # in order
        assert all(x["type"] in ("text", "number", "choice", "fixed", "accept") for x in f["fields"])
        words = f["confirm"]["words"]  # the exact change named, and the backup made first
        assert "{host} {rtype} {address}" in words and "{domain}" in words and "saved to a backup first" in words
        assert "the mail setting (custom MX) are kept" in words and "Dynamic DNS" not in words  # no Dynamic DNS host here
        (accept,) = [x for x in f["fields"] if x["type"] == "accept"]
        assert accept["name"] == ACCEPT and accept["yes"] == "Write anyway" and "{domain}" in accept["words"]
    set_form, remove_form = forms.values()
    rtype = next(x for x in set_form["fields"] if x["name"] == "rtype")
    assert [c["value"] for c in rtype["choices"]] == ["A", "AAAA", "CNAME", "ALIAS", "TXT", "MX", "NS", "URL", "URL301", "FRAME"]
    assert set(TYPES) == zones.WRITABLE and all(c["note"] for c in rtype["choices"])  # MXE: not this zone's mail setting
    assert next(x for x in set_form["fields"] if x["name"] == "domain") == {"name": "domain", "label": "Domain", "type": "fixed",
                                                                             "value": "hypokrites.me"}
    assert next(x for x in set_form["fields"] if x["name"] == "mx")["when"] == {"rtype": ["MX"]}
    assert remove_form["confirm"]["danger"] is True and all(x["type"] in ("fixed", "accept") for x in remove_form["fields"])
    table = zone_table(st)
    assert table["actions"] == [{"form": "set:hypokrites.me", "title": "Set a record…"}] and table["columns"][-1] == {"title": ""}
    assert "set and removed here" in table["note"] and all(len(r) == len(table["columns"]) for r in table["rows"])
    removes = [r[-1] for r in table["rows"]]
    assert len(removes) == 7 and {(c["form"], c["title"]) for c in removes} == {("remove:hypokrites.me", "Remove")}
    assert {"form": "remove:hypokrites.me", "title": "Remove", "label": "Remove _dmarc TXT v=DMARC1; p=quarantine",
            "values": {"host": "_dmarc", "rtype": "TXT", "address": "v=DMARC1; p=quarantine"}} in removes
    assert [(c["values"]["host"], c["values"]["rtype"], c["values"]["address"]) for c in removes] == [tuple(r[:3]) for r in table["rows"]]
    assert len(fake.requests) and not any(c == "namecheap.domains.dns.setHosts" for c in fake.commands())  # drawn: nothing written


def test_the_page_sets_and_removes_a_record_with_every_other_record_and_the_mail_kept(made, env):
    env(settings_of())
    p, fake, _ = made()
    p.refresh()
    forms = forms_of(p.status())
    set_form, remove_form = forms["set:hypokrites.me"], forms["remove:hypokrites.me"]
    proton = records(fake)
    args = page_args(set_form, {"host": "home", "rtype": "A", "address": HOME, "ttl": "", "mx": "5"})
    assert args == ["hypokrites.me", "home", "A", HOME, None, None, False]  # MX preference hidden for an A record: not sent
    rep = p.ask(set_form["hook"], *args)
    assert rep["ok"] and rep["said"] == f"added home A {HOME}" and rep["lines"][0].startswith("backup: ")
    assert rep["lines"][1] == "read back: every record as written (8); the mail setting (custom MX) kept" and len(rep["lines"]) == 2
    assert records(fake) == [*proton, ("home", "A", HOME)] and fake.zones["hypokrites.me"]["email"] == "MX"
    # the page draws the zone as read after the write: home has its own Remove now
    removes = [r[-1]["values"] for r in zone_table(p.status())["rows"]]
    assert {"host": "home", "rtype": "A", "address": HOME} in removes and len(removes) == 8
    rep = p.ask(set_form["hook"], *page_args(set_form, {"host": "@", "rtype": "MX", "address": "mail3.example.org", "mx": "30"}))
    assert rep["ok"] and rep["said"] == "added @ MX mail3.example.org (pref 30)"
    rep = p.ask(set_form["hook"], *page_args(set_form, {"host": "home", "rtype": "A", "address": HOME}))
    assert rep["changed"] is False and rep["lines"] == [] and "nothing written" in rep["said"]  # there already
    # a row's Remove: the record named by its address, the host's other records kept (@ holds two TXT records)
    removes = [r[-1]["values"] for r in zone_table(p.status())["rows"]]
    verification = next(v for v in removes if v["address"] == "protonmail-verification=0123456789abcdef")
    assert verification == {"host": "@", "rtype": "TXT", "address": "protonmail-verification=0123456789abcdef"}
    assert page_args(remove_form, verification) == ["hypokrites.me", "@", "TXT", "protonmail-verification=0123456789abcdef", False]
    rep = p.ask(remove_form["hook"], *page_args(remove_form, verification))
    assert rep["ok"] and rep["said"] == "removed @ TXT protonmail-verification=0123456789abcdef"
    assert ("@", "TXT", "v=spf1 include:_spf.protonmail.ch ~all") in records(fake) and ("@", "MX", "mail.protonmail.ch.") in records(fake)
    rep = p.ask(remove_form["hook"], *page_args(remove_form, {"host": "home", "rtype": "A", "address": HOME}))
    assert rep["ok"] and ("home", "A", HOME) not in records(fake)
    # what the plugin refuses comes back in its words (the page says them), nothing written
    calls = len(fake.requests)
    with pytest.raises(ValueError, match="not an IPv4 address"):
        p.ask(set_form["hook"], *page_args(set_form, {"host": "home", "rtype": "A", "address": "not-an-ip"}))
    with pytest.raises(Refusal, match="no A record at home") as refused:
        p.ask(remove_form["hook"], *page_args(remove_form, {"host": "home", "rtype": "A", "address": HOME}))
    assert refused.value.accept is None  # nothing the user could accept
    assert "namecheap.domains.dns.setHosts" not in fake.commands()[calls:]


def test_a_zone_with_dynamic_dns_hosts_is_written_from_the_page_only_once_that_is_accepted(made, env):
    env(settings_of())
    fake = FakeNamecheap()
    fake.zones["hypokrites.me"]["hosts"].append({"name": "home", "type": "A", "address": HOME, "ddns": True})
    p, fake, _ = made(fake)
    p.refresh()
    forms = forms_of(p.status())
    set_form, remove_form = forms["set:hypokrites.me"], forms["remove:hypokrites.me"]
    for f in (set_form, remove_form):  # said before it is asked: the confirmation names them
        assert "has Dynamic DNS hosts (home): you are asked again" in f["confirm"]["words"]
    calls = len(fake.requests)
    with pytest.raises(Refusal, match=r"Dynamic DNS hosts \(home\)") as refused:  # the first confirmation is not enough
        p.ask(set_form["hook"], *page_args(set_form, {"host": "blog", "rtype": "A", "address": "93.184.216.35"}))
    assert refused.value.accept == ACCEPT  # the argument the page's second confirmation sets
    assert fake.commands()[calls:] == ["namecheap.domains.dns.getHosts"] and ("blog", "A", "93.184.216.35") not in records(fake)
    with pytest.raises(Refusal) as refused:
        p.ask(remove_form["hook"], *page_args(remove_form, {"host": "www", "rtype": "CNAME", "address": "parkingpage.namecheap.com."}))
    assert refused.value.accept == ACCEPT and ("www", "CNAME", "parkingpage.namecheap.com.") in records(fake)
    # accepted (the second confirmation): written, the report saying whether they kept it
    rep = p.ask(set_form["hook"], *page_args(set_form, {"host": "blog", "rtype": "A", "address": "93.184.216.35"}, accepted={ACCEPT}))
    assert rep["ok"] and rep["ddnsLost"] == [] and ("blog", "A", "93.184.216.35") in records(fake)
    fake.keep_ddns = False  # Namecheap turning the host plain: said in the report's words
    rep = p.ask(remove_form["hook"], *page_args(remove_form, {"host": "blog", "rtype": "A", "address": "93.184.216.35"}, accepted={ACCEPT}))
    assert rep["ddnsLost"] == ["home"] and any(line.startswith("Dynamic DNS turned off on home") for line in rep["lines"])


def test_a_zone_every_write_would_be_refused_has_no_form_and_says_why(made, env):
    env(settings_of())
    fake = FakeNamecheap()
    fake.zones["hypokrites.me"]["hosts"].append({"name": "@", "type": "CAA", "address": '0 issue "letsencrypt.org"'})
    p, fake, _ = made(fake)
    p.refresh()
    st = p.status()
    table = zone_table(st)
    assert st["forms"] == [] and "actions" not in table and len(table["columns"]) == 6
    assert table["note"].endswith("not written here: hypokrites.me holds CAA records, which setHosts cannot take back as they are: "
                                  "a write would lose them, so none is made (change them in Namecheap's dashboard)")
    assert all(not isinstance(c, dict) or "form" not in c for r in table["rows"] for c in r)


def test_a_write_that_fails_after_its_backup_names_the_backup(made, env, tmp_path):
    """A write answered with an error, or not read back, says where the zone as it was is saved and how to put it back
    (the page shows the failure in these words)."""
    env(settings_of())
    p, fake, _ = made()
    fake.fail["namecheap.domains.dns.setHosts"] = ("2050900", "Unknown error when setting hosts")
    with pytest.raises(NamecheapError) as failed:
        p.set_record("hypokrites.me", "home", "A", HOME)
    (backup,) = zones.backups(tmp_path / "backups", "hypokrites.me")
    words = str(failed.value)
    assert words.startswith(f"the write (added home A {HOME}) was answered with an error: ") and failed.value.number == "2050900"
    assert f"the zone as it was before is saved in {backup}" in words and f'restore hypokrites.me "{backup}"' in words
    del fake.fail["namecheap.domains.dns.setHosts"]
    api = p.client()
    real = api.set_hosts

    def written_then_unreadable(*a, **k):
        done = real(*a, **k)
        fake.fail["namecheap.domains.dns.getHosts"] = ("2019166", "Domain not found")
        return done
    api.set_hosts = written_then_unreadable
    with pytest.raises(NamecheapError, match="was sent, answered as a success, but the zone could not be read back") as failed:
        p.set_record("hypokrites.me", "home", "A", HOME)
    assert "the zone as it was before is saved in " in str(failed.value) and len(zones.backups(tmp_path / "backups")) == 2


def test_a_second_confirmation_counts_only_when_exactly_true():
    """0.3.1: a write over Dynamic DNS hosts is accepted only by an exactly true accept_ddns_reset; a "false" string or a
    1 from a local program is no acceptance."""
    import inspect

    import plugin_platform_namecheap as module

    source = inspect.getsource(module.NamecheapPlugin)
    assert source.count("accept_ddns_reset=accept_ddns_reset is True") == 2 and "bool(accept_ddns_reset)" not in source
