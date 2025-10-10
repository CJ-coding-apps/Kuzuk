"""
Enterprise usage example for Kuzuk.
Demonstrates advanced features including function shipping, health monitoring, and alerting.
"""

import asyncio
import logging
from datetime import datetime
from kuzuk import (
    create_enterprise_kuzuk_driver,
    ConsistencyLevel,
    QueryContext,
    NodeHealth
)
from kuzuk.function_shipping import (
    create_count_query,
    create_distinct_query,
    create_fastest_first_query
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EnterpriseAlertManager:
    """Example alert manager for enterprise deployments."""
    
    def __init__(self):
        self.alerts = []
    
    def handle_health_alert(self, health_metrics):
        """Handle health alerts from the monitoring system."""
        alert = {
            "timestamp": datetime.now(),
            "node_id": health_metrics.node_id,
            "status": health_metrics.health_status.value,
            "cpu_usage": health_metrics.cpu_usage_percent,
            "memory_usage": health_metrics.memory_usage_percent,
            "replication_lag": health_metrics.replication_lag_ms,
            "error_count": health_metrics.error_count_1h
        }
        
        self.alerts.append(alert)
        
        if health_metrics.health_status == NodeHealth.CRITICAL:
            logger.error(f"🚨 CRITICAL ALERT: {health_metrics.node_id}")
            logger.error(f"   CPU: {health_metrics.cpu_usage_percent:.1f}%")
            logger.error(f"   Memory: {health_metrics.memory_usage_percent:.1f}%")
            logger.error(f"   Lag: {health_metrics.replication_lag_ms:.1f}ms")
            # In production: send to PagerDuty, Slack, email, etc.
            
        elif health_metrics.health_status == NodeHealth.WARNING:
            logger.warning(f"⚠️  WARNING: {health_metrics.node_id} performance degraded")
            # In production: log to monitoring dashboard
    
    def get_alert_summary(self):
        """Get summary of recent alerts."""
        if not self.alerts:
            return "No alerts"
        
        recent_alerts = self.alerts[-10:]  # Last 10 alerts
        critical_count = sum(1 for a in recent_alerts if a["status"] == "critical")
        warning_count = sum(1 for a in recent_alerts if a["status"] == "warning")
        
        return f"Recent alerts: {critical_count} critical, {warning_count} warnings"


async def enterprise_setup_example():
    """Enterprise-grade setup with all features enabled."""
    
    logger.info("🏢 Starting enterprise Kuzuk setup...")
    
    # Create alert manager
    alert_manager = EnterpriseAlertManager()
    
    # Create enterprise driver with all features
    driver = create_enterprise_kuzuk_driver(
        master_db_path="./enterprise_database.kuzu",
        replica_count=5
    )
    
    # Note: In the current implementation, we can't easily inject the alert callback
    # This would be added in the full integration
    
    try:
        # Initialize with enterprise settings
        logger.info("⚙️  Initializing enterprise scaling infrastructure...")
        await driver.initialize()
        
        # Give systems time to start up
        await asyncio.sleep(3)
        
        # Verify cluster health
        if driver.is_cluster_healthy():
            logger.info("✅ Enterprise cluster is healthy")
        else:
            logger.error("❌ Enterprise cluster has health issues")
        
        # Get comprehensive status
        status = driver.get_cluster_status()
        logger.info("📊 Enterprise Cluster Status:")
        logger.info(f"   Replicas: {status['replica_count']}")
        logger.info(f"   Initialized: {status['initialized']}")
        
        if 'health' in status:
            health = status['health']
            logger.info(f"   Health: {health.get('health_percentage', 0):.1f}%")
            logger.info(f"   Healthy nodes: {health.get('healthy_nodes', 0)}")
            logger.info(f"   Total nodes: {health.get('total_nodes', 0)}")
        
        return driver, alert_manager
        
    except Exception as e:
        logger.error(f"❌ Enterprise setup failed: {e}")
        await driver.close()
        raise


async def function_shipping_demo(driver):
    """Demonstrate parallel query execution with function shipping."""
    
    logger.info("⚡ Testing function shipping capabilities...")
    
    try:
        # Test different types of analytical queries
        analytical_queries = [
            {
                "name": "Node Count",
                "query": "MATCH (n) RETURN count(n) as total_nodes",
                "mode": "parallel_all"
            },
            {
                "name": "Relationship Count", 
                "query": "MATCH ()-[r]->() RETURN count(r) as total_relationships",
                "mode": "parallel_all"
            },
            {
                "name": "Distinct Node Types",
                "query": "MATCH (n) RETURN DISTINCT labels(n) as node_types",
                "mode": "parallel_all"
            },
            {
                "name": "Fast Query",
                "query": "MATCH (n) RETURN n LIMIT 1",
                "mode": "fastest_first"
            }
        ]
        
        for query_info in analytical_queries:
            logger.info(f"🔍 Executing {query_info['name']} with {query_info['mode']}...")
            
            try:
                start_time = datetime.now()
                
                result = await driver.execute_analytical_query(
                    query=query_info["query"],
                    execution_mode=query_info["mode"],
                    timeout_seconds=30.0
                )
                
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds() * 1000
                
                logger.info(f"   ✅ Result: {result}")
                logger.info(f"   ⏱️  Duration: {duration:.1f}ms")
                
            except Exception as e:
                logger.warning(f"   ❌ Query failed (expected for demo): {e}")
        
        logger.info("✅ Function shipping demo completed")
        
    except Exception as e:
        logger.error(f"❌ Function shipping demo failed: {e}")


async def consistency_levels_demo(driver):
    """Demonstrate different consistency levels."""
    
    logger.info("🔒 Testing consistency levels...")
    
    # Different consistency scenarios
    consistency_tests = [
        {
            "name": "Strong Consistency",
            "context": QueryContext(consistency_level=ConsistencyLevel.STRONG),
            "query": "MATCH (n:Critical) RETURN count(n)"
        },
        {
            "name": "Session Consistency", 
            "context": QueryContext(
                consistency_level=ConsistencyLevel.SESSION,
                user_session_id="user_123"
            ),
            "query": "MATCH (n:User {id: 'user_123'}) RETURN n"
        },
        {
            "name": "Eventual Consistency",
            "context": QueryContext(
                consistency_level=ConsistencyLevel.EVENTUAL,
                max_staleness_seconds=5.0
            ),
            "query": "MATCH (n:Report) RETURN count(n)"
        }
    ]
    
    for test in consistency_tests:
        logger.info(f"🎯 Testing {test['name']}...")
        
        try:
            result = await driver.execute_query(
                query=test["query"],
                context=test["context"]
            )
            logger.info(f"   ✅ Result: {result}")
            
        except Exception as e:
            logger.warning(f"   ❌ Query failed (expected for demo): {e}")
    
    logger.info("✅ Consistency levels demo completed")


async def monitoring_and_alerting_demo(driver, alert_manager):
    """Demonstrate monitoring and alerting capabilities."""
    
    logger.info("📊 Testing monitoring and alerting...")
    
    try:
        # Get current cluster health
        status = driver.get_cluster_status()
        logger.info("🏥 Current Health Status:")
        
        if 'health' in status:
            health = status['health']
            logger.info(f"   Overall health: {health.get('health_percentage', 0):.1f}%")
            logger.info(f"   Monitoring running: {health.get('monitoring_running', False)}")
            logger.info(f"   Healthy nodes: {health.get('healthy_nodes', 0)}")
            logger.info(f"   Warning nodes: {health.get('warning_nodes', 0)}")
            logger.info(f"   Critical nodes: {health.get('critical_nodes', 0)}")
            logger.info(f"   Offline nodes: {health.get('offline_nodes', 0)}")
        
        # Simulate some load to trigger monitoring
        logger.info("💪 Simulating load to test monitoring...")
        
        load_tasks = []
        for i in range(5):
            task = driver.execute_query(f"MATCH (n) WHERE id(n) % 5 = {i} RETURN count(n)")
            load_tasks.append(task)
        
        # Execute load in parallel
        await asyncio.gather(*load_tasks, return_exceptions=True)
        
        # Check health after load
        if driver.is_cluster_healthy():
            logger.info("💚 Cluster remained healthy under load")
        else:
            logger.warning("⚠️ Cluster health affected by load")
        
        # Show alert summary
        alert_summary = alert_manager.get_alert_summary()
        logger.info(f"🚨 Alert Summary: {alert_summary}")
        
        logger.info("✅ Monitoring and alerting demo completed")
        
    except Exception as e:
        logger.error(f"❌ Monitoring demo failed: {e}")


async def enterprise_operations_demo():
    """Complete enterprise operations demonstration."""
    
    logger.info("🚀 Starting comprehensive enterprise demo...")
    
    try:
        # Setup enterprise infrastructure
        driver, alert_manager = await enterprise_setup_example()
        
        # Wait for stabilization
        await asyncio.sleep(2)
        
        # Run comprehensive tests
        await function_shipping_demo(driver)
        await asyncio.sleep(1)
        
        await consistency_levels_demo(driver)
        await asyncio.sleep(1)
        
        await monitoring_and_alerting_demo(driver, alert_manager)
        
        # Final status report
        logger.info("📋 Final Enterprise Status Report:")
        final_status = driver.get_cluster_status()
        
        for component, data in final_status.items():
            if isinstance(data, dict) and len(data) > 0:
                logger.info(f"   {component}: {len(data)} items configured")
            elif not isinstance(data, dict):
                logger.info(f"   {component}: {data}")
        
        logger.info("🎉 Enterprise demo completed successfully!")
        
    except Exception as e:
        logger.error(f"❌ Enterprise demo failed: {e}")
    
    finally:
        # Cleanup
        logger.info("🧹 Cleaning up enterprise resources...")
        if 'driver' in locals():
            await driver.close()
        logger.info("✅ Enterprise cleanup completed")


if __name__ == "__main__":
    # Run the comprehensive enterprise demo
    asyncio.run(enterprise_operations_demo())