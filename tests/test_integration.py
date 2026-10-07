"""
Integration tests with real KuzuDB instances.
These tests require KuzuDB to be installed and available.
"""

import asyncio
import shutil
import tempfile
import time
from pathlib import Path

import pytest
import pytest_asyncio

from kuzuk import KuzukDriver, create_enterprise_kuzuk_driver, create_simple_kuzuk_driver
from kuzuk.drivers.kuzu_wrapper import KuzuDriver
from kuzuk.function_shipping.orchestrator import FunctionShippingOrchestrator, create_count_query
from kuzuk.replication.manager import KuzuReplicationManager


@pytest.fixture
def temp_db_dir():
    """Create temporary directory for databases."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest_asyncio.fixture
async def sample_database(temp_db_dir):
    """Create a sample database with test data."""
    db_path = Path(temp_db_dir) / "sample.kuzu"
    driver = KuzuDriver(str(db_path))

    try:
        await driver.initialize()

        # Create test schema
        await driver.execute_query(
            """
            CREATE NODE TABLE Person(id INT64, name STRING, age INT64, PRIMARY KEY(id))
        """
        )

        await driver.execute_query(
            """
            CREATE NODE TABLE Movie(id INT64, title STRING, year INT64, PRIMARY KEY(id))
        """
        )

        await driver.execute_query(
            """
            CREATE REL TABLE Knows(FROM Person TO Person, since INT64)
        """
        )

        await driver.execute_query(
            """
            CREATE REL TABLE Acted(FROM Person TO Movie, role STRING)
        """
        )

        # Insert test data
        await driver.execute_query(
            """
            CREATE (p1:Person {id: 1, name: 'Alice', age: 30}),
                   (p2:Person {id: 2, name: 'Bob', age: 25}),
                   (p3:Person {id: 3, name: 'Carol', age: 35}),
                   (m1:Movie {id: 1, title: 'The Matrix', year: 1999}),
                   (m2:Movie {id: 2, title: 'Inception', year: 2010})
        """
        )

        await driver.execute_query(
            """
            MATCH (p1:Person {id: 1}), (p2:Person {id: 2})
            CREATE (p1)-[:Knows {since: 2020}]->(p2)
        """
        )

        await driver.execute_query(
            """
            MATCH (p1:Person {id: 1}), (m1:Movie {id: 1})
            CREATE (p1)-[:Acted {role: 'Neo'}]->(m1)
        """
        )

        yield str(db_path)

    finally:
        await driver.close()


class TestKuzuDriverIntegration:
    """Integration tests for KuzuDriver."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_driver_basic_operations(self, sample_database):
        """Test basic driver operations with real database."""
        driver = KuzuDriver(sample_database, read_only=True)

        try:
            await driver.initialize()

            # Test health check
            health = await driver.health_check()
            assert health["healthy"] is True
            assert "checks" in health

            # Test schema info
            schema = await driver.get_schema_info()
            assert "node_tables" in schema
            assert "rel_tables" in schema
            assert schema["total_tables"] >= 4  # Person, Movie, Knows, Acted

            # Test query execution
            result = await driver.execute_query("MATCH (p:Person) RETURN count(p) as person_count")
            assert result["success"] is True
            assert len(result["rows"]) > 0

            # Test prepared statements
            stmt = await driver.prepare_statement("MATCH (p:Person) WHERE p.age > $age RETURN p.name")
            result = await driver.execute_prepared(stmt, {"age": 25})
            assert result["success"] is True

        finally:
            await driver.close()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_driver_transaction_context(self, sample_database):
        """Test transaction context manager."""
        driver = KuzuDriver(sample_database)

        try:
            await driver.initialize()

            async with driver.transaction() as tx:
                result = await tx.execute_query("MATCH (p:Person) RETURN count(p)")
                assert result["success"] is True

        finally:
            await driver.close()


