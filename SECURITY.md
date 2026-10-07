# Security Policy

CCMOD injects into a local process on your own machine; it has no server, accounts, or network
service of its own. Still, if you find a security-relevant issue (e.g. a code path that could be
abused, an unsafe file operation, or a supply-chain concern in the tooling), please report it.

## Reporting

- **Preferred:** open a private security advisory via GitHub (Security → Report a vulnerability).
- Or open a regular issue **without** exploit detail and ask a maintainer to make contact.

Please do **not** file reports that amount to "how to bypass CapCut paid features" — that is out of
scope and explicitly not supported (see [`DISCLAIMER.md`](DISCLAIMER.md)).

## Scope

In scope: the CCMOD tooling in this repo (injection DLL, frida scripts, Python helpers).
Out of scope: CapCut itself, ByteDance services, and anything that circumvents licensing/payment.

We aim to acknowledge reports within a few days.
