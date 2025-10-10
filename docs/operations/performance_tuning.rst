Performance Tuning Guide
========================

This guide provides comprehensive strategies for optimizing Kuzuk performance across different dimensions.

.. contents::
   :local:
   :depth: 3

Overview
--------

Kuzuk performance optimization involves several key areas:

* **Query Performance**: Optimizing individual query execution
* **Cluster Scaling**: Right-sizing and scaling the cluster
* * **Resource Allocation**: CPU, memory, and storage optimization
* **Network Optimization**: Reducing latency and improving throughput
* **Monitoring**: Continuous performance monitoring and alerting

Performance Baseline
--------------------

Before optimizing, establish performance baselines:

Measuring Current Performance
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. **Query Performance Metrics:**

   .. code-block:: bash

      # Use the performance benchmark script
      ./k8s/scripts/performance-benchmark.sh --duration 300 --concurrency 20
      
      # Or query Prometheus directly
      kubectl port-forward service/prometheus-service 9090:9090 -n kuzuk &
      
      # Query average response time
      curl -G 'http://localhost:9090/api/v1/query' \
        --data-urlencode 'query=rate(kuzu_query_duration_seconds_sum[5m])/rate(kuzu_query_duration_seconds_count[5m])'

2. **System Resource Utilization:**

   .. code-block:: bash

      kubectl top nodes
      kubectl top pods -n kuzuk

3. **Throughput Measurements:**

   .. code-block:: bash

      # Queries per second
      curl -G 'http://localhost:9090/api/v1/query' \
        --data-urlencode 'query=rate(kuzu_queries_total[5m])'

Establishing SLOs
~~~~~~~~~~~~~~~~

Define Service Level Objectives (SLOs):

.. code-block:: yaml

   # Example SLOs
   query_latency:
     p50: < 100ms
     p95: < 500ms
     p99: < 1000ms
   
   availability: > 99.9%
   throughput: > 1000 QPS
   error_rate: < 0.1%

Query Performance Optimization
------------------------------

Query Analysis
~~~~~~~~~~~~~~

1. **Identify Slow Queries:**

   .. code-block:: bash

      # Check slow query logs
      kubectl logs deployment/kuzuk-master -n kuzuk | grep "slow query"
      
      # Query Prometheus for slow queries
      curl -G 'http://localhost:9090/api/v1/query' \
        --data-urlencode 'query=histogram_quantile(0.95, rate(kuzu_query_duration_seconds_bucket[10m])) > 1'

2. **Query Profiling:**

   .. code-block:: python

      from kuzuk import KuzukDriver
      
      async def profile_query():
          driver = KuzukDriver("/path/to/database")
          
          # Enable profiling
          result = await driver.execute_query(
              query="MATCH (n:User)-[:FOLLOWS]->(f:User) RETURN count(*)",
              enable_profiling=True
          )
          
          print(f"Execution time: {result.metadata.execution_time}ms")
          print(f"Rows examined: {result.metadata.rows_examined}")
          print(f"Index usage: {result.metadata.index_usage}")

Query Optimization Strategies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. **Use Appropriate Indexes:**

   .. code-block:: cypher

      -- Create indexes for frequently queried properties
      CREATE INDEX user_email_idx FOR (u:User) ON (u.email)
      CREATE INDEX product_category_idx FOR (p:Product) ON (p.category)
      
      -- Use compound indexes for multi-property queries
      CREATE INDEX user_location_age_idx FOR (u:User) ON (u.country, u.age)

2. **Optimize Query Patterns:**

   .. code-block:: cypher

      -- AVOID: Cartesian products
      -- Bad
      MATCH (u:User), (p:Product) WHERE u.id = 123 AND p.category = 'electronics'
      
      -- Good
      MATCH (u:User {id: 123})
      MATCH (p:Product {category: 'electronics'})
      
      -- AVOID: Unnecessary aggregations
      -- Bad
      MATCH (u:User) RETURN count(*) WHERE u.age > 25
      
      -- Good
      MATCH (u:User) WHERE u.age > 25 RETURN count(*)

