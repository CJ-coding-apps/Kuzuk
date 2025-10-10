Driver Classes
==============

The driver classes provide the main interface for interacting with Kuzuk clusters.

.. currentmodule:: kuzuk.drivers

KuzukDriver
------------------

.. autoclass:: KuzukDriver
   :members:
   :undoc-members:
   :show-inheritance:

   The main driver class for Kuzuk. This class provides a high-level interface
   for executing queries against a scaled KuzuDB cluster with automatic load balancing,
   failover, and health monitoring.

   **Key Features:**

   * Automatic query routing between master and replicas
   * Built-in health monitoring and failover
   * Connection pooling and management
   * Function shipping for analytical queries
   * Comprehensive error handling

   **Basic Usage:**

   .. code-block:: python

      from kuzuk import KuzukDriver
      
      async def main():
          driver = KuzukDriver("/path/to/database", replica_count=3)
          
          # Read query (routed to replica)
          result = await driver.execute_query("MATCH (n) RETURN count(n)")
          
          # Write query (routed to master)
          await driver.execute_query("CREATE (n:Person {name: 'Alice'})")
          
          await driver.close()

   **Configuration Options:**

   The driver supports extensive configuration through parameters and environment variables:

   .. code-block:: python

      driver = KuzukDriver(
          database_path="/path/to/database",
          replica_count=5,
          health_check_interval=30,
          connection_timeout=60,
          max_retries=3,
          enable_monitoring=True,
          prometheus_port=9100
      )

KuzuWrapper
-----------

.. autoclass:: KuzuWrapper
   :members:
   :undoc-members:
   :show-inheritance:

   Lower-level wrapper around the KuzuDB driver that provides enhanced functionality
   for use in scaled environments.

   This class is typically used internally by :class:`KuzukDriver` but can
   be used directly for advanced use cases.

   **Key Features:**

   * Enhanced error handling and retries
   * Connection health monitoring
   * Query performance tracking
   * Async/await support
   * Resource management

   **Advanced Usage:**

   .. code-block:: python

      from kuzuk.drivers import KuzuWrapper
      
      # Create wrapper for specific replica
      wrapper = KuzuWrapper(
          database_path="/path/to/replica1",
          node_id="replica-1",
          is_replica=True
      )
      
      # Execute query with custom options
      result = await wrapper.execute_query(
          query="MATCH (n) RETURN count(n)",
          timeout=30,
          retry_count=2
      )

LoadBalancer
------------

.. autoclass:: LoadBalancer
   :members:
   :undoc-members:
   :show-inheritance:

   Intelligent load balancer that routes queries to the most appropriate replica
   based on current health, load, and query characteristics.

   **Load Balancing Strategies:**

   * **Round Robin**: Distributes queries evenly across healthy replicas
   * **Least Connections**: Routes to replica with fewest active connections
   * **Response Time**: Routes to replica with lowest average response time
   * **Weighted**: Routes based on replica capacity and performance

   **Query Routing Rules:**

   * Write queries → Master node only
   * Read queries → Any healthy replica
   * Analytical queries → All replicas (function shipping)
   * Health checks → Direct to specific nodes

   **Usage Example:**

   .. code-block:: python

      from kuzuk.drivers import LoadBalancer
      
      # Create load balancer with custom strategy
      balancer = LoadBalancer(
          replicas=replica_list,
          strategy="least_connections",
          health_check_interval=30
      )
      
      # Get best replica for query
      replica = await balancer.get_best_replica(query_type="read")
      
      # Execute query on selected replica
      result = await replica.execute_query(query)

Driver Configuration
-------------------

ClusterConfig
~~~~~~~~~~~~~

.. autoclass:: kuzuk.config.ClusterConfig
   :members:
   :undoc-members:
   :show-inheritance:

   Configuration class for cluster-wide settings.

   **Example:**

   .. code-block:: python

      from kuzuk.config import ClusterConfig
      
      config = ClusterConfig(
          name="production-cluster",
          replica_count=10,
          health_check_interval=15,
          failover_timeout=60,
          enable_monitoring=True,
          monitoring_port=9100
      )

DatabaseConfig
~~~~~~~~~~~~~~

.. autoclass:: kuzuk.config.DatabaseConfig
   :members:
   :undoc-members:
   :show-inheritance:

   Configuration class for database-specific settings.

ConnectionConfig
~~~~~~~~~~~~~~~~

.. autoclass:: kuzuk.config.ConnectionConfig
   :members:
   :undoc-members:
   :show-inheritance:

   Configuration class for connection management.

Error Handling
--------------

Driver Exceptions
~~~~~~~~~~~~~~~~~

.. autoclass:: kuzuk.exceptions.DriverError
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: kuzuk.exceptions.ConnectionError
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: kuzuk.exceptions.QueryError
   :members:
   :undoc-members:
   :show-inheritance:

.. autoclass:: kuzuk.exceptions.LoadBalancerError
   :members:
   :undoc-members:
   :show-inheritance:

Performance Monitoring
---------------------

QueryMetrics
~~~~~~~~~~~~

.. autoclass:: kuzuk.monitoring.QueryMetrics
   :members:
   :undoc-members:
   :show-inheritance:

   Tracks query execution metrics for performance analysis.

ConnectionMetrics
~~~~~~~~~~~~~~~~~

.. autoclass:: kuzuk.monitoring.ConnectionMetrics
   :members:
   :undoc-members:
   :show-inheritance:

   Monitors connection pool health and utilization.

Examples
--------

Basic Driver Setup
~~~~~~~~~~~~~~~~~~

