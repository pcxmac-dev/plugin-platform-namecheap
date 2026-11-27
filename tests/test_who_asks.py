"""Who may ask the plugin's changes and whether a name is free (0.3.4; the independent review's PLT-H1 and the sweep of
the plugins after it, 2026-11-25; 0.3.5, the user's choice of 2026-11-25: availability, which sends names of the asker's
choosing to Namecheap under the API key, the page's too). Its changes are asked only from its page (PAGE_ONLY_HOOKS, as
liminal-libs 1.66.0's apps/asking.py and liminal-platform 0.34.0 read them): a record set or removed in a domain's zone,
and a Dynamic DNS pass. Another plugin's ask is refused, and so is an ask that names no one; over HTTP the platform also
asks its login whether you are at the page. Before, any program on this PC asked them of the platform with a header
anyone can send, and the API key did the rest: the domain itself pointed at an address of the asker's, its SPF record
removed, each with no second question (the one there is, for a zone with Dynamic DNS hosts, is only an argument). Its
reads are asked only from its page too since 0.3.7 (closed by default: the account's key makes them; `present` and
`status` alone are anyone's): the account, a domain's records and the balance. A status another plugin asks holds none
of those (0.3.8). Asked through the library's own
App (its ask names who asks as the platform's does), over the stand-in Namecheap and the stand-in resolver: nothing
reaches Namecheap, a resolver or the network."""
from __future__ import annotations

import pytest

pytest.importorskip("liminal_libs.apps.asking", reason="no hook is asked only from its page before liminal-libs 1.66.0")

from conftest import HOME, settings_of  # noqa: E402 - after the skip, as each of these
from liminal_libs import internal  # noqa: E402
from liminal_libs.apps import App, EnvironmentLogin, asking  # noqa: E402
from liminal_libs.machines.plugin import MachinePlugin  # noqa: E402
from plugin_platform_namecheap import MACHINE  # noqa: E402

CHANGES = ("set_record", "remove_record", "ddns_update")
SENT_FOR_ANYONE = ("availability", "check_names")  # check_names: the page's Check a name form (0.3.6)  # a read that sends the asker's words to Namecheap: the page's alone since 0.3.5
READS = ("present", "status", "refresh", "domains", "hosts", "balance")
# 0.3.7, closed by default (the user, 2026-11-26: "Page-only"): the reads made with the account's key are its
# page's alone too; the contract's own two stay anyone's
OPEN_READS = ("present", "status")
PAGE_READS = tuple(h for h in READS if h not in OPEN_READS)
READ_ARGS = {'hosts': ('hypokrites.me',)}  # the argument a read takes, as another program words it
SET_HOSTS = "namecheap.domains.dns.setHosts"  # the one command that writes a zone (all of it)
ASKED = {  # each change as another program worded it: the hook's arguments
    "set_record": ("hypokrites.me", "@", "A", "203.0.113.99"),  # the domain itself, pointed at an address of the asker's
    "remove_record": ("hypokrites.me", "@", "TXT", "v=spf1 include:_spf.protonmail.ch ~all"),  # its mail's SPF record
    "ddns_update": (),
}
SENT = [SET_HOSTS, SET_HOSTS, "a Dynamic DNS update"]  # what the same asks send from the page, in CHANGES' order


def writes(fake) -> list[str]:
    """The requests that change something: a zone written, and a Dynamic DNS update (which is no API command)."""
    return [r["params"].get("Command") or "a Dynamic DNS update" for r in fake.requests
            if r["params"].get("Command") in (None, SET_HOSTS)]


class Neighbour(MachinePlugin):
    """Another plugin of the platform, asking Namecheap's through its app as any plugin may (a container plugin, or the
    MCP plugin for a local agent)."""

    name, title = "neighbour", "Neighbour"

    def wants(self, hook, *args):
        """Not a hook: one of Namecheap's asked through the app."""
        return self.app.ask("namecheap", hook, *args)


class Platform(App):
    """The library's App asking as the platform does: from its page's route, the page named in so many words, or from
    its own code, no one named. It holds the plugin as the platform's one-shot commands do (`once`): the plugin's
    background reads and Dynamic DNS passes are not started, so every request the stand-in sees is an ask's."""

    NAME, TITLE, ICON = "platform", "Platform", "chip"
    once = True

    def from_page(self, hook, *args):
        """As the page's route asks a hook."""
        with asking.asking(asking.PAGE):
            return self.ask("namecheap", hook, *args)

    def on_its_own(self, hook, *args):
        """As the app's own code asks a hook."""
        return self.ask("namecheap", hook, *args)


