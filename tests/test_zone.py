"""Records written as setHosts allows (the whole zone at once): every other record and the mail setting kept (the user's
Proton mail: MX, SPF, DKIM, DMARC), a backup first, the zone read again and checked; the refusals made before anything is
sent; a backup put back."""
from __future__ import annotations

import json

import pytest

from conftest import KEY, FakeNamecheap
from plugin_platform_namecheap import zone as zones
from plugin_platform_namecheap.api import Limiter, NamecheapApi, Record, Zone
from plugin_platform_namecheap.zone import Refusal


def client(fake) -> NamecheapApi:
    return NamecheapApi("tester", KEY, transport=fake, limiter=Limiter(windows=((60.0, 1000),)), client_ip="93.184.216.34")


def records(fake, domain="hypokrites.me") -> list[tuple]:
    return [(h["name"], h["type"], h["address"]) for h in fake.zones[domain]["hosts"]]


def test_a_record_set_keeps_every_other_record_and_the_mail_setting(tmp_path):
    fake = FakeNamecheap()
    before = records(fake)
    report, after = zones.write(client(fake), "hypokrites.me", lambda z: zones.plan_set(z, "home", "A", "93.184.216.34", ttl=300),
                                tmp_path, clock=lambda: 1_800_000_000.0)
    assert records(fake) == [*before, ("home", "A", "93.184.216.34")] and fake.zones["hypokrites.me"]["email"] == "MX"
    assert report["ok"] and report["changed"] and report["success"] and report["missing"] == [] and report["unexpected"] == []
    assert report["said"] == "added home A 93.184.216.34" and report["emailType"] == "MX" and report["records"] == 8
    assert fake.commands() == ["namecheap.domains.dns.getHosts", "namecheap.domains.dns.setHosts", "namecheap.domains.dns.getHosts"]
    saved = json.loads(open(report["backup"], encoding="utf-8").read())  # the zone as it was, before the write
    assert saved["domain"] == "hypokrites.me" and saved["emailType"] == "MX" and len(saved["records"]) == 7
    assert report["backup"].endswith("hypokrites.me-20270115T080000Z.json") and "restore hypokrites.me" in report["restore"]
    assert isinstance(after, Zone) and len(after.records) == 8


def test_set_replaces_a_single_record_adds_beside_many_and_says_so(tmp_path):
    fake = FakeNamecheap()
    fake.zones["hypokrites.me"]["hosts"].append({"name": "home", "type": "A", "address": "93.184.216.1", "ttl": 600})
    c = client(fake)
    rep, _ = zones.write(c, "hypokrites.me", lambda z: zones.plan_set(z, "HOME.hypokrites.me", "a", "93.184.216.34"), tmp_path)
    assert rep["said"] == "set home A 93.184.216.34 (it was 93.184.216.1)"
    home = [h for h in fake.zones["hypokrites.me"]["hosts"] if h["name"] == "home"]
    assert [(h["address"], h["ttl"]) for h in home] == [("93.184.216.34", 600)]  # its TTL kept
    rep, _ = zones.write(c, "hypokrites.me", lambda z: zones.plan_set(z, "@", "TXT", "google-site-verification=abc"), tmp_path)
    assert rep["said"].startswith("added @ TXT") and len([h for h in fake.zones["hypokrites.me"]["hosts"] if h["type"] == "TXT"]) == 4
    rep, _ = zones.write(c, "hypokrites.me", lambda z: zones.plan_set(z, "@", "MX", "mail3.example.org", mx=30), tmp_path)
    assert ("@", "MX", "mail3.example.org") in records(fake) and rep["said"] == "added @ MX mail3.example.org (pref 30)"
    calls = len(fake.requests)
    rep, _ = zones.write(c, "hypokrites.me", lambda z: zones.plan_set(z, "home", "A", "93.184.216.34"), tmp_path)
    assert not rep["changed"] and "nothing written" in rep["said"] and len(fake.requests) == calls + 1  # read alone


def test_remove_takes_one_record_and_asks_which_among_several(tmp_path):
    fake = FakeNamecheap()
    c = client(fake)
    with pytest.raises(Refusal, match="has 2 TXT records at @: name the one"):
        zones.write(c, "hypokrites.me", lambda z: zones.plan_remove(z, "@", "TXT"), tmp_path)
    rep, _ = zones.write(c, "hypokrites.me", lambda z: zones.plan_remove(z, "@", "TXT", "protonmail-verification=0123456789abcdef"), tmp_path)
    assert rep["ok"] and rep["said"] == "removed @ TXT protonmail-verification=0123456789abcdef"
    assert ("@", "TXT", "v=spf1 include:_spf.protonmail.ch ~all") in records(fake) and len(records(fake)) == 6
    with pytest.raises(Refusal, match="no CNAME record at blog"):
        zones.write(c, "hypokrites.me", lambda z: zones.plan_remove(z, "blog", "CNAME"), tmp_path)
    rep, _ = zones.write(c, "hypokrites.me", lambda z: zones.plan_remove(z, "www", "cname"), tmp_path)
    assert rep["ok"] and ("www", "CNAME", "parkingpage.namecheap.com.") not in records(fake)


