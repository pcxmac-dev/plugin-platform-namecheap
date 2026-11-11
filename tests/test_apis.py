"""What the plugin attaches to (plugin API 2.2; the user, 2026-11-11: "each plugin should reflect the the API its attached
to, and present links that provide documentation"): its cards are sound; the API card holds every command group and
command of Namecheap's methods page, and names as used exactly the commands the plugin sends (read from the stand-in
Namecheap as it sends them, and from its client's own command strings), none that spends; the Dynamic DNS card names the
update it sends; its facts ask nothing; and, with LIMINAL_VENDOR_PAGES=1 alone, every address on them answers (Namecheap's
pages refuse automated readers with 403, which counts as there; they were read in a browser on 2026-11-11)."""
from __future__ import annotations

import inspect
import os
import re
import urllib.parse

import pytest

import plugin_platform_namecheap as nc
import plugin_platform_namecheap.api as api_mod
from conftest import HOME, settings_of
from liminal_libs.sources import apis as A
from liminal_libs.sources.conformance import problems
from plugin_platform_namecheap import apis as cards


def card(name: str) -> A.Api:
    return next(a for a in nc.MACHINE.apis if a.name == name)


def flows(made, env):
    """The plugin doing everything it does with Namecheap: the account read, domains and records read again, a name
    checked, the balance read, a record set and removed, a Dynamic DNS pass. Every request, as sent."""
    env(settings_of(ddns=True))
    p, fake, dns = made()
    p.refresh()
    p.domains()
    p.hosts("hypokrites.me")
    p.availability("example.org", "hypokrites.dev")
    p.balance()
    p.set_record("hypokrites.me", "home", "A", HOME)
    p.ddns_update()
    p.remove_record("hypokrites.me", "home", "A", None, True)
    return p, fake


def test_its_cards_are_sound_and_written_for_plugin_api_2_2():
    p = nc.MACHINE
    assert p.api == "2.2" and problems(p) == [] and A.problems(p.apis) == []
    assert [a.name for a in p.apis] == [cards.API, cards.DDNS]
    for a in p.apis:
        assert a.verified == "2026-11-11" and a.docs.startswith("https://www.namecheap.com/support/") and a.used and a.covered
        assert all(c.area in {x.name for x in a.areas} for c in a.calls), a.name
        assert len(a.areas) > len(a.covered)  # more of the API than the plugin uses
    assert len(card(cards.API).calls) > len(card(cards.API).used)
    # its settings' page and its limits, as before
    assert p.signup == "https://www.namecheap.com/support/api/intro/" and p.limits.startswith("Namecheap's API: about 20 requests")


def test_the_api_card_holds_every_command_group_and_command():
    api = card(cards.API)
    assert [a.name for a in api.areas] == ["domains", "domains.dns", "domains.ns", "domains.transfer", "ssl", "users",
                                           "users.address", "domainprivacy"]
    assert len(api.calls) == 59 and len({c.name for c in api.calls}) == 59  # the methods page's, each once
    assert all(c.name.startswith(("namecheap.domains.", "namecheap.ssl.", "namecheap.users.", "namecheap.whoisguard."))
               for c in api.calls)
    assert all(c.docs.startswith("https://www.namecheap.com/support/api/methods/") for c in api.calls)
    counts = {a.name: sum(1 for c in api.calls if c.area == a.name) for a in api.areas}
    assert counts == {"domains": 11, "domains.dns": 7, "domains.ns": 4, "domains.transfer": 4, "ssl": 13, "users": 9,
                      "users.address": 6, "domainprivacy": 5}
    spends = {c.name for c in api.calls if c.costs}
    assert spends == {"namecheap.domains.create", "namecheap.domains.reactivate", "namecheap.domains.renew",
                      "namecheap.domains.transfer.create", "namecheap.ssl.create", "namecheap.ssl.renew",
                      "namecheap.ssl.purchasemoresans", "namecheap.users.createaddfundsrequest", "namecheap.whoisguard.renew"}
    assert all(c.writes for c in api.calls if c.costs)


def test_the_cards_name_every_call_the_plugin_makes_and_no_other(made, env):
    p, fake = flows(made, env)
    sent = set(fake.commands())
    used = {c.name for c in card(cards.API).used}
    assert sent == used, sent ^ used
    written = set(re.findall(r'"(namecheap\.[A-Za-z.]+)"', inspect.getsource(api_mod)))  # its client's own commands
    assert written == used, written ^ used
    assert {c.name for c in card(cards.API).used if c.writes} == {"namecheap.domains.dns.setHosts"}
    assert not any(c.costs for a in nc.MACHINE.apis for c in a.used)  # nothing that spends
    updates = [r for r in fake.requests if r["url"].startswith("https://dynamicdns.park-your-domain.com/")]
    assert updates and {r["method"] for r in updates} == {"GET"}
    (call,) = card(cards.DDNS).used
    method, _, target = call.name.partition(" ")
    path, _, query = target.partition("?")
    assert method == "GET" and urllib.parse.urlsplit(card(cards.DDNS).base).path == path
    asked = {k for r in updates for k in r["params"]}
    assert set(urllib.parse.parse_qs(query)) == asked, asked  # host, domain, password, ip: as the knowledge base gives them


def test_its_facts_say_what_it_learned_and_ask_nothing(made, env):
    env(settings_of(ddns=True))
    fresh, _, _ = made()
    assert fresh.api_facts() == {}  # nothing learned yet
    p, fake = flows(made, env)
    before = len(fake.requests)
    facts = A.facts_of(p)
    assert len(fake.requests) == before  # asked nothing to answer
    api = facts[cards.API]
    assert "this minute" in api["Requests"] and api["Environment"] == "production"
    assert api["Domains"] == "2 (1 on Namecheap's DNS, 1 read)" and api["Balance"] == "12.34 USD"
    assert facts[cards.DDNS]["This network's address"].startswith(HOME)
    assert "home.hypokrites.me" in facts[cards.DDNS]


@pytest.mark.skipif(os.environ.get("LIMINAL_VENDOR_PAGES") != "1", reason="reaches the makers' pages: LIMINAL_VENDOR_PAGES=1")
def test_every_address_on_its_cards_answers(monkeypatch):
    monkeypatch.undo()  # this test alone reaches the network (conftest refuses it to every other)
    assert A.dead_links(nc.MACHINE.apis) == []
