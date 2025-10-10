Kuzuk Documentation
=======================

.. image:: _static/kuzuk-banner.png
   :alt: Kuzuk
   :align: center
   :width: 600px

**KuzuDB Horizontal Scaling Framework with Read Replicas and Function Shipping**

Kuzuk provides production-ready horizontal scaling capabilities for KuzuDB, enabling you to scale beyond single-node limitations with read replicas and parallel query execution.

.. note::
   Kuzuk is designed for enterprise production environments and provides comprehensive monitoring, alerting, and operational capabilities.

Quick Start
-----------

Install Kuzuk::

   pip install kuzuk

Basic usage:

.. code-block:: python

   import asyncio
   from kuzuk import KuzukDriver

   async def main():
       # Create a scalable driver with 3 read replicas
       driver = KuzukDriver(
           database_path="/path/to/kuzu.db",
           replica_count=3
       )
       
       # Execute queries automatically routed to best replica
       result = await driver.execute_query("MATCH (n) RETURN count(n)")
       print(f"Node count: {result['data'][0]['count(n)']}")
       
       await driver.close()

   asyncio.run(main())

.. toctree::
   :maxdepth: 2
   :caption: User Guide

   installation
   quickstart
   configuration
   scaling_strategies
   monitoring
   troubleshooting

.. toctree::
   :maxdepth: 2
   :caption: API Reference

   api/index
   api/drivers
   api/replication
   api/function_shipping
   api/monitoring
   api/operators

.. toctree::
   :maxdepth: 2
   :caption: Deployment

   deployment/index
   deployment/kubernetes
   deployment/docker
   deployment/production
   deployment/security

.. toctree::
   :maxdepth: 2
   :caption: Operations

   operations/index
   operations/runbooks
   operations/performance_tuning
   operations/backup_restore
   operations/upgrades

.. toctree::
   :maxdepth: 2
   :caption: Developer Guide

   development/index
   development/architecture
   development/contributing
   development/testing
   development/releasing

.. toctree::
   :maxdepth: 1
   :caption: Additional Resources

   examples/index
   faq
   glossary
   changelog
   license

Features
--------

🚀 **Core Capabilities**
   * **Read Replica Pattern**: Automatically replicate KuzuDB to multiple read-only replicas
   * **Function Shipping**: Execute analytical queries in parallel across all replicas
   * **Intelligent Query Routing**: Route queries based on type and consistency requirements
   * **Automatic Failover**: Seamless failover when replicas become unhealthy

📊 **Enterprise Features**
   * **Comprehensive Monitoring**: Built-in Prometheus metrics and Grafana dashboards
   * **Advanced Alerting**: Multi-channel alerting with PagerDuty, Slack, and email integration
   * **Kubernetes Operator**: Native Kubernetes management with custom resources
   * **Production Hardening**: Security, backup, and disaster recovery capabilities

🔧 **Operational Excellence**
   * **Health Monitoring**: Real-time health checking and performance tracking
   * **Scaling Policies**: Horizontal Pod Autoscaling with custom metrics
   * **Troubleshooting**: Comprehensive runbooks and debugging tools
   * **Performance Tuning**: Optimization guides and best practices

Architecture Overview
--------------------

.. image:: _static/architecture-diagram.png
   :alt: Kuzuk Architecture
   :align: center
   :width: 800px

Kuzuk implements a master-replica architecture where:

* **Master Node**: Handles all write operations and coordinates the cluster
* **Read Replicas**: Serve read-only queries and receive updates via WAL streaming
* **Function Shipping**: Distributes analytical workloads across all replicas
* **Load Balancer**: Intelligently routes queries based on type and replica health

Supported Environments
---------------------

**Container Platforms**
   * Kubernetes 1.20+
   * Docker Compose
   * OpenShift 4.8+

**Cloud Providers**
   * Amazon EKS
   * Google GKE
   * Microsoft AKS
   * DigitalOcean Kubernetes

**Monitoring Integration**
   * Prometheus + Grafana
   * Datadog
   * New Relic
   * Custom metrics endpoints

Getting Help
-----------

* 📖 **Documentation**: Comprehensive guides and API reference
* 💬 **Community**: Join our Slack workspace for support
* 🐛 **Issues**: Report bugs on GitHub
* 📧 **Enterprise Support**: Contact us for commercial support

License
-------

Kuzuk is released under the MIT License. See :doc:`license` for details.

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`