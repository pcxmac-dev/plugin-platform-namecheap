"""Every plugin here conforms to the class contract (plugin API 2.1): liminal_libs.sources.conformance, read from the
plugin alone (nothing runs)."""
from __future__ import annotations

import plugin_platform_namecheap as module
from liminal_libs.sources.conformance import assert_module_conforms


def test_every_plugin_here_conforms_to_the_class_contract():
    found = assert_module_conforms(module)
    assert found and all(p.api == "2.1" and not p.is_record for p in found)
    assert {p.SYSTEM for p in found} == {"platform"} and {p.KIND for p in found} == {"machine"}
    assert {p.ICON for p in found} == {"globe"}


def test_its_settings_are_pairs_named_by_their_variables_and_nothing_spends():
    p = module.MACHINE
    assert [k.pair for k in p.keys] == ["namecheap-api-user", "namecheap-api-key", "namecheap-username", "namecheap-client-ip",
                                         "namecheap-sandbox", "namecheap-ddns-password", "namecheap-ddns-hosts",
                                         "namecheap-ddns-minutes"]
    assert {k.name for k in p.keys if k.secret} == {"NAMECHEAP_API_KEY", "NAMECHEAP_DDNS_PASSWORD"}
    hooks = p.interface()["hooks"]
    assert {"present", "status", "refresh", "domains", "hosts", "set_record", "remove_record", "availability", "ddns_update",
            "balance"} <= set(hooks)
    assert "check" not in hooks  # the platform's check is a plugin's check of this PC for an install: not this
    import inspect

    import plugin_platform_namecheap.api as api
    source = inspect.getsource(api)
    for spends in ("domains.create", "domains.renew", "domains.reactivate", "domains.transfer", "dns.setCustom", "dns.setDefault"):
        assert spends not in source  # no domain bought, renewed or moved, no nameserver changed
