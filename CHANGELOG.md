# Changelog

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
