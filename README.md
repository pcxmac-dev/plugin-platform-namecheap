# plugin-platform-namecheap

Namecheap for Liminal's platform: your domains and their records through Namecheap's API, and Dynamic DNS keeping
hosts at this network's public address.

The user's words (2026-11-08): "lets create a namecheap platform plugin that utilizes the API to create a dynamic DNS
method, as well as manage domains"; on its settings: "again, all the settings are stored on a login-app db", "but we
are not integrating login-app right now".

## What it does

A machine plugin of the platform (`liminal_libs.machines.MachinePlugin`, plugin API 2.1, its icon the globe):

- **The account**: every domain (its expiry, auto-renewal, registrar lock, whether it is on Namecheap's DNS, its
  privacy), the balance, and the records of each domain on Namecheap's DNS. Whether names are free to register
  (read only).
- **Records set and removed**, every other record and the mail setting kept (below).
- **Dynamic DNS**: each host set is checked every few minutes against this network's public IPv4 address, and
  updated when they differ.
- **Nothing that spends**: no domain is registered, renewed, reactivated or transferred from it, and no
  nameserver is changed.

While it is attached to the platform app, it reads the account every quarter of an hour and checks the Dynamic DNS
hosts every `NAMECHEAP_DDNS_MINUTES` (5), in a thread of its own. Detached (the platform ending, the plugin disabled
or not valid), nothing of it runs. The platform's page draws what it read last (no request is made to answer it):
the Dynamic DNS hosts, the domains and each zone in tables, the account in the facts on the right, and two actions,
**Refresh** and **Update DNS now** (liminal-platform 0.5.0 and later draw them). With liminal-platform 0.6.0 and
later, each zone's records are set and removed from the page too (below).

## From the platform's page

Under each zone's table, **Set a record…** opens a form: the host (`@` for the domain itself), the type (each with what
it holds, and whether it replaces the host's record of its type or is added beside the others), the address, the TTL
and, for an MX record, its preference. Each record has a **Remove**. Nothing is written until you confirm the change:
the confirmation names the host, the type and the address in the domain, and says that every other record and the mail
setting are kept and that the zone is saved to a backup first. The answer says what was done, where the backup is and
whether the zone read back holds every record as written (or what is missing, and the command that puts it back).

A zone with Dynamic DNS hosts is refused first, as from the command line; the page then asks a second time, naming
what may happen to them ("Write anyway?"), and writes only on that second yes. A zone that no write could keep whole
(a CAA or SRV record, a record turned off) has no form, and its note says why.

## Setting it up

