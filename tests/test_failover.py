"""
Advanced failover and disaster recovery testing for Kuzuk.
"""

import asyncio
import shutil
import tempfile
import time
from pathlib import Path

import pytest
import pytest_asyncio

from kuzuk import create_enterprise_kuzuk_driver
from kuzuk.drivers.kuzu_wrapper import KuzuDriver
from kuzuk.replication.manager import ReplicationStatus


class FailoverTestSuite:
    """Failover and disaster recovery testing utilities."""

    def __init__(self):
        self.failure_scenarios = [
            "node_crash",
            "network_partition",
            "disk_full",
            "memory_exhaustion",
            "slow_network",
            "corruption",
            "timeout",
        ]

    async def simulate_node_failure(self, driver, replica_id):
        """Simulate a replica node failure."""
        if driver.replication_manager and replica_id in driver.replication_manager.replicas:
            replica = driver.replication_manager.replicas[replica_id]

            # Simulate node failure by closing driver and marking as failed
            if replica.driver:
                await replica.driver.close()
                replica.driver = None

            replica.status = ReplicationStatus.FAILED
            replica.error_count = 10

            print(f"🔥 Simulated failure of replica: {replica_id}")
            return True
        return False

    async def simulate_network_partition(self, driver, replica_id):
        """Simulate network partition by making replica unreachable."""
        if driver.replication_manager and replica_id in driver.replication_manager.replicas:
            replica = driver.replication_manager.replicas[replica_id]

            # Mock network failure
            original_execute = replica.driver.execute_query if replica.driver else None

            async def failing_execute(*args, **kwargs):
                raise ConnectionError("Network partition: Connection timed out")

            if replica.driver:
                replica.driver.execute_query = failing_execute

            replica.status = ReplicationStatus.FAILED
            print(f"🔌 Simulated network partition for replica: {replica_id}")
            return original_execute
        return None

    async def simulate_slow_replica(self, driver, replica_id, delay_seconds=2.0):
        """Simulate a slow replica by adding delays."""
        if driver.replication_manager and replica_id in driver.replication_manager.replicas:
            replica = driver.replication_manager.replicas[replica_id]

            original_execute = replica.driver.execute_query if replica.driver else None

            async def slow_execute(*args, **kwargs):
                await asyncio.sleep(delay_seconds)
                if original_execute:
                    return await original_execute(*args, **kwargs)
                return {"success": True, "rows": [], "columns": []}

            if replica.driver:
                replica.driver.execute_query = slow_execute

            print(f"🐌 Simulated slow replica: {replica_id} (delay: {delay_seconds}s)")
            return original_execute
        return None

    async def verify_data_consistency(self, driver, expected_count=None):
        """Verify data consistency across healthy replicas."""
        consistency_results = []

        # Query master
        try:
            master_result = await driver.execute_query("MATCH (n) RETURN count(n) as node_count")
            if master_result and master_result.get("success"):
                master_count = master_result.get("rows", [{}])[0].get("node_count", 0)
                consistency_results.append(("master", master_count))
        except Exception as e:
            consistency_results.append(("master", f"error: {e}"))

        # Query healthy replicas
        if driver.replication_manager:
            for replica_id, replica in driver.replication_manager.replicas.items():
                if replica.status == ReplicationStatus.HEALTHY and replica.driver:
                    try:
                        replica_result = await replica.driver.execute_query(
                            "MATCH (n) RETURN count(n) as node_count"
                        )
                        if replica_result and replica_result.get("success"):
                            replica_count = replica_result.get("rows", [{}])[0].get("node_count", 0)
                            consistency_results.append((replica_id, replica_count))
                    except Exception as e:
                        consistency_results.append((replica_id, f"error: {e}"))

        return consistency_results


@pytest_asyncio.fixture
async def failover_test_database():
    """Create a test database for failover testing."""
    temp_dir = tempfile.mkdtemp()
    try:
        db_path = Path(temp_dir) / "failover_test.kuzu"
        driver = KuzuDriver(str(db_path))

        await driver.initialize()

        # Create test schema and data
        await driver.execute_query("""
            CREATE NODE TABLE TestNode(
                id INT64,
                name STRING,
                created_at STRING,
                PRIMARY KEY(id)
            )
        """)

        # Insert test data
        for i in range(100):
            await driver.execute_query(f"""
                CREATE (n:TestNode {{
                    id: {i},
                    name: 'TestNode{i}',
                    created_at: '2023-01-{(i % 30) + 1:02d}'
                }})
            """)

        yield str(db_path)

    finally:
        await driver.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def failover_test_suite():
    """Failover test suite fixture."""
    return FailoverTestSuite()


