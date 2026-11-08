"""Dynamic DNS over the stand-ins: this network's address read of DNS (OpenDNS, else Google), each host's record read of
its domain's nameserver, an update sent only when they differ (or when asked), without the address at most every half
hour, a failed one tried again after half an hour; the answer read whatever its layout, without the password."""
from __future__ import annotations

import pytest

from conftest import CALLER, DDNS_PASSWORD, HOME, FakeDns, FakeNamecheap, ddns_error, ddns_ok
from plugin_platform_namecheap import ddns
from plugin_platform_namecheap.settings import parse, split_host


def config(hosts="home.hypokrites.me", password=DDNS_PASSWORD):
    return parse({"NAMECHEAP_DDNS_HOSTS": hosts, "NAMECHEAP_DDNS_PASSWORD": password})


def updater(fake, dns, t):
    return ddns.Updater(transport=fake, run=dns, clock=lambda: t[0])


def test_this_networks_address_is_read_of_opendns_else_google_and_never_a_private_one():
    fake = FakeNamecheap()
    assert ddns.public_ipv4(FakeDns(fake)) == HOME
    assert ddns.public_ipv4(FakeDns(fake, google=True)) == HOME  # OpenDNS has no answer: Google's text record
    assert ddns.public_ipv4(FakeDns(fake, public=None)) is None
    assert ddns.public_ipv4(FakeDns(fake, public="192.168.1.20")) is None
    linux = "Server:\t\t127.0.0.53\nAddress:\t127.0.0.53#53\n\nNon-authoritative answer:\nName:\tmyip.opendns.com\nAddress: 93.184.216.34\n"
    assert ddns.answer_addresses(linux) == ["93.184.216.34"]
    assert ddns.nameservers_in("hypokrites.me\tnameserver = dns1.registrar-servers.com.\n") == ["dns1.registrar-servers.com"]
    asked = FakeDns(fake)
    ddns.public_ipv4(asked)
    assert asked.calls[0] == ("myip.opendns.com", "A", "208.67.222.222")  # the resolver by its IPv4 address


def test_an_update_is_sent_only_when_the_record_differs_and_then_holds_the_address():
    fake, t = FakeNamecheap(), [1_000_000.0]
    dns = FakeDns(fake)
    up = updater(fake, dns, t)
    [first] = up.run_pass(config())
    assert first["ok"] and first["result"] == f"updated to {HOME}" and first["address"] == HOME and first["updatedAt"] == t[0]
    sent = [r for r in fake.requests if "dynamicdns" in r["url"]]
    assert len(sent) == 1 and sent[0]["query"] == {"host": "home", "domain": "hypokrites.me", "password": DDNS_PASSWORD, "ip": HOME}
    assert ("home.hypokrites.me", "A", "dns1.registrar-servers.com") in dns.calls  # the record of the domain's own nameserver
    t[0] += 300
    [again] = up.run_pass(config())
    assert again["result"] == "unchanged" and again["updatedAt"] == 1_000_000.0 and len(fake.requests) == 1
    dns.public = "93.184.216.40"  # the network's address moved
    t[0] += 300
    [moved] = up.run_pass(config())
    assert moved["result"] == "updated to 93.184.216.40" and fake.ddns_records["home.hypokrites.me"] == "93.184.216.40"
    [forced] = up.run_pass(config(), force=True)
    assert forced["ok"] and len(fake.requests) == 3  # sent though nothing differs


def test_without_the_address_an_update_goes_without_it_at_most_every_half_hour():
    fake, t = FakeNamecheap(), [1_000_000.0]
    up = updater(fake, FakeDns(fake, public=None), t)
    [h] = up.run_pass(config("@.hypokrites.me"))
    sent = [r["query"] for r in fake.requests]
    assert sent == [{"host": "@", "domain": "hypokrites.me", "password": DDNS_PASSWORD}]  # no ip=: the request's own address
    assert h["ok"] and h["address"] == CALLER and "the address the request came from" in h["result"]
    t[0] += 600
    [h] = up.run_pass(config("@.hypokrites.me"))
    assert len(fake.requests) == 1 and "could not be found" in h["result"]
    t[0] += ddns.RETRY_S
    up.run_pass(config("@.hypokrites.me"))
    assert len(fake.requests) == 2


def test_a_failed_update_says_why_without_the_password_and_waits_half_an_hour():
    fake, t = FakeNamecheap(), [1_000_000.0]
    fake.ddns_password = "another-password-entirely"
    up = updater(fake, FakeDns(fake), t)
    [h] = up.run_pass(config())
    assert h["ok"] is False and h["result"].startswith("failed: Passwords do not match (NAMECHEAP_DDNS_PASSWORD is the domain's")
    t[0] += 300
    [h] = up.run_pass(config())
    assert len(fake.requests) == 1 and "tried again after" in h["result"]
    t[0] += ddns.RETRY_S
    up.run_pass(config())
    assert len(fake.requests) == 2
    [h] = updater(fake, FakeDns(fake), t).run_pass(config("home.hypokrites.me", "example.com=abc;other.org=def"))
    assert h["ok"] is False and "no Dynamic DNS password for hypokrites.me" in h["result"]


@pytest.mark.parametrize("body, ok, said", [
    (ddns_ok("93.184.216.34"), True, "updated to 93.184.216.34"),
    (ddns_error("No Records updated. A record not Found;"), False,
     "No Records updated. A record not Found; (the host must be an A + Dynamic DNS Record"),
    (ddns_error("Domain name not active"), False, "Domain name not active (Dynamic DNS must be on for the domain"),
    (b"<interface-response><ErrCount>1</ErrCount><errors><Err1>Invalid IP</Err1></errors><Done>true</Done>", False, "Invalid IP"),
    (b"<html>Bad Gateway password=" + DDNS_PASSWORD.encode() + b"</html>", False, "an answer it could not read (HTTP 200): <html>Bad Gateway password=***"),
])
def test_the_answer_is_read_whatever_its_layout(body, ok, said):
    a = ddns.parse_update(body, 200, (DDNS_PASSWORD,))
    assert a.ok is ok and a.said.startswith(said) and DDNS_PASSWORD not in a.said


def test_hosts_are_split_into_host_and_domain_and_passwords_by_domain():
    assert split_host("home.hypokrites.me") == ddns.DdnsHost("home", "hypokrites.me")
    assert split_host("@.Example.com.") == ddns.DdnsHost("@", "Example.com")  # the domain's letter case kept for Namecheap
    assert split_host("*.example.com").host == "*" and split_host("example.com").fqdn == "example.com"
    assert split_host("a.b.example.co.uk") == ddns.DdnsHost("a.b", "example.co.uk")
    assert split_host("vpn.home.example.com", known=["home.example.com"]) == ddns.DdnsHost("vpn", "home.example.com")
    for wrong in ("localhost", "@.a.example.com", "bad host.example.com", ""):
        with pytest.raises(ValueError):
            split_host(wrong)
    c = config("home.hypokrites.me, @.example.com ; nope", "hypokrites.me=one;example.com=two")
    found, wrong = c.ddns_hosts()
    assert [h.fqdn for h in found] == ["home.hypokrites.me", "example.com"] and len(wrong) == 1
    assert c.password_for("Hypokrites.me") == "one" and c.password_for("example.com") == "two" and c.password_for("x.org") is None
    assert config(password="justone").password_for("anything.net") == "justone"
    assert parse({"NAMECHEAP_DDNS_PASSWORD": "a=b=c;nope"}).problems  # neither one password nor domain=password pairs