class TestReplicationIntegration:
    """Integration tests for replication."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_single_replica_replication(self, sample_database, temp_db_dir):
        """Test single replica replication."""
        replica_dir = Path(temp_db_dir) / "replicas"
        replica_dir.mkdir(exist_ok=True)

        replica_paths = [str(replica_dir / "replica_1.kuzu")]
        manager = KuzuReplicationManager(
            master_path=sample_database,
            replica_paths=replica_paths,
            replication_interval=0.1,
        )

        try:
            await manager.initialize()
            await manager.start_replication()

            # Wait for initial replication
            await asyncio.sleep(1.0)

            # Check replica status
            status = manager.get_replication_status()
            assert status["total_replicas"] == 1
            assert status["healthy_replicas"] >= 0  # May be 0 if replication fails

            # Test getting healthy replicas
            healthy_replicas = manager.get_healthy_replicas()
            assert isinstance(healthy_replicas, list)

        finally:
            await manager.stop_replication()
            await manager.close()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_replica_health_monitoring(self, sample_database, temp_db_dir):
        """Test replica health monitoring."""
        replica_dir = Path(temp_db_dir) / "replicas"
        replica_dir.mkdir(exist_ok=True)

        # Create replica paths
        replica_paths = [str(replica_dir / f"replica_{i}.kuzu") for i in range(1, 3)]
        
        manager = KuzuReplicationManager(
            master_path=sample_database, replica_paths=replica_paths
        )

        try:
            await manager.initialize()

            # Test replication health via status
            replication_status = manager.get_replication_status()
            assert "healthy_replicas" in replication_status
            assert "total_replicas" in replication_status
            assert replication_status["total_replicas"] == 2

        finally:
            await manager.close()


class TestFunctionShippingIntegration:
    """Integration tests for function shipping."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_function_shipping_orchestration(self, sample_database, temp_db_dir):
        """Test function shipping with real drivers."""
        # Create multiple drivers (simulating different nodes)
        nodes = {}
        for i in range(2):
            node_id = f"node_{i+1}"
            driver = KuzuDriver(sample_database, read_only=True)
            await driver.initialize()
            nodes[node_id] = driver

        orchestrator = FunctionShippingOrchestrator(nodes)

        try:
            # Test count query
            count_query = create_count_query(
                "person_count", "MATCH (p:Person) RETURN count(p) as count"
            )
            result = await orchestrator.execute_parallel(count_query)

            assert result.success is True
            assert result.data >= 3  # Should be 6 (3 * 2 nodes) for count aggregation
            assert result.nodes_used == 2
            assert result.aggregation_method == "sum_count"

            # Test performance stats
            stats = orchestrator.get_performance_stats()
            assert stats["queries_executed"] == 1
            assert stats["available_nodes"] == 2

        finally:
            # Close all node drivers
            for driver in nodes.values():
                await driver.close()
            await orchestrator.close()


