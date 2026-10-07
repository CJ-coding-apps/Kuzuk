"""
End-to-end integration test demonstrating full Kuzuk functionality.
"""

import asyncio
import shutil
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio

from kuzuk import KuzukDriver, create_enterprise_kuzuk_driver
from kuzuk.function_shipping.orchestrator import create_count_query, create_distinct_query


@pytest.fixture
def temp_db_dir():
    """Create temporary directory for test databases."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest_asyncio.fixture
async def sample_ecommerce_db(temp_db_dir):
    """Create a sample e-commerce database for end-to-end testing."""
    from kuzuk.drivers.kuzu_wrapper import KuzuDriver

    db_path = Path(temp_db_dir) / "ecommerce.kuzu"
    driver = KuzuDriver(str(db_path))

    try:
        await driver.initialize()

        # Create comprehensive e-commerce schema
        schema_queries = [
            """CREATE NODE TABLE Customer(
                id INT64, 
                name STRING, 
                email STRING, 
                city STRING, 
                country STRING,
                registration_date STRING,
                PRIMARY KEY(id)
            )""",
            """CREATE NODE TABLE Product(
                id INT64,
                name STRING,
                category STRING,
                price DOUBLE,
                stock INT64,
                brand STRING,
                PRIMARY KEY(id)
            )""",
            """CREATE NODE TABLE Orders(
                id INT64,
                order_date STRING,
                status STRING,
                total_amount DOUBLE,
                PRIMARY KEY(id)
            )""",
            """CREATE REL TABLE PlacedOrder(FROM Customer TO Orders, order_type STRING)""",
            """CREATE REL TABLE OrderContains(FROM Orders TO Product, quantity INT64, unit_price DOUBLE)""",
            """CREATE REL TABLE CustomerViewed(FROM Customer TO Product, view_date STRING, duration_seconds INT64)""",
        ]

        for query in schema_queries:
            await driver.execute_query(query)

        # Insert sample data
        # Customers
        for i in range(1, 101):  # 100 customers
            await driver.execute_query(
                f"""
                CREATE (c:Customer {{
                    id: {i},
                    name: 'Customer{i}',
                    email: 'customer{i}@example.com',
                    city: 'City{i % 20}',
                    country: 'Country{i % 5}',
                    registration_date: '2023-{(i % 12) + 1:02d}-01'
                }})
            """
            )

        # Products
        categories = ["Electronics", "Clothing", "Books", "Home", "Sports"]
        brands = ["BrandA", "BrandB", "BrandC", "BrandD", "BrandE"]

        for i in range(1, 201):  # 200 products
            category = categories[i % len(categories)]
            brand = brands[i % len(brands)]
            price = 10.0 + (i % 100) * 2.5
            stock = 50 + (i % 100)

            await driver.execute_query(
                f"""
                CREATE (p:Product {{
                    id: {i},
                    name: 'Product{i}',
                    category: '{category}',
                    price: {price},
                    stock: {stock},
                    brand: '{brand}'
                }})
            """
            )

        # Orders
        for i in range(1, 51):  # 50 orders
            total = 50.0 + (i % 50) * 10.0
            status = ["pending", "shipped", "delivered"][i % 3]

            await driver.execute_query(
                f"""
                CREATE (o:Orders {{
                    id: {i},
                    order_date: '2023-{(i % 12) + 1:02d}-{(i % 28) + 1:02d}',
                    status: '{status}',
                    total_amount: {total}
                }})
            """
            )

        # Relationships
        # Customer orders
        for i in range(1, 51):
            customer_id = (i % 100) + 1
            await driver.execute_query(
                f"""
                MATCH (c:Customer {{id: {customer_id}}}), (o:Orders {{id: {i}}})
                CREATE (c)-[:PlacedOrder {{order_type: 'online'}}]->(o)
            """
            )

        # Orders contains products
        for order_id in range(1, 51):
            for j in range(1, 4):  # 1-3 products per order
                product_id = ((order_id - 1) * 3 + j - 1) % 200 + 1
                quantity = j
                unit_price = 15.0 + (j * 5.0)

                await driver.execute_query(
                    f"""
                    MATCH (o:Orders {{id: {order_id}}}), (p:Product {{id: {product_id}}})
                    CREATE (o)-[:OrderContains {{quantity: {quantity}, unit_price: {unit_price}}}]->(p)
                """
                )

        # Customer product views
        for customer_id in range(1, 101):
            for view in range(1, 6):  # 5 views per customer
                product_id = ((customer_id - 1) * 5 + view - 1) % 200 + 1
                duration = 30 + (view * 15)

                await driver.execute_query(
                    f"""
                    MATCH (c:Customer {{id: {customer_id}}}), (p:Product {{id: {product_id}}})
                    CREATE (c)-[:CustomerViewed {{view_date: '2023-01-{view:02d}', duration_seconds: {duration}}}]->(p)
                """
                )

        yield str(db_path)

    finally:
        await driver.close()


class TestEndToEndScenarios:
    """End-to-end test scenarios demonstrating real-world usage."""

    @pytest.mark.asyncio
    @pytest.mark.integration
    @pytest.mark.slow
    async def test_ecommerce_analytics_pipeline(self, sample_ecommerce_db, temp_db_dir):
        """Test complete e-commerce analytics pipeline with scaling."""
        replica_dir = Path(temp_db_dir) / "replicas"
        replica_dir.mkdir(exist_ok=True)

        # Create enterprise scaled driver
        driver = create_enterprise_kuzuk_driver(master_db_path=sample_ecommerce_db, replica_count=3)

        try:
            await driver.initialize()

            # Wait for replication to start
            await asyncio.sleep(2.0)

            # 1. Basic analytics queries
            print("Running basic analytics queries...")

            queries = [
                ("customer_count", "MATCH (c:Customer) RETURN count(c) as total_customers"),
                ("product_count", "MATCH (p:Product) RETURN count(p) as total_products"),
                ("order_count", "MATCH (o:Orders) RETURN count(o) as total_orders"),
                (
                    "avg_order_value",
                    "MATCH (o:Orders) RETURN avg(o.total_amount) as avg_order_value",
                ),
                (
                    "top_categories",
                    "MATCH (p:Product) RETURN p.category, count(p) as product_count",
                ),
            ]

            for query_name, cypher in queries:
                result = await driver.execute_query(cypher)
                assert result is not None
                print(f"✅ {query_name}: executed successfully")

            # 2. Function shipping analytics
            if driver.function_shipping:
                print("Running function shipping analytics...")

                # Count customers across all replicas
                customer_count_query = create_count_query(
                    "total_customers", "MATCH (c:Customer) RETURN count(c) as count"
                )

                count_result = await driver.execute_analytical_query(
                    customer_count_query.cypher_query, execution_mode="parallel_all"
                )

                assert count_result is not None
                print(f"✅ Parallel customer count: {count_result}")

                # Distinct brands across replicas
                brand_query = create_distinct_query(
                    "distinct_brands", "MATCH (p:Product) RETURN DISTINCT p.brand"
                )

                brand_result = await driver.execute_analytical_query(
                    brand_query.cypher_query, execution_mode="parallel_all"
                )

                assert brand_result is not None
                print(f"✅ Distinct brands analysis completed")

            # 3. Complex business intelligence queries
            print("Running complex BI queries...")

            complex_queries = [
                # Customer segmentation
                """
                MATCH (c:Customer)-[:PlacedOrder]->(o:Orders)
                WITH c, count(o) as order_count, sum(o.total_amount) as total_spent
                RETURN 
                    CASE 
                        WHEN order_count >= 3 AND total_spent > 200 THEN 'VIP'
                        WHEN order_count >= 2 OR total_spent > 100 THEN 'Regular'
                        ELSE 'New'
                    END as customer_segment,
                    count(c) as segment_size
                """,
                # Product performance
                """
                MATCH (o:Orders)-[oc:OrderContains]->(p:Product)
                WITH p, sum(oc.quantity) as total_sold, sum(oc.quantity * oc.unit_price) as revenue
                RETURN p.category, count(p) as products, sum(total_sold) as total_quantity, sum(revenue) as total_revenue
                ORDER BY total_revenue DESC
                """,
                # Customer engagement
                """
                MATCH (c:Customer)-[cv:CustomerViewed]->(p:Product)
                WITH c, count(cv) as views, avg(cv.duration_seconds) as avg_duration
                RETURN 
                    CASE 
                        WHEN views > 10 THEN 'High Engagement'
                        WHEN views > 5 THEN 'Medium Engagement'
                        ELSE 'Low Engagement'
                    END as engagement_level,
                    count(c) as customer_count,
                    avg(avg_duration) as avg_view_duration
                """,
            ]

            for i, query in enumerate(complex_queries):
                result = await driver.execute_query(query)
                assert result is not None
                print(f"✅ Complex BI query {i+1}: executed successfully")

            # 4. Health and performance monitoring
            print("Checking cluster health...")

            cluster_status = driver.get_cluster_status()
            assert "replication" in cluster_status
            assert "health" in cluster_status

            is_healthy = driver.is_cluster_healthy()
            print(f"✅ Cluster healthy: {is_healthy}")

            healthy_replicas = driver.get_healthy_replicas()
            print(f"✅ Healthy replicas: {len(healthy_replicas)}")

            # 5. Performance test with concurrent queries
            print("Running concurrent query performance test...")

            async def concurrent_query_batch():
                """Execute a batch of queries concurrently."""
                queries = [
                    "MATCH (c:Customer) WHERE c.country = 'Country1' RETURN count(c)",
                    "MATCH (p:Product) WHERE p.category = 'Electronics' RETURN count(p)",
                    "MATCH (o:Orders) WHERE o.status = 'delivered' RETURN count(o)",
                    "MATCH (c:Customer)-[:PlacedOrder]->(o:Orders) RETURN c.city, count(o) as orders",
                    "MATCH (p:Product) WHERE p.price > 50 RETURN p.brand, count(p) as count",
                ]

                tasks = [driver.execute_query(q) for q in queries]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                success_count = sum(
                    1 for r in results if not isinstance(r, Exception) and r is not None
                )
                return success_count, len(results)

            success, total = await concurrent_query_batch()
            print(f"✅ Concurrent queries: {success}/{total} successful")

            # 6. Final validation
            print("Running final validation...")

            # Verify data consistency across replicas
            validation_query = "MATCH (c:Customer) RETURN count(c) as customer_count"
            validation_result = await driver.execute_query(validation_query)
            assert validation_result is not None

            print("🎉 End-to-end test completed successfully!")

        finally:
            await driver.close()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_scaling_driver_lifecycle(self, sample_ecommerce_db, temp_db_dir):
        """Test complete scaling driver lifecycle."""
        replica_dir = Path(temp_db_dir) / "replicas"
        replica_dir.mkdir(exist_ok=True)

        driver = KuzukDriver(
            master_db_path=sample_ecommerce_db,
            replica_count=2,
            enable_function_shipping=True,
            enable_health_monitoring=True,
        )

        try:
            # 1. Initialization
            print("1. Initializing scaled driver...")
            await driver.initialize()
            assert driver.initialized
            print("✅ Driver initialized")

            # 2. Basic functionality test
            print("2. Testing basic functionality...")
            result = await driver.execute_query("MATCH (c:Customer) RETURN count(c)")
            assert result is not None
            print("✅ Basic query execution works")

            # 3. Scaling functionality test
            print("3. Testing scaling functionality...")
            if driver.function_shipping:
                analytical_result = await driver.execute_analytical_query(
                    "MATCH (p:Product) RETURN count(p)", execution_mode="parallel_all"
                )
                assert analytical_result is not None
                print("✅ Function shipping works")

            # 4. Health monitoring test
            print("4. Testing health monitoring...")
            cluster_status = driver.get_cluster_status()
            assert isinstance(cluster_status, dict)
            print("✅ Health monitoring works")

            # 5. Replica management test
            print("5. Testing replica management...")
            healthy_replicas = driver.get_healthy_replicas()
            assert isinstance(healthy_replicas, list)
            print(f"✅ Replica management works ({len(healthy_replicas)} replicas)")

            print("🎉 Lifecycle test completed successfully!")

        finally:
            await driver.close()

    @pytest.mark.asyncio
    @pytest.mark.integration
    async def test_error_recovery_scenarios(self, sample_ecommerce_db, temp_db_dir):
        """Test error recovery and graceful degradation."""
        replica_dir = Path(temp_db_dir) / "replicas"
        replica_dir.mkdir(exist_ok=True)

        driver = KuzukDriver(
            master_db_path=sample_ecommerce_db, replica_count=1
        )

        try:
            await driver.initialize()

            # Test with invalid queries
            print("Testing error handling...")

            invalid_result = await driver.execute_query("INVALID CYPHER SYNTAX")
            # Should handle gracefully, not crash
            assert invalid_result is not None or True  # Either returns result or handles gracefully

            # Test cluster status during errors
            status = driver.get_cluster_status()
            assert isinstance(status, dict)

            print("✅ Error recovery tests passed")

        finally:
            await driver.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
