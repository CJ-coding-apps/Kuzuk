"""
Pytest configuration and fixtures for Kuzuk tests.
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest


# Configure pytest markers
def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests requiring KuzuDB")
    config.addinivalue_line("markers", "performance: Performance benchmarks")
    config.addinivalue_line("markers", "slow: Slow tests")
    config.addinivalue_line("markers", "failover: Failover and disaster recovery tests")
    config.addinivalue_line("markers", "security: Security and penetration tests")
    config.addinivalue_line("markers", "enterprise: Enterprise-level functionality tests")
    config.addinivalue_line("markers", "end_to_end: End-to-end integration tests")


# Configure asyncio event loop for tests
pytest_plugins = ("pytest_asyncio",)


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def temp_test_dir():
    """Create temporary directory for all tests in session."""
    temp_dir = tempfile.mkdtemp(prefix="kuzuk_tests_")
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def temp_db_path(temp_test_dir):
    """Create temporary database path for individual tests."""
    db_path = Path(temp_test_dir) / f"test_{pytest.current_test_id}.kuzu"
    yield str(db_path)
    # Cleanup handled by session fixture


@pytest.fixture
def temp_replica_dir(temp_test_dir):
    """Create temporary replica directory for individual tests."""
    replica_dir = Path(temp_test_dir) / f"replicas_{pytest.current_test_id}"
    replica_dir.mkdir(exist_ok=True)
    yield str(replica_dir)
    # Cleanup handled by session fixture


# Store current test ID for unique file naming
@pytest.fixture(autouse=True)
def setup_test_id(request):
    """Set up unique test ID for file naming."""
    pytest.current_test_id = (
        request.node.name.replace("::", "_").replace("[", "_").replace("]", "_")
    )


# Pytest command line options
def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--run-performance", action="store_true", default=False, help="Run performance tests"
    )
    parser.addoption("--run-slow", action="store_true", default=False, help="Run slow tests")


def pytest_collection_modifyitems(config, items):
    """Apply skip markers.

    This hook used to be defined twice; the second definition shadowed the
    first, so the "skip integration tests when KuzuDB is missing" behaviour
    never ran. Both behaviours now live in this single hook.
    """
    # Skip integration tests if KuzuDB is not available.
    try:
        import kuzu  # noqa: F401  (presence check; used via ImportError below)

        kuzu_available = True
    except ImportError:
        kuzu_available = False

    skip_integration = pytest.mark.skip(reason="KuzuDB not available")
    for item in items:
        if "integration" in item.keywords and not kuzu_available:
            item.add_marker(skip_integration)

    # Skip performance / slow tests unless explicitly requested.
    if not config.getoption("--run-performance"):
        skip_performance = pytest.mark.skip(reason="need --run-performance option to run")
        for item in items:
            if "performance" in item.keywords:
                item.add_marker(skip_performance)

    if not config.getoption("--run-slow"):
        skip_slow = pytest.mark.skip(reason="need --run-slow option to run")
        for item in items:
            if "slow" in item.keywords:
                item.add_marker(skip_slow)