@pytest.fixture
def attached(made):
    """The plugin over the stand-ins, attached with another plugin to an app whose login holds its settings (the API key,
    a Dynamic DNS host and its password); let go after."""
    plugin, fake, dns = made()
    neighbour = Neighbour()
    app = Platform(log=lambda m: None, login=EnvironmentLogin(env=settings_of(ddns=True)))
    app.attach(plugin)
    app.attach(neighbour)
    yield app, plugin, neighbour, fake
    app.detach(neighbour.name)
    app.detach(plugin.name)


def test_its_changes_are_said_to_be_asked_only_from_its_page_and_its_reads_with_the_key_too():
    assert set(internal.page_only(MACHINE)) == {*CHANGES, *SENT_FOR_ANYONE, *PAGE_READS}  # what the platform reads
    assert internal.plugin_only(MACHINE) == ()
    assert internal.problems(MACHINE) == []  # each a hook of its own, and someone may ask it
    assert {*CHANGES, *SENT_FOR_ANYONE, *READS} == set(MACHINE.interface()["hooks"]) and set(ASKED) == set(CHANGES)
    for hook in (*CHANGES, *SENT_FOR_ANYONE):
        assert asking.refusal(MACHINE, hook, asking.PAGE) == ""
        assert asking.refusal(MACHINE, hook, "neighbour") == (f"namecheap's {hook} is asked only from its page, "
                                                              "never by another plugin: neighbour asked it.")
        assert asking.refusal(MACHINE, hook, None).endswith("This ask names no asker: neither the page nor a plugin.")
    for hook in PAGE_READS:  # 0.3.7
        assert asking.refusal(MACHINE, hook, asking.PAGE) == ""
        assert asking.refusal(MACHINE, hook, "neighbour") == (f"namecheap's {hook} is asked only from its page, "
                                                              "never by another plugin: neighbour asked it.")
        assert asking.refusal(MACHINE, hook, None).endswith("This ask names no asker: neither the page nor a plugin.")
    for hook in OPEN_READS:
        assert {asking.refusal(MACHINE, hook, who) for who in (asking.PAGE, "neighbour", None)} == {""}


def test_another_plugin_or_no_one_asking_a_change_sends_nothing_and_its_page_does(attached):
    app, plugin, neighbour, fake = attached
    for hook in CHANGES:
        for ask in (neighbour.wants, app.on_its_own):
            with pytest.raises(asking.AskRefused, match=f"namecheap's {hook} is asked only from its page"):
                ask(hook, *ASKED[hook])
    for hook in PAGE_READS:  # 0.3.7: a read made with the key is refused them too, and nothing is sent for it
        for ask in (neighbour.wants, app.on_its_own):
            with pytest.raises(asking.AskRefused, match=f"namecheap's {hook} is asked only from its page"):
                ask(hook, *READ_ARGS.get(hook, ()))
    assert fake.requests == [] and fake.ddns_records == {}  # nothing sent, nor read: not the read a change makes first
    assert neighbour.wants("present") is True and neighbour.wants("status")["valid"] is True  # the contract's reads, anyone's as before
    assert [d["name"] for d in app.from_page("domains")] == ["hypokrites.me", "example.net"]
    assert len(app.from_page("hosts", "hypokrites.me")["records"]) == 7 and app.from_page("balance") is not None
    assert app.from_page("refresh")["domains"] == 2 and writes(fake) == []
    for hook in CHANGES:  # the same asks from its page: each one sent
        sent = len(writes(fake))
        assert app.from_page(hook, *ASKED[hook]) is not None
        assert len(writes(fake)) == sent + 1, hook
    assert writes(fake) == SENT and fake.ddns_records == {"home.hypokrites.me": HOME}
    rows = {(h["name"], h["type"], h["address"]) for h in fake.zones["hypokrites.me"]["hosts"]}
    assert ("@", "A", "203.0.113.99") in rows and ("@", "TXT", "v=spf1 include:_spf.protonmail.ch ~all") not in rows