3. **Limit Result Sets:**

   .. code-block:: cypher

      -- Use LIMIT for large result sets
      MATCH (u:User)-[:FOLLOWS]->(f:User)
      RETURN u.name, f.name
      ORDER BY u.name
      LIMIT 1000
      
      -- Use pagination for UI
      MATCH (u:User)
      RETURN u
      ORDER BY u.created_at DESC
      SKIP $offset LIMIT $limit

4. **Optimize Aggregations:**

   .. code-block:: cypher

      -- Use WITH clauses to reduce intermediate results
      MATCH (u:User)-[:PURCHASED]->(p:Product)
      WITH u, sum(p.price) as total_spent
      WHERE total_spent > 1000
      RETURN u.name, total_spent

Function Shipping Optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

1. **Optimal Query Distribution:**

   .. code-block:: python

      # Use function shipping for analytical queries
      result = await driver.execute_distributed_query(
          query="""
          MATCH (u:User)-[:PURCHASED]->(p:Product)
          WITH u.country as country, sum(p.price) as sales
          RETURN country, sales
          """,
          aggregation_mode="merge",  # Merge results from all replicas
          partition_key="country"    # Partition by country for efficiency
      )

2. **Parallel Execution Tuning:**

   .. code-block:: yaml

      # Configuration for function shipping
      function_shipping:
        max_parallel_queries: 8
        chunk_size: 10000
        timeout_seconds: 300
        retry_attempts: 2

Cluster Scaling Optimization
----------------------------

Horizontal Scaling
~~~~~~~~~~~~~~~~~

1. **Replica Count Optimization:**

   .. code-block:: bash

      # Monitor replica utilization
      kubectl top pods -n kuzuk -l component=replica
      
      # Scale based on CPU/memory usage
      kubectl scale deployment kuzuk-replica --replicas=8 -n kuzuk

2. **Auto-scaling Configuration:**

   .. code-block:: yaml

      # Enhanced HPA configuration
      apiVersion: autoscaling/v2
      kind: HorizontalPodAutoscaler
      metadata:
        name: kuzuk-replica-hpa
      spec:
        scaleTargetRef:
          apiVersion: apps/v1
          kind: Deployment
          name: kuzuk-replica
        minReplicas: 3
        maxReplicas: 20
        metrics:
        - type: Resource
          resource:
            name: cpu
            target:
              type: Utilization
              averageUtilization: 60  # Lower threshold for faster scaling
        - type: Resource
          resource:
            name: memory
            target:
              type: Utilization
              averageUtilization: 70
        - type: Pods
          pods:
            metric:
              name: kuzu_queries_per_second
            target:
              type: AverageValue
              averageValue: "80"  # Scale when >80 QPS per pod
        behavior:
          scaleUp:
            stabilizationWindowSeconds: 60
            policies:
            - type: Percent
              value: 100  # Double replicas quickly
              periodSeconds: 60
            - type: Pods
              value: 3    # Add max 3 pods at once
              periodSeconds: 60
            selectPolicy: Max
          scaleDown:
            stabilizationWindowSeconds: 300
            policies:
            - type: Percent
              value: 10   # Remove 10% at a time
              periodSeconds: 60

3. **Load Balancing Optimization:**

   .. code-block:: yaml

      # Load balancer configuration
      load_balancer:
        strategy: "least_response_time"  # Options: round_robin, least_connections, least_response_time
        health_check_interval: 10
        unhealthy_threshold: 3
        healthy_threshold: 2
        circuit_breaker:
          enabled: true
          failure_threshold: 5
          recovery_time: 30

Vertical Scaling
~~~~~~~~~~~~~~~

1. **Resource Sizing Guidelines:**

   .. code-block:: yaml

      # Master node sizing
      master_resources:
        small_workload:    # <1M nodes, <100 QPS
          cpu: "2000m"
          memory: "4Gi"
        medium_workload:   # 1M-10M nodes, 100-500 QPS
          cpu: "4000m"
          memory: "8Gi"
        large_workload:    # 10M+ nodes, 500+ QPS
          cpu: "8000m"
          memory: "16Gi"
      
      # Replica node sizing
      replica_resources:
        small_workload:
          cpu: "1000m"
          memory: "2Gi"
        medium_workload:
          cpu: "2000m"
          memory: "4Gi"
        large_workload:
          cpu: "4000m"
          memory: "8Gi"

