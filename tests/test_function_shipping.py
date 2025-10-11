"""
Unit tests for Function Shipping components.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kuzuk.function_shipping.orchestrator import (
    AggregatedResult,
    AnalyticalQuery,
    FunctionShippingOrchestrator,
    QueryExecutionMode,
    QueryResult,
    QuerySerializer,
    ResultAggregator,
    create_count_query,
    create_distinct_query,
    create_fastest_first_query,
)
from kuzuk.function_shipping.transport import (
    NetworkTransportManager,
    NodeEndpoint,
    TransportProtocol,
    create_http_endpoint,
    create_tcp_endpoint,
)


class TestAnalyticalQuery:
    """Test AnalyticalQuery data class."""

    @pytest.mark.unit
    @pytest.mark.unit
    def test_query_creation(self):
        """Test query creation and serialization."""
        query = AnalyticalQuery(
            query_id="test_query",
            cypher_query="MATCH (n) RETURN count(n)",
            parameters={"limit": 100},
            execution_mode=QueryExecutionMode.PARALLEL_ALL,
            timeout_seconds=30.0,
            aggregation_function="count",
        )

        assert query.query_id == "test_query"
        assert query.cypher_query == "MATCH (n) RETURN count(n)"
        assert query.parameters == {"limit": 100}
        assert query.execution_mode == QueryExecutionMode.PARALLEL_ALL
        assert query.timeout_seconds == 30.0
        assert query.aggregation_function == "count"

    @pytest.mark.unit
    def test_query_serialization(self):
        """Test query to_dict and from_dict."""
        query = AnalyticalQuery(
            query_id="test",
            cypher_query="RETURN 1",
            parameters={},
            execution_mode=QueryExecutionMode.FASTEST_FIRST,
            timeout_seconds=10.0,
        )

        data = query.to_dict()
        reconstructed = AnalyticalQuery.from_dict(data)

        assert reconstructed.query_id == query.query_id
        assert reconstructed.cypher_query == query.cypher_query
        assert reconstructed.execution_mode == query.execution_mode
        assert reconstructed.timeout_seconds == query.timeout_seconds


class TestQueryResult:
    """Test QueryResult data class."""

    @pytest.mark.unit
    def test_result_creation(self):
        """Test query result creation."""
        result = QueryResult(
            node_id="node_1",
            query_id="test_query",
            success=True,
            data={"count": 100},
            execution_time_ms=150.5,
            metadata={"node_type": "replica"},
        )

        assert result.node_id == "node_1"
        assert result.query_id == "test_query"
        assert result.success is True
        assert result.data == {"count": 100}
        assert result.execution_time_ms == 150.5
        assert result.metadata == {"node_type": "replica"}


class TestResultAggregator:
    """Test result aggregation functionality."""

    @pytest.fixture
    def sample_count_results(self):
        """Create sample count results."""
        return [
            QueryResult("node_1", "count_query", True, 50, 100),
            QueryResult("node_2", "count_query", True, 75, 120),
            QueryResult("node_3", "count_query", True, 25, 90),
        ]

    @pytest.fixture
    def sample_distinct_results(self):
        """Create sample distinct results."""
        return [
            QueryResult(
                "node_1", "distinct_query", True, [{"name": "Alice"}, {"name": "Bob"}], 100
            ),
            QueryResult(
                "node_2", "distinct_query", True, [{"name": "Bob"}, {"name": "Carol"}], 120
            ),
            QueryResult(
                "node_3", "distinct_query", True, [{"name": "Alice"}, {"name": "Dave"}], 90
            ),
        ]

    @pytest.mark.unit
    def test_aggregate_count_results(self, sample_count_results):
        """Test count result aggregation."""
        aggregated = ResultAggregator.aggregate_count_results(sample_count_results)

        assert aggregated.success is True
        assert aggregated.data == 150  # 50 + 75 + 25
        assert aggregated.aggregation_method == "sum_count"
        assert aggregated.nodes_used == 3
        assert aggregated.total_execution_time_ms == 120  # max(100, 120, 90)

    @pytest.mark.unit
    def test_aggregate_distinct_results(self, sample_distinct_results):
        """Test distinct result aggregation."""
        aggregated = ResultAggregator.aggregate_distinct_results(sample_distinct_results)

        assert aggregated.success is True
        assert len(aggregated.data) == 4  # Alice, Bob, Carol, Dave
        assert aggregated.aggregation_method == "distinct_union"
        assert aggregated.nodes_used == 3

    @pytest.mark.unit
    def test_aggregate_first_result(self, sample_count_results):
        """Test first result aggregation."""
        aggregated = ResultAggregator.aggregate_first_result(sample_count_results)

        assert aggregated.success is True
        assert aggregated.data == 25  # From node_3 (fastest)
        assert aggregated.aggregation_method == "first_result"
        assert aggregated.nodes_used == 1
        assert aggregated.total_execution_time_ms == 90


class TestQuerySerializer:
    """Test query serialization."""

    @pytest.mark.unit
    def test_serialize_deserialize_query(self):
        """Test query serialization and deserialization."""
        query = AnalyticalQuery(
            query_id="test",
            cypher_query="MATCH (n) RETURN count(n)",
            parameters={"limit": 100},
            execution_mode=QueryExecutionMode.PARALLEL_ALL,
            timeout_seconds=30.0,
        )

        # Serialize
        serialized = QuerySerializer.serialize_query(query)
        assert isinstance(serialized, str)

        # Deserialize
        deserialized = QuerySerializer.deserialize_query(serialized)
        assert deserialized.query_id == query.query_id
        assert deserialized.cypher_query == query.cypher_query
        assert deserialized.execution_mode == query.execution_mode


class TestFunctionShippingOrchestrator:
    """Test function shipping orchestrator."""

    @pytest.fixture
    def mock_nodes(self):
        """Create mock KuzuDB nodes."""
        nodes = {}
        for i in range(3):
            node_id = f"node_{i+1}"
            mock_driver = AsyncMock()
            mock_driver.execute_query.return_value = {
                "success": True,
                "rows": [{"count": 50 + i * 10}],
            }
            nodes[node_id] = mock_driver
        return nodes

    @pytest.fixture
    def orchestrator(self, mock_nodes):
        """Create orchestrator with mock nodes."""
        return FunctionShippingOrchestrator(mock_nodes)

    @pytest.mark.unit
    def test_orchestrator_initialization(self, mock_nodes):
        """Test orchestrator initialization."""
        orchestrator = FunctionShippingOrchestrator(mock_nodes)

        assert len(orchestrator.nodes) == 3
        assert orchestrator.stats["queries_executed"] == 0

    @pytest.mark.asyncio
    async def test_execute_parallel_all_nodes(self, orchestrator):
        """Test parallel execution on all nodes."""
        query = create_count_query("test_count", "MATCH (n) RETURN count(n)")

        result = await orchestrator.execute_parallel(query)

        assert result.success is True
        assert result.data == 180  # 50 + 60 + 70
        assert result.aggregation_method == "sum_count"
        assert result.nodes_used == 3

    @pytest.mark.asyncio
    async def test_execute_parallel_subset(self, orchestrator):
        """Test parallel execution on subset of nodes."""
        query = AnalyticalQuery(
            query_id="test_subset",
            cypher_query="MATCH (n) RETURN count(n)",
            parameters={},
            execution_mode=QueryExecutionMode.PARALLEL_SUBSET,
            timeout_seconds=30.0,
            aggregation_function="count",
        )

        result = await orchestrator.execute_parallel(query)

        assert result.success is True
        assert result.nodes_used <= 3  # Should use subset

    @pytest.mark.asyncio
    async def test_execute_fastest_first(self, orchestrator):
        """Test fastest-first execution mode."""
        query = create_fastest_first_query("test_fastest", "RETURN 1")

        result = await orchestrator.execute_parallel(query)

        assert result.success is True
        assert result.nodes_used == 1
        assert result.aggregation_method == "first_result"

    @pytest.mark.unit
    def test_get_performance_stats(self, orchestrator):
        """Test performance statistics."""
        stats = orchestrator.get_performance_stats()

        assert "queries_executed" in stats
        assert "avg_execution_time" in stats
        assert "parallel_queries" in stats
        assert "available_nodes" in stats
        assert stats["available_nodes"] == 3


class TestNetworkTransport:
    """Test network transport functionality."""

    @pytest.mark.unit
    def test_node_endpoint_creation(self):
        """Test node endpoint creation."""
        endpoint = create_http_endpoint("node_1", "localhost", 8080)

        assert endpoint.node_id == "node_1"
        assert endpoint.protocol == TransportProtocol.HTTP
        assert endpoint.host == "localhost"
        assert endpoint.port == 8080
        assert endpoint.get_url() == "http://localhost:8080/query"

    @pytest.mark.unit
    def test_tcp_endpoint_creation(self):
        """Test TCP endpoint creation."""
        endpoint = create_tcp_endpoint("node_1", "localhost", 9090)

        assert endpoint.protocol == TransportProtocol.TCP
        assert endpoint.get_url() == "localhost:9090"

    @pytest.mark.unit
    def test_transport_manager_initialization(self):
        """Test transport manager initialization."""
        manager = NetworkTransportManager()

        assert len(manager.endpoints) == 0
        assert manager.stats["requests_sent"] == 0

    @pytest.mark.unit
    def test_register_endpoint(self):
        """Test endpoint registration."""
        manager = NetworkTransportManager()
        endpoint = create_http_endpoint("node_1", "localhost", 8080)

        manager.register_endpoint(endpoint)

        assert "node_1" in manager.endpoints
        assert manager.endpoints["node_1"] == endpoint

    @pytest.mark.unit
    def test_unregister_endpoint(self):
        """Test endpoint unregistration."""
        manager = NetworkTransportManager()
        endpoint = create_http_endpoint("node_1", "localhost", 8080)

        manager.register_endpoint(endpoint)
        manager.unregister_endpoint("node_1")

        assert "node_1" not in manager.endpoints


class TestFactoryFunctions:
    """Test factory functions."""

    @pytest.mark.unit
    def test_create_count_query(self):
        """Test count query factory."""
        query = create_count_query("count_test", "MATCH (n) RETURN count(n)")

        assert query.query_id == "count_test"
        assert query.execution_mode == QueryExecutionMode.PARALLEL_ALL
        assert query.aggregation_function == "count"
        assert query.timeout_seconds == 30.0

    @pytest.mark.unit
    def test_create_distinct_query(self):
        """Test distinct query factory."""
        query = create_distinct_query("distinct_test", "MATCH (n) RETURN DISTINCT n.name")

        assert query.query_id == "distinct_test"
        assert query.execution_mode == QueryExecutionMode.PARALLEL_ALL
        assert query.aggregation_function == "distinct"
        assert query.timeout_seconds == 60.0

    @pytest.mark.unit
    def test_create_fastest_first_query(self):
        """Test fastest-first query factory."""
        query = create_fastest_first_query("fast_test", "RETURN 1")

        assert query.query_id == "fast_test"
        assert query.execution_mode == QueryExecutionMode.FASTEST_FIRST
        assert query.aggregation_function == "first"
        assert query.timeout_seconds == 10.0


if __name__ == "__main__":
    pytest.main([__file__])