1. **Turn API access on** (production): Namecheap's dashboard, Profile > Tools > Business & Dev Tools >
   Namecheap API Access > ON. Namecheap opens production API access to accounts that meet its requirements (its
   FAQ names a number of domains, a balance or a past spend); otherwise its support can open it. The API key is
   shown there. The sandbox (https://www.sandbox.namecheap.com) is open to anyone, with an account of its own.
2. **Whitelist this network's address** on the same page: Whitelisted IPs > Edit > Add IP. Namecheap takes IPv4
   addresses alone; the plugin connects over IPv4. `python -m plugin_platform_namecheap ip` prints this network's
   address as the plugin finds it (no setting needed).
3. **Dynamic DNS**, for each domain whose hosts it keeps: Domain List > Manage > Advanced DNS > Dynamic DNS > ON. The
   Dynamic DNS password is shown there (each domain has its own). Then add each host as an **A + Dynamic DNS
   Record** under Host Records (home, @ or *; any address: the first update replaces it). Dynamic DNS needs the
   domain on Namecheap's DNS (BasicDNS, PremiumDNS or FreeDNS) and keeps IPv4 (A) records alone.
4. **Enter the settings**: on the platform's page, the plugin's **Settings…** (liminal-platform 0.9.0) asks for each
   one below, the key and the Dynamic DNS password typed hidden; a field left empty keeps its value, and no value is
   ever shown back. They are pairs the plugin asks of the login of the app it is attached to, each named by its
   variable (NAMECHEAP_API_KEY is the pair `namecheap-api-key`): today the platform's login keeps them as your user
   environment variables (so they hold across a restart), and the plugin reads them at once. Once the platform binds
   the login app, they are the signed-in user's pairs there instead. Setting the variables yourself works too.

| Variable | | |
|---|---|---|
| `NAMECHEAP_API_USER` | the API | your Namecheap username |
| `NAMECHEAP_API_KEY` | the API (secret) | the key of step 1 |
| `NAMECHEAP_USERNAME` | optional | the account the commands act on (the API user's own unless set) |
| `NAMECHEAP_CLIENT_IP` | optional | the whitelisted IPv4 address sent as ClientIp (this network's address unless set) |
| `NAMECHEAP_SANDBOX` | optional | `1`: Namecheap's sandbox instead of production |
| `NAMECHEAP_DDNS_PASSWORD` | Dynamic DNS (secret) | the domain's Dynamic DNS password; several domains: `example.com=PASSWORD;example.net=PASSWORD` |
| `NAMECHEAP_DDNS_HOSTS` | Dynamic DNS | the hosts kept at this network's address, comma separated: `home.example.com`, `@.example.com` (the domain itself), `*.example.com` |
| `NAMECHEAP_DDNS_MINUTES` | optional | minutes between Dynamic DNS checks, 1 to 1440 (5 unless set) |

The API needs the first two; Dynamic DNS needs its password and hosts. Either part alone is enough. The plugin keeps
no settings file and never shows a value: its status names the settings that are set.

## A write never loses a record

Namecheap's setHosts writes a domain's whole zone at once and deletes every record it is not given. So each change
reads the zone afresh, changes the one record and writes everything back, with the mail setting (EmailType: a domain
whose mail is at Proton keeps its MX, SPF, DKIM and DMARC records):

- **Refused, with nothing sent**, when what was read cannot be written back as it is: no mail setting in the answer,
  a CAA or SRV record (setHosts cannot take them back whole), a record turned off, a zone read back empty (never a
  misreading written over), a domain not on Namecheap's DNS; an MX record unless the mail setting is Custom MX.
- **Dynamic DNS hosts**: setHosts has no record type for an A + Dynamic DNS Record, so a write may turn them into
  plain A records that Dynamic DNS no longer updates. A write to a zone holding them is refused unless asked with
  `--accept-ddns-reset` (the hooks' `accept_ddns_reset`, which the refusal names: the platform's page asks it as a
  second confirmation); the result then says whether they kept it, and the dashboard turns it back on.
- **A backup before each write**: the zone as read, as JSON, in the platform's folder under `namecheap/backups/`
  (`LIMINAL_PLATFORM_DIR`, else the data folder's `platform/`). `backups` lists them; `restore` puts one back
  (the zone as it is is backed up first).
- **Checked after each write**: the zone read again; a record missing, one there that was not written, the mail
  setting changed, a Dynamic DNS host turned plain, each reported, with the command that puts the backup back.

Setting an A, AAAA, ALIAS, CNAME, MXE or URL record replaces the host's records of that type; a TXT, MX or NS record
is added beside the others. Removing names the record by its address when the host has several.

## Dynamic DNS

This network's public IPv4 address is asked of DNS (`myip.opendns.com` of OpenDNS's resolver, else Google's
`o-o.myaddr.l.google.com`, each asked by its IPv4 address), and each host's A record of its domain's own nameserver
(not a resolver's copy, which lags by its TTL). An update
(`https://dynamicdns.park-your-domain.com/update?host=...&domain=...&password=...&ip=...`, GET alone, as Namecheap's
knowledge base gives it) goes only when they differ; Update DNS now sends one for every host. When the address
cannot be found, an update goes without it (Namecheap then takes the address the request comes from) at most every
half hour; a failed update is tried again after half an hour. Namecheap's answer is not documented: it is read for
its error count, its errors, the address and Done, and shown shortened, without the password, when it cannot be.

## Valid, and the platform

The plugin is valid while some part set up works or has not been tried yet: the platform disables a plugin that is
not valid, which would stop Dynamic DNS, so an API trouble while Dynamic DNS works is said beside it, not taken for
the plugin's. With nothing set, it is not valid and names the variables. A part that failed is taken as untried a
quarter of an hour later (the platform attaches it again and it is tried again), or at once when its settings change.

## Its hooks

`present`, `status` (the summary, the facts, `tables`, `actions`, `forms`), `refresh()`, `domains()`, `hosts(domain)`,
`set_record(domain, host, rtype, address, ttl=None, mx=None, accept_ddns_reset=False)`,
`remove_record(domain, host, rtype, address=None, accept_ddns_reset=False)`, `availability(*names)`, `balance()`,
`ddns_update(force=True)`. A write's report: `said`, `lines` (its words), `ok`, `missing`, `unexpected`, `ddnsLost`,
`backup`, `restore`.

## From the command line

Its settings read from the environment (as this shell has them):

```
python -m plugin_platform_namecheap ip
python -m plugin_platform_namecheap status
python -m plugin_platform_namecheap domains
python -m plugin_platform_namecheap hosts example.com
python -m plugin_platform_namecheap set example.com home A 203.0.113.7 --ttl 300
python -m plugin_platform_namecheap set example.com @ TXT "google-site-verification=..."
python -m plugin_platform_namecheap remove example.com @ TXT "google-site-verification=..."
python -m plugin_platform_namecheap backups example.com
python -m plugin_platform_namecheap restore example.com <a backup's file>
python -m plugin_platform_namecheap check some-name.com another.net
python -m plugin_platform_namecheap balance
python -m plugin_platform_namecheap ddns [--now]
```

`--json` before the command prints the answer as JSON.

## Limits

Namecheap's API allows about 20 requests a minute (some reports say 50), 700 an hour and 8,000 a day per key; the
plugin keeps under the lower, waits up to 30 s for room and otherwise says so. A refresh reads at most 12 zones
(the rest: `hosts DOMAIN`).

## Install

```
pip install "plugin-platform-namecheap @ git+https://github.com/pcxmac-dev/plugin-platform-namecheap@main"
```

or, for the platform's preview, a checkout in the plugin directory (`LIMINAL_PLUGINS`). Its tests use stand-ins for
Namecheap and DNS alone (`python -m pytest`): none reaches Namecheap or the network.