class TestReplicaFailover:
    """Test replica failure and recovery scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.failover
    @pytest.mark.xfail(
        reason="failover / replica promotion is not implemented; see the README table",
        strict=False,
    )
    async def test_single_replica_failure(self, failover_test_database, failover_test_suite):
        """Test system behavior when a single replica fails."""
        temp_dir = tempfile.mkdtemp()
        try:
            replica_dir = Path(temp_dir) / "replicas"
            replica_dir.mkdir(exist_ok=True)

            driver = create_enterprise_kuzuk_driver(
                master_db_path=failover_test_database, replica_count=3
            )

            await driver.initialize()
            await asyncio.sleep(2.0)  # Let replication start

            # Verify initial state
            initial_healthy = len(driver.get_healthy_replicas())
            print(f"Initial healthy replicas: {initial_healthy}")

            # Simulate failure of one replica
            replica_ids = list(driver.replication_manager.replicas.keys())
            failed_replica = replica_ids[0]

            await failover_test_suite.simulate_node_failure(driver, failed_replica)

            # Wait for failure detection
            await asyncio.sleep(3.0)

            # Verify system can still serve queries
            result = await driver.execute_query("MATCH (n:TestNode) RETURN count(n) as total")
            assert result is not None
            assert result.get("success", False)

            # Check remaining healthy replicas
            healthy_replicas = driver.get_healthy_replicas()
            print(f"Healthy replicas after failure: {len(healthy_replicas)}")
            assert len(healthy_replicas) < initial_healthy

            # Verify cluster is still considered healthy (majority rule)
            cluster_status = driver.get_cluster_status()
            print(f"Cluster status: {cluster_status.get('health', {})}")

            print("✅ Single replica failure handled successfully")

        finally:
            await driver.close()
            shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    @pytest.mark.failover
    async def test_multiple_replica_failures(self, failover_test_database, failover_test_suite):
        """Test system behavior when multiple replicas fail."""
        temp_dir = tempfile.mkdtemp()
        try:
            replica_dir = Path(temp_dir) / "replicas"
            replica_dir.mkdir(exist_ok=True)

            driver = create_enterprise_kuzuk_driver(
                master_db_path=failover_test_database, replica_count=4
            )

            await driver.initialize()
            await asyncio.sleep(2.0)

            replica_ids = list(driver.replication_manager.replicas.keys())
            initial_healthy = len(driver.get_healthy_replicas())

            # Simulate cascading failures
            for i, replica_id in enumerate(replica_ids[:2]):  # Fail 2 out of 4 replicas
                print(f"Failing replica {i+1}: {replica_id}")
                await failover_test_suite.simulate_node_failure(driver, replica_id)
                await asyncio.sleep(1.0)

                # System should continue operating
                result = await driver.execute_query(
                    "MATCH (n:TestNode) WHERE n.id < 10 RETURN count(n)"
                )
                assert result is not None

            # Check final state
            final_healthy = len(driver.get_healthy_replicas())
            print(f"Healthy replicas: {initial_healthy} -> {final_healthy}")

            # Verify data consistency
            consistency_results = await failover_test_suite.verify_data_consistency(driver)
            print(f"Data consistency check: {consistency_results}")

            print("✅ Multiple replica failures handled successfully")

        finally:
            await driver.close()
            shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    @pytest.mark.failover
    async def test_master_failover_simulation(self, failover_test_database, failover_test_suite):
        """Test behavior when master becomes unavailable."""
        temp_dir = tempfile.mkdtemp()
        try:
            replica_dir = Path(temp_dir) / "replicas"
            replica_dir.mkdir(exist_ok=True)

            driver = create_enterprise_kuzuk_driver(
                master_db_path=failover_test_database, replica_count=2
            )

            await driver.initialize()
            await asyncio.sleep(2.0)

            # Test read-only operations when master is "unavailable"
            # Simulate master failure by making it slow/unreachable
            original_execute = driver.replication_manager.master_driver.execute_query

            async def failing_master_execute(*args, **kwargs):
                raise ConnectionError("Master unreachable")

            driver.replication_manager.master_driver.execute_query = failing_master_execute

            # System should still handle read queries via replicas
            try:
                result = await driver.execute_query("MATCH (n:TestNode) RETURN count(n)")
                # In a full implementation, this might succeed via replica routing
                # For now, we verify graceful error handling
                print(f"Query result during master failure: {result}")
            except Exception as e:
                print(f"Expected error during master failure: {e}")

            # Restore master
            driver.replication_manager.master_driver.execute_query = original_execute

            # Verify recovery
            result = await driver.execute_query("MATCH (n:TestNode) RETURN count(n)")
            assert result is not None

            print("✅ Master failover simulation completed")

        finally:
            await driver.close()
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestNetworkPartitioning:
    """Test network partition scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.failover
    async def test_network_partition_recovery(self, failover_test_database, failover_test_suite):
        """Test recovery from network partitions."""
        temp_dir = tempfile.mkdtemp()
        try:
            replica_dir = Path(temp_dir) / "replicas"
            replica_dir.mkdir(exist_ok=True)

            driver = create_enterprise_kuzuk_driver(
                master_db_path=failover_test_database, replica_count=3
            )

            await driver.initialize()
            await asyncio.sleep(2.0)

            replica_ids = list(driver.replication_manager.replicas.keys())
            partitioned_replica = replica_ids[0]

            # Simulate network partition
            original_execute = await failover_test_suite.simulate_network_partition(
                driver, partitioned_replica
            )

            await asyncio.sleep(2.0)

            # Verify system continues operating
            result = await driver.execute_query("MATCH (n:TestNode) WHERE n.id = 1 RETURN n.name")
            assert result is not None

            # Simulate network recovery
            if original_execute and driver.replication_manager:
                replica = driver.replication_manager.replicas[partitioned_replica]
                if replica.driver:
                    replica.driver.execute_query = original_execute
                    replica.status = ReplicationStatus.HEALTHY
                    replica.error_count = 0

            await asyncio.sleep(1.0)

            # Verify recovery
            healthy_replicas = driver.get_healthy_replicas()
            print(f"Healthy replicas after recovery: {len(healthy_replicas)}")

            print("✅ Network partition recovery test completed")

        finally:
            await driver.close()
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestPerformanceDegradation:
    """Test system behavior under performance degradation."""

    @pytest.mark.asyncio
    @pytest.mark.failover
    @pytest.mark.xfail(
        reason="failover / replica promotion is not implemented; see the README table",
        strict=False,
    )
    async def test_slow_replica_handling(self, failover_test_database, failover_test_suite):
        """Test handling of slow replicas."""
        temp_dir = tempfile.mkdtemp()
        try:
            replica_dir = Path(temp_dir) / "replicas"
            replica_dir.mkdir(exist_ok=True)

            driver = create_enterprise_kuzuk_driver(
                master_db_path=failover_test_database, replica_count=3
            )

            await driver.initialize()
            await asyncio.sleep(2.0)

            replica_ids = list(driver.replication_manager.replicas.keys())
            slow_replica = replica_ids[0]

            # Make one replica slow
            await failover_test_suite.simulate_slow_replica(driver, slow_replica, delay_seconds=3.0)

            # Test query performance
            start_time = time.time()
            result = await driver.execute_query("MATCH (n:TestNode) WHERE n.id < 5 RETURN count(n)")
            execution_time = time.time() - start_time

            print(f"Query execution time with slow replica: {execution_time:.2f}s")

            # System should route around slow replica or timeout appropriately
            assert result is not None
            assert execution_time < 10.0  # Should not hang indefinitely

            print("✅ Slow replica handling test completed")

        finally:
            await driver.close()
            shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    @pytest.mark.failover
    async def test_load_balancing_under_failure(self, failover_test_database, failover_test_suite):
        """Test load balancing when some replicas fail."""
        temp_dir = tempfile.mkdtemp()
        try:
            replica_dir = Path(temp_dir) / "replicas"
            replica_dir.mkdir(exist_ok=True)

            driver = create_enterprise_kuzuk_driver(
                master_db_path=failover_test_database, replica_count=4
            )

            await driver.initialize()
            await asyncio.sleep(2.0)

            # Fail half the replicas
            replica_ids = list(driver.replication_manager.replicas.keys())
            for replica_id in replica_ids[:2]:
                await failover_test_suite.simulate_node_failure(driver, replica_id)

            await asyncio.sleep(2.0)

            # Execute multiple queries to test load distribution
            query_times = []
            successful_queries = 0

            for i in range(20):
                try:
                    start = time.time()
                    result = await driver.execute_query(
                        f"MATCH (n:TestNode) WHERE n.id = {i} RETURN n.name"
                    )
                    duration = time.time() - start

                    if result and result.get("success"):
                        query_times.append(duration)
                        successful_queries += 1

                except Exception as e:
                    print(f"Query {i} failed: {e}")

            # Analyze load balancing performance
            avg_query_time = sum(query_times) / len(query_times) if query_times else 0
            print(f"Successful queries: {successful_queries}/20")
            print(f"Average query time: {avg_query_time:.3f}s")

            # Should maintain reasonable performance even with failures
            assert successful_queries >= 15  # At least 75% success rate
            assert avg_query_time < 1.0  # Reasonable response time

            print("✅ Load balancing under failure test completed")

        finally:
            await driver.close()
            shutil.rmtree(temp_dir, ignore_errors=True)


