# Kuzuk

**An experimental prototype for horizontally scaling [KùzuDB](https://kuzudb.com/) — not production software.**

Kuzuk explores a few patterns for running a KùzuDB database as a read-scaled
cluster: one master that takes writes, snapshot read replicas that serve reads,
a router that sends each query to the right place, and a sketch of "function
shipping" for analytical queries across nodes.

It is a prototype. Some parts are implemented and exercised against a real
KùzuDB; some are not implemented at all. This README says which is which — treat
it as the source of truth, not the module names.

> Kuzuk is an independent project. It is not affiliated with, or endorsed by,
> KùzuDB or its maintainers.

## What works, and what does not

| Area | State |
| --- | --- |
| `KuzuDriver` (async wrapper) | **Works.** Query execution, parameter binding, read-only mode, result reading, connection pooling. |
| Parameterised queries (`$param`) | **Works.** Parameters are bound to Kùzu placeholders. |
| Read-only databases (`read_only=True`) | **Works.** Enforced by Kùzu itself; writes raise. |
| Snapshot read replicas | **Works, coarsely.** Replicas are refreshed by checkpointing the master and copying the database file each interval. Replicas converge at the poll interval (seconds), **not** continuously — this is not change-data-capture. |
| Query routing (`kuzuk.routing`) | Implemented and unit-tested: it classifies queries and picks a target, applying consistency rules after a recent write. |
| Health monitoring (`kuzuk.monitoring`) | Implemented: node health, metrics, Prometheus export. |
| Incremental WAL replication | **Not implemented.** Kùzu's write-ahead log is an internal format, not a supported interface. `kuzuk/replication/wal_streamer.py` is a non-functional sketch; do not rely on it. |
| Automatic failover / replica promotion | **Not implemented.** There is no master election despite what the class names suggest. |
| Function shipping (`kuzuk.function_shipping`) | Implemented over an HTTP transport, but exercised **only** against in-process mocks — never against real Kùzu nodes. Treat as unproven. |
| Kubernetes operator (`k8s/operator`) | Manifests plus a controller script. Not tested against a live cluster. |
| Type checking (`mypy`) | **Not strictly typed.** mypy runs over every function body (`check_untyped_defs`) but with no `disallow_*` gates and no `warn_return_any`, so annotations are best-effort rather than enforced. |

If you need scalable, consistent KùzuDB today, this prototype is not it.

## Requirements

- Python 3.11–3.13
- [KùzuDB](https://pypi.org/project/kuzu/) `0.11.3` (pinned — the driver targets this version's bindings)
- An HTTP transport dependency (`aiohttp`) is needed only for function shipping

## Installation

Kuzuk is **not published on PyPI**. Install it from a checkout:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

## Quick start

```python
import asyncio
from kuzuk import KuzukDriver


async def main():
    driver = KuzukDriver(database_path="/path/to/database", replica_count=2)

    result = await driver.execute_query(
        "MATCH (n:Person) RETURN count(n) AS n"
    )
    print(result["rows"])

    await driver.close()


asyncio.run(main())
```

Parameterised query (parameters are bound, not interpolated):

```python
result = await driver.execute_query(
    "MATCH (u:User) WHERE u.username = $username RETURN u.role AS role",
    parameters={"username": "alice"},
)
```

## Running the tests

The project's own test runner shells out to a `python` on `PATH`; inside a
virtual environment `python -m pytest` is more reliable:

```bash
python -m pytest tests/ -q
```

Integration tests run against a real KùzuDB and are skipped automatically if
the `kuzu` package is not importable.

## Design notes

**Snapshot replication, not WAL streaming.** KùzuDB keeps recently committed
data in a write-ahead log (`<database>.wal`) until a checkpoint. The replication
manager therefore calls `CHECKPOINT` on the master and then copies the database
file *and* its WAL to each replica, replacing any stale WAL on the replica. This
is simple and correct, but it copies the whole database per pass and applies at
the poll interval — fine for a prototype, unsuitable for large databases or
tight freshness requirements.

**Why not incremental replication?** Kùzu does not expose a supported interface
for reading or applying its WAL, so a correct incremental implementation is not
buildable on the public API. The earlier code parsed a fabricated record format
and reported success without replicating; that is gone.

## Project status

Prototype / Alpha. Interfaces may change. See the table above for what is real.

## License

MIT — see [LICENSE](LICENSE).
