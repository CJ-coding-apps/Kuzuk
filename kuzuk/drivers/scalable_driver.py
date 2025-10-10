"""
Kuzuk Driver - High-level interface integrating all scaling components.
Provides a drop-in replacement for KuzuDriver with built-in scaling capabilities.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

# Import only what we need at runtime, using dependency injection pattern

logger = logging.getLogger(__name__)


class KuzukDriver:
    """
    High-level Kuzuk driver that integrates replication, function shipping,
    routing, and health monitoring capabilities.

    Provides a drop-in replacement for KuzuDriver with horizontal scaling features.
    """

    def __init__(
        self,
        master_db_path: str,
        replica_count: int = 2,
        enable_function_shipping: bool = True,
        enable_health_monitoring: bool = True,
        default_consistency: str = "eventual",
        replication_interval: float = 1.0,
        health_check_interval: float = 30.0,
    ):
        """
        Initialize Kuzuk driver.

        Args:
            master_db_path: Path to master KuzuDB database
            replica_count: Number of read replicas to create
            enable_function_shipping: Enable parallel query execution
            enable_health_monitoring: Enable health monitoring
            default_consistency: Default consistency level for queries
            replication_interval: Seconds between replication checks
            health_check_interval: Seconds between health checks
        """
        self.master_db_path = Path(master_db_path)
        self.replica_count = replica_count
        self.enable_function_shipping = enable_function_shipping
        self.enable_health_monitoring = enable_health_monitoring
        self.default_consistency = default_consistency

        # Core components (initialized in setup)
        self.replication_manager: Optional[Any] = None
        self.function_shipping: Optional[Any] = None
        self.query_router: Optional[Any] = None
        self.health_monitor: Optional[Any] = None

        # State
        self.initialized = False

        logger.info(
            f"Scalable KuzuDB driver created: {master_db_path} with {replica_count} replicas"
        )

    async def initialize(self) -> None:
        """Initialize all scaling components."""
        if self.initialized:
            logger.warning("Driver already initialized")
            return

        try:
            logger.info("Initializing scalable KuzuDB driver...")

            # 1. Setup replication manager
            await self._setup_replication()

            # 2. Setup function shipping (if enabled)
            if self.enable_function_shipping:
                await self._setup_function_shipping()

            # 3. Setup query router
            await self._setup_query_router()

            # 4. Setup health monitoring (if enabled)
            if self.enable_health_monitoring:
                await self._setup_health_monitoring()

            # 5. Start background services
            await self._start_services()

            self.initialized = True
            logger.info("Scalable KuzuDB driver initialization complete")

        except Exception as e:
            logger.error(f"Failed to initialize scalable driver: {e}")
            await self.close()
            raise

    async def _setup_replication(self) -> None:
        """Setup replication manager with replicas."""
        # Dynamic import to avoid circular dependency
        from ..replication.manager import create_multi_replica_manager

        # Create replication manager with multiple replicas
        self.replication_manager = create_multi_replica_manager(
            master_path=str(self.master_db_path),
            replica_count=self.replica_count,
            base_replica_dir=str(self.master_db_path.parent / "replicas"),
        )

        # Initialize replication
        await self.replication_manager.initialize()
        logger.info(f"Replication manager initialized with {self.replica_count} replicas")

    async def _setup_function_shipping(self) -> None:
        """Setup function shipping orchestrator."""
        if not self.replication_manager:
            raise RuntimeError("Replication manager must be initialized first")

        # Create node mapping for function shipping
        # Create real KuzuDriver instances for function shipping
        kuzu_nodes = {}

        # Add master node
        kuzu_nodes["master"] = self.replication_manager.master_driver

        # Add replica nodes
        for replica in self.replication_manager.replicas.values():
            kuzu_nodes[replica.id] = replica.driver

        # Dynamic import to avoid circular dependency
        from ..function_shipping.orchestrator import FunctionShippingOrchestrator

        self.function_shipping = FunctionShippingOrchestrator(kuzu_nodes)
        logger.info("Function shipping orchestrator initialized")

    async def _setup_query_router(self) -> None:
        """Setup intelligent query router."""
        if not self.replication_manager:
            raise RuntimeError("Replication manager must be initialized first")

        # Dynamic import to avoid circular dependency
        from ..routing.router import create_enterprise_router

        self.query_router = create_enterprise_router(
            replication_manager=self.replication_manager, function_shipping=self.function_shipping
        )
        logger.info("Query router initialized")

    async def _setup_health_monitoring(self) -> None:
        """Setup health monitoring for all nodes."""
        if not self.replication_manager:
            raise RuntimeError("Replication manager must be initialized first")

        # Dynamic import to avoid circular dependency
        from ..monitoring.health_monitor import create_enterprise_monitor

        self.health_monitor = create_enterprise_monitor(
            check_interval=30.0, alert_callback=self._health_alert_callback
        )

        # Add master node to monitoring
        self.health_monitor.add_node(
            node_id="master", driver=self.replication_manager.master_driver, node_type="master"
        )

        # Add replica nodes to monitoring
        for replica in self.replication_manager.replicas.values():
            self.health_monitor.add_node(
                node_id=replica.id, driver=replica.driver, node_type="replica", replica_info=replica
            )

        logger.info("Health monitoring initialized")

    async def _start_services(self) -> None:
        """Start background services."""
        # Start replication
        if self.replication_manager:
            await self.replication_manager.start_replication()

        # Start health monitoring
        if self.health_monitor:
            await self.health_monitor.start_monitoring()

        logger.info("Background services started")

    def _health_alert_callback(self, health_metrics) -> None:
        """Handle health alerts."""
        logger.warning(
            f"Health alert: {health_metrics.node_id} is {health_metrics.health_status.value}"
        )
        # TODO: Implement alerting logic (notifications, failover, etc.)

    async def execute_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Execute a query with intelligent routing and scaling.

        Args:
            query: Cypher query to execute
            parameters: Query parameters
            context: Query context for routing decisions

        Returns:
            Query result
        """
        if not self.initialized:
            raise RuntimeError("Driver not initialized. Call initialize() first.")

        if not self.query_router:
            raise RuntimeError("Query router not available")

        # Use provided context or create default
        if context is None:
            # Dynamic import for QueryContext
            from ..routing.router import ConsistencyLevel, QueryContext

            context = QueryContext(consistency_level=ConsistencyLevel(self.default_consistency))

        # Route and execute query
        result = await self.query_router.execute_query(query, context)
        return result

    async def execute_analytical_query(
        self,
        query: str,
        execution_mode: str = "parallel_all",
        timeout_seconds: float = 60.0,
        aggregation_function: Optional[str] = None,
    ) -> Any:
        """
        Execute an analytical query with function shipping.

        Args:
            query: Analytical Cypher query
            execution_mode: How to execute across nodes
            timeout_seconds: Query timeout
            aggregation_function: How to aggregate results

        Returns:
            Aggregated query result
        """
        if not self.initialized:
            raise RuntimeError("Driver not initialized. Call initialize() first.")

        if not self.function_shipping:
            # Fallback to regular execution
            return await self.execute_query(query)

        # Create analytical query
        # Dynamic import for AnalyticalQuery
        from ..function_shipping.orchestrator import AnalyticalQuery

        analytical_query = AnalyticalQuery(
            query_id=f"analytical_{hash(query)}",
            cypher_query=query,
            parameters={},
            execution_mode=execution_mode,
            timeout_seconds=timeout_seconds,
            aggregation_function=aggregation_function,
        )

        # Execute with function shipping
        result = await self.function_shipping.execute_parallel(analytical_query)
        return result.data

    def get_cluster_status(self) -> Dict[str, Any]:
        """Get comprehensive cluster status."""
        status = {
            "initialized": self.initialized,
            "master_path": str(self.master_db_path),
            "replica_count": self.replica_count,
        }

        if self.replication_manager:
            status["replication"] = self.replication_manager.get_replication_status()

        if self.query_router:
            status["routing"] = self.query_router.get_routing_stats()

        if self.function_shipping:
            status["function_shipping"] = self.function_shipping.get_performance_stats()

        if self.health_monitor:
            status["health"] = self.health_monitor.get_health_summary()

        return status

    def get_healthy_replicas(self) -> List[str]:
        """Get list of healthy replica IDs."""
        if not self.replication_manager:
            return []

        healthy_replicas = self.replication_manager.get_healthy_replicas()
        return [replica.id for replica in healthy_replicas]

    def is_cluster_healthy(self) -> bool:
        """Check if the cluster is healthy overall."""
        if not self.initialized:
            return False

        if self.health_monitor:
            health_summary = self.health_monitor.get_health_summary()
            return health_summary.get("health_percentage", 0) >= 50  # At least 50% healthy

        # Fallback: check if we have healthy replicas
        return len(self.get_healthy_replicas()) > 0

    async def close(self) -> None:
        """Clean up all resources."""
        logger.info("Closing scalable KuzuDB driver...")

        # Stop health monitoring
        if self.health_monitor:
            await self.health_monitor.close()

        # Stop replication
        if self.replication_manager:
            await self.replication_manager.close()

        # Close function shipping
        if self.function_shipping:
            await self.function_shipping.close()

        # Close query router
        if self.query_router:
            await self.query_router.cleanup()

        self.initialized = False
        logger.info("Kuzuk driver closed")


# Convenience factory functions
def create_simple_kuzuk_driver(master_db_path: str, replica_count: int = 2) -> KuzukDriver:
    """Create a simple Kuzuk driver with basic features."""
    return KuzukDriver(
        master_db_path=master_db_path,
        replica_count=replica_count,
        enable_function_shipping=False,
        enable_health_monitoring=True,
        default_consistency="eventual",
    )


def create_enterprise_kuzuk_driver(master_db_path: str, replica_count: int = 3) -> KuzukDriver:
    """Create an enterprise Kuzuk driver with all features enabled."""
    return KuzukDriver(
        master_db_path=master_db_path,
        replica_count=replica_count,
        enable_function_shipping=True,
        enable_health_monitoring=True,
        default_consistency="session",
        replication_interval=0.5,  # More frequent replication
        health_check_interval=10.0,  # More frequent health checks
    )
