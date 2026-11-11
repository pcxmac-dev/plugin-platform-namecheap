"""What the Namecheap plugin attaches to (plugin API 2.2; the user, 2026-11-11: "each plugin should reflect the the API its
attached to, and present links that provide documentation ... it should also expose more of what the API is about"):
Namecheap's XML API, every command of every group its methods page lists (59, each with its own page), and Namecheap's
Dynamic DNS update. Namecheap's pages refuse automated readers (403): they were read in a browser on 2026-11-11, each
address seen there, each command named as its page names it (the domainprivacy group's are namecheap.whoisguard.*)."""
from __future__ import annotations

from liminal_libs.sources.apis import Api, Area, Call, Link

VERIFIED = "2026-11-11"
API = "Namecheap API"
DDNS = "Namecheap Dynamic DNS"

_N = "https://www.namecheap.com/support/api/"
_M = _N + "methods/"
_KB = "https://www.namecheap.com/support/knowledgebase/"
_DDNS_ARTICLE = _KB + "article.aspx/29/11/how-to-dynamically-update-the-hosts-ip-with-an-https-request/"

# every command, as the methods page lists it: (command, its page, what it does, writes, starts or raises a charge)
COMMANDS = (
    ("namecheap.domains.getList", "domains/get-list/", "the account's domains, a page at a time", False, False),
    ("namecheap.domains.getContacts", "domains/get-contacts/", "a domain's contacts", False, False),
    ("namecheap.domains.create", "domains/create/", "a domain registered", True, True),
    ("namecheap.domains.getTldList", "domains/get-tld-list/", "the TLDs and what each allows", False, False),
    ("namecheap.domains.setContacts", "domains/set-contacts/", "a domain's contacts changed", True, False),
    ("namecheap.domains.check", "domains/check/", "whether names are free to register (50 at most)", False, False),
    ("namecheap.domains.reactivate", "domains/reactivate/", "an expired domain reactivated", True, True),
    ("namecheap.domains.renew", "domains/renew/", "a domain renewed", True, True),
    ("namecheap.domains.getRegistrarLock", "domains/get-registrar-lock/", "whether a domain is locked", False, False),
    ("namecheap.domains.setRegistrarLock", "domains/set-registrar-lock/", "a domain locked or unlocked", True, False),
    ("namecheap.domains.getInfo", "domains/get-info/", "a domain's details", False, False),
    ("namecheap.domains.dns.setDefault", "domains-dns/set-default/", "a domain put on Namecheap's own nameservers", True, False),
    ("namecheap.domains.dns.setCustom", "domains-dns/set-custom/", "a domain given other nameservers", True, False),
    ("namecheap.domains.dns.getList", "domains-dns/get-list/", "a domain's nameservers", False, False),
    ("namecheap.domains.dns.getHosts", "domains-dns/get-hosts/", "a domain's host records and its mail setting", False, False),
    ("namecheap.domains.dns.getEmailForwarding", "domains-dns/get-email-forwarding/", "a domain's email forwarding",
     False, False),
    ("namecheap.domains.dns.setEmailForwarding", "domains-dns/set-email-forwarding/", "a domain's email forwarding set",
     True, False),
    ("namecheap.domains.dns.setHosts", "domains-dns/set-hosts/", "a domain's host records written whole (every record "
     "not given is deleted)", True, False),
    ("namecheap.domains.ns.create", "domains-ns/create/", "a nameserver made under a domain (a glue record)", True, False),
    ("namecheap.domains.ns.delete", "domains-ns/delete/", "a nameserver under a domain deleted", True, False),
    ("namecheap.domains.ns.getInfo", "domains-ns/getinfo/", "a nameserver's address and state", False, False),
    ("namecheap.domains.ns.update", "domains-ns/update/", "a nameserver's address changed", True, False),
    ("namecheap.domains.transfer.create", "domains-transfer/create/", "a domain's transfer in begun", True, True),
    ("namecheap.domains.transfer.getStatus", "domains-transfer/get-status/", "a transfer's status", False, False),
    ("namecheap.domains.transfer.updateStatus", "domains-transfer/update-status/", "a transfer submitted again", True, False),
    ("namecheap.domains.transfer.getList", "domains-transfer/get-list/", "the account's transfers", False, False),
    ("namecheap.ssl.create", "ssl/create/", "an SSL certificate bought", True, True),
    ("namecheap.ssl.getList", "ssl/get-list/", "the account's certificates", False, False),
    ("namecheap.ssl.parseCSR", "ssl/parse-csr/", "a CSR read", False, False),
    ("namecheap.ssl.getApproverEmailList", "ssl/get-approver-email-list/", "the addresses that may approve a certificate",
     False, False),
    ("namecheap.ssl.activate", "ssl/activate/", "a bought certificate activated", True, False),
    ("namecheap.ssl.resendApproverEmail", "ssl/resend-approver-email/", "the approval email sent again", True, False),
    ("namecheap.ssl.getInfo", "ssl/get-info/", "a certificate's details", False, False),
    ("namecheap.ssl.renew", "ssl/renew/", "a certificate renewed", True, True),
    ("namecheap.ssl.reissue", "ssl/reissue/", "a certificate reissued", True, False),
    ("namecheap.ssl.resendfulfillmentemail", "ssl/resend-fulfillment-email/", "the certificate's email sent again",
     True, False),
    ("namecheap.ssl.purchasemoresans", "ssl/purchasemoresans/", "more names bought for a certificate", True, True),
    ("namecheap.ssl.revokecertificate", "ssl/revokecertificate/", "a certificate revoked", True, False),
    ("namecheap.ssl.editDCVMethod", "ssl/editdcvmethod/", "how a certificate's domain is validated, changed", True, False),
    ("namecheap.users.getPricing", "users/get-pricing/", "the prices of Namecheap's products for the account", False, False),
    ("namecheap.users.getBalances", "users/get-balances/", "the account's funds", False, False),
    ("namecheap.users.changePassword", "users/change-password/", "an account's password changed", True, False),
    ("namecheap.users.update", "users/update/", "an account's details changed", True, False),
    ("namecheap.users.createaddfundsrequest", "users/create-add-funds-request/", "funds added from a credit card",
     True, True),
    ("namecheap.users.getAddFundsStatus", "users/get-add-funds-status/", "whether funds were added", False, False),
    ("namecheap.users.create", "users/create/", "an account made under the API user", True, False),
    ("namecheap.users.login", "users/login/", "an account's name and password checked", False, False),
    ("namecheap.users.resetPassword", "users/reset-password/", "a password's reset sent", True, False),
    ("namecheap.users.address.create", "users-address/create/", "an address made", True, False),
    ("namecheap.users.address.delete", "users-address/delete/", "an address deleted", True, False),
    ("namecheap.users.address.getInfo", "users-address/get-info/", "an address", False, False),
    ("namecheap.users.address.getList", "users-address/get-list/", "the account's addresses", False, False),
    ("namecheap.users.address.setDefault", "users-address/set-default/", "the default address chosen", True, False),
    ("namecheap.users.address.update", "users-address/update/", "an address changed", True, False),
    ("namecheap.whoisguard.changeemailaddress", "domainprivacy/change-email-address/", "domain privacy's forwarding "
     "address changed", True, False),
    ("namecheap.whoisguard.enable", "domainprivacy/enable/", "domain privacy turned on", True, False),
    ("namecheap.whoisguard.disable", "domainprivacy/disable/", "domain privacy turned off", True, False),
    ("namecheap.whoisguard.getlist", "domainprivacy/getlist/", "the account's domain privacy subscriptions", False, False),
    ("namecheap.whoisguard.renew", "domainprivacy/renew/", "domain privacy renewed", True, True),
)
USED = {  # what the plugin makes each call it makes for
    "namecheap.domains.getList": "the Domains table (a hundred a page, every page)",
    "namecheap.domains.dns.getHosts": "each zone's table and its mail setting; read again before a write and after it",
    "namecheap.domains.dns.setHosts": ("Set a record… and Remove: the zone written whole by POST, every other record and the "
                                       "mail setting kept, a backup first, a check after"),
    "namecheap.domains.check": "whether names are free to register (nothing is bought)",
    "namecheap.users.getBalances": "the balance fact, and what the auto-renewals due need",
}
GROUPS = {  # each command group as the methods page names it: what it is, its first command's page, what the plugin does
    "domains": ("domains: registered, renewed, reactivated, their contacts, locks and details", "domains/get-list/",
                "the account's domains listed (their expiry, renewal, lock, DNS and privacy); names checked"),
    "domains.dns": ("a domain's DNS: its nameservers, host records, email forwarding", "domains-dns/get-hosts/",
                    "each zone's records and mail setting read, written whole with every other record kept"),
    "domains.ns": ("nameservers made under a domain (glue records)", "domains-ns/create/", ""),
    "domains.transfer": ("domains transferred in", "domains-transfer/create/", ""),
    "ssl": ("SSL certificates: bought, activated, renewed, reissued, revoked", "ssl/create/", ""),
    "users": ("the account: its prices, its balance and funds, its password and details, accounts under it",
              "users/get-pricing/", "the balance read"),
    "users.address": ("the account's addresses", "users-address/create/", ""),
    "domainprivacy": ("domain privacy (WhoisGuard): turned on and off, renewed, its forwarding address",
                      "domainprivacy/enable/", ""),
}


