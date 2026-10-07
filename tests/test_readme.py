"""
The README quick start has to actually run.

The quick start is the first thing a visitor pastes, and it had already drifted
from the code once: it passed ``database_path=`` when the driver's parameter is
``master_db_path``, and it skipped the ``await driver.initialize()`` the driver
requires. This test executes the README's snippet verbatim against a temporary
database, so the example cannot drift again without a failing test.
"""

import asyncio
import re
from pathlib import Path

import pytest

README_PATH = Path(__file__).resolve().parent.parent / "README.md"
PATH_PLACEHOLDER = "/path/to/database"


def readme_quickstart_code() -> str:
    """Return the python snippet from the README's ``## Quick start`` section."""
    text = README_PATH.read_text(encoding="utf-8")
    sections = text.split("## Quick start", 1)
    if len(sections) != 2:
        pytest.fail("README has no '## Quick start' section")

    match = re.search(r"```python\n(.*?)```", sections[1], re.DOTALL)
    if match is None:
        pytest.fail("README 'Quick start' section has no python code block")
    return match.group(1)


@pytest.mark.integration
def test_readme_quickstart_runs(tmp_path):
    """Run the README's quick-start snippet against a temporary database."""
    code = readme_quickstart_code()

    assert PATH_PLACEHOLDER in code, (
        f"README quick start should reference {PATH_PLACEHOLDER!r} so this test "
        "can substitute a temporary database path"
    )

    db_path = tmp_path / "database"
    asyncio.run(_seed_person_table(db_path))

    snippet = code.replace(PATH_PLACEHOLDER, str(db_path))

    # The snippet prints result["rows"]; capture it so we assert on the real
    # output rather than merely on the snippet not raising.
    printed = []
    exec(
        compile(snippet, "README.md#quick-start", "exec"),
        {"__name__": "__main__", "print": lambda *args, **kwargs: printed.append(args)},
    )

    assert printed == [([{"n": 1}],)], f"quick start printed unexpected output: {printed}"


async def _seed_person_table(db_path: Path) -> None:
    """Create the Person table the README example queries."""
    from kuzuk.drivers.kuzu_wrapper import KuzuDriver

    driver = KuzuDriver(str(db_path))
    await driver.initialize()
    try:
        await driver.execute_query(
            "CREATE NODE TABLE Person(id INT64, name STRING, PRIMARY KEY(id))"
        )
        await driver.execute_query("CREATE (p:Person {id: 1, name: 'Alice'})")
    finally:
        await driver.close()
