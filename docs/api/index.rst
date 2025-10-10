API Reference
=============

This section provides detailed documentation for all Kuzuk APIs, classes, and functions.

.. toctree::
   :maxdepth: 2

   drivers
   replication
   function_shipping
   monitoring
   operators

Core Components
---------------

The Kuzuk API is organized into several key modules:

* :doc:`drivers` - Main driver classes for database operations
* :doc:`replication` - WAL streaming and replica management
* :doc:`function_shipping` - Parallel query execution across replicas
* :doc:`monitoring` - Health monitoring and metrics collection
* :doc:`operators` - Kubernetes operator and custom resources

Quick API Overview
------------------

Main Classes
~~~~~~~~~~~~

.. currentmodule:: kuzuk

.. autosummary::
   :toctree: _autosummary

   KuzukDriver
   ReplicationManager
   FunctionShippingManager
   HealthMonitor
   LoadBalancer

Core Functions
~~~~~~~~~~~~~~

.. autosummary::
   :toctree: _autosummary

   create_cluster
   scale_replicas
   execute_distributed_query
   monitor_health
   backup_cluster

Configuration Classes
~~~~~~~~~~~~~~~~~~~~

.. autosummary::
   :toctree: _autosummary

   ClusterConfig
   ReplicationConfig
   MonitoringConfig
   SecurityConfig

Exception Classes
~~~~~~~~~~~~~~~~~

.. autosummary::
   :toctree: _autosummary

   KuzukError
   ReplicationError
   FunctionShippingError
   HealthCheckError

Examples
--------

Basic Driver Usage
~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from kuzuk import KuzukDriver
   
   # Create driver with default configuration
   driver = KuzukDriver("/path/to/database")
   
   # Execute read query (routed to replica)
   result = await driver.execute_query("MATCH (n) RETURN count(n)")
   
   # Execute write query (routed to master)
   await driver.execute_query("CREATE (n:Person {name: 'Alice'})")

Advanced Configuration
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   from kuzuk import KuzukDriver, ClusterConfig, ReplicationConfig
   
   # Configure cluster settings
   cluster_config = ClusterConfig(
       replica_count=5,
       health_check_interval=10,
       failover_timeout=30
   )
   
   # Configure replication settings
   replication_config = ReplicationConfig(
       wal_retention_hours=48,
       sync_mode="async",
       lag_threshold_seconds=5
   )
   
   # Create driver with custom configuration
   driver = KuzukDriver(
       database_path="/path/to/database",
       cluster_config=cluster_config,
       replication_config=replication_config
   )

Function Shipping
~~~~~~~~~~~~~~~~~

.. code-block:: python

   from kuzuk import FunctionShippingManager
   
   # Create function shipping manager
   fs_manager = FunctionShippingManager(driver)
   
   # Execute analytical query across all replicas
   results = await fs_manager.execute_distributed_query(
       query="MATCH (n:User) RETURN n.country, count(*) GROUP BY n.country",
       aggregation_mode="merge"
   )

Health Monitoring
~~~~~~~~~~~~~~~~~

.. code-block:: python

   from kuzuk import HealthMonitor
   
   # Create health monitor
   monitor = HealthMonitor(driver)
   
   # Start monitoring
   await monitor.start_monitoring()
   
   # Get cluster health status
   health_status = await monitor.get_cluster_health()
   print(f"Cluster health: {health_status.overall_status}")
   
   # Get individual replica health
   for replica_id, replica_health in health_status.replicas.items():
       print(f"Replica {replica_id}: {replica_health.status}")

Error Handling
--------------

Kuzuk provides comprehensive error handling with specific exception types:

.. code-block:: python

   from kuzuk import (
       KuzukDriver, 
       KuzukError, 
       ReplicationError,
       FunctionShippingError
   )
   
   try:
       driver = KuzukDriver("/path/to/database")
       result = await driver.execute_query("MATCH (n) RETURN count(n)")
   except ReplicationError as e:
       print(f"Replication failed: {e}")
       # Handle replication issues
   except FunctionShippingError as e:
       print(f"Function shipping failed: {e}")
       # Handle distributed query issues
   except KuzukError as e:
       print(f"General Kuzuk error: {e}")
       # Handle general errors
   except Exception as e:
       print(f"Unexpected error: {e}")
       # Handle unexpected errors

Async/Await Patterns
-------------------

Kuzuk is built with async/await from the ground up. Here are common patterns:

Context Manager Usage
~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

   async with KuzukDriver("/path/to/database") as driver:
       # Driver is automatically initialized
       result = await driver.execute_query("MATCH (n) RETURN count(n)")
       # Driver is automatically closed when exiting context

Batch Operations
~~~~~~~~~~~~~~~

.. code-block:: python

   # Execute multiple queries in parallel
   queries = [
       "MATCH (n:User) RETURN count(n)",
       "MATCH (n:Product) RETURN count(n)",
       "MATCH (n:Order) RETURN count(n)"
   ]
   
   results = await asyncio.gather(*[
       driver.execute_query(query) for query in queries
   ])