def group_of(command: str) -> str:
    if command.startswith("namecheap.whoisguard."):
        return "domainprivacy"
    return command[len("namecheap."):].rsplit(".", 1)[0]


NAMECHEAP_API = Api(
    name=API, maker="Namecheap", kind="xml",
    about=("Namecheap's XML API: a domain's registration, renewal, contacts and lock, its DNS and nameservers, transfers, "
           "SSL certificates, the account's prices, balance and addresses, and domain privacy, each a Command sent with the "
           "global parameters to one service URL and answered as an ApiResponse. The plugin reads the account's domains, "
           "each domain's records and mail setting, whether names are free and the balance, and writes a domain's records "
           "whole; nothing that spends (no domain registered, renewed, reactivated or transferred) and no nameserver changed."),
    base="https://api.namecheap.com/xml.response (the sandbox: https://api.sandbox.namecheap.com/xml.response)",
    version="the XML API as Namecheap documents it (no version number: its change log)",
    auth=("ApiUser, ApiKey and UserName with every request, from an IPv4 address whitelisted for the key (ClientIp; Profile "
          "> Tools > Namecheap API Access); API access needs 20 domains, $50 on the balance or $50 spent in two years"),
    limits=("50 calls a minute, 700 an hour and 8,000 a day across the whole key (Namecheap's API FAQ); the plugin keeps to "
            "20 a minute, 700 an hour and 8,000 a day"),
    costs=("the API itself is free; registering, renewing, reactivating or transferring a domain, buying or renewing a "
           "certificate or more of its names, renewing domain privacy and adding funds charge the account (none is made "
           "here)"),
    links=(
        Link("API introduction", _N + "intro/", "docs"),
        Link("API methods", _M, "reference"),
        Link("Global parameters", _N + "global-parameters/", "reference"),
        Link("Error codes", _N + "error-codes/", "reference"),
        Link("Extended attributes", _N + "extended-attributes/", "reference"),
        Link("Transfer statuses", _N + "transfer-statuses/", "reference"),
        Link("API FAQ (its limits, its requirements)", _KB + "article.aspx/9739/63/api-faq/", "limits"),
        Link("Domain prices", "https://www.namecheap.com/domains/", "pricing"),
        Link("Status updates", "https://www.namecheap.com/status-updates/", "status"),
        Link("API change log", _N + "change-log/", "changelog"),
        Link("API access (Profile > Tools)", "https://ap.www.namecheap.com/settings/tools/apiaccess/", "console"),
        Link("The sandbox", "https://www.sandbox.namecheap.com/", "tool"),
        Link("Terms and conditions", "https://www.namecheap.com/legal/", "terms"),
    ),
    areas=tuple(Area(g, about, _M + page, covered=covered) for g, (about, page, covered) in GROUPS.items()),
    calls=tuple(Call(cmd, about, group_of(cmd), used=USED.get(cmd, ""), docs=_M + page, writes=writes, costs=costs)
                for cmd, page, about, writes, costs in COMMANDS),
    verified=VERIFIED)

