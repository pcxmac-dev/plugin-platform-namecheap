# Changelog

## 0.3.6 (2026-11-26)

A **Check a name** form on the plugin's page (the user's "Add it later" of 2026-11-26, after 0.3.5 made the check the
page's alone).

- Once the API is set up, the page's actions hold **Check a name…**: one field, the names (up to 50, apart by spaces,
  commas or lines, a name typed twice asked once). It is asked at once (it changes nothing, so there is no second
  step), and the dialog says the answer: "example.com is free to register", or "2 of 3 names are free to register"
  with a line for each, a premium name with its price. Nothing is bought. The names are sent to Namecheap as one
  `namecheap.domains.check` under your API key; a name that is not a domain, or more than 50, is refused before
  anything is sent.
- The new hook `check_names(names)` is page-only (`PAGE_ONLY_HOOKS`) like `availability`: refused to another plugin
  and to an ask that names no one.
- Tests: `tests/test_forms.py` (the form, its answer in words, what is sent, what is refused before sending) and
  `tests/test_who_asks.py` (refused to another plugin and to no one, nothing sent; sent from the page). Taking
  `check_names` out of `PAGE_ONLY_HOOKS` fails both.

## 0.3.5 (2026-11-26)

Whether a name is free is asked only from the page (the user's choice of 2026-11-25, "Root reads and Namecheap").

- **`availability` is page-only** (`PAGE_ONLY_HOOKS`, beside the three changes). It buys nothing, yet it sends the
  names it is given to Namecheap (`namecheap.domains.check`, up to 50 an ask) under your API key, from this machine's
  address, each a call the account makes. Before, another plugin, or a program on this PC over HTTP with a header
  anyone can send, chose the names and spent the calls. Now another plugin's ask is refused (403), and so is one that
  names no one; liminal-platform 0.34.0 refuses one over HTTP (401) unless its login shows that you are at the page.
  The same caveat as 0.3.4's: a local login signs `secret` and `default` in with no password, so a program that signs
  itself in asks it still.
- The page draws no form for it today; the command line's `check NAME...` calls the code itself, as before.
- Asked by anyone, as before: `present`, `status`, `refresh`, `domains`, `hosts` and `balance`.
- Tests: `tests/test_who_asks.py` names `availability` among the page's hooks, so taking it out fails it: refused to
  another plugin and to no one with no request made, and answered when the page asks it.
- `__version__` is 0.3.5, as pyproject says.

## 0.3.4 (2026-11-25)

Its changes are asked only from the page (`PAGE_ONLY_HOOKS`, liminal-libs 1.66.0's word): the independent review's
finding PLT-H1, and the sweep of every plugin's hooks that followed it. The user, 2026-11-25, chose "Plugin releases":
each plugin says which of its hooks only its page asks.

- **What only the page asks**: `set_record`, `remove_record` and `ddns_update`. Another plugin's ask of one is refused
  (403), and so is an ask that names no asker; liminal-platform 0.34.0 refuses one over HTTP (401) unless its login
  shows that you are at the page. A platform that holds no login asks them as before. The 401 rests on the login's
  word that your browser is signed in, and a local login signs `secret` and `default` in with no password, so a
  program on this PC can sign itself in and ask them still: a proof that a program cannot make is the login's and the
  platform's to give, not this plugin's.
- **Before**, the platform handed an ask of any program on this PC (`POST /api/machines/namecheap/ask`, with a header
  anyone can send and a Host the client chooses, no sign-in) straight to the hook it named, and the hook used your API
  key. The page's dialog was the only confirmation: `set_record` with `[domain, "@", "A", address]` pointed the domain
  itself at an address of the asker's, and `remove_record` took out a record (the SPF record of a domain's mail,
  say), each a whole zone written, asked once. The one second confirmation there is, for a zone holding Dynamic DNS
  hosts (`accept_ddns_reset`), is an argument the asker sets. `ddns_update` sent an update for every Dynamic DNS host.
- **As before**: its reads are asked by anyone: `present`, `status`, `refresh`, `domains`, `hosts`, `balance`, and
  `availability`, which asks Namecheap whether the names given are free and buys nothing. The background (the account
  read every quarter of an hour, the Dynamic DNS checks) and the command line (`restore` among its commands, which is
  no hook) call the plugin's code themselves, not through an ask. The library floor stays 1.49.0: a library before
  1.66.0 does not read the word, and asks the hooks as it did.
- Tests: `tests/test_who_asks.py`, through the library's own App over the stand-in Namecheap and resolver: each of the
  three refused to another plugin and to no one, no request made; the same three asked from the page, each sent; the
  reads answered to a plugin; a Dynamic DNS pass run by the plugin's own code. A hook taken out of `PAGE_ONLY_HOOKS`
  fails it. Skipped on a library before 1.66.0.

## 0.3.3 (2026-11-24)

Dynamic DNS no longer re-sends an update taken while the name server catches up (the review of 2026-11-21, item 26).
Each pass compares this network's address with the host's A record at its domain's nameserver, and an update taken
was sent again on every pass (every few minutes) until that record showed it, and forever for a host whose record
never does (a CNAME, a URL redirect: no A + Dynamic DNS record). Now, once an update of an address is taken, it is
not sent again within `RETRY_S` (half an hour) while the record still shows the old one, and the host says so ("sent
at ... and taken; its name server still shows ..."); after `UNSEEN_MAX` (2) updates taken that it never came to show,
it is said to be likely no A + Dynamic DNS record and not sent again until it shows the address or this network's
address changes (Update now still sends it). Test: passes every five minutes over a lagging record send nothing; half
an hour on, one more; then none, said so; Update now sends; once shown, a later change is sent at once.

## 0.3.2 (2026-11-14)

Drawn under the platform's Cloud plugins section, in the list on the left, beside the cloud providers
(the user: "please create cloud plugins section on the left side and include cloud service plugins in that section"): Namecheap is a cloud service for domains and DNS. It sets `SECTION = "cloud"`, the attribute from
liminal-libs 1.51.0; liminal-platform 0.25.0 draws it, and an older platform keeps it under Machine plugins. Nothing
else changes.

## 0.3.1 (2026-11-11)

What the audit before the cloud plugins' keys found here: Update DNS now asks first (a form straight to its
confirmation; it sent on one click), and a write over Dynamic DNS hosts is accepted only by an exactly true
`accept_ddns_reset` (a "false" or a 1 from a local program is no acceptance). Its background reading starts only
when the platform attaches it (not its one-shot status or machine command): the charts app run alone attaches every
plugin it finds.

## 0.3.0 (2026-11-11)

Its API on its page (plugin API 2.2, liminal-libs 1.49.0; the user: "each plugin should reflect the the API its attached
to, and present links that provide documentation, the plugin interface should more or less contain what it already has,
BUT, it should also expose more of what the API is about"). Needs liminal-libs>=1.49.0. Its `signup` and `limits` are as
they were.

- `apis` (apis.py): two cards. Namecheap's pages refuse automated readers (403), so they were read in a browser on
  2026-11-11 and every address on the cards was seen there (each answered 200). The **Namecheap API**: the introduction,
  the methods page, the global parameters, error codes, extended attributes, transfer statuses, the change log, the API
  FAQ (its limits: 50 calls a minute, 700 an hour, 8,000 a day across the key; its requirements: 20 domains, $50 on the
  balance or $50 spent in two years), the API access settings, the sandbox, prices, status updates and terms; its eight
  command groups as the methods page names them (domains, domains.dns, domains.ns, domains.transfer, ssl, users,
  users.address, domainprivacy), each with what the plugin does with it (domains, domains.dns and users used), and all
  59 commands, each with its own page, as their pages name them (domainprivacy's are namecheap.whoisguard.*): the five
  the plugin sends with what for, the changes marked as writes, and the nine that charge the account (create, renew,
  reactivate, a transfer, a certificate, more of its names, privacy's renewal, funds added) marked as costing, none sent.
  **Namecheap Dynamic DNS**: the knowledge base's update (an HTTPS GET of host, domain, password and ip; IPv4 only; GET,
  never POST), the A + Dynamic DNS hosts it needs, the clients.
- `api_facts()`: what the plugin already holds, asking nothing (neither Namecheap nor the login): the requests its
  limiter counted against the key, the environment, when the account was read and what it held (the domains, the zones
  read, the balance), the last trouble; each Dynamic DNS host's last result and this network's address as last found.
- Tests: the cards are sound; the API card holds every group and command of the methods page; the commands it names as
  used are exactly those the plugin sends (read from the stand-in Namecheap and from its client's own strings), none
  that spends; the update's parameters are the knowledge base's; the facts ask nothing; with LIMINAL_VENDOR_PAGES=1,
  every address answers (Namecheap's 403 counts as there).

## 0.2.2 (2026-11-08)

Its icon is Namecheap's N, drawn in the library's line (liminal-libs 1.33.0's `namecheap`; the user: "for name cheap, use it's icon"). Needs liminal-libs>=1.33.0.

## 0.2.1 (2026-11-08)

Its settings entered on the platform's page (the user: "i need a way to put my credentials in to the namecheap
plugin and allow it to function"): liminal-platform 0.9.0's Settings… keeps them through the platform's login, then
calls `settings_changed`, which reads them anew at once (not after the 30 s they are otherwise kept). The README's
setup says so.

## 0.2.0 (2026-11-08)

Records set and removed from the platform's page, each with a confirmation, instead of only the command line (its forms:
liminal-platform 0.6.0 draws `status.forms`):

- under each zone's table, **Set a record…**: the host, the type (each with what it holds and whether it replaces the
  host's record of its type or is added beside the others; MX with the Custom MX mail setting alone, MXE with MXE), the
  address, the TTL and, for MX, the preference; on each of its records, **Remove**, naming the record by its whole
  address. The fields are the hooks' arguments in order (`set_record`, `remove_record`);
- the confirmation names the change (the host, the type and the address in the domain) and says that every other record
  and the mail setting are kept and that the zone is saved to a backup first, then written whole, read back and checked;
- a zone with Dynamic DNS hosts is still refused first: the refusal names `accept_ddns_reset` (`zone.Refusal.accept`),
  which the page asks as a second, explicit confirmation ("Write anyway?") before it writes; the confirmation of such a
  zone says beforehand that it will ask again;
- a zone every write would be refused (CAA or SRV records, a record turned off, no mail setting said) has no form and
  says why in its note;
- a write's report has its words (`lines`, shared with the command line): the backup, the check after it, what to do
  about a fault (the command that puts the backup back);
- a write answered with an error, or not read back after it, says where the zone as it was is saved and the command
  that puts it back, so the page shows it beside the failure.

## 0.1.0 (2026-11-08)

The first release (the user: "lets create a namecheap platform plugin that utilizes the API to create a dynamic DNS method,
as well as manage domains"; "again, all the settings are stored on a login-app db"; "but we are not integrating login-app
right now"):

- the settings read through the library's Login interface alone, as pairs named by their variables (`namecheap-api-key`
  for NAMECHEAP_API_KEY): the platform's EnvironmentLogin today, the login app's pairs once the platform binds it; no
  settings file; the status names the settings set, never a value;
- the account through Namecheap's API (getList, getHosts, setHosts, check, getBalances), over IPv4 (the whitelist takes
  IPv4 alone), its answers read by their local names in any case and namespace, its errors in words of what to do beside
  Namecheap's own, the key scrubbed from every message, at most 20 requests a minute, 700 an hour, 8,000 a day; nothing
  that spends (no domain registered, renewed or transferred) and no nameserver changed;
- records set and removed with every other record and the mail setting (EmailType) kept: a fresh read, refusals before
  anything is sent (no mail setting in the answer, CAA, SRV or records turned off, a zone read back empty, a domain not on
  Namecheap's DNS, Dynamic DNS hosts unless accepted), a JSON backup before each write, the zone read again and checked
  after it (a record missing, one not written, the mail setting, the Dynamic DNS hosts), `restore` putting a backup back;
- Dynamic DNS: this network's IPv4 address read of DNS, each host's record read of its domain's nameserver, an update
  only when they differ (or Update DNS now), without the address at most every half hour, a failed one again after half
  an hour; Namecheap's undocumented answer read tolerantly, without the password;
- while attached to the platform app: the account read every quarter of an hour and the hosts checked every
  NAMECHEAP_DDNS_MINUTES (5) in a thread of its own; detached, nothing runs. Valid while some part set up works or is
  untried; a part that failed is tried again a quarter of an hour later, or at once when its settings change;
- the platform's page: the Dynamic DNS hosts, the domains and each zone read in tables, the account in its facts, and the
  actions Refresh and Update DNS now (liminal-platform 0.5.0 draws `status.actions`);
- `python -m plugin_platform_namecheap ip | status | domains | hosts | set | remove | restore | backups | check | balance | ddns`
  (`ip`: this network's address, to whitelist).
