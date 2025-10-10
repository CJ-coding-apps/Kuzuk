"""
Prometheus Metrics Integration for Kuzuk
Provides comprehensive metrics collection for monitoring and alerting.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to import prometheus_client, but make it optional
try:
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        Info,
        generate_latest,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:
    logger.warning("prometheus_client not available - metrics will be collected but not exposed")
    PROMETHEUS_AVAILABLE = False


class MetricType(Enum):
    """Types of metrics we collect."""

    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    INFO = "info"


@dataclass
class MetricDefinition:
    """Definition of a metric."""

    name: str
    description: str
    metric_type: MetricType
    labels: List[str] = None
    buckets: List[float] = None  # For histograms


class PrometheusMetrics:
    """Manages Prometheus metrics for Kuzuk."""

    def __init__(self, registry: Optional[Any] = None):
        """Initialize Prometheus metrics."""
        self.registry = registry or (CollectorRegistry() if PROMETHEUS_AVAILABLE else None)
        self.metrics: Dict[str, Any] = {}
        self._initialize_metrics()

        logger.info(f"Prometheus metrics initialized (available: {PROMETHEUS_AVAILABLE})")

    def _initialize_metrics(self) -> None:
        """Initialize all Kuzuk metrics."""
        if not PROMETHEUS_AVAILABLE:
            return

        # Cluster health metrics
        self.metrics["kuzu_cluster_health_status"] = Gauge(
            "kuzu_cluster_health_status",
            "Overall cluster health status (1=healthy, 0=unhealthy)",
            registry=self.registry,
        )

        # Node metrics
        self.metrics["kuzu_node_health"] = Gauge(
            "kuzu_node_health",
            "Health status of individual nodes",
            ["node_id", "node_type"],
            registry=self.registry,
        )

        self.metrics["kuzu_node_response_time"] = Histogram(
            "kuzu_node_response_time_seconds",
            "Response time for node health checks",
            ["node_id", "node_type"],
            buckets=[0.001, 0.01, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
            registry=self.registry,
        )

        # Query metrics
        self.metrics["kuzu_queries_total"] = Counter(
            "kuzu_queries_total",
            "Total number of queries executed",
            ["node_id", "query_type", "status"],
            registry=self.registry,
        )

        self.metrics["kuzu_query_duration"] = Histogram(
            "kuzu_query_duration_seconds",
            "Query execution duration",
            ["node_id", "query_type"],
            buckets=[0.001, 0.01, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
            registry=self.registry,
        )

        # Error metrics
        self.metrics["kuzu_errors_total"] = Counter(
            "kuzu_errors_total",
            "Total number of errors",
            ["node_id", "error_type"],
            registry=self.registry,
        )

        # Replication metrics
        self.metrics["kuzu_replica_status"] = Gauge(
            "kuzu_replica_status",
            "Status of replica nodes (1=healthy, 0=unhealthy)",
            ["replica_id", "master_id"],
            registry=self.registry,
        )

        self.metrics["kuzu_replication_lag_seconds"] = Gauge(
            "kuzu_replication_lag_seconds",
            "Replication lag in seconds",
            ["replica_id", "master_id"],
            registry=self.registry,
        )

        self.metrics["kuzu_wal_records_streamed_total"] = Counter(
            "kuzu_wal_records_streamed_total",
            "Total WAL records streamed to replicas",
            ["replica_id"],
            registry=self.registry,
        )

        self.metrics["kuzu_wal_file_size_bytes"] = Gauge(
            "kuzu_wal_file_size_bytes",
            "Current WAL file size in bytes",
            ["node_id"],
            registry=self.registry,
        )

        self.metrics["kuzu_replica_sync_status"] = Gauge(
            "kuzu_replica_sync_status",
            "Replica synchronization status (1=in_sync, 0=out_of_sync)",
            ["replica_id"],
            registry=self.registry,
        )

        self.metrics["kuzu_replication_errors_total"] = Counter(
            "kuzu_replication_errors_total",
            "Total replication errors",
            ["replica_id", "error_type"],
            registry=self.registry,
        )

        # Resource metrics
        self.metrics["kuzu_cpu_usage_percent"] = Gauge(
            "kuzu_cpu_usage_percent", "CPU usage percentage", ["node_id"], registry=self.registry
        )

        self.metrics["kuzu_memory_usage_bytes"] = Gauge(
            "kuzu_memory_usage_bytes", "Memory usage in bytes", ["node_id"], registry=self.registry
        )

        self.metrics["kuzu_disk_usage_bytes"] = Gauge(
            "kuzu_disk_usage_bytes",
            "Disk usage in bytes",
            ["node_id", "mount_point"],
            registry=self.registry,
        )

        # Connection metrics
        self.metrics["kuzu_connection_pool_active"] = Gauge(
            "kuzu_connection_pool_active",
            "Number of active database connections",
            ["node_id"],
            registry=self.registry,
        )

        self.metrics["kuzu_connection_pool_idle"] = Gauge(
            "kuzu_connection_pool_idle",
            "Number of idle database connections",
            ["node_id"],
            registry=self.registry,
        )

        # Disk I/O metrics
        self.metrics["kuzu_disk_reads_total"] = Counter(
            "kuzu_disk_reads_total",
            "Total disk read operations",
            ["node_id"],
            registry=self.registry,
        )

        self.metrics["kuzu_disk_writes_total"] = Counter(
            "kuzu_disk_writes_total",
            "Total disk write operations",
            ["node_id"],
            registry=self.registry,
        )

        # Function shipping metrics
        self.metrics["kuzu_function_shipping_requests_total"] = Counter(
            "kuzu_function_shipping_requests_total",
            "Total function shipping requests",
            ["source_node", "target_node", "status"],
            registry=self.registry,
        )

        self.metrics["kuzu_function_shipping_duration"] = Histogram(
            "kuzu_function_shipping_duration_seconds",
            "Function shipping request duration",
            ["source_node", "target_node"],
            buckets=[0.001, 0.01, 0.1, 0.5, 1.0, 2.0, 5.0],
            registry=self.registry,
        )

        # Version info
        self.metrics["kuzu_build_info"] = Info(
            "kuzu_build_info", "Build information", registry=self.registry
        )

    def record_cluster_health(self, is_healthy: bool) -> None:
        """Record overall cluster health status."""
        if not PROMETHEUS_AVAILABLE or "kuzu_cluster_health_status" not in self.metrics:
            return

        self.metrics["kuzu_cluster_health_status"].set(1 if is_healthy else 0)

    def record_node_health(
        self, node_id: str, node_type: str, health_value: float, response_time: float
    ) -> None:
        """Record node health metrics."""
        if not PROMETHEUS_AVAILABLE:
            return

        if "kuzu_node_health" in self.metrics:
            self.metrics["kuzu_node_health"].labels(node_id=node_id, node_type=node_type).set(
                health_value
            )

        if "kuzu_node_response_time" in self.metrics:
            self.metrics["kuzu_node_response_time"].labels(
                node_id=node_id, node_type=node_type
            ).observe(response_time)

    def record_query(self, node_id: str, query_type: str, status: str, duration: float) -> None:
        """Record query execution metrics."""
        if not PROMETHEUS_AVAILABLE:
            return

        if "kuzu_queries_total" in self.metrics:
            self.metrics["kuzu_queries_total"].labels(
                node_id=node_id, query_type=query_type, status=status
            ).inc()

        if "kuzu_query_duration" in self.metrics:
            self.metrics["kuzu_query_duration"].labels(
                node_id=node_id, query_type=query_type
            ).observe(duration)

    def record_error(self, node_id: str, error_type: str) -> None:
        """Record error occurrence."""
        if not PROMETHEUS_AVAILABLE or "kuzu_errors_total" not in self.metrics:
            return

        self.metrics["kuzu_errors_total"].labels(node_id=node_id, error_type=error_type).inc()

    def record_replica_status(
        self, replica_id: str, master_id: str, is_healthy: bool, lag_seconds: float
    ) -> None:
        """Record replica status and replication lag."""
        if not PROMETHEUS_AVAILABLE:
            return

        if "kuzu_replica_status" in self.metrics:
            self.metrics["kuzu_replica_status"].labels(
                replica_id=replica_id, master_id=master_id
            ).set(1 if is_healthy else 0)

        if "kuzu_replication_lag_seconds" in self.metrics:
            self.metrics["kuzu_replication_lag_seconds"].labels(
                replica_id=replica_id, master_id=master_id
            ).set(lag_seconds)

    def record_wal_streaming(self, replica_id: str, records_count: int) -> None:
        """Record WAL streaming activity."""
        if not PROMETHEUS_AVAILABLE or "kuzu_wal_records_streamed_total" not in self.metrics:
            return

        self.metrics["kuzu_wal_records_streamed_total"].labels(replica_id=replica_id).inc(
            records_count
        )

    def record_wal_file_size(self, node_id: str, size_bytes: int) -> None:
        """Record WAL file size."""
        if not PROMETHEUS_AVAILABLE or "kuzu_wal_file_size_bytes" not in self.metrics:
            return

        self.metrics["kuzu_wal_file_size_bytes"].labels(node_id=node_id).set(size_bytes)

    def record_replica_sync_status(self, replica_id: str, is_in_sync: bool) -> None:
        """Record replica synchronization status."""
        if not PROMETHEUS_AVAILABLE or "kuzu_replica_sync_status" not in self.metrics:
            return

        self.metrics["kuzu_replica_sync_status"].labels(replica_id=replica_id).set(
            1 if is_in_sync else 0
        )

    def record_replication_error(self, replica_id: str, error_type: str) -> None:
        """Record replication error."""
        if not PROMETHEUS_AVAILABLE or "kuzu_replication_errors_total" not in self.metrics:
            return

        self.metrics["kuzu_replication_errors_total"].labels(
            replica_id=replica_id, error_type=error_type
        ).inc()

    def record_resource_usage(self, node_id: str, cpu_percent: float, memory_bytes: int) -> None:
        """Record resource usage metrics."""
        if not PROMETHEUS_AVAILABLE:
            return

        if "kuzu_cpu_usage_percent" in self.metrics:
            self.metrics["kuzu_cpu_usage_percent"].labels(node_id=node_id).set(cpu_percent)

        if "kuzu_memory_usage_bytes" in self.metrics:
            self.metrics["kuzu_memory_usage_bytes"].labels(node_id=node_id).set(memory_bytes)

    def record_disk_usage(self, node_id: str, mount_point: str, usage_bytes: int) -> None:
        """Record disk usage."""
        if not PROMETHEUS_AVAILABLE or "kuzu_disk_usage_bytes" not in self.metrics:
            return

        self.metrics["kuzu_disk_usage_bytes"].labels(node_id=node_id, mount_point=mount_point).set(
            usage_bytes
        )

    def record_connection_pool(
        self, node_id: str, active_connections: int, idle_connections: int
    ) -> None:
        """Record connection pool metrics."""
        if not PROMETHEUS_AVAILABLE:
            return

        if "kuzu_connection_pool_active" in self.metrics:
            self.metrics["kuzu_connection_pool_active"].labels(node_id=node_id).set(
                active_connections
            )

        if "kuzu_connection_pool_idle" in self.metrics:
            self.metrics["kuzu_connection_pool_idle"].labels(node_id=node_id).set(idle_connections)

    def record_disk_io(self, node_id: str, reads: int, writes: int) -> None:
        """Record disk I/O operations."""
        if not PROMETHEUS_AVAILABLE:
            return

        if "kuzu_disk_reads_total" in self.metrics:
            self.metrics["kuzu_disk_reads_total"].labels(node_id=node_id).inc(reads)

        if "kuzu_disk_writes_total" in self.metrics:
            self.metrics["kuzu_disk_writes_total"].labels(node_id=node_id).inc(writes)

    def record_function_shipping(
        self, source_node: str, target_node: str, status: str, duration: float
    ) -> None:
        """Record function shipping metrics."""
        if not PROMETHEUS_AVAILABLE:
            return

        if "kuzu_function_shipping_requests_total" in self.metrics:
            self.metrics["kuzu_function_shipping_requests_total"].labels(
                source_node=source_node, target_node=target_node, status=status
            ).inc()

        if "kuzu_function_shipping_duration" in self.metrics:
            self.metrics["kuzu_function_shipping_duration"].labels(
                source_node=source_node, target_node=target_node
            ).observe(duration)

    def set_build_info(self, version: str, commit: str, build_date: str) -> None:
        """Set build information."""
        if not PROMETHEUS_AVAILABLE or "kuzu_build_info" not in self.metrics:
            return

        self.metrics["kuzu_build_info"].info(
            {"version": version, "commit": commit, "build_date": build_date}
        )

    def get_metrics_text(self) -> str:
        """Get metrics in Prometheus text format."""
        if not PROMETHEUS_AVAILABLE:
            return "# Prometheus client not available\n"

        return generate_latest(self.registry).decode("utf-8")

    def get_metric_names(self) -> List[str]:
        """Get list of all metric names."""
        return list(self.metrics.keys())

    def reset_metrics(self) -> None:
        """Reset all metrics (useful for testing)."""
        if not PROMETHEUS_AVAILABLE:
            return

        for metric in self.metrics.values():
            if hasattr(metric, "clear"):
                metric.clear()


# Global metrics instance
_global_metrics: Optional[PrometheusMetrics] = None


def get_metrics() -> PrometheusMetrics:
    """Get the global metrics instance."""
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = PrometheusMetrics()
    return _global_metrics


def initialize_metrics(registry: Optional[Any] = None) -> PrometheusMetrics:
    """Initialize global metrics instance."""
    global _global_metrics
    _global_metrics = PrometheusMetrics(registry)
    return _global_metrics


# Convenience functions for common metrics
def record_query_metric(node_id: str, query_type: str, status: str, duration: float) -> None:
    """Record query metric using global instance."""
    get_metrics().record_query(node_id, query_type, status, duration)


def record_error_metric(node_id: str, error_type: str) -> None:
    """Record error metric using global instance."""
    get_metrics().record_error(node_id, error_type)


def record_health_metric(
    node_id: str, node_type: str, is_healthy: bool, response_time: float
) -> None:
    """Record health metric using global instance."""
    health_value = 1.0 if is_healthy else 0.0
    get_metrics().record_node_health(node_id, node_type, health_value, response_time)