def test_whether_a_name_is_free_is_asked_only_from_its_page(attached):
    """availability (0.3.5): names of another plugin's choosing, or of no one named, are never sent to Namecheap under
    the API key; the page's ask sends them, as before."""
    app, plugin, neighbour, fake = attached
    names = ("free-one.com", "taken.com")
    for ask in (neighbour.wants, app.on_its_own):
        with pytest.raises(asking.AskRefused, match="namecheap's availability is asked only from its page") as refused:
            ask("availability", *names)
        assert refused.value.status == 403 and refused.value.hook == "availability"
    assert fake.requests == []  # no name sent
    assert [n["available"] for n in app.from_page("availability", *names)] == [True, False]
    assert [r["params"].get("Command") for r in fake.requests] == ["namecheap.domains.check"]


def test_check_a_name_is_asked_only_from_its_page(attached):
    """check_names (0.3.6), the page's Check a name form: refused to another plugin and to no one, nothing sent; the
    page's ask sends the names, once."""
    app, plugin, neighbour, fake = attached
    for ask in (neighbour.wants, app.on_its_own):
        with pytest.raises(asking.AskRefused, match="namecheap's check_names is asked only from its page"):
            ask("check_names", "free-one.com taken.com")
    assert fake.requests == []
    assert app.from_page("check_names", "free-one.com taken.com")["said"].startswith("1 of 2 names are free")
    assert [r["params"].get("Command") for r in fake.requests] == ["namecheap.domains.check"]


def test_its_own_code_asks_nothing_of_the_app_and_runs_as_before(attached):
    """The background's Dynamic DNS pass and the command line call the plugin's code themselves: not an ask, so no asker
    is named and none is needed."""
    app, plugin, neighbour, fake = attached
    assert asking.asker() is None
    (home,) = plugin.ddns_update(force=False)
    assert home["host"] == "home.hypokrites.me" and writes(fake) == ["a Dynamic DNS update"]
    assert fake.ddns_records == {"home.hypokrites.me": HOME}


def test_no_hook_is_left_undeclared():
    """0.3.7, closed by default (liminal-libs 1.107.0): every hook it answers says who may ask it, so none is left to
    the default and the library's conformance has no warning. Read from its words, so it holds on an older library."""
    from liminal_libs.sources import conformance

    said = {h for word in ("READ_HOOKS", "SERVICE_HOOKS", "PLUGIN_ONLY_HOOKS", "PAGE_ONLY_HOOKS")
            for h in internal.declared(MACHINE, word)}
    own = [h for h in MACHINE.interface()["hooks"] if h not in ("setup", "run", "scan")]
    assert own and [h for h in own if h not in said] == []
    assert set(PAGE_READS) <= set(internal.declared(MACHINE, "PAGE_ONLY_HOOKS"))
    assert not set(PAGE_READS) & set(internal.declared(MACHINE, "READ_HOOKS"))  # none is opened again as a read
    warnings = getattr(conformance, "warnings", None)  # liminal-libs 1.107.0
    assert warnings is None or warnings(MACHINE) == []


def test_a_status_another_plugin_asks_holds_no_domain_record_or_balance_and_its_page_s_holds_them_all(attached):
    """0.3.8 (Liminal's complete review, item 14's P2-2): status is anyone's, but another plugin's ask of it (the MCP
    plugin's, for an agent you granted it) gets no balance, no domain and no zone's records, no table, form or action:
    what domains, hosts and balance refuse it. Nothing is sent for it. Its page's status holds them all, and so does
    one naming no one: the platform (0.42.1) draws the page from GET /api/machines/namecheap, which names no one."""
    app, plugin, neighbour, fake = attached
    assert app.from_page("refresh")["domains"] == 2  # the account read, as its page reads it
    app.from_page("ddns_update")
    whole = app.from_page("status")
    assert whole["balance"] and whole["tables"] and whole["forms"] and whole["actions"] and "lists" not in whole
    shown = repr(whole)
    secret = [whole["balance"].split()[0], "hypokrites.me", "example.net", "protonmail"]
    assert all(s in shown for s in secret)
    sent = len(fake.requests)
    told = neighbour.wants("status")
    assert told["present"] is True and told["valid"] is True and "on its page alone" in told["lists"]
    assert told["tables"] == [] and told["forms"] == [] and told["actions"] == [] and "balance" not in told
    said = repr(told)
    assert [s for s in secret if s in said] == []  # no balance, domain (nor a host of one) or record
    assert "its page" in told["summary"] and len(fake.requests) == sent  # nothing sent to answer it
    assert app.on_its_own("status")["tables"] == whole["tables"]  # naming no one: the platform's page, today