2. **Dynamic Resource Adjustment:**

   .. code-block:: bash

      # Monitor resource usage patterns
      kubectl top pods -n kuzuk --containers
      
      # Adjust based on usage patterns
      kubectl patch deployment kuzuk-replica -n kuzuk -p '{
        "spec": {
          "template": {
            "spec": {
              "containers": [{
                "name": "kuzuk-replica",
                "resources": {
                  "requests": {"cpu": "1500m", "memory": "3Gi"},
                  "limits": {"cpu": "3000m", "memory": "6Gi"}
                }
              }]
            }
          }
        }
      }'

Resource Optimization
---------------------

CPU Optimization
~~~~~~~~~~~~~~~~

1. **CPU Affinity and Requests:**

   .. code-block:: yaml

      spec:
        template:
          spec:
            containers:
            - name: kuzuk-master
              resources:
                requests:
                  cpu: "2000m"    # Guaranteed CPU
                limits:
                  cpu: "4000m"    # Maximum CPU burst
              nodeSelector:
                node-type: "cpu-optimized"
              affinity:
                nodeAffinity:
                  requiredDuringSchedulingIgnoredDuringExecution:
                    nodeSelectorTerms:
                    - matchExpressions:
                      - key: cpu-architecture
                        operator: In
                        values: ["x86_64"]

2. **CPU Governor Settings:**

   .. code-block:: bash

      # Set CPU governor to performance mode on nodes
      kubectl apply -f - <<EOF
      apiVersion: apps/v1
      kind: DaemonSet
      metadata:
        name: cpu-performance-tuning
        namespace: kube-system
      spec:
        selector:
          matchLabels:
            app: cpu-performance-tuning
        template:
          metadata:
            labels:
              app: cpu-performance-tuning
          spec:
            hostPID: true
            hostIPC: true
            containers:
            - name: cpu-tuning
              image: busybox
              command: ["sh", "-c", "echo performance > /host/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor && sleep infinity"]
              securityContext:
                privileged: true
              volumeMounts:
              - name: host-sys
                mountPath: /host/sys
            volumes:
            - name: host-sys
              hostPath:
                path: /sys
      EOF

Memory Optimization
~~~~~~~~~~~~~~~~~~

1. **Memory Allocation Strategy:**

   .. code-block:: yaml

      # Memory configuration
      memory_config:
        # Reserve memory for OS and kubelet
        system_reserved: "1Gi"
        
        # Kuzuk memory allocation
        master:
          heap_size: "75%"        # 75% of available memory
          off_heap_size: "20%"    # For file system cache
        replica:
          heap_size: "70%"
          off_heap_size: "25%"

2. **Memory Tuning Parameters:**

   .. code-block:: yaml

      env:
      - name: KUZU_HEAP_SIZE
        value: "4g"
      - name: KUZU_OFF_HEAP_SIZE
        value: "1g"
      - name: KUZU_GC_ALGORITHM
        value: "G1GC"              # Optimized for low latency
      - name: KUZU_GC_MAX_PAUSE
        value: "200"               # Max GC pause time in ms

3. **Memory Monitoring:**

   .. code-block:: bash

      # Monitor memory usage patterns
      kubectl exec -it deployment/kuzuk-master -n kuzuk -- \
        cat /proc/meminfo | grep -E "(MemTotal|MemFree|MemAvailable|Cached)"
      
      # Monitor heap usage
      kubectl exec -it deployment/kuzuk-master -n kuzuk -- \
        curl http://localhost:8000/metrics | grep heap_memory

Storage Optimization
~~~~~~~~~~~~~~~~~~~

