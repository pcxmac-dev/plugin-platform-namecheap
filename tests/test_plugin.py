"""The plugin over the stand-ins: its settings read through the Login interface (an EnvironmentLogin not attached, the
app's login attached), its status from what was read (no request made to answer it; no value of a setting in it), valid
while some part set up works or is untried, the background reading only while attached, its hooks asked by name, the
command line."""
from __future__ import annotations

import json
import time

import pytest

import plugin_platform_namecheap.__main__ as cli
from conftest import DDNS_PASSWORD, HOME, KEY, Pairs, settings_of
from plugin_platform_namecheap import NOT_SET, RETRY_S
from plugin_platform_namecheap.settings import read


def wait_until(test, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if test():
            return True
        time.sleep(0.02)
    return False


def test_nothing_set_is_not_valid_and_names_the_variables(made):
    p, fake, _ = made()
    st = p.status()
    assert st["present"] is False and st["valid"] is False and st["why"] == NOT_SET and "NAMECHEAP_API_KEY" in st["why"]
    assert st["tables"] == [] and st["actions"] == [] and not p.present() and fake.requests == []
    with pytest.raises(ValueError, match="the API is not set up"):
        p.refresh()
    with pytest.raises(ValueError, match="Dynamic DNS is not set up"):
        p.ddns_update()


def test_the_settings_are_read_through_the_login_by_their_pairs():
    login = Pairs(settings_of(ddns=True, NAMECHEAP_DDNS_MINUTES="15", NAMECHEAP_SANDBOX="1", NAMECHEAP_CLIENT_IP="not-an-ip"))
    c = read(login)
    assert (c.api_user, c.api_key, c.sandbox, c.minutes, c.client_ip) == ("tester", KEY, True, 15.0, "")
    assert c.api_ready and c.ddns_ready and c.password_for("hypokrites.me") == DDNS_PASSWORD
    assert any("NAMECHEAP_CLIENT_IP is not an IPv4 address" in w for w in c.problems)
    assert "namecheap-api-key" in login.asked and "NAMECHEAP_API_KEY" not in login.asked  # asked by the pairs' names
    assert KEY not in repr(c) and DDNS_PASSWORD not in repr(c)

    class Down(Pairs):
        def names(self):
            raise ConnectionError("the login app is not answering")
    assert read(Down({})).problems == ("the settings could not be read from the login: ConnectionError",)


def test_the_status_is_what_was_read_last_with_its_tables_and_actions_and_no_value_in_it(made, env):
    env(settings_of(ddns=True))
    p, fake, _ = made()
    st = p.status()
    assert st["valid"] is True and st["summary"] == "the account is read once attached · Dynamic DNS: checked once attached"
    done = p.refresh()
    assert (done["domains"], done["zones"]) == (2, 1) and done["refreshedAt"] == p.status()["readAt"]
    p.ddns_update(force=False)
    calls = len(fake.requests)
    st = p.status()
    assert len(fake.requests) == calls  # the status asks nothing of Namecheap
    assert st["valid"] is True and "problem" not in st
    assert st["summary"] == f"2 domains · 12.34 USD · home.hypokrites.me at {HOME}"
    assert st["api"] == "production" and st["balance"] == "12.34 USD" and st["clientIp"] == f"{HOME}, this network's"
    assert st["settingsSet"] == "NAMECHEAP_API_USER, NAMECHEAP_API_KEY, NAMECHEAP_DDNS_PASSWORD, NAMECHEAP_DDNS_HOSTS"
    assert [t["title"] for t in st["tables"]] == ["Dynamic DNS", "Domains", "hypokrites.me records"]
    ddns_table, domains, records = st["tables"]
    assert ddns_table["rows"][0][:2] == ["home.hypokrites.me", HOME] and ddns_table["rows"][0][4] == f"updated to {HOME}"
    assert domains["rows"][0][0] == "hypokrites.me" and domains["rows"][1][0] == {"text": "example.net", "sub": "expired"}
    assert domains["rows"][1][4] == "elsewhere" and domains["rows"][0][5] == "on"
    assert records["rows"][0][:3] == ["@", "MX", "mail.protonmail.ch."] and "mail: custom MX" in records["note"]
    assert [a["hook"] for a in st["actions"]] == ["refresh", "ddns_update"] and all(a["args"] == [] for a in st["actions"])
    text = json.dumps(st)
    assert KEY not in text and DDNS_PASSWORD not in text and "tester" not in text  # names of the settings, never a value


def test_valid_while_a_part_works_and_the_api_trouble_said_beside_it(made, env):
    env(settings_of(ddns=True))
    p, fake, _ = made()
    fake.error = ("1011150", "Invalid request IP")
    with pytest.raises(Exception, match="not whitelisted"):
        p.refresh()
    st = p.status()
    assert st["valid"] is True and "the account is read" not in st["summary"] and "not whitelisted" in st["summary"]
    p.ddns_update()
    st = p.status()
    assert st["valid"] is True and st["problem"].startswith("the API: this network's address is not whitelisted")


def test_the_api_alone_failing_is_not_valid_and_is_tried_again_later_when_detached(made, env):
    env(settings_of())
    t = [1_000_000.0]
    p, fake, _ = made()
    p._clock = lambda: t[0]
    fake.error = ("1011150", "Invalid request IP")
    with pytest.raises(Exception):
        p.refresh()
    st = p.status()
    assert st["valid"] is False and st["why"].startswith("the API: this network's address is not whitelisted")
    t[0] += RETRY_S
    st = p.status()
    assert st["valid"] is True and st["summary"] == "the account is read once attached"  # the platform attaches it: tried again


def test_a_change_of_the_settings_makes_a_failed_part_untried(made, env, monkeypatch):
    env(settings_of())
    p, fake, _ = made()
    fake.error = ("1010102", "API Key is invalid")
    with pytest.raises(Exception):
        p.refresh()
    assert p.status()["valid"] is False
    monkeypatch.setenv("NAMECHEAP_API_KEY", KEY + "x")
    assert p.config(fresh=True).api_key == KEY + "x" and p.status()["valid"] is True


def test_attached_it_reads_in_the_background_through_the_apps_login_and_detached_nothing_runs(made):
    p, fake, dns = made()
    login = Pairs(settings_of(ddns=True))
    p.attach(object(), login)
    try:
        assert p.working
        assert wait_until(lambda: p.status()["summary"] == f"2 domains · 12.34 USD · home.hypokrites.me at {HOME}")
        assert "namecheap-api-key" in login.asked
    finally:
        p.detach()
    assert not p.working and p.login is None
    calls = len(fake.requests)
    time.sleep(0.1)
    assert len(fake.requests) == calls


def test_the_hooks_are_asked_by_name_as_the_platform_asks_them(made, env, tmp_path):
    env(settings_of())
    p, fake, _ = made()
    assert [d["name"] for d in p.ask("domains")] == ["hypokrites.me", "example.net"]
    assert p.ask("hosts", "hypokrites.me")["emailType"] == "MX"
    rep = p.ask("set_record", "hypokrites.me", "home", "A", HOME, 300)
    assert rep["ok"] and rep["backup"].startswith(str(tmp_path / "backups"))
    assert ("home", "A", HOME) in [(h["name"], h["type"], h["address"]) for h in fake.zones["hypokrites.me"]["hosts"]]
    assert p.ask("remove_record", "hypokrites.me", "home", "A")["ok"]
    assert [a["available"] for a in p.ask("availability", "free-x.com", "taken.com")] == [True, False]
    assert p.ask("balance")["available"] == "12.34"
    with pytest.raises(LookupError):
        p.ask("check")
    records = [t for t in p.status()["tables"] if t["title"] == "hypokrites.me records"][0]
    assert len(records["rows"]) == 7  # the zone read after the last write


def test_the_command_line(made, env, tmp_path):
    env(settings_of(ddns=True))
    p, fake, _ = made()
    lines, errors = [], []

    def run(*argv):
        lines.clear()
        errors.clear()
        return cli.main(list(argv), plugin=p, out=lines.append, err=errors.append)
    assert run("ip") == 0 and lines == [HOME]
    assert run("domains") == 0 and lines[0].startswith("hypokrites.me") and "Namecheap DNS" in lines[0]
    assert run("hosts", "hypokrites.me") == 0 and lines[0] == "hypokrites.me · mail: custom MX · Namecheap DNS" and len(lines) == 8
    assert run("set", "hypokrites.me", "home", "A", HOME, "--ttl", "300") == 0
    assert lines[0] == f"hypokrites.me: added home A {HOME}" and lines[1].startswith("  backup: ")
    assert run("set", "hypokrites.me", "@", "MX", "mail.example.org") == 0 and "pref 10" in lines[0]
    assert run("remove", "hypokrites.me", "@", "TXT") == 1 and errors[0].startswith("refused: hypokrites.me has 2 TXT records")
    assert run("backups", "hypokrites.me") == 0 and len(lines) == 2
    assert run("restore", "hypokrites.me", lines[-1]) == 0 and lines[0].startswith("hypokrites.me: put back the 7 records")
    assert run("check", "free-one.com") == 0 and lines == [f"{'free-one.com':<32} free"]
    assert run("balance") == 0 and lines == ["12.34 USD available"]
    assert run("ddns") == 0 and lines[0].startswith("home.hypokrites.me") and f"updated to {HOME}" in lines[0]
    assert run("--json", "ddns", "--now") == 0 and json.loads("\n".join(lines))[0]["ok"] is True
    assert run("status") == 0 and json.loads("\n".join(lines))["valid"] is True
    fake.error = ("1011150", "Invalid request IP")
    assert run("domains") == 1 and errors[0].startswith("namecheap: this network's address is not whitelisted")
    with pytest.raises(SystemExit):
        run("nonsense")


def test_the_platform_reads_it_in_its_own_shape(made, env):
    """What the platform's page draws: facts as words, tables of columns and rows, actions it asks by name."""
    env(settings_of(ddns=True))
    p, fake, dns = made()
    p.refresh()
    st = p.status()
    for t in st["tables"]:
        assert set(t) >= {"title", "columns", "rows"} and all(len(r) == len(t["columns"]) for r in t["rows"])
    hooks = p.interface()["hooks"]
    assert all(a["hook"] in hooks for a in st["actions"])
    flat = {k: v for k, v in st.items() if not isinstance(v, (list, dict))}
    assert all(isinstance(v, (str, bool)) for v in flat.values())


def test_settings_entered_on_the_platforms_page_are_read_at_once(made):
    """liminal-platform 0.9.0 keeps a plugin's settings through its login, then calls settings_changed: the settings
    are read anew at once, not after the 30 s they are otherwise kept (the user: "i need a way to put my credentials in
    to the namecheap plugin and allow it to function")."""
    from liminal_libs.apps import EnvironmentLogin

    p, fake, dns = made()
    kept: dict[str, str] = {}
    p.login = EnvironmentLogin(env=kept)  # as the platform lends its login to a plugin not yet attached
    assert p.status()["valid"] is False and p.status()["why"].startswith("not set up")
    for variable, value in settings_of().items():
        p.login.save(variable, value)  # what the platform's settings route does
    assert p.status()["valid"] is False  # still the settings read a moment ago
    p.settings_changed()
    st = p.status()
    assert st["valid"] is True and "NAMECHEAP_API_KEY" in st["settingsSet"] and KEY not in str(st)  # named, never shown
