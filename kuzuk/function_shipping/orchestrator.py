"""
Function Shipping Orchestrator for Enhanced RAG 6.2
Enables parallel execution of analytical queries across KuzuDB replicas.
"""

import asyncio
import json
import logging
import time
from typing import List, Dict, Any, Optional, Union, Callable
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

from ..drivers.kuzu_wrapper import KuzuDriver

logger = logging.getLogger(__name__)


class QueryExecutionMode(Enum):
    """Query execution modes for function shipping."""
    PARALLEL_ALL = "parallel_all"          # Execute on all nodes
    PARALLEL_SUBSET = "parallel_subset"    # Execute on subset of nodes
    FASTEST_FIRST = "fastest_first"        # Execute on fastest responding node
    ROUND_ROBIN = "round_robin"           # Distribute across nodes


@dataclass
class AnalyticalQuery:
    """Represents an analytical query for function shipping."""
    query_id: str
    cypher_query: str
    parameters: Dict[str, Any]
    execution_mode: QueryExecutionMode
    timeout_seconds: float
    aggregation_function: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "query_id": self.query_id,
            "cypher_query": self.cypher_query,
            "parameters": self.parameters,
            "execution_mode": self.execution_mode.value,
            "timeout_seconds": self.timeout_seconds,
            "aggregation_function": self.aggregation_function
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AnalyticalQuery":
        """Create from dictionary."""
        return cls(
            query_id=data["query_id"],
            cypher_query=data["cypher_query"],
            parameters=data["parameters"],
            execution_mode=QueryExecutionMode(data["execution_mode"]),
            timeout_seconds=data["timeout_seconds"],
            aggregation_function=data.get("aggregation_function")
        )


@dataclass
class QueryResult:
    """Result from a single node execution."""
    node_id: str
    query_id: str
    success: bool
    data: Any
    execution_time_ms: float
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


@dataclass
class AggregatedResult:
    """Aggregated result from multiple node executions."""
    query_id: str
    success: bool
    data: Any
    total_execution_time_ms: float
    node_results: List[QueryResult]
    aggregation_method: str
    nodes_used: int


class ResultAggregator:
    """Aggregates results from multiple nodes."""
    
    @staticmethod
    def aggregate_count_results(results: List[QueryResult]) -> AggregatedResult:
        """Aggregate COUNT query results by summing."""
        total_count = 0
        successful_results = [r for r in results if r.success]
        
        for result in successful_results:
            if isinstance(result.data, (int, float)):
                total_count += result.data
            elif isinstance(result.data, list) and len(result.data) > 0:
                # Assume first column is count
                first_item = result.data[0]
                if first_item is not None:
                    count_value = first_item.get("count", 0) if isinstance(first_item, dict) else first_item
                    if count_value is not None:
                        total_count += count_value
        
        return AggregatedResult(
            query_id=results[0].query_id if results else "",
            success=len(successful_results) > 0,
            data=total_count,
            total_execution_time_ms=max(r.execution_time_ms for r in results) if results else 0,
            node_results=results,
            aggregation_method="sum_count",
            nodes_used=len(successful_results)
        )
    
    @staticmethod
    def aggregate_distinct_results(results: List[QueryResult]) -> AggregatedResult:
        """Aggregate results by collecting distinct values."""
        distinct_values = set()
        successful_results = [r for r in results if r.success]
        
        for result in successful_results:
            if isinstance(result.data, list):
                for item in result.data:
                    if isinstance(item, dict):
                        # Convert dict to tuple for hashing
                        distinct_values.add(tuple(sorted(item.items())))
                    else:
                        distinct_values.add(item)
        
        # Convert back to list of dicts if needed
        aggregated_data = []
        for value in distinct_values:
            if isinstance(value, tuple):
                aggregated_data.append(dict(value))
            else:
                aggregated_data.append(value)
        
        return AggregatedResult(
            query_id=results[0].query_id if results else "",
            success=len(successful_results) > 0,
            data=aggregated_data,
            total_execution_time_ms=max(r.execution_time_ms for r in results) if results else 0,
            node_results=results,
            aggregation_method="distinct_union",
            nodes_used=len(successful_results)
        )
    
    @staticmethod
    def aggregate_first_result(results: List[QueryResult]) -> AggregatedResult:
        """Return first successful result (for fastest-first mode)."""
        successful_results = [r for r in results if r.success]
        
        if successful_results:
            fastest = min(successful_results, key=lambda r: r.execution_time_ms)
            return AggregatedResult(
                query_id=fastest.query_id,
                success=True,
                data=fastest.data,
                total_execution_time_ms=fastest.execution_time_ms,
                node_results=results,
                aggregation_method="first_result",
                nodes_used=1
            )
        
        return AggregatedResult(
            query_id=results[0].query_id if results else "",
            success=False,
            data=None,
            total_execution_time_ms=0,
            node_results=results,
            aggregation_method="first_result",
            nodes_used=0
        )


