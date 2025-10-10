Troubleshooting Runbooks
========================

This section provides step-by-step troubleshooting procedures for common Kuzuk issues.

.. contents::
   :local:
   :depth: 2

Critical Issues
---------------

Cluster Down
~~~~~~~~~~~~

**Symptoms:**
- All Kuzuk instances showing as down
- Unable to connect to any replica
- Health checks failing across the cluster

**Immediate Actions:**

1. **Check Kubernetes cluster status:**

   .. code-block:: bash

      kubectl get nodes
      kubectl get pods -n kuzuk
      kubectl describe pods -n kuzuk

2. **Verify network connectivity:**

   .. code-block:: bash

      # Test internal DNS resolution
      kubectl exec -it deploy/kuzuk-master -n kuzuk -- nslookup kuzuk-service
      
      # Check service endpoints
      kubectl get endpoints -n kuzuk

3. **Check resource availability:**

   .. code-block:: bash

      kubectl top nodes
      kubectl top pods -n kuzuk
      kubectl describe nodes

4. **Review cluster events:**

   .. code-block:: bash

      kubectl get events -n kuzuk --sort-by=.metadata.creationTimestamp

**Investigation Steps:**

1. **Check master node status:**

   .. code-block:: bash

      kubectl logs -f deployment/kuzuk-master -n kuzuk --tail=100
      kubectl describe pod $(kubectl get pods -n kuzuk -l component=master -o name | head -1)

2. **Examine storage issues:**

   .. code-block:: bash

      kubectl get pvc -n kuzuk
      kubectl describe pvc kuzuk-master-data -n kuzuk

3. **Check configuration:**

   .. code-block:: bash

      kubectl get configmap kuzuk-config -n kuzuk -o yaml
      kubectl get secret kuzuk-secrets -n kuzuk -o yaml

**Resolution:**

1. **If storage issues:**

   .. code-block:: bash

      # Check storage class
      kubectl get storageclass
      
      # Recreate PVC if corrupted
      kubectl delete pvc kuzuk-master-data -n kuzuk
      kubectl apply -f k8s/persistent-volume.yaml

2. **If configuration issues:**

   .. code-block:: bash

      # Update configuration
      kubectl apply -f k8s/configmap.yaml
      kubectl apply -f k8s/secret.yaml
      
      # Restart deployments
      kubectl rollout restart deployment/kuzuk-master -n kuzuk
      kubectl rollout restart deployment/kuzuk-replica -n kuzuk

3. **If resource constraints:**

   .. code-block:: bash

      # Scale down non-essential workloads
      kubectl scale deployment non-essential-app --replicas=0
      
      # Add more nodes if possible
      # Update resource requests/limits
      kubectl patch deployment kuzuk-master -n kuzuk -p '{"spec":{"template":{"spec":{"containers":[{"name":"kuzuk-master","resources":{"requests":{"memory":"1Gi","cpu":"500m"}}}]}}}}'

**Prevention:**
- Monitor resource utilization with alerts
- Implement proper backup and disaster recovery
- Use multiple availability zones
- Regular health checks and monitoring

Master Node Down
~~~~~~~~~~~~~~~~~

**Symptoms:**
- Master node showing as unhealthy
- Write operations failing
- Read operations still working via replicas

**Immediate Actions:**

1. **Check master pod status:**

   .. code-block:: bash

      kubectl get pods -n kuzuk -l component=master
      kubectl logs -f deployment/kuzuk-master -n kuzuk --tail=50

2. **Verify master service:**

   .. code-block:: bash

      kubectl get service kuzuk-master -n kuzuk
      kubectl describe service kuzuk-master -n kuzuk

**Investigation Steps:**

1. **Check master logs for errors:**

   .. code-block:: bash

      kubectl logs deployment/kuzuk-master -n kuzuk | grep -i error
      kubectl logs deployment/kuzuk-master -n kuzuk | grep -i fatal