1. **Storage Class Selection:**

   .. code-block:: yaml

      # High-performance storage class
      apiVersion: storage.k8s.io/v1
      kind: StorageClass
      metadata:
        name: kuzu-fast-ssd
      provisioner: kubernetes.io/aws-ebs  # Or your cloud provider
      parameters:
        type: gp3
        iops: "10000"
        throughput: "1000"
        fsType: ext4
      mountOptions:
      - noatime
      - nodiratime
      volumeBindingMode: WaitForFirstConsumer
      allowVolumeExpansion: true

2. **File System Optimization:**

   .. code-block:: bash

      # Optimize file system for database workloads
      kubectl apply -f - <<EOF
      apiVersion: v1
      kind: ConfigMap
      metadata:
        name: storage-tuning
        namespace: kuzuk
      data:
        tune-storage.sh: |
          #!/bin/bash
          # Set optimal mount options
          mount -o remount,noatime,nodiratime /data
          
          # Optimize for database I/O
          echo deadline > /sys/block/nvme0n1/queue/scheduler
          echo 0 > /sys/block/nvme0n1/queue/rotational
          echo 1 > /sys/block/nvme0n1/queue/iosched/fifo_batch
      EOF

3. **Storage Performance Monitoring:**

   .. code-block:: bash

      # Monitor I/O performance
      kubectl exec -it deployment/kuzuk-master -n kuzuk -- iostat -x 1 5
      
      # Test storage performance
      kubectl exec -it deployment/kuzuk-master -n kuzuk -- \
        dd if=/dev/zero of=/data/test bs=1M count=1000 conv=fdatasync

Network Optimization
--------------------

Network Configuration
~~~~~~~~~~~~~~~~~~~~~

1. **Network Policies for Performance:**

   .. code-block:: yaml

      # Optimized network policy
      apiVersion: networking.k8s.io/v1
      kind: NetworkPolicy
      metadata:
        name: kuzuk-performance
        namespace: kuzuk
      spec:
        podSelector:
          matchLabels:
            app: kuzuk
        policyTypes:
        - Ingress
        - Egress
        ingress:
        - from:
          - podSelector:
              matchLabels:
                app: kuzuk
          ports:
          - protocol: TCP
            port: 8000
          - protocol: TCP
            port: 8001  # Replication port
        egress:
        - to: []  # Allow all outbound for better performance

2. **Service Mesh Optimization:**

   .. code-block:: yaml

      # Istio service mesh configuration for performance
      apiVersion: networking.istio.io/v1beta1
      kind: DestinationRule
      metadata:
        name: kuzuk-performance
        namespace: kuzuk
      spec:
        host: kuzuk-service
        trafficPolicy:
          connectionPool:
            tcp:
              maxConnections: 100
              connectTimeout: 10s
              keepAlive:
                time: 600s
                interval: 60s
            http:
              http1MaxPendingRequests: 100
              http2MaxRequests: 100
              maxRequestsPerConnection: 10
              maxRetries: 3
              consecutiveGatewayErrors: 5
              interval: 30s
              baseEjectionTime: 30s

Connection Pooling
~~~~~~~~~~~~~~~~~

1. **Optimal Pool Sizing:**

   .. code-block:: yaml

      connection_pool:
        master:
          min_connections: 5
          max_connections: 50
          connection_timeout: 30s
          idle_timeout: 300s
          max_lifetime: 3600s
        replica:
          min_connections: 3
          max_connections: 30
          connection_timeout: 15s
          idle_timeout: 180s
          max_lifetime: 1800s

2. **Connection Pool Monitoring:**

   .. code-block:: bash

      # Monitor connection pool metrics
      curl -s http://localhost:9090/api/v1/query?query=kuzu_connection_pool_active
      curl -s http://localhost:9090/api/v1/query?query=kuzu_connection_pool_idle

Replication Performance
~~~~~~~~~~~~~~~~~~~~~~

1. **WAL Streaming Optimization:**

   .. code-block:: yaml

      replication:
        wal_sender_timeout: 30s
        wal_receiver_timeout: 30s
        wal_batch_size: 1000
        wal_flush_interval: 100ms
        max_replication_slots: 20
        tcp_keepalive:
          enabled: true
          idle: 600
          interval: 60
          count: 3