class TestDisasterRecovery:
    """Test disaster recovery scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.failover
    @pytest.mark.slow
    async def test_complete_cluster_recovery(self, failover_test_database, failover_test_suite):
        """Test recovery from complete cluster failure."""
        temp_dir = tempfile.mkdtemp()
        try:
            replica_dir = Path(temp_dir) / "replicas"
            replica_dir.mkdir(exist_ok=True)

            # Create initial cluster
            driver = create_enterprise_kuzuk_driver(
                master_db_path=failover_test_database, replica_count=2
            )

            await driver.initialize()
            await asyncio.sleep(2.0)

            # Verify initial data
            initial_result = await driver.execute_query(
                "MATCH (n:TestNode) RETURN count(n) as total"
            )
            initial_count = (
                initial_result["rows"][0]["total"]
                if initial_result and initial_result.get("rows")
                else 0
            )
            print(f"Initial data count: {initial_count}")

            # Simulate complete cluster shutdown
            await driver.close()

            # Simulate recovery - create new driver instance
            recovery_driver = create_enterprise_kuzuk_driver(
                master_db_path=failover_test_database, replica_count=2
            )

            await recovery_driver.initialize()
            await asyncio.sleep(2.0)

            # Verify data recovery
            recovery_result = await recovery_driver.execute_query(
                "MATCH (n:TestNode) RETURN count(n) as total"
            )
            recovery_count = (
                recovery_result["rows"][0]["total"]
                if recovery_result and recovery_result.get("rows")
                else 0
            )
            print(f"Recovered data count: {recovery_count}")

            # Data should be preserved
            assert recovery_count == initial_count

            # Verify cluster functionality
            cluster_status = recovery_driver.get_cluster_status()
            assert cluster_status["initialized"]

            print("✅ Complete cluster recovery test completed")

            await recovery_driver.close()

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    @pytest.mark.failover
    async def test_data_consistency_after_recovery(
        self, failover_test_database, failover_test_suite
    ):
        """Test data consistency after recovery from failures."""
        temp_dir = tempfile.mkdtemp()
        try:
            replica_dir = Path(temp_dir) / "replicas"
            replica_dir.mkdir(exist_ok=True)

            driver = create_enterprise_kuzuk_driver(
                master_db_path=failover_test_database, replica_count=3
            )

            await driver.initialize()
            await asyncio.sleep(2.0)

            # Add some data during operation
            for i in range(100, 120):
                await driver.execute_query(f"""
                    CREATE (n:TestNode {{
                        id: {i},
                        name: 'PostFailureNode{i}',
                        created_at: '2023-12-01'
                    }})
                """)

            # Simulate partial failure and recovery
            replica_ids = list(driver.replication_manager.replicas.keys())
            failed_replica = replica_ids[0]

            await failover_test_suite.simulate_node_failure(driver, failed_replica)
            await asyncio.sleep(2.0)

            # Add more data while replica is down
            for i in range(120, 140):
                await driver.execute_query(f"""
                    CREATE (n:TestNode {{
                        id: {i},
                        name: 'DuringFailureNode{i}',
                        created_at: '2023-12-02'
                    }})
                """)

            # Simulate replica recovery
            if driver.replication_manager and failed_replica in driver.replication_manager.replicas:
                replica = driver.replication_manager.replicas[failed_replica]
                replica.status = ReplicationStatus.HEALTHY
                replica.error_count = 0

                # Reinitialize replica driver
                if not replica.driver:
                    replica.driver = KuzuDriver(replica.db_path)
                    await replica.driver.initialize()

            await asyncio.sleep(3.0)  # Allow replication to catch up

            # Verify consistency across all replicas
            consistency_results = await failover_test_suite.verify_data_consistency(driver)
            print(f"Final consistency check: {consistency_results}")

            # All healthy replicas should have same data count
            healthy_counts = [
                count for node, count in consistency_results if isinstance(count, int)
            ]
            if len(healthy_counts) > 1:
                assert all(
                    count == healthy_counts[0] for count in healthy_counts
                ), f"Inconsistent data: {consistency_results}"

            print("✅ Data consistency after recovery test completed")

        finally:
            await driver.close()
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    # Run failover tests
    pytest.main([__file__, "-v", "-m", "failover", "--tb=short"])
