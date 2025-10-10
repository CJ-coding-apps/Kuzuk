"""
Performance benchmarking for Kuzuk components.
"""

import asyncio
import os
import shutil
import statistics
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psutil
import pytest

from kuzuk import KuzukDriver
from kuzuk.drivers.kuzu_wrapper import KuzuDriver, KuzuDriverPool
from kuzuk.function_shipping.orchestrator import FunctionShippingOrchestrator, create_count_query
from kuzuk.replication.manager import KuzuReplicationManager


class PerformanceBenchmark:
    """Base class for performance benchmarks."""

    def __init__(self, name: str):
        self.name = name
        self.results = []
        self.start_time = None
        self.end_time = None
        self.process = psutil.Process()
        self.initial_memory = None
        self.peak_memory = None

    def start(self):
        """Start benchmark timing."""
        self.start_time = time.perf_counter()
        self.initial_memory = self.process.memory_info().rss

    def end(self):
        """End benchmark timing."""
        self.end_time = time.perf_counter()
        self.peak_memory = self.process.memory_info().rss

    def add_result(self, duration: float, success: bool = True, metadata: dict = None):
        """Add a benchmark result."""
        self.results.append({"duration": duration, "success": success, "metadata": metadata or {}})

    def get_stats(self) -> dict:
        """Get benchmark statistics."""
        if not self.results:
            return {"error": "No results recorded"}

        durations = [r["duration"] for r in self.results if r["success"]]
        success_count = sum(1 for r in self.results if r["success"])

        total_duration = self.end_time - self.start_time if self.start_time and self.end_time else 0
        memory_used = (
            self.peak_memory - self.initial_memory
            if self.peak_memory and self.initial_memory
            else 0
        )

        return {
            "name": self.name,
            "total_operations": len(self.results),
            "successful_operations": success_count,
            "success_rate": success_count / len(self.results),
            "total_duration": total_duration,
            "avg_duration": statistics.mean(durations) if durations else 0,
            "min_duration": min(durations) if durations else 0,
            "max_duration": max(durations) if durations else 0,
            "median_duration": statistics.median(durations) if durations else 0,
            "std_deviation": statistics.stdev(durations) if len(durations) > 1 else 0,
            "operations_per_second": success_count / total_duration if total_duration > 0 else 0,
            "memory_used_mb": memory_used / (1024 * 1024),
            "results": self.results,
        }


