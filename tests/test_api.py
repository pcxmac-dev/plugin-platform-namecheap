"""The API client over the stand-in: the answers read whatever their namespace and case, the errors in words without the
key, the limits kept, setHosts by POST with every record and the mail setting, a misread zone never taken for an empty one."""
from __future__ import annotations

import pytest

from conftest import KEY, NS, FakeNamecheap, api_xml, error_xml
from plugin_platform_namecheap import api
from plugin_platform_namecheap.api import Limiter, NamecheapApi, NamecheapError, Record, scrub


def client(fake, **more) -> NamecheapApi:
    return NamecheapApi("tester", KEY, transport=fake, limiter=Limiter(windows=((60.0, 1000),)), ip_of=lambda: "93.184.216.34", **more)


def test_the_answers_are_read_by_their_local_names_in_any_case_and_namespace():
    fake = FakeNamecheap()
    for ns, lower in ((NS, True), ("https://api.namecheap.com/xml.response", False), ("", True)):
        fake.namespace, fake.lowercase_hosts = ns, lower
        z = client(fake).hosts("hypokrites.me")
        assert z.domain == "hypokrites.me" and z.email_type == "MX" and z.using_our_dns is True and len(z.records) == 7
        mx = [r for r in z.records if r.type == "MX"]
        assert [(r.address, r.mxpref) for r in mx] == [("mail.protonmail.ch.", 10), ("mailsec.protonmail.ch.", 20)]
        assert all(r.active is True and r.ddns is False and r.ttl == 1799 for r in z.records)
    q = fake.requests[-1]["query"]
    assert q["Command"] == "namecheap.domains.dns.getHosts" and (q["SLD"], q["TLD"]) == ("hypokrites", "me")
    assert (q["ApiUser"], q["UserName"], q["ClientIp"]) == ("tester", "tester", "93.184.216.34") and fake.requests[-1]["method"] == "GET"


def test_a_zone_whose_hosts_are_not_where_they_are_read_is_never_taken_for_an_empty_one():
    def misplaced(method, url, query, form, timeout):  # the host elements outside the result: a layout not expected
        return 200, api_xml("namecheap.domains.dns.getHosts", '<DomainDNSGetHostsResult Domain="a.com" EmailType="MX" '
                            'IsUsingOurDNS="true" /><Other><host Name="@" Type="A" Address="1.2.3.4" /></Other>')
    with pytest.raises(NamecheapError, match="1 host elements and 0 were read"):
        client(misplaced).hosts("a.com")


def test_errors_say_what_to_do_in_namecheaps_words_too_and_never_hold_the_key():
    fake = FakeNamecheap()
    fake.error = ("1011150", f"Parameter RequestIP is invalid (ApiKey={KEY})")
    with pytest.raises(NamecheapError) as e:
        client(fake).domains()
    assert e.value.number == "1011150" and e.value.refused and "not whitelisted" in str(e.value)
    assert "Namecheap 1011150: Parameter RequestIP is invalid" in str(e.value) and KEY not in str(e.value)
    fake.error = ("2019166", "Domain not found")
    with pytest.raises(NamecheapError, match="the domain is not found") as e:
        client(fake).hosts("nobody.com")
    assert not e.value.refused
    wrong = NamecheapApi("tester", "a-wrong-key-of-length", transport=fake, limiter=Limiter(windows=((60.0, 10),)), client_ip="93.184.216.34")
    fake.error = None
    with pytest.raises(NamecheapError, match="API key is missing or refused") as e:
        wrong.domains()
    assert e.value.number == "1011102" and "a-wrong-key-of-length" not in str(e.value)

    def broken(method, url, query, form, timeout):
        raise OSError(f"[Errno 11001] getaddrinfo failed for {url}?ApiKey={query['ApiKey']}")
    with pytest.raises(NamecheapError, match="could not be reached") as e:
        client(broken).domains()
    assert KEY not in str(e.value) and e.value.number == "network"

    def html(method, url, query, form, timeout):
        return 503, b"<html><body>Service Unavailable</body>"
    with pytest.raises(NamecheapError, match="HTTP 503 and no XML"):
        client(html).domains()


def test_scrub_takes_out_the_secrets_and_any_key_or_password_in_a_query():
    assert scrub(f"x {KEY} y", [KEY]) == "x *** y"
    assert scrub("GET /update?host=@&password=abcdef123&ip=1.2.3.4") == "GET /update?host=@&password=***&ip=1.2.3.4"
    assert scrub("ApiUser=me&ApiKey=zzz&x=1") == "ApiUser=me&ApiKey=***&x=1"