.. code-block:: python

   import asyncio
   from kuzuk import KuzukDriver

   async def basic_example():
       # Create driver with default settings
       driver = KuzukDriver("/path/to/database")
       
       try:
           # Initialize cluster
           await driver.initialize()
           
           # Execute some queries
           result = await driver.execute_query("MATCH (n) RETURN count(n)")
           print(f"Total nodes: {result['data'][0]['count(n)']}")
           
           # Create some data
           await driver.execute_query("""
               CREATE (p:Person {name: 'Alice', age: 30})
               CREATE (c:Company {name: 'TechCorp'})
               CREATE (p)-[:WORKS_FOR]->(c)
           """)
           
       finally:
           await driver.close()

   asyncio.run(basic_example())

Advanced Configuration
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from kuzuk import KuzukDriver
   from kuzuk.config import ClusterConfig, ConnectionConfig

   async def advanced_example():
       # Configure cluster
       cluster_config = ClusterConfig(
           name="analytics-cluster",
           replica_count=8,
           health_check_interval=10,
           failover_timeout=30
       )
       
       # Configure connections
       connection_config = ConnectionConfig(
           max_connections_per_replica=20,
           connection_timeout=60,
           retry_attempts=3,
           pool_size=50
       )
       
       # Create driver with custom configuration
       driver = KuzukDriver(
           database_path="/data/analytics.db",
           cluster_config=cluster_config,
           connection_config=connection_config,
           enable_monitoring=True
       )
       
       try:
           await driver.initialize()
           
           # Execute analytical query across all replicas
           result = await driver.execute_distributed_query("""
               MATCH (u:User)-[:PURCHASED]->(p:Product)
               WITH u.country as country, sum(p.price) as total_sales
               RETURN country, total_sales
               ORDER BY total_sales DESC
               LIMIT 10
           """)
           
           print("Top countries by sales:")
           for row in result['data']:
               print(f"{row['country']}: ${row['total_sales']:,.2f}")
               
       finally:
           await driver.close()

Error Handling and Resilience
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from kuzuk import KuzukDriver
   from kuzuk.exceptions import (
       DriverError, ConnectionError, QueryError, ReplicationError
   )

   async def resilient_example():
       driver = KuzukDriver("/path/to/database", replica_count=3)
       
       try:
           await driver.initialize()
           
           # Execute query with comprehensive error handling
           try:
               result = await driver.execute_query(
                   "MATCH (n:User) WHERE n.age > $age RETURN count(n)",
                   parameters={"age": 25},
                   timeout=30,
                   retry_on_failure=True
               )
               print(f"Users over 25: {result['data'][0]['count(n)']}")
               
           except QueryError as e:
               print(f"Query failed: {e}")
               # Try simpler fallback query
               result = await driver.execute_query("MATCH (n:User) RETURN count(n)")
               print(f"Total users: {result['data'][0]['count(n)']}")
               
           except ConnectionError as e:
               print(f"Connection lost: {e}")
               # Wait and retry
               await asyncio.sleep(5)
               await driver.reconnect()
               
           except ReplicationError as e:
               print(f"Replication issue: {e}")
               # Check cluster health
               health = await driver.get_cluster_health()
               print(f"Healthy replicas: {health.healthy_replica_count}")
               
       except DriverError as e:
           print(f"Driver error: {e}")
           # Log error and potentially restart
           
       finally:
           await driver.close()

Context Manager Usage
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   async def context_manager_example():
       # Using context manager for automatic resource cleanup
       async with KuzukDriver("/path/to/database") as driver:
           # Driver is automatically initialized
           
           # Execute multiple queries
           queries = [
               "MATCH (n:User) RETURN count(n)",
               "MATCH (n:Product) RETURN count(n)",
               "MATCH ()-[r:PURCHASED]->() RETURN count(r)"
           ]
           
           # Execute in parallel
           results = await asyncio.gather(*[
               driver.execute_query(query) for query in queries
           ])
           
           for i, result in enumerate(results):
               count = result['data'][0][list(result['data'][0].keys())[0]]
               entity = ["Users", "Products", "Purchases"][i]
               print(f"{entity}: {count}")
           
       # Driver is automatically closed when exiting context

Performance Monitoring Example
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   async def monitoring_example():
       driver = KuzukDriver(
           "/path/to/database",
           enable_monitoring=True,
           prometheus_port=9100
       )
       
       try:
           await driver.initialize()
           
           # Get performance statistics
           stats = await driver.get_performance_stats()
           print(f"Average query time: {stats.avg_query_time:.2f}ms")
           print(f"Queries per second: {stats.queries_per_second:.1f}")
           print(f"Active connections: {stats.active_connections}")
           
           # Get replica health information
           health = await driver.get_cluster_health()
           print(f"Cluster status: {health.overall_status}")
           
           for replica_id, replica_health in health.replicas.items():
               print(f"Replica {replica_id}: {replica_health.status}")
               print(f"  Response time: {replica_health.response_time:.1f}ms")
               print(f"  CPU usage: {replica_health.cpu_usage:.1f}%")
               print(f"  Memory usage: {replica_health.memory_usage:.1f}%")
           
           # Get query execution plan for optimization
           plan = await driver.explain_query(
               "MATCH (u:User)-[:FOLLOWS]->(f:User) RETURN u.name, count(f)"
           )
           print("Query execution plan:")
           print(plan.formatted_plan)
           
       finally:
           await driver.close()

See Also
--------

* :doc:`replication` - Replication and WAL streaming
* :doc:`monitoring` - Health monitoring and metrics
* :doc:`../troubleshooting` - Driver troubleshooting guide
* :doc:`../operations/performance_tuning` - Performance optimization