class QuerySerializer:
    """Serializes and deserializes queries for network transport."""
    
    @staticmethod
    def serialize_query(query: AnalyticalQuery) -> str:
        """Serialize query to JSON string."""
        try:
            return json.dumps(query.to_dict())
        except Exception as e:
            logger.error(f"Query serialization failed: {e}")
            raise
    
    @staticmethod
    def deserialize_query(query_str: str) -> AnalyticalQuery:
        """Deserialize query from JSON string."""
        try:
            data = json.loads(query_str)
            return AnalyticalQuery.from_dict(data)
        except Exception as e:
            logger.error(f"Query deserialization failed: {e}")
            raise


class FunctionShippingOrchestrator:
    """Orchestrates parallel query execution across KuzuDB nodes."""
    
    def __init__(self, kuzu_nodes: Dict[str, KuzuDriver]):
        """
        Initialize function shipping orchestrator.
        
        Args:
            kuzu_nodes: Dictionary mapping node IDs to KuzuDriver instances
        """
        self.nodes = kuzu_nodes
        self.query_serializer = QuerySerializer()
        self.result_aggregator = ResultAggregator()
        
        # Performance tracking
        self.stats = {
            "queries_executed": 0,
            "total_execution_time": 0.0,
            "parallel_queries": 0,
            "nodes_used": 0,
            "aggregations_performed": 0
        }
        
        logger.info(f"Initialized function shipping with {len(kuzu_nodes)} nodes")
    
    async def execute_parallel(
        self,
        query: AnalyticalQuery,
        node_subset: Optional[List[str]] = None
    ) -> AggregatedResult:
        """
        Execute query in parallel across nodes.
        
        Args:
            query: Analytical query to execute
            node_subset: Optional subset of node IDs to use
            
        Returns:
            Aggregated result from all nodes
        """
        start_time = time.time()
        
        try:
            # Determine which nodes to use
            target_nodes = self._select_target_nodes(query.execution_mode, node_subset)
            
            if not target_nodes:
                raise ValueError("No target nodes available for execution")
            
            # Execute on all target nodes in parallel
            tasks = []
            for node_id in target_nodes:
                if node_id in self.nodes:
                    task = self._execute_on_node(node_id, query)
                    tasks.append(task)
            
            # Wait for all executions to complete
            node_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Filter out exceptions and convert to QueryResult objects
            valid_results = []
            for i, result in enumerate(node_results):
                if isinstance(result, Exception):
                    error_result = QueryResult(
                        node_id=target_nodes[i],
                        query_id=query.query_id,
                        success=False,
                        data=None,
                        execution_time_ms=0,
                        error=str(result)
                    )
                    valid_results.append(error_result)
                else:
                    valid_results.append(result)
            
            # Aggregate results
            aggregated = await self._aggregate_results(query, valid_results)
            
            # Update statistics
            execution_time = time.time() - start_time
            self._update_stats(execution_time, len(target_nodes))
            
            return aggregated
            
        except Exception as e:
            logger.error(f"Parallel execution failed for query {query.query_id}: {e}")
            raise
    
    async def _execute_on_node(self, node_id: str, query: AnalyticalQuery) -> QueryResult:
        """Execute query on a single node."""
        start_time = time.time()
        
        try:
            node_driver = self.nodes[node_id]
            
            # Execute the query
            # Note: This would need to be adapted based on KuzuDriver's actual interface
            result_data = await self._execute_cypher_query(node_driver, query)
            
            execution_time = (time.time() - start_time) * 1000
            
            return QueryResult(
                node_id=node_id,
                query_id=query.query_id,
                success=True,
                data=result_data,
                execution_time_ms=execution_time
            )
            
        except Exception as e:
            execution_time = (time.time() - start_time) * 1000
            logger.error(f"Query execution failed on node {node_id}: {e}")
            
            return QueryResult(
                node_id=node_id,
                query_id=query.query_id,
                success=False,
                data=None,
                execution_time_ms=execution_time,
                error=str(e)
            )
    
    async def _execute_cypher_query(self, driver: KuzuDriver, query: AnalyticalQuery) -> Any:
        """Execute Cypher query on KuzuDriver."""
        try:
            # Execute the query using the real KuzuDB driver
            result = await driver.execute_query(query.cypher_query, query.parameters)
            
            # Return the data portion of the result
            if result.get("success"):
                return result.get("rows", [])
            else:
                raise Exception(f"Query execution failed: {result.get('error', 'Unknown error')}")
                
        except Exception as e:
            logger.error(f"Cypher query execution failed: {e}")
            raise
    
    def _select_target_nodes(
        self,
        execution_mode: QueryExecutionMode,
        node_subset: Optional[List[str]] = None
    ) -> List[str]:
        """Select target nodes based on execution mode."""
        available_nodes = list(self.nodes.keys())
        
        if node_subset:
            available_nodes = [n for n in available_nodes if n in node_subset]
        
        if execution_mode == QueryExecutionMode.PARALLEL_ALL:
            return available_nodes
        elif execution_mode == QueryExecutionMode.PARALLEL_SUBSET:
            # Use half of available nodes
            subset_size = max(1, len(available_nodes) // 2)
            return available_nodes[:subset_size]
        elif execution_mode == QueryExecutionMode.FASTEST_FIRST:
            # Return first node (in practice, would track node performance)
            return available_nodes[:1]
        elif execution_mode == QueryExecutionMode.ROUND_ROBIN:
            # Simple round-robin selection
            node_index = self.stats["queries_executed"] % len(available_nodes)
            return [available_nodes[node_index]]
        
        return available_nodes
    
    async def _aggregate_results(
        self,
        query: AnalyticalQuery,
        results: List[QueryResult]
    ) -> AggregatedResult:
        """Aggregate results based on query type."""
        if not results:
            return AggregatedResult(
                query_id=query.query_id,
                success=False,
                data=None,
                total_execution_time_ms=0,
                node_results=[],
                aggregation_method="none",
                nodes_used=0
            )
        
        # Determine aggregation method
        if query.aggregation_function:
            aggregation_method = query.aggregation_function
        elif "count" in query.cypher_query.lower():
            aggregation_method = "count"
        elif "distinct" in query.cypher_query.lower():
            aggregation_method = "distinct"
        else:
            aggregation_method = "first"
        
        # Apply aggregation
        if aggregation_method == "count":
            result = self.result_aggregator.aggregate_count_results(results)
        elif aggregation_method == "distinct":
            result = self.result_aggregator.aggregate_distinct_results(results)
        else:
            result = self.result_aggregator.aggregate_first_result(results)
        
        self.stats["aggregations_performed"] += 1
        return result
    
    def _update_stats(self, execution_time: float, nodes_used: int) -> None:
        """Update performance statistics."""
        self.stats["queries_executed"] += 1
        self.stats["total_execution_time"] += execution_time
        self.stats["parallel_queries"] += 1 if nodes_used > 1 else 0
        self.stats["nodes_used"] += nodes_used
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """Get performance statistics."""
        executed = max(self.stats["queries_executed"], 1)
        
        return {
            "queries_executed": self.stats["queries_executed"],
            "avg_execution_time": self.stats["total_execution_time"] / executed,
            "parallel_queries": self.stats["parallel_queries"],
            "avg_nodes_per_query": self.stats["nodes_used"] / executed,
            "aggregations_performed": self.stats["aggregations_performed"],
            "available_nodes": len(self.nodes),
            "parallel_efficiency": self.stats["parallel_queries"] / executed if executed > 0 else 0
        }
    
    async def close(self) -> None:
        """Clean up resources."""
        logger.info("Function shipping orchestrator closed")


# Factory functions for common query patterns
def create_count_query(
    query_id: str,
    cypher_query: str,
    timeout_seconds: float = 30.0
) -> AnalyticalQuery:
    """Create a count aggregation query."""
    return AnalyticalQuery(
        query_id=query_id,
        cypher_query=cypher_query,
        parameters={},
        execution_mode=QueryExecutionMode.PARALLEL_ALL,
        timeout_seconds=timeout_seconds,
        aggregation_function="count"
    )


def create_distinct_query(
    query_id: str,
    cypher_query: str,
    timeout_seconds: float = 60.0
) -> AnalyticalQuery:
    """Create a distinct values query."""
    return AnalyticalQuery(
        query_id=query_id,
        cypher_query=cypher_query,
        parameters={},
        execution_mode=QueryExecutionMode.PARALLEL_ALL,
        timeout_seconds=timeout_seconds,
        aggregation_function="distinct"
    )


def create_fastest_first_query(
    query_id: str,
    cypher_query: str,
    timeout_seconds: float = 10.0
) -> AnalyticalQuery:
    """Create a fastest-first query for time-sensitive operations."""
    return AnalyticalQuery(
        query_id=query_id,
        cypher_query=cypher_query,
        parameters={},
        execution_mode=QueryExecutionMode.FASTEST_FIRST,
        timeout_seconds=timeout_seconds,
        aggregation_function="first"
    )