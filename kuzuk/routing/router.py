"""
Query Router for Enhanced RAG 6.2
Routes queries between master and replica nodes based on query type and consistency requirements.
"""

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from ..drivers.kuzu_wrapper import KuzuDriver
from ..function_shipping.orchestrator import AnalyticalQuery, FunctionShippingOrchestrator
from ..replication.manager import KuzuReplicationManager, ReplicaInfo

logger = logging.getLogger(__name__)


class QueryType(Enum):
    """Types of queries for routing decisions."""

    READ = "read"
    WRITE = "write"
    ANALYTICAL = "analytical"
    ADMIN = "admin"


class ConsistencyLevel(Enum):
    """Consistency requirements for queries."""

    STRONG = "strong"  # Must read from master
    EVENTUAL = "eventual"  # Can read from replicas
    SESSION = "session"  # Read-your-writes consistency


@dataclass
class QueryContext:
    """Context information for query routing."""

    user_session_id: Optional[str] = None
    consistency_level: ConsistencyLevel = ConsistencyLevel.EVENTUAL
    max_staleness_seconds: float = 5.0
    prefer_local_replica: bool = False
    analytics_mode: bool = False


@dataclass
class RoutingDecision:
    """Result of query routing decision."""

    target_node: str
    node_type: str  # "master", "replica", "analytical"
    query_type: QueryType
    routing_reason: str
    estimated_latency_ms: float


class QueryAnalyzer:
    """Analyzes queries to determine their type and characteristics."""

    # Query type patterns
    READ_PATTERNS = [
        r"^\s*MATCH\s+",
        r"^\s*CALL\s+.*\s+YIELD\s+",
        r"^\s*SHOW\s+",
        r"^\s*RETURN\s+",
    ]

    WRITE_PATTERNS = [
        r"^\s*CREATE\s+",
        r"^\s*MERGE\s+",
        r"^\s*DELETE\s+",
        r"^\s*SET\s+",
        r"^\s*REMOVE\s+",
        r"^\s*COPY\s+",
        r"^\s*DROP\s+",
        r"^\s*ALTER\s+",
    ]

    ANALYTICAL_PATTERNS = [
        r".*COUNT\s*\(",
        r".*SUM\s*\(",
        r".*AVG\s*\(",
        r".*MAX\s*\(",
        r".*MIN\s*\(",
        r".*COLLECT\s*\(",
        r".*GROUP\s+BY\s+",
        r".*ORDER\s+BY\s+",
        r".*\*\s+SHORTEST\s+",
        r".*\*\d+\.\.\d+",  # Variable length paths
    ]

    ADMIN_PATTERNS = [
        r"^\s*CALL\s+dbms\.",
        r"^\s*CALL\s+db\.",
        r"^\s*EXPLAIN\s+",
        r"^\s*PROFILE\s+",
    ]

    def __init__(self):
        """Initialize query analyzer."""
        self.read_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.READ_PATTERNS]
        self.write_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.WRITE_PATTERNS]
        self.analytical_regex = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.ANALYTICAL_PATTERNS
        ]
        self.admin_regex = [re.compile(pattern, re.IGNORECASE) for pattern in self.ADMIN_PATTERNS]

    def analyze_query(self, query: str) -> Tuple[QueryType, Dict[str, Any]]:
        """
        Analyze query to determine type and characteristics.

        Args:
            query: Cypher query string

        Returns:
            Tuple of (QueryType, analysis metadata)
        """
        query = query.strip()
        analysis = {
            "is_analytical": False,
            "estimated_complexity": "low",
            "requires_consistency": False,
            "involves_writes": False,
        }

        # Check for administrative queries first
        if any(regex.match(query) for regex in self.admin_regex):
            analysis["requires_consistency"] = True
            return QueryType.ADMIN, analysis

        # Check for write operations
        if any(regex.match(query) for regex in self.write_regex):
            analysis["involves_writes"] = True
            analysis["requires_consistency"] = True
            return QueryType.WRITE, analysis

        # Check for analytical patterns
        if any(regex.search(query) for regex in self.analytical_regex):
            analysis["is_analytical"] = True
            analysis["estimated_complexity"] = self._estimate_complexity(query)
            return QueryType.ANALYTICAL, analysis

        # Default to read operation
        if any(regex.match(query) for regex in self.read_regex) or True:
            return QueryType.READ, analysis

        # Fallback to read with strong consistency for safety
        analysis["requires_consistency"] = True
        return QueryType.READ, analysis

    def _estimate_complexity(self, query: str) -> str:
        """Estimate query complexity based on patterns."""
        complexity_indicators = [
            ("high", [r"\*\d+\.\.\d+", r"SHORTEST\s+", r"ALL\s+SHORTEST"]),
            ("medium", [r"GROUP\s+BY", r"ORDER\s+BY", r"COUNT\s*\(", r"SUM\s*\("]),
            ("low", [r"MATCH", r"RETURN"]),
        ]

        for complexity, patterns in complexity_indicators:
            if any(re.search(pattern, query, re.IGNORECASE) for pattern in patterns):
                return complexity

        return "low"


