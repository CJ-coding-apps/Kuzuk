"""
Health Monitor for Enhanced RAG 6.2 KuzuDB Scaling
Monitors health and performance of master and replica nodes.
"""

import asyncio
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import psutil

logger = logging.getLogger(__name__)


class NodeHealth(Enum):
    """Health status of a node."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"
    UNKNOWN = "unknown"
    OFFLINE = "offline"


@dataclass
class HealthMetrics:
    """Health metrics for a node."""

    node_id: str
    timestamp: datetime
    health_status: NodeHealth

    # Performance metrics
    response_time_ms: float
    cpu_usage_percent: float
    memory_usage_percent: float
    disk_usage_percent: float

    # Database-specific metrics
    query_success_rate: float
    replication_lag_ms: float
    connection_count: int
    active_queries: int

    # Error metrics
    error_count_1h: int
    error_count_24h: int
    last_error: Optional[str]

    # Custom metrics
    custom_metrics: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = asdict(self)
        result["timestamp"] = self.timestamp.isoformat()
        result["health_status"] = self.health_status.value
        return result


@dataclass
class HealthThresholds:
    """Configurable health thresholds."""

    response_time_warning_ms: float = 1000
    response_time_critical_ms: float = 5000
    cpu_warning_percent: float = 80
    cpu_critical_percent: float = 95
    memory_warning_percent: float = 80
    memory_critical_percent: float = 95
    disk_warning_percent: float = 80
    disk_critical_percent: float = 90
    replication_lag_warning_ms: float = 5000
    replication_lag_critical_ms: float = 30000
    error_rate_warning: float = 0.05  # 5%
    error_rate_critical: float = 0.20  # 20%


class HealthChecker:
    """Performs health checks on individual nodes."""

    def __init__(self, thresholds: Optional[HealthThresholds] = None):
        """Initialize health checker."""
        self.thresholds = thresholds or HealthThresholds()
        self.error_history: Dict[str, List[datetime]] = {}

    async def check_node_health(
        self, node_id: str, driver: Any, replica_info: Optional[Any] = None
    ) -> HealthMetrics:
        """
        Perform comprehensive health check on a node.

        Args:
            node_id: Unique identifier for the node
            driver: Database driver/connection
            replica_info: Optional replica information

        Returns:
            HealthMetrics with current health status
        """
        time.time()

        try:
            # Basic connectivity and response time
            response_time_ms = await self._check_connectivity(driver)

            # System resource metrics
            cpu_usage = self._get_cpu_usage()
            memory_usage = self._get_memory_usage()
            disk_usage = self._get_disk_usage()

            # Database-specific metrics
            query_success_rate = await self._check_query_success_rate(driver)
            replication_lag_ms = self._get_replication_lag(replica_info)
            connection_count = await self._get_connection_count(driver)
            active_queries = await self._get_active_queries(driver)

            # Error metrics
            error_1h, error_24h, last_error = self._get_error_metrics(node_id)

            # Determine overall health status
            health_status = self._calculate_health_status(
                response_time_ms,
                cpu_usage,
                memory_usage,
                disk_usage,
                replication_lag_ms,
                query_success_rate,
            )

            return HealthMetrics(
                node_id=node_id,
                timestamp=datetime.now(),
                health_status=health_status,
                response_time_ms=response_time_ms,
                cpu_usage_percent=cpu_usage,
                memory_usage_percent=memory_usage,
                disk_usage_percent=disk_usage,
                query_success_rate=query_success_rate,
                replication_lag_ms=replication_lag_ms,
                connection_count=connection_count,
                active_queries=active_queries,
                error_count_1h=error_1h,
                error_count_24h=error_24h,
                last_error=last_error,
                custom_metrics={},
            )

        except Exception as e:
            logger.error(f"Health check failed for {node_id}: {e}")
            self._record_error(node_id, str(e))

            return HealthMetrics(
                node_id=node_id,
                timestamp=datetime.now(),
                health_status=NodeHealth.OFFLINE,
                response_time_ms=0,
                cpu_usage_percent=0,
                memory_usage_percent=0,
                disk_usage_percent=0,
                query_success_rate=0,
                replication_lag_ms=float("inf"),
                connection_count=0,
                active_queries=0,
                error_count_1h=0,
                error_count_24h=0,
                last_error=str(e),
                custom_metrics={},
            )

    async def _check_connectivity(self, driver: Any) -> float:
        """Check basic connectivity and measure response time."""
        start_time = time.time()

        try:
            # Use the KuzuDriver's health_check method for real connectivity testing
            if hasattr(driver, "health_check"):
                health_result = await driver.health_check()
                if health_result.get("healthy"):
                    response_time = (time.time() - start_time) * 1000
                    return response_time
                else:
                    logger.warning(
                        f"Driver health check failed: {health_result.get('error', 'Unknown')}"
                    )
                    return float("inf")
            else:
                # Fallback: try a simple query
                result = await driver.execute_query("RETURN 1 as health_check")
                if result.get("success"):
                    response_time = (time.time() - start_time) * 1000
                    return response_time
                else:
                    return float("inf")

        except Exception as e:
            logger.error(f"Connectivity check failed: {e}")
            return float("inf")

    def _get_cpu_usage(self) -> float:
        """Get current CPU usage percentage."""
        try:
            return psutil.cpu_percent(interval=0.1)
        except Exception:
            return 0.0

    def _get_memory_usage(self) -> float:
        """Get current memory usage percentage."""
        try:
            memory = psutil.virtual_memory()
            return memory.percent
        except Exception:
            return 0.0

    def _get_disk_usage(self) -> float:
        """Get current disk usage percentage."""
        try:
            disk = psutil.disk_usage("/")
            return (disk.used / disk.total) * 100
        except Exception:
            return 0.0

    async def _check_query_success_rate(self, driver: Any) -> float:
        """Check query success rate by running test queries."""
        try:
            # Test a simple query to check if the database is responding
            test_queries = ["RETURN 1 as test", "RETURN 'health_check' as status"]

            successful_queries = 0
            for query in test_queries:
                try:
                    result = await driver.execute_query(query)
                    if result.get("success"):
                        successful_queries += 1
                except Exception as e:
                    # Best-effort probe: a failed probe simply counts as unsuccessful.
                    logger.debug(f"Health-check query failed: {e}")

            return successful_queries / len(test_queries) if test_queries else 0.0

        except Exception as e:
            logger.error(f"Query success rate check failed: {e}")
            return 0.0

    def _get_replication_lag(self, replica_info: Optional[Any]) -> float:
        """Get replication lag from replica info."""
        if replica_info and hasattr(replica_info, "lag_ms"):
            return replica_info.lag_ms
        return 0.0

    async def _get_connection_count(self, driver: Any) -> int:
        """Get current connection count."""
        # Placeholder - would query actual connection count
        return 1

    async def _get_active_queries(self, driver: Any) -> int:
        """Get number of active queries."""
        # Placeholder - would query actual active queries
        return 0

    def _record_error(self, node_id: str, error: str) -> None:
        """Record an error for the node."""
        if node_id not in self.error_history:
            self.error_history[node_id] = []

        self.error_history[node_id].append(datetime.now())

        # Clean up old errors (older than 24 hours)
        cutoff = datetime.now() - timedelta(hours=24)
        self.error_history[node_id] = [
            err_time for err_time in self.error_history[node_id] if err_time > cutoff
        ]

    def _get_error_metrics(self, node_id: str) -> tuple:
        """Get error metrics for the node."""
        if node_id not in self.error_history:
            return 0, 0, None

        errors = self.error_history[node_id]
        now = datetime.now()

        errors_1h = len([err for err in errors if now - err <= timedelta(hours=1)])
        errors_24h = len(errors)
        last_error = "Recent connectivity issue" if errors else None

        return errors_1h, errors_24h, last_error

    def _calculate_health_status(
        self,
        response_time_ms: float,
        cpu_usage: float,
        memory_usage: float,
        disk_usage: float,
        replication_lag_ms: float,
        query_success_rate: float,
    ) -> NodeHealth:
        """Calculate overall health status based on metrics."""

        # Check for critical conditions
        if (
            response_time_ms > self.thresholds.response_time_critical_ms
            or cpu_usage > self.thresholds.cpu_critical_percent
            or memory_usage > self.thresholds.memory_critical_percent
            or disk_usage > self.thresholds.disk_critical_percent
            or replication_lag_ms > self.thresholds.replication_lag_critical_ms
            or query_success_rate < (1 - self.thresholds.error_rate_critical)
        ):
            return NodeHealth.CRITICAL

        # Check for warning conditions
        if (
            response_time_ms > self.thresholds.response_time_warning_ms
            or cpu_usage > self.thresholds.cpu_warning_percent
            or memory_usage > self.thresholds.memory_warning_percent
            or disk_usage > self.thresholds.disk_warning_percent
            or replication_lag_ms > self.thresholds.replication_lag_warning_ms
            or query_success_rate < (1 - self.thresholds.error_rate_warning)
        ):
            return NodeHealth.WARNING

        return NodeHealth.HEALTHY


class HealthMonitor:
    """Monitors health of all nodes in the scaling infrastructure."""

    def __init__(
        self,
        check_interval: float = 30.0,
        thresholds: Optional[HealthThresholds] = None,
        alert_callback: Optional[Callable[[HealthMetrics], None]] = None,
    ):
        """
        Initialize health monitor.

        Args:
            check_interval: Seconds between health checks
            thresholds: Health thresholds configuration
            alert_callback: Callback function for health alerts
        """
        self.check_interval = check_interval
        self.alert_callback = alert_callback
        self.health_checker = HealthChecker(thresholds)

        # Monitored nodes
        self.nodes: Dict[str, Dict[str, Any]] = {}

        # Health history
        self.health_history: Dict[str, List[HealthMetrics]] = {}
        self.max_history_entries = 1000

        # Monitoring state
        self.monitoring_task: Optional[asyncio.Task] = None
        self.running = False

        logger.info("Health monitor initialized")

    def add_node(
        self,
        node_id: str,
        driver: Any,
        node_type: str = "replica",
        replica_info: Optional[Any] = None,
    ) -> None:
        """
        Add a node to monitor.

        Args:
            node_id: Unique identifier for the node
            driver: Database driver/connection
            node_type: Type of node ("master", "replica", "analytical")
            replica_info: Optional replica information
        """
        self.nodes[node_id] = {
            "driver": driver,
            "node_type": node_type,
            "replica_info": replica_info,
        }
        self.health_history[node_id] = []

        logger.info(f"Added node to monitoring: {node_id} ({node_type})")

    def remove_node(self, node_id: str) -> None:
        """Remove a node from monitoring."""
        if node_id in self.nodes:
            del self.nodes[node_id]
            # Keep health history for analysis

        logger.info(f"Removed node from monitoring: {node_id}")

    async def start_monitoring(self) -> None:
        """Start the health monitoring loop."""
        if self.running:
            logger.warning("Health monitoring already running")
            return

        self.running = True
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        logger.info("Health monitoring started")

    async def stop_monitoring(self) -> None:
        """Stop the health monitoring loop."""
        self.running = False
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass

        logger.info("Health monitoring stopped")

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        while self.running:
            try:
                # Check health of all nodes
                health_checks = []
                for node_id, node_info in self.nodes.items():
                    check_task = self.health_checker.check_node_health(
                        node_id, node_info["driver"], node_info.get("replica_info")
                    )
                    health_checks.append((node_id, check_task))

                # Execute all health checks in parallel
                for node_id, check_task in health_checks:
                    try:
                        health_metrics = await check_task
                        await self._process_health_metrics(health_metrics)
                    except Exception as e:
                        logger.error(f"Health check failed for {node_id}: {e}")

                # Wait for next check interval
                await asyncio.sleep(self.check_interval)

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                await asyncio.sleep(self.check_interval)

    async def _process_health_metrics(self, metrics: HealthMetrics) -> None:
        """Process health metrics and trigger alerts if needed."""
        # Store in history
        if metrics.node_id not in self.health_history:
            self.health_history[metrics.node_id] = []

        self.health_history[metrics.node_id].append(metrics)

        # Limit history size
        if len(self.health_history[metrics.node_id]) > self.max_history_entries:
            self.health_history[metrics.node_id] = self.health_history[metrics.node_id][
                -self.max_history_entries :
            ]

        # Trigger alerts for critical or warning conditions
        if metrics.health_status in [NodeHealth.CRITICAL, NodeHealth.WARNING, NodeHealth.OFFLINE]:
            logger.warning(f"Health alert: {metrics.node_id} is {metrics.health_status.value}")

            if self.alert_callback:
                try:
                    self.alert_callback(metrics)
                except Exception as e:
                    logger.error(f"Alert callback failed: {e}")

    async def get_node_health(self, node_id: str) -> Optional[HealthMetrics]:
        """Get current health metrics for a specific node."""
        if node_id not in self.nodes:
            return None

        node_info = self.nodes[node_id]
        return await self.health_checker.check_node_health(
            node_id, node_info["driver"], node_info.get("replica_info")
        )

    def get_all_health_status(self) -> Dict[str, HealthMetrics]:
        """Get latest health status for all monitored nodes."""
        latest_health = {}

        for node_id, history in self.health_history.items():
            if history:
                latest_health[node_id] = history[-1]

        return latest_health

    def get_healthy_nodes(self) -> List[str]:
        """Get list of currently healthy node IDs."""
        healthy_nodes = []

        for node_id, history in self.health_history.items():
            if history and history[-1].health_status == NodeHealth.HEALTHY:
                healthy_nodes.append(node_id)

        return healthy_nodes

    def get_health_summary(self) -> Dict[str, Any]:
        """Get overall health summary."""
        total_nodes = len(self.nodes)
        if total_nodes == 0:
            return {"total_nodes": 0, "healthy_nodes": 0, "health_percentage": 0}

        latest_health = self.get_all_health_status()
        healthy_count = len(
            [
                metrics
                for metrics in latest_health.values()
                if metrics.health_status == NodeHealth.HEALTHY
            ]
        )

        warning_count = len(
            [
                metrics
                for metrics in latest_health.values()
                if metrics.health_status == NodeHealth.WARNING
            ]
        )

        critical_count = len(
            [
                metrics
                for metrics in latest_health.values()
                if metrics.health_status == NodeHealth.CRITICAL
            ]
        )

        offline_count = len(
            [
                metrics
                for metrics in latest_health.values()
                if metrics.health_status == NodeHealth.OFFLINE
            ]
        )

        return {
            "total_nodes": total_nodes,
            "healthy_nodes": healthy_count,
            "warning_nodes": warning_count,
            "critical_nodes": critical_count,
            "offline_nodes": offline_count,
            "health_percentage": (healthy_count / total_nodes) * 100,
            "monitoring_running": self.running,
        }

    def get_node_history(self, node_id: str, limit: int = 100) -> List[HealthMetrics]:
        """Get health history for a specific node."""
        if node_id not in self.health_history:
            return []

        return self.health_history[node_id][-limit:]

    async def close(self) -> None:
        """Clean up resources."""
        await self.stop_monitoring()
        logger.info("Health monitor closed")


# Factory functions
def create_basic_monitor(check_interval: float = 30.0) -> HealthMonitor:
    """Create a basic health monitor with default settings."""
    return HealthMonitor(check_interval=check_interval)


def create_enterprise_monitor(
    check_interval: float = 10.0, alert_callback: Optional[Callable[[HealthMetrics], None]] = None
) -> HealthMonitor:
    """Create an enterprise health monitor with more frequent checks."""
    # More strict thresholds for enterprise
    thresholds = HealthThresholds(
        response_time_warning_ms=500,
        response_time_critical_ms=2000,
        cpu_warning_percent=70,
        cpu_critical_percent=90,
        memory_warning_percent=70,
        memory_critical_percent=90,
        replication_lag_warning_ms=2000,
        replication_lag_critical_ms=10000,
    )

    return HealthMonitor(
        check_interval=check_interval, thresholds=thresholds, alert_callback=alert_callback
    )
