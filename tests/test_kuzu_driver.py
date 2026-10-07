"""
Unit tests for KuzuDriver wrapper.
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from kuzuk.drivers.kuzu_wrapper import (
    KuzuDriver,
    KuzuDriverPool,
    create_high_performance_driver,
    create_read_only_driver,
    create_write_driver,
)


class TestKuzuDriver:
    """Test KuzuDriver functionality."""

    @pytest.fixture
    def temp_db_path(self):
        """Create temporary database path."""
        temp_dir = tempfile.mkdtemp()
        db_path = Path(temp_dir) / "test.kuzu"
        yield str(db_path)
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def driver(self, temp_db_path):
        """Create KuzuDriver instance."""
        return KuzuDriver(temp_db_path)

    @pytest.mark.unit
    def test_driver_initialization(self, temp_db_path):
        """Test driver initialization parameters."""
        driver = KuzuDriver(
            database_path=temp_db_path,
            buffer_pool_size=512 * 1024 * 1024,
            max_num_threads=2,
            enable_compression=False,
            read_only=True,
        )

        assert str(driver.database_path) == temp_db_path
        assert driver.buffer_pool_size == 512 * 1024 * 1024
        assert driver.max_num_threads == 2
        assert driver.enable_compression is False
        assert driver.read_only is True
        assert driver._initialized is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_driver_initialize(self, driver):
        """Test driver initialization."""
        assert not driver._initialized

        await driver.initialize()

        assert driver._initialized
        assert driver.database is not None
        assert driver.connection is not None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_driver_double_initialize(self, driver):
        """Test that double initialization is safe."""
        await driver.initialize()
        first_db = driver.database
        first_conn = driver.connection

        await driver.initialize()  # Second call should be no-op

        assert driver.database is first_db
        assert driver.connection is first_conn

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_query(self, driver):
        """Test query execution."""
        result = await driver.execute_query("RETURN 1 as test")

        assert result["success"] is True
        assert "rows" in result
        assert "columns" in result

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_read_query(self, driver):
        """Test read query execution."""
        result = await driver.execute_read_query("RETURN 1 as test")

        assert result["success"] is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_write_query_read_only(self, temp_db_path):
        """Test write query fails on read-only driver."""
        driver = KuzuDriver(temp_db_path, read_only=True)

        with pytest.raises(RuntimeError, match="Cannot execute write queries"):
            await driver.execute_write_query("CREATE NODE TABLE test(id INT64, PRIMARY KEY(id))")

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_health_check(self, driver):
        """Test health check functionality."""
        health = await driver.health_check()

        assert "healthy" in health
        assert "database_path" in health
        assert "checks" in health
        assert "response_time_ms" in health

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_get_schema_info(self, driver):
        """Test schema information retrieval."""
        schema = await driver.get_schema_info()

        assert "database_path" in schema
        assert "node_tables" in schema
        assert "rel_tables" in schema
        assert "total_tables" in schema

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_prepare_statement(self, driver):
        """Test statement preparation."""
        stmt = await driver.prepare_statement("RETURN $1 as value")

        assert stmt is not None

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_execute_prepared(self, driver):
        """Test prepared statement execution."""
        stmt = await driver.prepare_statement("RETURN 1 as value")
        result = await driver.execute_prepared(stmt)

        assert result["success"] is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_transaction_context(self, driver):
        """Test transaction context manager."""
        async with driver.transaction() as tx:
            assert tx is driver

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_driver_close(self, driver):
        """Test driver cleanup."""
        await driver.initialize()
        assert driver._initialized

        await driver.close()

        assert not driver._initialized
        assert driver.database is None
        assert driver.connection is None


class TestKuzuDriverPool:
    """Test KuzuDriverPool functionality."""

    @pytest.fixture
    def temp_db_path(self):
        """Create temporary database path."""
        temp_dir = tempfile.mkdtemp()
        db_path = Path(temp_dir) / "test.kuzu"
        yield str(db_path)
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def pool(self, temp_db_path):
        """Create KuzuDriverPool instance."""
        return KuzuDriverPool(temp_db_path, pool_size=3)

    @pytest.mark.unit
    def test_pool_initialization(self, temp_db_path):
        """Test pool initialization."""
        pool = KuzuDriverPool(temp_db_path, pool_size=5)

        assert pool.database_path == temp_db_path
        assert pool.pool_size == 5
        assert not pool._initialized
        assert len(pool.pool) == 0

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pool_initialize(self, pool):
        """Test pool initialization."""
        assert not pool._initialized

        await pool.initialize()

        assert pool._initialized
        assert len(pool.pool) == 3
        assert pool.available.qsize() == 3

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pool_get_connection(self, pool):
        """Test getting connection from pool."""
        await pool.initialize()

        async with pool.get_connection() as driver:
            assert isinstance(driver, KuzuDriver)
            assert driver._initialized

        # Connection should be returned to pool
        assert pool.available.qsize() == 3

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_pool_close(self, pool):
        """Test pool cleanup."""
        await pool.initialize()
        assert pool._initialized

        await pool.close()

        assert not pool._initialized
        assert len(pool.pool) == 0


class TestDriverFactories:
    """Test driver factory functions."""

    @pytest.fixture
    def temp_db_path(self):
        """Create temporary database path."""
        temp_dir = tempfile.mkdtemp()
        db_path = Path(temp_dir) / "test.kuzu"
        yield str(db_path)
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.mark.unit
    def test_create_read_only_driver(self, temp_db_path):
        """Test read-only driver factory."""
        driver = create_read_only_driver(temp_db_path)

        assert driver.read_only is True
        assert driver.buffer_pool_size == 512 * 1024 * 1024

    @pytest.mark.unit
    def test_create_write_driver(self, temp_db_path):
        """Test write driver factory."""
        driver = create_write_driver(temp_db_path)

        assert driver.read_only is False
        assert driver.buffer_pool_size == 1024 * 1024 * 1024

    @pytest.mark.unit
    def test_create_high_performance_driver(self, temp_db_path):
        """Test high-performance driver factory."""
        driver = create_high_performance_driver(temp_db_path)

        assert driver.read_only is False
        assert driver.buffer_pool_size == 4 * 1024 * 1024 * 1024
        assert driver.max_num_threads == 8
        assert driver.enable_compression is True


# Mock tests for when KuzuDB is not available
class TestMockImplementation:
    """Test mock implementation when KuzuDB is not available."""

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_mock_driver_works(self):
        """Test that mock driver works when KuzuDB is not available."""
        with patch("kuzuk.drivers.kuzu_wrapper.KUZU_AVAILABLE", False):
            driver = KuzuDriver("/tmp/mock.kuzu")
            await driver.initialize()

            result = await driver.execute_query("RETURN 1 as test")
            assert result["success"] is True

            await driver.close()


if __name__ == "__main__":
    pytest.main([__file__])