2. **Check database file integrity:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- ls -la /data/
      kubectl exec -it deployment/kuzuk-master -n kuzuk -- du -sh /data/*

3. **Check resource usage:**

   .. code-block:: bash

      kubectl top pod -n kuzuk -l component=master
      kubectl describe pod $(kubectl get pods -n kuzuk -l component=master -o name | head -1)

**Resolution:**

1. **If pod crashed:**

   .. code-block:: bash

      # Get crash details
      kubectl describe pod $(kubectl get pods -n kuzuk -l component=master -o name | head -1)
      
      # Restart deployment
      kubectl rollout restart deployment/kuzuk-master -n kuzuk
      kubectl rollout status deployment/kuzuk-master -n kuzuk

2. **If database corruption:**

   .. code-block:: bash

      # Scale down master
      kubectl scale deployment kuzuk-master --replicas=0 -n kuzuk
      
      # Restore from backup
      kubectl apply -f backup-restore-job.yaml
      
      # Scale back up
      kubectl scale deployment kuzuk-master --replicas=1 -n kuzuk

3. **If resource exhaustion:**

   .. code-block:: bash

      # Increase resource limits
      kubectl patch deployment kuzuk-master -n kuzuk -p '{"spec":{"template":{"spec":{"containers":[{"name":"kuzuk-master","resources":{"limits":{"memory":"8Gi","cpu":"4000m"}}}]}}}}'

**Prevention:**
- Monitor master node health continuously
- Implement automated failover
- Regular database backups
- Resource monitoring and alerting

Majority of Replicas Down
~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptoms:**
- More than 50% of replicas showing as unhealthy
- Increased latency on read operations
- Load balancer struggling to find healthy replicas

**Immediate Actions:**

1. **Check replica pod status:**

   .. code-block:: bash

      kubectl get pods -n kuzuk -l component=replica
      kubectl describe pods -n kuzuk -l component=replica

2. **Check replica logs:**

   .. code-block:: bash

      kubectl logs deployment/kuzuk-replica -n kuzuk --tail=100

**Investigation Steps:**

1. **Identify root cause:**

   .. code-block:: bash

      # Check for common issues
      kubectl get events -n kuzuk | grep replica
      kubectl top pods -n kuzuk -l component=replica

2. **Check replication status:**

   .. code-block:: bash

      # Connect to master and check replication
      kubectl exec -it deployment/kuzuk-master -n kuzuk -- curl http://localhost:8000/replication/status

3. **Check network connectivity:**

   .. code-block:: bash

      # Test replica to master connectivity
      kubectl exec -it deployment/kuzuk-replica -n kuzuk -- nc -zv kuzuk-master 8000

**Resolution:**

1. **If network partitioning:**

   .. code-block:: bash

      # Check network policies
      kubectl get networkpolicy -n kuzuk
      
      # Temporarily disable network policies if needed
      kubectl delete networkpolicy kuzuk-network-policy -n kuzuk

2. **If resource contention:**

   .. code-block:: bash

      # Scale up nodes or reduce replica resource requests
      kubectl patch deployment kuzuk-replica -n kuzuk -p '{"spec":{"template":{"spec":{"containers":[{"name":"kuzuk-replica","resources":{"requests":{"memory":"512Mi","cpu":"250m"}}}]}}}}'

3. **If image pull issues:**

   .. code-block:: bash

      # Check image availability
      kubectl describe pods -n kuzuk -l component=replica | grep -i image
      
      # Update image pull policy
      kubectl patch deployment kuzuk-replica -n kuzuk -p '{"spec":{"template":{"spec":{"containers":[{"name":"kuzuk-replica","imagePullPolicy":"Always"}]}}}}'

**Prevention:**
- Distribute replicas across availability zones
- Monitor replica health with alerting
- Implement graceful degradation
- Use pod disruption budgets

Performance Issues
------------------

High Query Latency
~~~~~~~~~~~~~~~~~~~

**Symptoms:**
- 95th percentile query latency > 2 seconds
- Users reporting slow responses
- Dashboard showing performance degradation

**Immediate Actions:**

1. **Check current performance metrics:**

   .. code-block:: bash

      # Access Grafana dashboard
      kubectl port-forward service/grafana-service 3000:3000 -n kuzuk
      # Open http://localhost:3000/d/kuzuk-performance

2. **Identify slow queries:**

   .. code-block:: bash

      kubectl logs deployment/kuzuk-master -n kuzuk | grep "slow query"
      kubectl logs deployment/kuzuk-replica -n kuzuk | grep "slow query"

**Investigation Steps:**

1. **Check system resource usage:**

   .. code-block:: bash

      kubectl top pods -n kuzuk
      kubectl top nodes

2. **Analyze query patterns:**

   .. code-block:: bash

      # Get query statistics from Prometheus
      kubectl port-forward service/prometheus-service 9090:9090 -n kuzuk
      # Query: rate(kuzu_query_duration_seconds_sum[5m]) / rate(kuzu_query_duration_seconds_count[5m])

3. **Check replica load distribution:**

   .. code-block:: bash

      # Check load balancer metrics
      kubectl exec -it deployment/kuzuk-master -n kuzuk -- curl http://localhost:8000/load-balancer/stats

**Resolution:**

1. **If CPU bound:**

   .. code-block:: bash

      # Increase CPU limits
      kubectl patch deployment kuzuk-replica -n kuzuk -p '{"spec":{"template":{"spec":{"containers":[{"name":"kuzuk-replica","resources":{"limits":{"cpu":"2000m"}}}]}}}}'
      
      # Scale up replicas
      kubectl scale deployment kuzuk-replica --replicas=6 -n kuzuk

2. **If memory bound:**

   .. code-block:: bash

      # Increase memory limits
      kubectl patch deployment kuzuk-replica -n kuzuk -p '{"spec":{"template":{"spec":{"containers":[{"name":"kuzuk-replica","resources":{"limits":{"memory":"4Gi"}}}]}}}}'

3. **If I/O bound:**

   .. code-block:: bash

      # Check storage performance
      kubectl exec -it deployment/kuzuk-master -n kuzuk -- iostat -x 1 3
      
      # Consider storage class upgrade
      kubectl patch pvc kuzuk-master-data -n kuzuk -p '{"spec":{"storageClassName":"fast-ssd"}}'

4. **If inefficient queries:**

   .. code-block:: bash

      # Enable query plan logging
      kubectl patch configmap kuzuk-config -n kuzuk --patch '{"data":{"log_query_plans":"true"}}'
      
      # Restart to apply changes
      kubectl rollout restart deployment/kuzuk-master -n kuzuk
      kubectl rollout restart deployment/kuzuk-replica -n kuzuk

**Prevention:**
- Implement query caching
- Regular performance testing
- Proactive capacity planning
- Query optimization training

High Memory Usage
~~~~~~~~~~~~~~~~~

**Symptoms:**
- Memory usage > 85% consistently
- OOMKilled events in pod logs
- Application becoming unresponsive

**Immediate Actions:**

1. **Check memory usage:**

   .. code-block:: bash

      kubectl top pods -n kuzuk
      kubectl describe nodes | grep -A 5 "Allocated resources"

2. **Check for memory leaks:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- ps aux --sort=-%mem | head -10

**Investigation Steps:**

1. **Analyze memory patterns:**

   .. code-block:: bash

      # Check memory growth over time in Grafana
      # Query: kuzu_memory_usage_bytes

2. **Check for large queries:**

   .. code-block:: bash

      kubectl logs deployment/kuzuk-master -n kuzuk | grep "large result set"

3. **Examine garbage collection:**

   .. code-block:: bash

      kubectl logs deployment/kuzuk-master -n kuzuk | grep -i "gc"

**Resolution:**

1. **Immediate relief:**

   .. code-block:: bash

      # Increase memory limits
      kubectl patch deployment kuzuk-master -n kuzuk -p '{"spec":{"template":{"spec":{"containers":[{"name":"kuzuk-master","resources":{"limits":{"memory":"8Gi"}}}]}}}}'

2. **Restart high-memory pods:**

   .. code-block:: bash

      kubectl delete pods -n kuzuk -l component=master
      kubectl delete pods -n kuzuk -l component=replica

3. **Enable memory profiling:**

   .. code-block:: bash

      kubectl patch configmap kuzuk-config -n kuzuk --patch '{"data":{"enable_memory_profiling":"true"}}'

**Prevention:**
- Implement memory monitoring and alerting
- Regular memory usage analysis
- Query result size limits
- Proper connection pool sizing

High CPU Usage
~~~~~~~~~~~~~~

**Symptoms:**
- CPU usage > 80% sustained
- Query queue backlog building
- Response times increasing

**Investigation:**

1. **Check CPU usage patterns:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- top -p $(pgrep kuzuk)

2. **Analyze query complexity:**

   .. code-block:: bash

      kubectl logs deployment/kuzuk-master -n kuzuk | grep "complex query"

**Resolution:**

1. **Scale horizontally:**

   .. code-block:: bash

      kubectl scale deployment kuzuk-replica --replicas=8 -n kuzuk

2. **Optimize queries:**

   .. code-block:: bash

      # Enable query optimization
      kubectl patch configmap kuzuk-config -n kuzuk --patch '{"data":{"enable_query_optimization":"true"}}'

3. **Increase CPU limits:**

   .. code-block:: bash

      kubectl patch deployment kuzuk-replica -n kuzuk -p '{"spec":{"template":{"spec":{"containers":[{"name":"kuzuk-replica","resources":{"limits":{"cpu":"3000m"}}}]}}}}'

Replication Issues
------------------

Replication Lag
~~~~~~~~~~~~~~~

**Symptoms:**
- Replication lag > 5 seconds
- Stale data being returned from replicas
- WAL files building up

**Investigation:**

1. **Check replication status:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- curl http://localhost:8000/replication/lag

2. **Check WAL file sizes:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- ls -la /data/wal/

3. **Check network bandwidth:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- iftop -t -s 10

**Resolution:**

1. **Increase network bandwidth:**

   .. code-block:: bash

      # Use faster instance types or increase network limits

2. **Optimize WAL streaming:**

   .. code-block:: bash

      kubectl patch configmap kuzuk-config -n kuzuk --patch '{"data":{"wal_batch_size":"1000","wal_flush_interval":"100ms"}}'

3. **Add more replicas:**

   .. code-block:: bash

      kubectl scale deployment kuzuk-replica --replicas=4 -n kuzuk

WAL Streaming Failures
~~~~~~~~~~~~~~~~~~~~~~

**Symptoms:**
- WAL streaming error rate > 0.1/sec
- Replicas falling out of sync
- Error messages in replication logs

**Investigation:**

1. **Check WAL streaming logs:**

   .. code-block:: bash

      kubectl logs deployment/kuzuk-master -n kuzuk | grep "wal streaming"

2. **Check replica connectivity:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-replica -n kuzuk -- nc -zv kuzuk-master 8001

**Resolution:**

1. **Restart WAL streaming:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- curl -X POST http://localhost:8000/replication/restart

2. **Check disk space:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- df -h

3. **Rebuild replicas if needed:**

   .. code-block:: bash

      kubectl scale deployment kuzuk-replica --replicas=0 -n kuzuk
      # Wait for shutdown
      kubectl scale deployment kuzuk-replica --replicas=3 -n kuzuk

Monitoring and Alerting Issues
------------------------------

Prometheus Not Scraping
~~~~~~~~~~~~~~~~~~~~~~~

**Symptoms:**
- Missing metrics in Grafana
- Prometheus targets showing as down
- No data in monitoring dashboards

**Investigation:**

1. **Check Prometheus targets:**

   .. code-block:: bash

      kubectl port-forward service/prometheus-service 9090:9090 -n kuzuk
      # Open http://localhost:9090/targets

2. **Check Prometheus configuration:**

   .. code-block:: bash

      kubectl get configmap prometheus-config -n kuzuk -o yaml

3. **Check ServiceMonitor:**

   .. code-block:: bash

      kubectl get servicemonitor -n kuzuk

**Resolution:**

1. **Restart Prometheus:**

   .. code-block:: bash

      kubectl rollout restart deployment/prometheus -n kuzuk

2. **Update configuration:**

   .. code-block:: bash

      kubectl apply -f k8s/monitoring/prometheus-config.yaml

3. **Check service labels:**

   .. code-block:: bash

      kubectl get service kuzuk-service -n kuzuk --show-labels

Grafana Dashboard Issues
~~~~~~~~~~~~~~~~~~~~~~~

**Symptoms:**
- Dashboards showing no data
- Cannot connect to data sources
- Dashboard loading errors

**Investigation:**

1. **Check Grafana logs:**

   .. code-block:: bash

      kubectl logs deployment/grafana -n kuzuk

2. **Test data source connectivity:**

   .. code-block:: bash

      kubectl exec -it deployment/grafana -n kuzuk -- curl http://prometheus-service:9090/api/v1/query?query=up

**Resolution:**

1. **Restart Grafana:**

   .. code-block:: bash

      kubectl rollout restart deployment/grafana -n kuzuk

2. **Reimport dashboards:**

   .. code-block:: bash

      kubectl apply -f k8s/monitoring/grafana-dashboards.yaml

Alertmanager Not Firing
~~~~~~~~~~~~~~~~~~~~~~~

**Symptoms:**
- No alerts being sent despite issues
- Alertmanager showing configuration errors
- Notification channels not working

**Investigation:**

1. **Check Alertmanager status:**

   .. code-block:: bash

      kubectl port-forward service/alertmanager-service 9093:9093 -n kuzuk
      # Open http://localhost:9093

2. **Check alert rules:**

   .. code-block:: bash

      kubectl get prometheusrule -n kuzuk

3. **Test notification channels:**

   .. code-block:: bash

      kubectl exec -it deployment/alertmanager -n kuzuk -- amtool config test

**Resolution:**

1. **Update Alertmanager config:**

   .. code-block:: bash

      kubectl apply -f k8s/monitoring/alertmanager-config.yaml

2. **Restart Alertmanager:**

   .. code-block:: bash

      kubectl rollout restart deployment/alertmanager -n kuzuk

3. **Verify secrets:**

   .. code-block:: bash

      kubectl get secret kuzuk-secrets -n kuzuk -o yaml

Networking Issues
-----------------

Service Discovery Problems
~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptoms:**
- Pods cannot reach each other
- DNS resolution failing
- Connection timeouts

**Investigation:**

1. **Test DNS resolution:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- nslookup kuzuk-service
      kubectl exec -it deployment/kuzuk-master -n kuzuk -- nslookup kubernetes.default

2. **Check service endpoints:**

   .. code-block:: bash

      kubectl get endpoints -n kuzuk

3. **Test network connectivity:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- nc -zv kuzuk-replica 8000

**Resolution:**

1. **Restart CoreDNS:**

   .. code-block:: bash

      kubectl rollout restart deployment/coredns -n kube-system

2. **Check network policies:**

   .. code-block:: bash

      kubectl get networkpolicy -n kuzuk
      kubectl describe networkpolicy kuzuk-network-policy -n kuzuk

3. **Recreate services:**

   .. code-block:: bash

      kubectl delete service kuzuk-service -n kuzuk
      kubectl apply -f k8s/service.yaml

Ingress Not Working
~~~~~~~~~~~~~~~~~~

**Symptoms:**
- Cannot access Kuzuk from outside cluster
- Ingress returning 502/503 errors
- TLS certificate issues

**Investigation:**

1. **Check ingress status:**

   .. code-block:: bash

      kubectl get ingress -n kuzuk
      kubectl describe ingress kuzuk-ingress -n kuzuk

2. **Check ingress controller:**

   .. code-block:: bash

      kubectl get pods -n ingress-nginx
      kubectl logs -n ingress-nginx deployment/ingress-nginx-controller

3. **Test backend connectivity:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- curl http://kuzuk-service:8000/health

**Resolution:**

1. **Update ingress configuration:**

   .. code-block:: bash

      kubectl apply -f k8s/ingress.yaml

2. **Restart ingress controller:**

   .. code-block:: bash

      kubectl rollout restart deployment/ingress-nginx-controller -n ingress-nginx

3. **Check TLS certificates:**

   .. code-block:: bash

      kubectl get certificate -n kuzuk
      kubectl describe certificate kuzuk-tls -n kuzuk

Storage Issues
--------------

Disk Space Exhaustion
~~~~~~~~~~~~~~~~~~~~~

**Symptoms:**
- Disk usage > 90%
- Database write failures
- Pod evictions due to disk pressure

**Investigation:**

1. **Check disk usage:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- df -h
      kubectl top nodes

2. **Identify large files:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- du -sh /data/* | sort -hr

**Resolution:**

1. **Clean up logs:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- find /var/log -name "*.log" -mtime +7 -delete

2. **Expand PVC if supported:**

   .. code-block:: bash

      kubectl patch pvc kuzuk-master-data -n kuzuk -p '{"spec":{"resources":{"requests":{"storage":"200Gi"}}}}'

3. **Clean up WAL files:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- find /data/wal -name "*.wal" -mtime +1 -delete

Storage Performance Issues
~~~~~~~~~~~~~~~~~~~~~~~~~~

**Symptoms:**
- High I/O wait times
- Slow query execution
- Database timeouts

**Investigation:**

1. **Check I/O statistics:**

   .. code-block:: bash

      kubectl exec -it deployment/kuzuk-master -n kuzuk -- iostat -x 1 5

2. **Check storage class performance:**

   .. code-block:: bash

      kubectl describe storageclass fast-ssd

**Resolution:**

1. **Upgrade storage class:**

   .. code-block:: bash

      # Create new PVC with faster storage
      kubectl apply -f fast-storage-pvc.yaml
      
      # Migrate data
      kubectl apply -f data-migration-job.yaml

2. **Tune storage parameters:**

   .. code-block:: bash

      # Update mount options for better performance
      kubectl patch pv pv-name -p '{"spec":{"mountOptions":["noatime","nodiratime"]}}'

Escalation Procedures
--------------------

When to Escalate
~~~~~~~~~~~~~~~~

**Critical Issues (Immediate Escalation):**
- Complete cluster outage > 15 minutes
- Data corruption detected
- Security breach suspected
- >50% of replicas down > 30 minutes

**High Priority Issues (Escalate within 2 hours):**
- Master node down > 1 hour
- Performance degradation > 4 hours
- Replication lag > 1 hour
- Monitoring completely down

**Medium Priority Issues (Escalate within 8 hours):**
- Single replica down > 4 hours
- Non-critical performance issues
- Alerting issues
- Documentation/configuration issues

Escalation Contacts
~~~~~~~~~~~~~~~~~~~

**Level 1 - On-Call Engineer:**
- Slack: #kuzuk-oncall
- PagerDuty: Kuzuk High Priority
- Phone: Emergency hotline

**Level 2 - Senior Engineers:**
- Slack: #kuzuk-escalation
- Email: kuzuk-senior@company.com

**Level 3 - Architecture Team:**
- Slack: #kuzuk-architecture
- Email: kuzuk-architects@company.com

Information to Gather
~~~~~~~~~~~~~~~~~~~~~

Before escalating, collect:

1. **Incident Timeline:**
   - When did the issue start?
   - What triggered it?
   - What actions have been taken?

2. **System State:**
   - Current cluster status
   - Resource utilization
   - Recent changes

3. **Logs and Evidence:**
   - Relevant log excerpts
   - Error messages
   - Monitoring screenshots

4. **Impact Assessment:**
   - Affected users/systems
   - Business impact
   - Estimated resolution time

Documentation for Escalation:

.. code-block:: bash

   # Gather cluster information
   kubectl get all -n kuzuk > cluster-state.txt
   kubectl describe nodes > node-status.txt
   kubectl get events -n kuzuk --sort-by=.metadata.creationTimestamp > events.txt
   
   # Collect logs
   kubectl logs deployment/kuzuk-master -n kuzuk --tail=1000 > master-logs.txt
   kubectl logs deployment/kuzuk-replica -n kuzuk --tail=1000 > replica-logs.txt
   
   # Get performance data
   kubectl top nodes > resource-usage.txt
   kubectl top pods -n kuzuk >> resource-usage.txt