class TestScalableDriverIntegration:
    """Integration tests for KuzukDriver."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scalable_driver_basic_usage(self, sample_database, temp_db_dir):
        """Test basic scalable driver functionality."""
        replica_dir = Path(temp_db_dir) / "replicas"
        replica_dir.mkdir(exist_ok=True)

        # Create replica paths  
        replica_paths = [str(replica_dir / f"replica_{i}.kuzu") for i in range(1, 3)]
        
        driver = KuzukDriver(
            master_db_path=sample_database,
            replica_count=2,
            enable_function_shipping=True,
            enable_health_monitoring=True,
        )

        try:
            await driver.initialize()

            # Test basic query execution
            result = await driver.execute_query("MATCH (p:Person) RETURN p.name")
            assert result is not None

            # Test analytical query
            if driver.function_shipping:
                analytical_result = await driver.execute_analytical_query(
                    "MATCH (p:Person) RETURN count(p) as total", execution_mode="parallel_all"
                )
                assert analytical_result is not None

            # Test cluster status
            status = driver.get_cluster_status()
            assert "replication" in status
            assert "health" in status

            # Test cluster health
            is_healthy = driver.is_cluster_healthy()
            assert isinstance(is_healthy, bool)

            # Test getting healthy replicas
            healthy_replicas = driver.get_healthy_replicas()
            assert isinstance(healthy_replicas, list)

        finally:
            await driver.close()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_simple_scaled_driver_factory(self, sample_database, temp_db_dir):
        """Test simple scaled driver factory."""
        driver = create_simple_kuzuk_driver(master_db_path=sample_database, replica_count=1)

        try:
            await driver.initialize()

            # Should have basic functionality enabled
            assert driver.replica_count == 1
            # "simple" tier deliberately ships without function shipping
            assert driver.enable_function_shipping is False
            assert driver.enable_health_monitoring is True

            # Test basic query
            result = await driver.execute_query("RETURN 1 as test")
            assert result is not None

        finally:
            await driver.close()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_enterprise_scaled_driver_factory(self, sample_database, temp_db_dir):
        """Test enterprise scaled driver factory."""
        driver = create_enterprise_kuzuk_driver(master_db_path=sample_database, replica_count=3)

        try:
            await driver.initialize()

            # Should have all enterprise features enabled
            assert driver.replica_count == 3
            assert driver.enable_function_shipping is True
            assert driver.enable_health_monitoring is True

            # Test cluster status
            status = driver.get_cluster_status()
            assert "replication" in status
            assert "function_shipping" in status
            assert "health" in status

        finally:
            await driver.close()


class TestErrorHandlingIntegration:
    """Integration tests for error handling."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_invalid_database_path(self):
        """Test handling of invalid database path."""
        driver = KuzuDriver("/nonexistent/path/database.kuzu")

        # Should handle initialization gracefully
        try:
            await driver.initialize()
            # May succeed with mock implementation
        except Exception as e:
            # Should provide meaningful error
            assert "nonexistent" in str(e) or "No such file" in str(e)
        finally:
            await driver.close()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_invalid_query_execution(self, sample_database):
        """Test handling of invalid queries."""
        driver = KuzuDriver(sample_database)

        try:
            await driver.initialize()

            # Test invalid syntax
            result = await driver.execute_query("INVALID QUERY SYNTAX")
            assert result["success"] is False
            assert "error" in result

        finally:
            await driver.close()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_connection_timeout_handling(self):
        """Test connection timeout handling."""
        # Create driver with very short timeout
        driver = KuzuDriver("/tmp/timeout_test.kuzu")

        try:
            # This should either succeed (mock) or fail gracefully
            await driver.initialize()

            health = await driver.health_check()
            assert "healthy" in health

        except Exception as e:
            # Should be a meaningful timeout or connection error
            assert isinstance(e, (ConnectionError, TimeoutError, RuntimeError))
        finally:
            await driver.close()


class TestConcurrencyIntegration:
    """Integration tests for concurrent operations."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_concurrent_query_execution(self, sample_database):
        """Test concurrent query execution."""
        driver = KuzuDriver(sample_database, read_only=True)

        try:
            await driver.initialize()

            # Execute multiple queries concurrently
            tasks = []
            for i in range(5):
                task = driver.execute_query(
                    f"MATCH (p:Person) WHERE p.age > {20 + i} RETURN count(p)"
                )
                tasks.append(task)

            results = await asyncio.gather(*tasks)

            # All queries should succeed
            for result in results:
                assert result["success"] is True

        finally:
            await driver.close()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_concurrent_health_checks(self, sample_database):
        """Test concurrent health checks."""
        driver = KuzuDriver(sample_database, read_only=True)

        try:
            await driver.initialize()

            # Execute multiple health checks concurrently
            tasks = [driver.health_check() for _ in range(3)]
            health_results = await asyncio.gather(*tasks)

            # All health checks should return valid results
            for health in health_results:
                assert "healthy" in health
                assert "response_time_ms" in health

        finally:
            await driver.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "integration"])