2. **Network Bandwidth Optimization:**

   .. code-block:: bash

      # Monitor replication bandwidth
      kubectl exec -it deployment/kuzuk-master -n kuzuk -- \
        iftop -t -s 10 -i eth0

Application-Level Optimization
------------------------------

Query Caching
~~~~~~~~~~~~~

1. **Result Cache Configuration:**

   .. code-block:: yaml

      cache:
        enabled: true
        type: "redis"  # or "memory"
        ttl: 300       # 5 minutes
        max_size: "1Gi"
        eviction_policy: "lru"
        
        # Cache key strategy
        key_strategy: "query_hash"  # or "query_params"
        
        # What to cache
        cache_rules:
        - query_pattern: "MATCH.*count\\(.*\\)"
          ttl: 600
        - query_pattern: "MATCH.*WHERE.*age.*"
          ttl: 180

2. **Cache Implementation:**

   .. code-block:: python

      from kuzuk import KuzukDriver
      from kuzuk.cache import QueryCache
      
      # Enable caching
      cache = QueryCache(
          backend="redis",
          host="redis-service",
          port=6379,
          ttl=300
      )
      
      driver = KuzukDriver(
          "/path/to/database",
          query_cache=cache
      )
      
      # Cached queries
      result1 = await driver.execute_query("MATCH (n:User) RETURN count(n)")  # Cache miss
      result2 = await driver.execute_query("MATCH (n:User) RETURN count(n)")  # Cache hit

Connection Management
~~~~~~~~~~~~~~~~~~~~

1. **Connection Lifecycle:**

   .. code-block:: python

      # Optimal connection usage
      async with KuzukDriver("/path/to/database") as driver:
          # Batch related queries to reuse connections
          async with driver.transaction() as tx:
              await tx.execute("CREATE (u:User {name: 'Alice'})")
              await tx.execute("CREATE (u:User {name: 'Bob'})")
              await tx.commit()

2. **Connection Health Monitoring:**

   .. code-block:: python

      # Monitor connection health
      health_stats = await driver.get_connection_health()
      print(f"Active connections: {health_stats.active}")
      print(f"Idle connections: {health_stats.idle}")
      print(f"Failed connections: {health_stats.failed}")

Monitoring and Alerting
-----------------------

Performance Metrics
~~~~~~~~~~~~~~~~~~~

1. **Key Performance Indicators:**

   .. code-block:: yaml

      # Define performance SLIs
      slis:
        query_latency:
          name: "Query Response Time"
          query: "histogram_quantile(0.95, rate(kuzu_query_duration_seconds_bucket[5m]))"
          target: "< 0.5"  # 500ms
          
        throughput:
          name: "Queries Per Second"
          query: "rate(kuzu_queries_total[5m])"
          target: "> 100"
          
        error_rate:
          name: "Query Error Rate"
          query: "rate(kuzu_errors_total[5m]) / rate(kuzu_queries_total[5m])"
          target: "< 0.001"  # 0.1%
          
        availability:
          name: "Service Availability"
          query: "up{job=\"kuzuk\"}"
          target: "> 0.999"  # 99.9%

2. **Performance Dashboards:**

   Create custom Grafana panels:

   .. code-block:: json

      {
        "title": "Query Performance Analysis",
        "panels": [
          {
            "title": "Query Latency Distribution",
            "type": "heatmap",
            "targets": [
              {
                "expr": "rate(kuzu_query_duration_seconds_bucket[5m])",
                "format": "heatmap"
              }
            ]
          },
          {
            "title": "Top Slow Queries",
            "type": "table",
            "targets": [
              {
                "expr": "topk(10, rate(kuzu_slow_queries_total[10m]))"
              }
            ]
          }
        ]
      }

Performance Alerting
~~~~~~~~~~~~~~~~~~~