class SessionTracker:
    """Tracks user sessions for read-your-writes consistency."""

    def __init__(self, session_timeout: float = 300.0):
        """Initialize session tracker."""
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.session_timeout = session_timeout

    def record_write(self, session_id: str) -> None:
        """Record a write operation for a session."""
        if session_id:
            self.sessions[session_id] = {
                "last_write": datetime.now(),
                "write_count": self.sessions.get(session_id, {}).get("write_count", 0) + 1,
            }

    def has_recent_writes(self, session_id: str, within_seconds: float = 5.0) -> bool:
        """Check if session has recent writes that might not be replicated."""
        if not session_id or session_id not in self.sessions:
            return False

        session = self.sessions[session_id]
        time_since_write = (datetime.now() - session["last_write"]).total_seconds()
        return time_since_write <= within_seconds

    def cleanup_expired_sessions(self) -> None:
        """Remove expired sessions."""
        now = datetime.now()
        expired_sessions = [
            session_id
            for session_id, session_data in self.sessions.items()
            if (now - session_data["last_write"]).total_seconds() > self.session_timeout
        ]

        for session_id in expired_sessions:
            del self.sessions[session_id]


class LoadBalancer:
    """Load balances queries across healthy replicas."""

    def __init__(self):
        """Initialize load balancer."""
        self.replica_stats: Dict[str, Dict[str, Any]] = {}
        self.round_robin_index = 0

    def select_replica(
        self, replicas: List[ReplicaInfo], strategy: str = "round_robin"
    ) -> Optional[ReplicaInfo]:
        """
        Select the best replica for a query.

        Args:
            replicas: List of healthy replicas
            strategy: Selection strategy ("round_robin", "least_lag", "least_load")

        Returns:
            Selected replica or None if no healthy replicas
        """
        if not replicas:
            return None

        if strategy == "round_robin":
            replica = replicas[self.round_robin_index % len(replicas)]
            self.round_robin_index += 1
            return replica

        elif strategy == "least_lag":
            return min(replicas, key=lambda r: r.lag_ms)

        elif strategy == "least_load":
            # For now, use round robin as proxy for load balancing
            return self.select_replica(replicas, "round_robin")

        else:
            return replicas[0]

    def update_replica_stats(self, replica_id: str, execution_time_ms: float) -> None:
        """Update performance statistics for a replica."""
        if replica_id not in self.replica_stats:
            self.replica_stats[replica_id] = {"query_count": 0, "total_time": 0.0, "avg_time": 0.0}

        stats = self.replica_stats[replica_id]
        stats["query_count"] += 1
        stats["total_time"] += execution_time_ms
        stats["avg_time"] = stats["total_time"] / stats["query_count"]