@pytest.fixture
def temp_db_dir():
    """Create temporary directory for test databases."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
async def benchmark_database(temp_db_dir):
    """Create a database with benchmark data."""
    db_path = Path(temp_dir) / "benchmark.kuzu"
    driver = KuzuDriver(str(db_path))

    try:
        await driver.initialize()

        # Create schema
        await driver.execute_query(
            """
            CREATE NODE TABLE User(id INT64, name STRING, age INT64, city STRING, PRIMARY KEY(id))
        """
        )

        await driver.execute_query(
            """
            CREATE NODE TABLE Product(id INT64, name STRING, price DOUBLE, category STRING, PRIMARY KEY(id))
        """
        )

        await driver.execute_query(
            """
            CREATE REL TABLE Purchases(FROM User TO Product, quantity INT64, date STRING)
        """
        )

        # Insert benchmark data
        for i in range(1000):
            await driver.execute_query(
                f"""
                CREATE (u:User {{id: {i}, name: 'User{i}', age: {20 + (i % 50)}, city: 'City{i % 10}'}})
            """
            )

        for i in range(500):
            await driver.execute_query(
                f"""
                CREATE (p:Product {{id: {i}, name: 'Product{i}', price: {10.0 + (i % 100)}, category: 'Category{i % 5}'}})
            """
            )

        # Create some relationships
        for i in range(0, 1000, 10):
            product_id = i % 500
            await driver.execute_query(
                f"""
                MATCH (u:User {{id: {i}}}), (p:Product {{id: {product_id}}})
                CREATE (u)-[:Purchases {{quantity: {1 + (i % 5)}, date: '2023-01-01'}}]->(p)
            """
            )

        yield str(db_path)

    finally:
        await driver.close()


class TestKuzuDriverPerformance:
    """Performance tests for KuzuDriver."""

    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_query_execution_performance(self, benchmark_database):
        """Benchmark query execution performance."""
        benchmark = PerformanceBenchmark("query_execution")
        driver = KuzuDriver(benchmark_database, read_only=True)

        try:
            await driver.initialize()
            benchmark.start()

            # Benchmark different types of queries
            queries = [
                "MATCH (u:User) RETURN count(u)",
                "MATCH (u:User) WHERE u.age > 30 RETURN count(u)",
                "MATCH (u:User)-[:Purchases]->(p:Product) RETURN count(*)",
                "MATCH (u:User) WHERE u.city = 'City1' RETURN u.name",
                "MATCH (p:Product) WHERE p.price > 50 RETURN p.name, p.price",
            ]

            for _ in range(50):  # Run each query multiple times
                for query in queries:
                    start = time.perf_counter()
                    result = await driver.execute_query(query)
                    duration = time.perf_counter() - start

                    benchmark.add_result(duration, result.get("success", False))

            benchmark.end()
            stats = benchmark.get_stats()

            # Performance assertions
            assert stats["success_rate"] > 0.95, "Success rate should be > 95%"
            assert stats["avg_duration"] < 1.0, "Average query time should be < 1 second"

            print(f"Query Performance: {stats['operations_per_second']:.2f} ops/sec")
            print(f"Average duration: {stats['avg_duration']:.3f}s")

        finally:
            await driver.close()

    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_concurrent_query_performance(self, benchmark_database):
        """Benchmark concurrent query performance."""
        benchmark = PerformanceBenchmark("concurrent_queries")
        driver = KuzuDriver(benchmark_database, read_only=True)

        try:
            await driver.initialize()
            benchmark.start()

            async def execute_queries(query_count: int):
                """Execute multiple queries concurrently."""
                tasks = []
                for i in range(query_count):
                    query = f"MATCH (u:User) WHERE u.id = {i % 1000} RETURN u.name"
                    task = driver.execute_query(query)
                    tasks.append(task)

                start = time.perf_counter()
                results = await asyncio.gather(*tasks, return_exceptions=True)
                duration = time.perf_counter() - start

                success_count = sum(
                    1 for r in results if not isinstance(r, Exception) and r.get("success")
                )
                return duration, success_count, len(results)

            # Test different concurrency levels
            for concurrency in [10, 25, 50]:
                duration, successes, total = await execute_queries(concurrency)
                benchmark.add_result(
                    duration,
                    successes == total,
                    {"concurrency": concurrency, "successes": successes, "total": total},
                )

            benchmark.end()
            stats = benchmark.get_stats()

            print(f"Concurrent Query Performance: {stats['operations_per_second']:.2f} batches/sec")

        finally:
            await driver.close()

    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_connection_pool_performance(self, benchmark_database):
        """Benchmark connection pool performance."""
        benchmark = PerformanceBenchmark("connection_pool")

        pool = KuzuDriverPool(benchmark_database, pool_size=5, read_only=True)

        try:
            await pool.initialize()
            benchmark.start()

            async def pool_operation():
                """Single pool operation."""
                async with pool.get_connection() as driver:
                    result = await driver.execute_query("MATCH (u:User) RETURN count(u)")
                    return result.get("success", False)

            # Execute operations using the pool
            for _ in range(100):
                start = time.perf_counter()
                success = await pool_operation()
                duration = time.perf_counter() - start
                benchmark.add_result(duration, success)

            benchmark.end()
            stats = benchmark.get_stats()

            print(f"Pool Performance: {stats['operations_per_second']:.2f} ops/sec")

        finally:
            await pool.close()


class TestFunctionShippingPerformance:
    """Performance tests for function shipping."""

    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_function_shipping_scalability(self, benchmark_database):
        """Benchmark function shipping scalability."""
        benchmark = PerformanceBenchmark("function_shipping_scalability")

        # Test with different numbers of nodes
        for node_count in [1, 2, 4]:
            nodes = {}
            drivers = []

            try:
                # Create nodes
                for i in range(node_count):
                    driver = KuzuDriver(benchmark_database, read_only=True)
                    await driver.initialize()
                    drivers.append(driver)
                    nodes[f"node_{i+1}"] = driver

                orchestrator = FunctionShippingOrchestrator(nodes)

                # Benchmark parallel execution
                query = create_count_query("user_count", "MATCH (u:User) RETURN count(u)")

                start = time.perf_counter()
                result = await orchestrator.execute_parallel(query)
                duration = time.perf_counter() - start

                benchmark.add_result(
                    duration,
                    result.success,
                    {
                        "node_count": node_count,
                        "result_data": result.data,
                        "nodes_used": result.nodes_used,
                    },
                )

                await orchestrator.close()

            finally:
                for driver in drivers:
                    await driver.close()

        stats = benchmark.get_stats()

        # Verify scaling behavior
        node_1_time = None
        node_4_time = None

        for result in stats["results"]:
            if result["metadata"]["node_count"] == 1:
                node_1_time = result["duration"]
            elif result["metadata"]["node_count"] == 4:
                node_4_time = result["duration"]

        if node_1_time and node_4_time:
            speedup = node_1_time / node_4_time
            print(f"Function shipping speedup (1 vs 4 nodes): {speedup:.2f}x")

    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_aggregation_performance(self, benchmark_database):
        """Benchmark aggregation performance."""
        benchmark = PerformanceBenchmark("aggregation_performance")

        # Create multiple nodes
        nodes = {}
        drivers = []

        try:
            for i in range(3):
                driver = KuzuDriver(benchmark_database, read_only=True)
                await driver.initialize()
                drivers.append(driver)
                nodes[f"node_{i+1}"] = driver

            orchestrator = FunctionShippingOrchestrator(nodes)

            # Test different aggregation queries
            queries = [
                ("count_users", "MATCH (u:User) RETURN count(u)"),
                ("count_products", "MATCH (p:Product) RETURN count(p)"),
                ("count_purchases", "MATCH (u:User)-[:Purchases]->(p:Product) RETURN count(*)"),
                ("avg_age", "MATCH (u:User) RETURN avg(u.age)"),
                ("max_price", "MATCH (p:Product) RETURN max(p.price)"),
            ]

            benchmark.start()

            for query_id, cypher_query in queries:
                query = create_count_query(query_id, cypher_query)

                start = time.perf_counter()
                result = await orchestrator.execute_parallel(query)
                duration = time.perf_counter() - start

                benchmark.add_result(
                    duration,
                    result.success,
                    {"query_id": query_id, "aggregation_method": result.aggregation_method},
                )

            benchmark.end()
            stats = benchmark.get_stats()

            print(f"Aggregation Performance: {stats['avg_duration']:.3f}s average")

            await orchestrator.close()

        finally:
            for driver in drivers:
                await driver.close()


class TestScalableDriverPerformance:
    """Performance tests for KuzukDriver."""

    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_scalable_driver_throughput(self, benchmark_database, temp_db_dir):
        """Benchmark scalable driver throughput."""
        benchmark = PerformanceBenchmark("scalable_driver_throughput")

        replica_dir = Path(temp_db_dir) / "replicas"
        replica_dir.mkdir(exist_ok=True)

        driver = KuzukDriver(
            master_db_path=benchmark_database,
            replica_count=2,
            base_replica_dir=str(replica_dir),
            enable_function_shipping=True,
            enable_health_monitoring=False,  # Disable for pure performance test
        )

        try:
            await driver.initialize()

            # Wait for initialization to complete
            await asyncio.sleep(1.0)

            benchmark.start()

            # Test regular queries
            for i in range(50):
                start = time.perf_counter()
                result = await driver.execute_query(
                    f"MATCH (u:User) WHERE u.id = {i * 10} RETURN u.name"
                )
                duration = time.perf_counter() - start

                benchmark.add_result(duration, result is not None)

            # Test analytical queries
            if driver.function_shipping:
                for i in range(10):
                    start = time.perf_counter()
                    result = await driver.execute_analytical_query(
                        "MATCH (u:User) RETURN count(u)", execution_mode="parallel_all"
                    )
                    duration = time.perf_counter() - start

                    benchmark.add_result(duration, result is not None, {"type": "analytical"})

            benchmark.end()
            stats = benchmark.get_stats()

            print(f"Scalable Driver Throughput: {stats['operations_per_second']:.2f} ops/sec")

        finally:
            await driver.close()

    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_cluster_health_monitoring_overhead(self, benchmark_database, temp_db_dir):
        """Benchmark health monitoring overhead."""
        benchmark = PerformanceBenchmark("health_monitoring_overhead")

        replica_dir = Path(temp_db_dir) / "replicas"
        replica_dir.mkdir(exist_ok=True)

        # Test with health monitoring disabled
        driver_no_health = KuzukDriver(
            master_db_path=benchmark_database,
            replica_count=1,
            base_replica_dir=str(replica_dir),
            enable_health_monitoring=False,
        )

        # Test with health monitoring enabled
        driver_with_health = KuzukDriver(
            master_db_path=benchmark_database,
            replica_count=1,
            base_replica_dir=str(replica_dir),
            enable_health_monitoring=True,
        )

        try:
            await driver_no_health.initialize()
            await driver_with_health.initialize()

            benchmark.start()

            # Test queries without health monitoring
            for i in range(25):
                start = time.perf_counter()
                result = await driver_no_health.execute_query("MATCH (u:User) RETURN count(u)")
                duration = time.perf_counter() - start

                benchmark.add_result(duration, result is not None, {"health_monitoring": False})

            # Test queries with health monitoring
            for i in range(25):
                start = time.perf_counter()
                result = await driver_with_health.execute_query("MATCH (u:User) RETURN count(u)")
                duration = time.perf_counter() - start

                benchmark.add_result(duration, result is not None, {"health_monitoring": True})

            benchmark.end()
            stats = benchmark.get_stats()

            # Calculate overhead
            no_health_times = [
                r["duration"] for r in stats["results"] if not r["metadata"]["health_monitoring"]
            ]
            with_health_times = [
                r["duration"] for r in stats["results"] if r["metadata"]["health_monitoring"]
            ]

            if no_health_times and with_health_times:
                no_health_avg = statistics.mean(no_health_times)
                with_health_avg = statistics.mean(with_health_times)
                overhead = ((with_health_avg - no_health_avg) / no_health_avg) * 100

                print(f"Health monitoring overhead: {overhead:.2f}%")

        finally:
            await driver_no_health.close()
            await driver_with_health.close()


class TestMemoryPerformance:
    """Memory usage and leak tests."""

    @pytest.mark.asyncio
    @pytest.mark.performance
    async def test_memory_usage_scaling(self, benchmark_database):
        """Test memory usage with increasing load."""
        benchmark = PerformanceBenchmark("memory_scaling")

        driver = KuzuDriver(benchmark_database, read_only=True)

        try:
            await driver.initialize()
            benchmark.start()

            # Measure memory usage with increasing query load
            for batch_size in [10, 50, 100, 200]:
                initial_memory = psutil.Process().memory_info().rss

                # Execute batch of queries
                tasks = []
                for i in range(batch_size):
                    task = driver.execute_query(f"MATCH (u:User) WHERE u.id = {i} RETURN u.name")
                    tasks.append(task)

                start = time.perf_counter()
                results = await asyncio.gather(*tasks, return_exceptions=True)
                duration = time.perf_counter() - start

                final_memory = psutil.Process().memory_info().rss
                memory_increase = final_memory - initial_memory

                success_count = sum(1 for r in results if not isinstance(r, Exception))

                benchmark.add_result(
                    duration,
                    success_count == batch_size,
                    {
                        "batch_size": batch_size,
                        "memory_increase_mb": memory_increase / (1024 * 1024),
                        "memory_per_query_kb": (
                            (memory_increase / batch_size) / 1024 if batch_size > 0 else 0
                        ),
                    },
                )

            benchmark.end()
            stats = benchmark.get_stats()

            print(f"Peak memory usage: {stats['memory_used_mb']:.2f} MB")

        finally:
            await driver.close()


def generate_performance_report(benchmark_results: list) -> str:
    """Generate a performance report from benchmark results."""
    report = "# Kuzuk Performance Report\n\n"
    report += f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n"

    for stats in benchmark_results:
        report += f"## {stats['name']}\n\n"
        report += f"- Total Operations: {stats['total_operations']}\n"
        report += f"- Success Rate: {stats['success_rate']:.2%}\n"
        report += f"- Operations/Second: {stats['operations_per_second']:.2f}\n"
        report += f"- Average Duration: {stats['avg_duration']:.3f}s\n"
        report += (
            f"- Min/Max Duration: {stats['min_duration']:.3f}s / {stats['max_duration']:.3f}s\n"
        )
        report += f"- Memory Used: {stats['memory_used_mb']:.2f} MB\n\n"

    return report


if __name__ == "__main__":
    # Run performance tests
    pytest.main([__file__, "-v", "-m", "performance", "--tb=short"])