1. **Performance-based Alerts:**

   .. code-block:: yaml

      # Advanced performance alerts
      groups:
      - name: performance-alerts
        rules:
        - alert: QueryLatencyHigh
          expr: histogram_quantile(0.95, rate(kuzu_query_duration_seconds_bucket[10m])) > 2
          for: 5m
          labels:
            severity: warning
            component: performance
          annotations:
            summary: "High query latency detected"
            description: "95th percentile latency is {{ $value }}s"
            
        - alert: ThroughputDrop
          expr: rate(kuzu_queries_total[10m]) < rate(kuzu_queries_total[1h] offset 1h) * 0.5
          for: 10m
          labels:
            severity: warning
          annotations:
            summary: "Query throughput dropped significantly"
            
        - alert: ResourceExhaustion
          expr: |
            (
              kuzu_cpu_usage_percent > 90 or
              kuzu_memory_usage_percent > 90 or
              kuzu_disk_usage_percent > 85
            )
          for: 10m
          labels:
            severity: critical
          annotations:
            summary: "Resource exhaustion detected"

Continuous Optimization
-----------------------

Performance Testing
~~~~~~~~~~~~~~~~~~~

1. **Automated Performance Tests:**

   .. code-block:: bash

      #!/bin/bash
      # performance-regression-test.sh
      
      # Run baseline performance test
      ./k8s/scripts/performance-benchmark.sh --duration 600 --concurrency 50 > baseline.json
      
      # Deploy new version
      kubectl set image deployment/kuzuk-master kuzuk-master=kuzuk:new-version -n kuzuk
      kubectl rollout status deployment/kuzuk-master -n kuzuk
      
      # Run performance test on new version
      ./k8s/scripts/performance-benchmark.sh --duration 600 --concurrency 50 > new-version.json
      
      # Compare results
      python compare-performance.py baseline.json new-version.json

2. **Load Testing Strategy:**

   .. code-block:: yaml

      # Load test configuration
      load_test:
        stages:
        - name: "ramp-up"
          duration: "5m"
          target_qps: 100
        - name: "sustained"
          duration: "20m"
          target_qps: 500
        - name: "peak"
          duration: "10m"
          target_qps: 1000
        - name: "ramp-down"
          duration: "5m"
          target_qps: 100
          
        scenarios:
        - name: "read-heavy"
          weight: 70
          queries:
          - "MATCH (n:User) RETURN count(n)"
          - "MATCH (u:User)-[:FOLLOWS]->(f) RETURN u.name, count(f)"
        - name: "write-heavy"
          weight: 20
          queries:
          - "CREATE (u:User {name: randomString()})"
          - "MATCH (u:User {id: randomInt()}) SET u.last_login = timestamp()"
        - name: "analytical"
          weight: 10
          queries:
          - "MATCH (u:User)-[:PURCHASED]->(p:Product) RETURN u.country, sum(p.price) GROUP BY u.country"

Capacity Planning
~~~~~~~~~~~~~~~~

1. **Growth Projections:**

   .. code-block:: python

      # Capacity planning model
      def calculate_capacity_requirements(
          current_qps: float,
          growth_rate: float,  # Monthly growth percentage
          target_latency: float,  # Target p95 latency in seconds
          planning_horizon: int   # Months
      ):
          projected_qps = current_qps * (1 + growth_rate) ** planning_horizon
          
          # Estimate required replicas based on capacity per replica
          qps_per_replica = 100  # Adjust based on benchmarks
          required_replicas = math.ceil(projected_qps / qps_per_replica)
          
          # Add buffer for failover and maintenance
          recommended_replicas = int(required_replicas * 1.3)
          
          return {
              "projected_qps": projected_qps,
              "required_replicas": required_replicas,
              "recommended_replicas": recommended_replicas
          }

2. **Resource Forecasting:**

   .. code-block:: bash

      # Monitor resource trends
      curl -G 'http://localhost:9090/api/v1/query_range' \
        --data-urlencode 'query=rate(kuzu_cpu_usage_seconds_total[1h])' \
        --data-urlencode 'start=2024-01-01T00:00:00Z' \
        --data-urlencode 'end=2024-12-31T23:59:59Z' \
        --data-urlencode 'step=1d' | \
        python analyze-trends.py