Configuration Reference
----------------------

Environment Variables
~~~~~~~~~~~~~~~~~~~~~

Kuzuk supports configuration via environment variables:

.. code-block:: bash

   # Basic configuration
   KUZU_DATABASE_PATH=/path/to/database
   KUZU_REPLICA_COUNT=3
   KUZU_HEALTH_CHECK_INTERVAL=30
   
   # Replication configuration
   KUZU_WAL_RETENTION_HOURS=24
   KUZU_REPLICATION_SYNC_MODE=async
   KUZU_REPLICATION_LAG_THRESHOLD=5
   
   # Monitoring configuration
   KUZU_MONITORING_ENABLED=true
   KUZU_PROMETHEUS_PORT=9100
   KUZU_GRAFANA_ENABLED=true
   
   # Security configuration
   KUZU_TLS_ENABLED=false
   KUZU_AUTH_ENABLED=false

Configuration Files
~~~~~~~~~~~~~~~~~~

You can also use YAML configuration files:

.. code-block:: yaml

   # kuzuk.yaml
   cluster:
     name: "my-cluster"
     replica_count: 5
     health_check_interval: 10
   
   replication:
     wal_retention_hours: 48
     sync_mode: "async"
     lag_threshold_seconds: 5
   
   monitoring:
     enabled: true
     prometheus:
       port: 9100
       metrics_path: "/metrics"
     grafana:
       enabled: true
       port: 3000
   
   security:
     tls_enabled: false
     auth_enabled: false

Load the configuration:

.. code-block:: python

   from kuzuk import KuzukDriver
   
   # Load from YAML file
   driver = KuzukDriver.from_config_file("kuzuk.yaml")

Performance Considerations
-------------------------

Connection Pooling
~~~~~~~~~~~~~~~~~

Kuzuk automatically manages connection pools for optimal performance:

.. code-block:: python

   # Configure connection pool settings
   driver = KuzukDriver(
       database_path="/path/to/database",
       max_connections_per_replica=10,
       connection_timeout=30,
       connection_retry_attempts=3
   )

Query Routing
~~~~~~~~~~~~

Queries are automatically routed based on type:

* **Read queries**: Routed to healthy replicas using round-robin
* **Write queries**: Always routed to master node
* **Analytical queries**: Distributed across all replicas using function shipping

.. code-block:: python

   # Force query to specific replica (advanced usage)
   result = await driver.execute_query(
       query="MATCH (n) RETURN count(n)",
       replica_hint="replica-2"
   )
   
   # Execute on master only
   result = await driver.execute_query(
       query="MATCH (n) RETURN count(n)",
       force_master=True
   )

Monitoring and Observability
---------------------------

Kuzuk provides extensive monitoring capabilities:

Metrics Collection
~~~~~~~~~~~~~~~~~

.. code-block:: python

   from kuzuk.monitoring import PrometheusMetrics
   
   # Initialize metrics collection
   metrics = PrometheusMetrics()
   
   # Record custom metrics
   metrics.record_query_metric("replica-1", "read", "success", 0.05)
   metrics.record_error_metric("replica-2", "connection_timeout")
   
   # Get metrics in Prometheus format
   metrics_text = metrics.get_metrics_text()

Health Checks
~~~~~~~~~~~~

.. code-block:: python

   # Customize health check behavior
   from kuzuk import HealthMonitor, HealthThresholds
   
   thresholds = HealthThresholds(
       response_time_warning_ms=1000,
       response_time_critical_ms=5000,
       cpu_warning_percent=80,
       memory_warning_percent=85
   )
   
   monitor = HealthMonitor(
       driver=driver,
       check_interval=30,
       thresholds=thresholds
   )

Troubleshooting
--------------

Common Issues
~~~~~~~~~~~~

**Connection Failures**

.. code-block:: python

   # Enable debug logging
   import logging
   logging.getLogger('kuzuk').setLevel(logging.DEBUG)
   
   # Check replica connectivity
   health_status = await driver.get_replica_health()
   for replica_id, health in health_status.items():
       if not health.is_healthy:
           print(f"Replica {replica_id} is unhealthy: {health.error}")

**Performance Issues**

.. code-block:: python

   # Get query performance metrics
   performance_stats = await driver.get_performance_stats()
   print(f"Average query time: {performance_stats.avg_query_time}ms")
   print(f"Query throughput: {performance_stats.queries_per_second}/sec")
   
   # Enable query tracing
   result = await driver.execute_query(
       query="MATCH (n) RETURN count(n)",
       enable_tracing=True
   )
   print(f"Query executed on: {result.metadata.replica_id}")
   print(f"Execution time: {result.metadata.execution_time}ms")

See Also
--------

* :doc:`../troubleshooting` - Comprehensive troubleshooting guide
* :doc:`../operations/performance_tuning` - Performance optimization
* :doc:`../examples/index` - Code examples and tutorials