class QueryRouter:
    """Routes queries to appropriate nodes based on type and consistency requirements."""

    def __init__(
        self,
        replication_manager: KuzuReplicationManager,
        function_shipping: Optional[FunctionShippingOrchestrator] = None,
        default_consistency: ConsistencyLevel = ConsistencyLevel.EVENTUAL,
    ):
        """
        Initialize query router.

        Args:
            replication_manager: KuzuDB replication manager
            function_shipping: Optional function shipping orchestrator
            default_consistency: Default consistency level
        """
        self.replication_manager = replication_manager
        self.function_shipping = function_shipping
        self.default_consistency = default_consistency

        # Components
        self.query_analyzer = QueryAnalyzer()
        self.session_tracker = SessionTracker()
        self.load_balancer = LoadBalancer()

        # Configuration
        self.analytical_threshold_ms = 1000  # Queries expected to take >1s
        self.max_replica_lag_ms = 5000  # Max acceptable replica lag

        # Statistics
        self.routing_stats = {
            "queries_routed": 0,
            "master_queries": 0,
            "replica_queries": 0,
            "analytical_queries": 0,
            "routing_errors": 0,
        }

        logger.info("Query router initialized")

    async def route_query(
        self, query: str, context: Optional[QueryContext] = None
    ) -> RoutingDecision:
        """
        Route a query to the appropriate node.

        Args:
            query: Cypher query to route
            context: Query context and preferences

        Returns:
            Routing decision with target node and metadata
        """
        start_time = time.time()
        context = context or QueryContext()

        try:
            # Analyze query
            query_type, analysis = self.query_analyzer.analyze_query(query)

            # Make routing decision
            decision = await self._make_routing_decision(query, query_type, analysis, context)

            # Update statistics
            self._update_routing_stats(decision)

            logger.debug(f"Query routed to {decision.target_node} ({decision.routing_reason})")
            return decision

        except Exception as e:
            self.routing_stats["routing_errors"] += 1
            logger.error(f"Query routing failed: {e}")

            # Fallback to master
            return RoutingDecision(
                target_node="master",
                node_type="master",
                query_type=QueryType.READ,
                routing_reason=f"routing_error: {str(e)}",
                estimated_latency_ms=0,
            )

    async def _make_routing_decision(
        self, query: str, query_type: QueryType, analysis: Dict[str, Any], context: QueryContext
    ) -> RoutingDecision:
        """Make the actual routing decision based on query analysis."""

        # Administrative and write queries always go to master
        if query_type in [QueryType.ADMIN, QueryType.WRITE]:
            if context.user_session_id and query_type == QueryType.WRITE:
                self.session_tracker.record_write(context.user_session_id)

            return RoutingDecision(
                target_node="master",
                node_type="master",
                query_type=query_type,
                routing_reason=f"{query_type.value}_requires_master",
                estimated_latency_ms=10,
            )

        # Check for analytical queries that could benefit from function shipping
        if query_type == QueryType.ANALYTICAL and self.function_shipping and context.analytics_mode:

            return RoutingDecision(
                target_node="analytical_cluster",
                node_type="analytical",
                query_type=query_type,
                routing_reason="analytical_function_shipping",
                estimated_latency_ms=self.analytical_threshold_ms / 2,
            )

        # Check consistency requirements
        if self._requires_strong_consistency(context, analysis):
            return RoutingDecision(
                target_node="master",
                node_type="master",
                query_type=query_type,
                routing_reason="strong_consistency_required",
                estimated_latency_ms=10,
            )

        # Route to replica if available and healthy
        healthy_replicas = self.replication_manager.get_healthy_replicas()

        if healthy_replicas:
            # Filter replicas by staleness requirement
            fresh_replicas = [
                replica
                for replica in healthy_replicas
                if replica.lag_ms <= context.max_staleness_seconds * 1000
            ]

            if fresh_replicas:
                selected_replica = self.load_balancer.select_replica(fresh_replicas)
                if selected_replica:
                    return RoutingDecision(
                        target_node=selected_replica.id,
                        node_type="replica",
                        query_type=query_type,
                        routing_reason="replica_load_balanced",
                        estimated_latency_ms=selected_replica.lag_ms + 10,
                    )

        # Fallback to master
        return RoutingDecision(
            target_node="master",
            node_type="master",
            query_type=query_type,
            routing_reason="no_healthy_replicas",
            estimated_latency_ms=10,
        )

    def _requires_strong_consistency(self, context: QueryContext, analysis: Dict[str, Any]) -> bool:
        """Determine if query requires strong consistency."""

        # Explicit strong consistency requirement
        if context.consistency_level == ConsistencyLevel.STRONG:
            return True

        # Query analysis indicates consistency needed
        if analysis.get("requires_consistency", False):
            return True

        # Session consistency: recent writes in same session
        if (
            context.consistency_level == ConsistencyLevel.SESSION
            and context.user_session_id
            and self.session_tracker.has_recent_writes(context.user_session_id)
        ):
            return True

        return False

    async def execute_query(self, query: str, context: Optional[QueryContext] = None) -> Any:
        """
        Route and execute a query.

        Args:
            query: Cypher query to execute
            context: Query context

        Returns:
            Query result
        """
        decision = await self.route_query(query, context)
        execution_start = time.time()

        try:
            if decision.node_type == "master":
                result = await self._execute_on_master(query)
            elif decision.node_type == "replica":
                result = await self._execute_on_replica(decision.target_node, query)
            elif decision.node_type == "analytical":
                result = await self._execute_analytical(query, context)
            else:
                raise ValueError(f"Unknown node type: {decision.node_type}")

            # Update load balancer stats
            execution_time = (time.time() - execution_start) * 1000
            if decision.node_type == "replica":
                self.load_balancer.update_replica_stats(decision.target_node, execution_time)

            return result

        except Exception as e:
            logger.error(f"Query execution failed on {decision.target_node}: {e}")
            raise

    async def _execute_on_master(self, query: str) -> Any:
        """Execute query on master node."""
        try:
            master_driver = self.replication_manager.master_driver
            if not master_driver:
                raise RuntimeError("Master driver not available")

            result = await master_driver.execute_query(query)
            return result

        except Exception as e:
            logger.error(f"Master query execution failed: {e}")
            raise

    async def _execute_on_replica(self, replica_id: str, query: str) -> Any:
        """Execute query on replica node."""
        try:
            replica = self.replication_manager.replicas.get(replica_id)
            if not replica or not replica.driver:
                raise RuntimeError(f"Replica {replica_id} driver not available")

            result = await replica.driver.execute_query(query)
            return result

        except Exception as e:
            logger.error(f"Replica {replica_id} query execution failed: {e}")
            raise

    async def _execute_analytical(self, query: str, context: QueryContext) -> Any:
        """Execute analytical query using function shipping."""
        if not self.function_shipping:
            # Fallback to master
            return await self._execute_on_master(query)

        # Create analytical query
        analytical_query = AnalyticalQuery(
            query_id=self._generate_query_id(query),
            cypher_query=query,
            parameters={},
            execution_mode="parallel_all",
            timeout_seconds=60.0,
        )

        # Execute with function shipping
        result = await self.function_shipping.execute_parallel(analytical_query)
        return result.data

    def _generate_query_id(self, query: str) -> str:
        """Generate unique query ID."""
        query_hash = hashlib.md5(query.encode()).hexdigest()[:8]
        timestamp = int(time.time() * 1000)
        return f"query_{timestamp}_{query_hash}"

    def _update_routing_stats(self, decision: RoutingDecision) -> None:
        """Update routing statistics."""
        self.routing_stats["queries_routed"] += 1

        if decision.node_type == "master":
            self.routing_stats["master_queries"] += 1
        elif decision.node_type == "replica":
            self.routing_stats["replica_queries"] += 1
        elif decision.node_type == "analytical":
            self.routing_stats["analytical_queries"] += 1

    def get_routing_stats(self) -> Dict[str, Any]:
        """Get routing statistics."""
        total_queries = max(self.routing_stats["queries_routed"], 1)

        return {
            **self.routing_stats,
            "master_percentage": (self.routing_stats["master_queries"] / total_queries) * 100,
            "replica_percentage": (self.routing_stats["replica_queries"] / total_queries) * 100,
            "analytical_percentage": (self.routing_stats["analytical_queries"] / total_queries)
            * 100,
            "healthy_replicas": len(self.replication_manager.get_healthy_replicas()),
            "total_replicas": len(self.replication_manager.replicas),
        }

    async def cleanup(self) -> None:
        """Perform cleanup operations."""
        self.session_tracker.cleanup_expired_sessions()
        logger.info("Query router cleanup complete")


# Factory functions
def create_simple_router(replication_manager: KuzuReplicationManager) -> QueryRouter:
    """Create a simple router without function shipping."""
    return QueryRouter(
        replication_manager=replication_manager,
        function_shipping=None,
        default_consistency=ConsistencyLevel.EVENTUAL,
    )


def create_enterprise_router(
    replication_manager: KuzuReplicationManager, function_shipping: FunctionShippingOrchestrator
) -> QueryRouter:
    """Create an enterprise router with full capabilities."""
    return QueryRouter(
        replication_manager=replication_manager,
        function_shipping=function_shipping,
        default_consistency=ConsistencyLevel.SESSION,
    )