Performance Troubleshooting
---------------------------

Common Performance Issues
~~~~~~~~~~~~~~~~~~~~~~~~~

1. **High CPU Usage:**

   **Symptoms:** CPU utilization > 80%, slow query responses
   
   **Investigation:**
   
   .. code-block:: bash

      # Check CPU usage by process
      kubectl exec -it deployment/kuzuk-master -n kuzuk -- top -p $(pgrep kuzu)
      
      # Analyze CPU-intensive queries
      kubectl logs deployment/kuzuk-master -n kuzuk | grep "cpu_time" | sort -k3 -nr | head -10

   **Solutions:**
   
   - Scale horizontally (add more replicas)
   - Optimize queries (add indexes, reduce complexity)
   - Increase CPU limits
   - Use query caching

2. **Memory Pressure:**

   **Symptoms:** Memory usage > 85%, OOMKilled events
   
   **Investigation:**
   
   .. code-block:: bash

      # Check memory usage patterns
      kubectl exec -it deployment/kuzuk-master -n kuzuk -- cat /proc/meminfo
      
      # Monitor heap usage
      kubectl exec -it deployment/kuzuk-master -n kuzuk -- curl http://localhost:8000/memory-stats

   **Solutions:**
   
   - Increase memory limits
   - Optimize query result sizes
   - Implement query result streaming
   - Tune garbage collection

3. **I/O Bottlenecks:**

   **Symptoms:** High I/O wait, slow disk operations
   
   **Investigation:**
   
   .. code-block:: bash

      # Monitor I/O statistics
      kubectl exec -it deployment/kuzuk-master -n kuzuk -- iostat -x 1 5
      
      # Check disk queue depth
      kubectl exec -it deployment/kuzuk-master -n kuzuk -- cat /proc/diskstats

   **Solutions:**
   
   - Upgrade to faster storage class
   - Optimize file system (use noatime, nodiratime)
   - Implement read-ahead tuning
   - Consider SSD storage

Performance Optimization Checklist
----------------------------------

Pre-Production Checklist
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   □ Baseline performance measurements established
   □ Resource requirements calculated
   □ Storage class optimized for workload
   □ Network policies configured for performance
   □ Connection pooling configured
   □ Query caching implemented
   □ Monitoring and alerting configured
   □ Load testing completed
   □ Capacity planning documented
   □ Performance regression tests automated

Production Monitoring Checklist
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   □ Key performance metrics monitored
   □ Performance alerts configured
   □ Regular performance reviews scheduled
   □ Capacity utilization tracked
   □ Performance trends analyzed
   □ Optimization opportunities identified
   □ Performance impact of changes measured
   □ SLO compliance monitored
   □ Performance runbooks maintained
   □ Team trained on performance tools

Ongoing Optimization Checklist
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: text

   □ Weekly performance reviews
   □ Monthly capacity planning updates
   □ Quarterly performance optimization sprints
   □ Performance test automation maintained
   □ Monitoring dashboards updated
   □ Alert thresholds tuned
   □ Performance documentation updated
   □ Team knowledge sharing sessions
   □ Performance budget tracking
   □ Continuous improvement initiatives

Best Practices Summary
---------------------

1. **Measure Before Optimizing:** Always establish baselines before making changes
2. **Optimize Incrementally:** Make one change at a time and measure impact
3. **Monitor Continuously:** Use comprehensive monitoring and alerting
4. **Plan for Growth:** Regular capacity planning and resource forecasting
5. **Test Regularly:** Automated performance testing in CI/CD pipeline
6. **Document Everything:** Maintain performance runbooks and optimization guides
7. **Train the Team:** Ensure team understands performance tools and techniques
8. **Review Regularly:** Conduct regular performance reviews and optimization sessions

See Also
--------

* :doc:`runbooks` - Performance troubleshooting procedures
* :doc:`../monitoring` - Comprehensive monitoring setup
* :doc:`../deployment/production` - Production deployment guide
* :doc:`../api/monitoring` - Monitoring API reference