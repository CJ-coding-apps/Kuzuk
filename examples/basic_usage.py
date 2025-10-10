"""
Basic usage example for Kuzuk.
Demonstrates simple read replica setup and query execution.
"""

import asyncio
import logging
from kuzuk import KuzukDriver, create_simple_kuzuk_driver

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def basic_scaling_example():
    """Basic example of using Kuzuk with read replicas."""
    
    logger.info("🚀 Starting basic Kuzuk example...")
    
    # Create a simple Kuzuk driver with 2 read replicas
    driver = create_simple_kuzuk_driver(
        master_db_path="./example_database.kuzu",
        replica_count=2
    )
    
    try:
        # Initialize the scaling infrastructure
        logger.info("📊 Initializing scaling infrastructure...")
        await driver.initialize()
        
        # Wait a moment for replication to sync
        await asyncio.sleep(2)
        
        # Check cluster status
        status = driver.get_cluster_status()
        logger.info(f"✅ Cluster initialized with {status['replica_count']} replicas")
        
        # Execute simple read queries (will be routed to replicas)
        logger.info("🔍 Executing read queries...")
        
        # These queries will be automatically routed to healthy replicas
        queries = [
            "MATCH (n) RETURN count(n) as node_count",
            "MATCH (n:Person) RETURN n.name LIMIT 5",
            "MATCH (a)-[r]->(b) RETURN count(r) as edge_count"
        ]
        
        for query in queries:
            try:
                result = await driver.execute_query(query)
                logger.info(f"Query result: {result}")
            except Exception as e:
                logger.warning(f"Query failed (this is expected for demo): {e}")
        
        # Check which replicas are healthy
        healthy_replicas = driver.get_healthy_replicas()
        logger.info(f"💚 Healthy replicas: {healthy_replicas}")
        
        # Get detailed cluster status
        cluster_status = driver.get_cluster_status()
        logger.info("📈 Cluster Status:")
        for component, status in cluster_status.items():
            if isinstance(status, dict):
                logger.info(f"  {component}: {len(status)} items")
            else:
                logger.info(f"  {component}: {status}")
        
    except Exception as e:
        logger.error(f"❌ Error in basic example: {e}")
    
    finally:
        # Clean up resources
        logger.info("🧹 Cleaning up...")
        await driver.close()
        logger.info("✅ Basic example completed")


async def read_replica_performance_demo():
    """Demonstrate performance benefits of read replicas."""
    
    logger.info("⚡ Starting read replica performance demo...")
    
    # Create driver with more replicas for better performance
    driver = KuzukDriver(
        master_db_path="./performance_test.kuzu",
        replica_count=3,
        enable_function_shipping=False,  # Focus on read replicas only
        enable_health_monitoring=True
    )
    
    try:
        await driver.initialize()
        
        # Simulate multiple concurrent read queries
        logger.info("🔄 Simulating concurrent read queries...")
        
        async def execute_read_query(query_id: int):
            """Execute a single read query."""
            query = f"MATCH (n) WHERE id(n) % 10 = {query_id % 10} RETURN count(n)"
            try:
                result = await driver.execute_query(query)
                logger.info(f"Query {query_id} completed: {result}")
                return True
            except Exception as e:
                logger.warning(f"Query {query_id} failed: {e}")
                return False
        
        # Execute 10 queries concurrently
        tasks = [execute_read_query(i) for i in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        successful_queries = sum(1 for r in results if r is True)
        logger.info(f"📊 Completed {successful_queries}/10 concurrent queries")
        
        # Show final cluster health
        if driver.is_cluster_healthy():
            logger.info("💚 Cluster remains healthy after load test")
        else:
            logger.warning("⚠️ Cluster health degraded during load test")
    
    except Exception as e:
        logger.error(f"❌ Error in performance demo: {e}")
    
    finally:
        await driver.close()
        logger.info("✅ Performance demo completed")


if __name__ == "__main__":
    # Run the basic example
    asyncio.run(basic_scaling_example())
    
    # Add a separator
    print("\n" + "="*60 + "\n")
    
    # Run the performance demo
    asyncio.run(read_replica_performance_demo())