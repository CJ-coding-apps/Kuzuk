"""
Kuzuk - Enterprise KuzuDB Scaling Framework
Provides read replica pattern and function shipping for KuzuDB scaling.

This package provides production-ready scaling components for enterprise KuzuDB deployments,
making horizontal scaling available as a standalone library for any KuzuDB application.
"""

__version__ = "0.1.0"
__author__ = "Enhanced RAG Team"
__description__ = (
    "Kuzuk - Enterprise KuzuDB scaling framework with read replicas and function shipping"
)

from .function_shipping.orchestrator import (
    AggregatedResult,
    AnalyticalQuery,
    FunctionShippingOrchestrator,
    QueryExecutionMode,
    QueryResult,
    ResultAggregator,
    create_count_query,
    create_distinct_query,
    create_fastest_first_query,
)
from .monitoring.health_monitor import (
    HealthChecker,
    HealthMetrics,
    HealthMonitor,
    HealthThresholds,
    NodeHealth,
    create_basic_monitor,
    create_enterprise_monitor,
)

# Core components
from .replication.manager import (
    KuzuReplicationManager,
    ReplicaInfo,
    ReplicationStatus,
    WALStreamer,
    create_multi_replica_manager,
    create_single_replica_manager,
)
from .routing.router import (
    ConsistencyLevel,
    LoadBalancer,
    QueryAnalyzer,
    QueryContext,
    QueryRouter,
    QueryType,
    RoutingDecision,
    SessionTracker,
    create_enterprise_router,
    create_simple_router,
)

# Convenience imports for common usage patterns
# Note: KuzuDriver and KuzukDriver are imported lazily to avoid circular imports

__all__ = [
    # Version info
    "__version__",
    "__author__",
    "__description__",
    # Replication components
    "KuzuReplicationManager",
    "ReplicationStatus",
    "ReplicaInfo",
    "WALStreamer",
    "create_single_replica_manager",
    "create_multi_replica_manager",
    # Function shipping components
    "FunctionShippingOrchestrator",
    "AnalyticalQuery",
    "QueryExecutionMode",
    "QueryResult",
    "AggregatedResult",
    "ResultAggregator",
    "create_count_query",
    "create_distinct_query",
    "create_fastest_first_query",
    # Routing components
    "QueryRouter",
    "QueryType",
    "ConsistencyLevel",
    "QueryContext",
    "RoutingDecision",
    "QueryAnalyzer",
    "SessionTracker",
    "LoadBalancer",
    "create_simple_router",
    "create_enterprise_router",
    # Monitoring components
    "HealthMonitor",
    "NodeHealth",
    "HealthMetrics",
    "HealthThresholds",
    "HealthChecker",
    "create_basic_monitor",
    "create_enterprise_monitor",
    # High-level drivers (imported lazily)
    # "KuzuDriver",
    # "KuzukDriver"
]


# Lazy imports to avoid circular dependencies
def __getattr__(name):
    """Lazy import mechanism for high-level drivers."""
    if name == "KuzuDriver":
        from .drivers.kuzu_wrapper import KuzuDriver

        return KuzuDriver
    elif name == "KuzukDriver":
        from .drivers.scalable_driver import KuzukDriver

        return KuzukDriver
    elif name == "create_simple_kuzuk_driver":
        from .drivers.scalable_driver import create_simple_kuzuk_driver

        return create_simple_kuzuk_driver
    elif name == "create_enterprise_kuzuk_driver":
        from .drivers.scalable_driver import create_enterprise_kuzuk_driver

        return create_enterprise_kuzuk_driver
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