@pytest.mark.parametrize("change, words", [
    (lambda f: f.zones["hypokrites.me"].update(email=None), "did not say hypokrites.me's mail setting"),
    (lambda f: f.zones["hypokrites.me"]["hosts"].append({"name": "@", "type": "CAA", "address": '0 issue "letsencrypt.org"'}), "holds CAA records"),
    (lambda f: f.zones["hypokrites.me"]["hosts"].append({"name": "_sip._tcp", "type": "SRV", "address": "10 5 5060 sip.example.org"}), "holds SRV records"),
    (lambda f: f.zones["hypokrites.me"]["hosts"].append({"name": "old", "type": "A", "address": "93.184.216.2", "active": False}), "turned off (old)"),
    (lambda f: f.zones["hypokrites.me"].update(hosts=[]), "read back empty"),
    (lambda f: f.zones["hypokrites.me"]["hosts"].append({"name": "home", "type": "A", "address": "127.0.0.1", "ddns": True}), "Dynamic DNS hosts (home)"),
])
def test_what_a_write_could_lose_refuses_it_before_anything_is_sent(tmp_path, change, words):
    fake = FakeNamecheap()
    change(fake)
    with pytest.raises(Refusal, match=words.replace("(", r"\(").replace(")", r"\)")):
        zones.write(client(fake), "hypokrites.me", lambda z: zones.plan_set(z, "blog", "A", "93.184.216.34"), tmp_path)
    assert fake.commands() == ["namecheap.domains.dns.getHosts"] and not list(tmp_path.iterdir())  # read alone, nothing saved


@pytest.mark.parametrize("args, words", [
    (("@", "CNAME", "example.org"), "cannot stand for the domain itself"),
    (("www", "A", "93.184.216.34"), "www is a CNAME"),
    (("protonmail._domainkey", "TXT", "x"), "is a CNAME"),
    (("@", "CAA", '0 issue "x"'), "CAA records are not written"),
    (("home", "A", "not-an-ip"), "not an IPv4 address"),
    (("home", "AAAA", "93.184.216.34"), "not an IPv6 address"),
    (("go", "URL", "ftp://x"), "http or https"),
    (("bad host!", "A", "93.184.216.34"), "is not a host"),
    (("@", "TXT", "two\nlines"), "one line"),
])
def test_a_record_set_wrong_is_refused_before_anything_is_sent(args, words):
    z = Zone("hypokrites.me", "MX", True, tuple(Record(h["name"], h["type"], h["address"], mxpref=h.get("mxpref", 10))
                                                for h in FakeNamecheap().zones["hypokrites.me"]["hosts"]))
    with pytest.raises(ValueError, match=words):
        zones.plan_set(z, *args)
    with pytest.raises(ValueError, match="the TTL is 60 to 60000"):
        zones.plan_set(z, "home", "A", "93.184.216.34", ttl=30)
    with pytest.raises(ValueError, match="an MX record's alone"):
        zones.plan_set(z, "home", "A", "93.184.216.34", mx=5)


def test_mx_records_are_written_only_with_the_custom_mx_setting(tmp_path):
    fake = FakeNamecheap()
    fake.zones["hypokrites.me"]["email"] = "FWD"
    fake.zones["hypokrites.me"]["hosts"] = [h for h in fake.zones["hypokrites.me"]["hosts"] if h["type"] != "MX"]
    with pytest.raises(Refusal, match="mail setting is FWD: MX records are its mail only with Custom MX"):
        zones.write(client(fake), "hypokrites.me", lambda z: zones.plan_set(z, "@", "MX", "mail.example.org"), tmp_path)
    rep, _ = zones.write(client(fake), "hypokrites.me", lambda z: zones.plan_set(z, "home", "A", "93.184.216.34"), tmp_path)
    assert rep["ok"] and fake.zones["hypokrites.me"]["email"] == "FWD"  # forwarding kept as it was


def test_the_check_after_a_write_says_what_was_lost_and_how_to_put_it_back(tmp_path):
    fake = FakeNamecheap()
    fake.zones["hypokrites.me"]["hosts"].append({"name": "home", "type": "A", "address": "93.184.216.34", "ddns": True})
    fake.keep_ddns, fake.drop_on_write = False, "v=DMARC1; p=quarantine"
    rep, after = zones.write(client(fake), "hypokrites.me", lambda z: zones.plan_set(z, "blog", "A", "93.184.216.35"), tmp_path,
                             accept_ddns_reset=True)
    assert not rep["ok"] and rep["missing"] == ["_dmarc TXT v=DMARC1; p=quarantine"] and rep["ddnsLost"] == ["home"]
    assert rep["unexpected"] == [] and 'restore hypokrites.me "' in rep["restore"]
    fake.drop_on_write = None
    back, _ = zones.restore(client(fake), "hypokrites.me", rep["backup"], tmp_path)
    assert back["ok"] and ("_dmarc", "TXT", "v=DMARC1; p=quarantine") in records(fake) and ("blog", "A", "93.184.216.35") not in records(fake)
    assert back["dropped"] == ["blog A 93.184.216.35"] and back["said"].startswith("put back the 8 records of")
    assert len(zones.backups(tmp_path, "hypokrites.me")) == 2  # the zone before the restore was saved too
    with pytest.raises(Refusal, match="a backup of hypokrites.me, not of example.net"):
        zones.restore(client(fake), "example.net", rep["backup"], tmp_path)
    (tmp_path / "x.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="not a zone backup"):
        zones.load_backup(tmp_path / "x.json")


def test_a_domain_not_on_namecheaps_dns_is_not_written(tmp_path):
    z = Zone("example.net", "MX", False, (Record("@", "A", "93.184.216.34"),))
    with pytest.raises(Refusal, match="not on Namecheap's DNS"):
        zones.check_writable(z)
    assert zones.host_name("example.net", "example.net") == "@" and zones.host_name("*.Example.NET", "example.net") == "*"
    assert zones.same((Record("@", "CNAME", "A.example.org."),), (Record("@", "CNAME", "a.example.org"),))
