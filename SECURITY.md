# Security policy

Kuzuk is an **experimental prototype**, not production software (see the
[README](https://github.com/CJ-coding-apps/Kuzuk#what-works-and-what-does-not)).
It is not published on PyPI, has no releases, and should not be run anywhere
it is exposed to untrusted users or networks. This policy says how to report a
problem and what to expect, so that expectations match the project's status.

## Supported versions

| Version | Supported |
| --- | --- |
| `main` | Best effort |
| Anything else | No |

There are no tagged releases. A fix, if one is made, lands on `main`.

## Reporting a vulnerability

Please report privately rather than in a public issue: use **[Report a
vulnerability](https://github.com/CJ-coding-apps/Kuzuk/security/advisories/new)**
on this repository's Security tab. Include what you ran, what you expected,
and what happened.

This is a one-maintainer prototype. Reports are read, but there is no response-time
commitment, and a report may be answered by documenting the limitation rather
than fixing it.

## Known limitations (not vulnerabilities in themselves, but read before using)

- **No authentication or encryption between nodes.** The function-shipping
  transport (`kuzuk/function_shipping/transport.py`) talks plain HTTP or TCP to
  whatever endpoints it is given, with no authentication and no TLS. The only
  server in the code is a mock bound to `localhost`. Do not point the transport
  at nodes reachable by anyone you do not trust.
- **Untested deployment manifests.** The Kubernetes operator and manifests under
  `k8s/` have not been run against a live cluster. Review their RBAC rules and
  network exposure before applying them anywhere.
- **Archived storage engine.** Kuzuk pins [KùzuDB](https://github.com/kuzudb/kuzu)
  `0.11.3`, the final release; KùzuDB is archived upstream and receives no
  further fixes, including security fixes. A vulnerability in KùzuDB itself
  cannot be fixed here. Report it here anyway, and it will be documented.
- **Snapshot replication copies database files.** Replicas are refreshed by
  copying the master's database file, so anyone who can read the replica
  directory can read the whole database. Set file permissions accordingly.