def test_the_client_ip_is_the_one_set_else_this_networks_and_without_either_nothing_is_asked():
    fake = FakeNamecheap()
    NamecheapApi("tester", KEY, client_ip="198.51.100.7", transport=fake, limiter=Limiter(windows=((60.0, 10),))).domains()
    assert fake.requests[-1]["query"]["ClientIp"] == "198.51.100.7"
    lost = NamecheapApi("tester", KEY, transport=fake, limiter=Limiter(windows=((60.0, 10),)), ip_of=lambda: None)
    before = len(fake.requests)
    with pytest.raises(NamecheapError, match="NAMECHEAP_CLIENT_IP") as e:
        lost.domains()
    assert e.value.number == "ip" and len(fake.requests) == before


def test_the_domains_come_a_page_at_a_time_until_all_are_read():
    fake = FakeNamecheap()
    fake.domains = [{**fake.domains[0], "ID": str(i), "Name": f"d{i:03}.com"} for i in range(230)]
    found = client(fake).domains()
    assert len(found) == 230 and found[0]["name"] == "d000.com" and found[-1]["name"] == "d229.com"
    pages = [r["query"] for r in fake.requests]
    assert [(p["Page"], p["PageSize"], p["ListType"]) for p in pages] == [("1", "100", "ALL"), ("2", "100", "ALL"), ("3", "100", "ALL")]
    d = found[0]
    assert (d["expires"], d["autoRenew"], d["ourDns"], d["locked"], d["privacy"]) == ("05/01/2027", True, True, False, "ENABLED")


def test_set_hosts_posts_every_record_with_the_mail_setting_and_the_keys_in_the_query_only():
    fake = FakeNamecheap()
    c = client(fake)
    z = c.hosts("hypokrites.me")
    assert c.set_hosts("hypokrites.me", z.records, z.email_type) is True
    sent = fake.requests[-1]
    assert sent["method"] == "POST" and sent["query"]["Command"] == "namecheap.domains.dns.setHosts" and sent["query"]["ApiKey"] == KEY
    form = sent["form"]
    assert "ApiKey" not in form and form["EmailType"] == "MX" and (form["SLD"], form["TLD"]) == ("hypokrites", "me")
    assert [form[f"RecordType{i}"] for i in range(1, 8)] == ["MX", "MX", "TXT", "TXT", "TXT", "CNAME", "CNAME"] and "HostName8" not in form
    assert (form["HostName2"], form["Address2"], form["MXPref2"], form["TTL2"]) == ("@", "mailsec.protonmail.ch.", "20", "1799")
    with pytest.raises(ValueError, match="empty the zone"):
        c.set_hosts("hypokrites.me", (), "MX")
    with pytest.raises(ValueError, match="EmailType"):
        c.set_hosts("hypokrites.me", z.records, "")


def test_availability_reads_only_and_takes_at_most_fifty():
    fake = FakeNamecheap()
    found = client(fake).availability(["free-one.com", "taken.com", "free-premium.io"])
    assert [(a["domain"], a["available"], a["premium"]) for a in found] == [("free-one.com", True, False), ("taken.com", False, False),
                                                                           ("free-premium.io", True, True)]
    assert found[2]["premiumPrice"] == "13000.0000" and fake.requests[-1]["query"]["DomainList"] == "free-one.com,taken.com,free-premium.io"
    with pytest.raises(ValueError, match="at most 50"):
        client(fake).availability([f"n{i}.com" for i in range(51)])
    with pytest.raises(ValueError, match="not a domain name"):
        client(fake).availability(["not a domain"])
    b = client(fake).balances()
    assert (b["available"], b["currency"], b["autoRenew"]) == ("12.34", "USD", "0.00")


def test_the_limiter_waits_for_room_and_refuses_a_wait_too_long():
    t, slept = [1000.0], []

    def sleep(s):
        slept.append(s)
        t[0] += s
    lim = Limiter(windows=((60.0, 3), (3600.0, 5)), clock=lambda: t[0], sleep=sleep, max_wait=120.0)
    for _ in range(3):
        lim.acquire()
    assert slept == []
    lim.acquire()  # the fourth in the minute waits until the first leaves it
    assert slept == [60.0] and [n for _, n, _ in lim.used()] == [1, 4]
    lim.acquire()
    with pytest.raises(NamecheapError, match="the next request may go in") as e:  # the hour's five used: an hour's wait
        lim.acquire()
    assert e.value.number == "limit"
    assert "20 a minute, 700 an hour, 8,000 a day" == api.Limiter().describe()


def test_records_round_trip_through_their_dicts_and_domains_are_split_as_namecheap_asks():
    r = Record("home", "A", "93.184.216.34", 300, 10, "7", True, True, "", "")
    assert Record.from_dict(r.as_dict()) == r
    assert api.split_domain("Hypokrites.ME.") == ("hypokrites", "me") and api.split_domain("example.co.uk") == ("example", "co.uk")
    with pytest.raises(ValueError):
        api.split_domain("localhost")
    assert api.answer_of(error_xml("1", "x").replace(b'Status="ERROR"', b'Status="OK"'), 200, "c") is not None