NAMECHEAP_DDNS = Api(
    name=DDNS, maker="Namecheap", kind="query",
    about=("Namecheap's Dynamic DNS: one HTTPS GET sets a host's A record (@, *, www, home …) of a domain on Namecheap's "
           "BasicDNS, PremiumDNS or FreeDNS to an IPv4 address, or to the address the request comes from, authenticated by "
           "the domain's own Dynamic DNS password. IPv4 only. The plugin keeps its hosts at this network's public address: "
           "the address is asked of DNS, each host's record of the domain's own nameserver, and an update sent only when "
           "they differ."),
    base="https://dynamicdns.park-your-domain.com/update",
    version="as Namecheap's knowledge base gives it (its answer's layout is not documented)",
    auth="the domain's Dynamic DNS password (Advanced DNS > Dynamic DNS), never the account's; GET only (POST does not work)",
    limits=("none published; the plugin sends an update only when a record differs, and at most every half hour when the "
            "address cannot be found or an update failed"),
    costs="",
    links=(
        Link("How to dynamically update the host's IP with an HTTPS request", _DDNS_ARTICLE, "docs"),
        Link("How do I set up a host for Dynamic DNS?", _KB + "article.aspx/43/11/how-do-i-set-up-a-host-for-dynamic-dns/",
             "guide"),
        Link("Dynamic DNS (the knowledge base)", _KB + "subcategory/11/dynamic-dns/", "guide"),
        Link("Using the Dynamic DNS client", _KB + "article.aspx/596/11/using-dynamic-dns-client-version-001/", "tool"),
    ),
    areas=(
        Area("The update", "a host's A record set by an HTTPS GET (host, domain, password, ip)", _DDNS_ARTICLE,
             covered="each host kept at this network's public IPv4 address, an update sent only when its record differs; "
                     "Update DNS now sends one for every host"),
        Area("A + Dynamic DNS records", "the hosts Dynamic DNS may change, made in Advanced DNS",
             _KB + "article.aspx/43/11/how-do-i-set-up-a-host-for-dynamic-dns/",
             covered="a write over a zone with such hosts refused until accepted twice; the flag a write loses said"),
        Area("Dynamic DNS clients", "Namecheap's own client, routers' and others' clients",
             _KB + "article.aspx/596/11/using-dynamic-dns-client-version-001/"),
    ),
    calls=(
        Call("GET /update?host=HOST&domain=DOMAIN&password=PASSWORD&ip=ADDRESS", "a host's A record set (without ip: the "
             "address the request comes from)", "The update", used="each Dynamic DNS host kept at this network's address",
             docs=_DDNS_ARTICLE, writes=True),
    ),
    verified=VERIFIED)

APIS = (NAMECHEAP_API, NAMECHEAP_DDNS)
