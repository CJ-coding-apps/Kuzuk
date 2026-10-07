"""
Network Transport Layer for Function Shipping
Handles communication between function shipping orchestrator and remote KuzuDB nodes.
"""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

try:
    import aiohttp

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    aiohttp = None  # type: ignore[assignment]  # optional dependency

from .orchestrator import AnalyticalQuery, QueryResult

logger = logging.getLogger(__name__)


class TransportProtocol(Enum):
    """Supported transport protocols."""

    HTTP = "http"
    HTTPS = "https"
    TCP = "tcp"
    UNIX_SOCKET = "unix"


@dataclass
class NodeEndpoint:
    """Represents a network endpoint for a KuzuDB node."""

    node_id: str
    protocol: TransportProtocol
    host: str
    port: int
    path: str = "/query"
    timeout: float = 30.0

    def get_url(self) -> str:
        """Get the full URL for this endpoint."""
        if self.protocol in [TransportProtocol.HTTP, TransportProtocol.HTTPS]:
            return f"{self.protocol.value}://{self.host}:{self.port}{self.path}"
        elif self.protocol == TransportProtocol.TCP:
            return f"{self.host}:{self.port}"
        else:
            return f"{self.path}"


@dataclass
class TransportRequest:
    """Represents a transport request."""

    request_id: str
    query: AnalyticalQuery
    timestamp: float
    metadata: Dict[str, Any]


@dataclass
class TransportResponse:
    """Represents a transport response."""

    request_id: str
    success: bool
    result: Optional[QueryResult] = None
    error: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class HTTPTransport:
    """HTTP/HTTPS transport implementation."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.session: Optional[aiohttp.ClientSession] = None

    async def initialize(self) -> None:
        """Initialize the HTTP session."""
        if self.session is None:
            if not AIOHTTP_AVAILABLE:
                raise ImportError(
                    "aiohttp is required for HTTP transport. Install with: pip install aiohttp"
                )

            connector = aiohttp.TCPConnector(
                limit=100, limit_per_host=30, keepalive_timeout=30, enable_cleanup_closed=True
            )
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self.session = aiohttp.ClientSession(connector=connector, timeout=timeout)

    async def send_request(
        self, endpoint: NodeEndpoint, request: TransportRequest
    ) -> TransportResponse:
        """Send HTTP request to node endpoint."""
        await self.initialize()

        try:
            # Prepare request payload
            payload = {
                "request_id": request.request_id,
                "query": request.query.to_dict(),
                "timestamp": request.timestamp,
                "metadata": request.metadata,
            }

            headers = {
                "Content-Type": "application/json",
                "X-Request-ID": request.request_id,
                "X-Node-ID": endpoint.node_id,
            }

            # Send HTTP request
            session = self.session
            if session is None:
                raise RuntimeError("HTTP transport session was not initialized")
            async with session.post(
                endpoint.get_url(),
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=endpoint.timeout),
            ) as response:

                if response.status == 200:
                    response_data = await response.json()

                    # Parse response
                    if response_data.get("success"):
                        result = QueryResult(
                            node_id=endpoint.node_id,
                            query_id=request.query.query_id,
                            success=True,
                            data=response_data.get("data"),
                            execution_time_ms=response_data.get("execution_time_ms", 0),
                            metadata=response_data.get("metadata", {}),
                        )

                        return TransportResponse(
                            request_id=request.request_id,
                            success=True,
                            result=result,
                            metadata=response_data.get("metadata", {}),
                        )
                    else:
                        return TransportResponse(
                            request_id=request.request_id,
                            success=False,
                            error=response_data.get("error", "Unknown error"),
                            metadata=response_data.get("metadata", {}),
                        )
                else:
                    error_text = await response.text()
                    return TransportResponse(
                        request_id=request.request_id,
                        success=False,
                        error=f"HTTP {response.status}: {error_text}",
                    )

        except asyncio.TimeoutError:
            return TransportResponse(
                request_id=request.request_id,
                success=False,
                error=f"Request timeout after {endpoint.timeout}s",
            )
        except Exception as e:
            return TransportResponse(request_id=request.request_id, success=False, error=str(e))

    async def close(self) -> None:
        """Close the HTTP session."""
        if self.session:
            await self.session.close()
            self.session = None


class TCPTransport:
    """TCP transport implementation for binary protocols."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    async def send_request(
        self, endpoint: NodeEndpoint, request: TransportRequest
    ) -> TransportResponse:
        """Send TCP request to node endpoint."""
        try:
            # Serialize request
            request_data = {
                "request_id": request.request_id,
                "query": request.query.to_dict(),
                "timestamp": request.timestamp,
                "metadata": request.metadata,
            }

            message = json.dumps(request_data).encode("utf-8")
            message_length = len(message)

            # Create TCP connection
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(endpoint.host, endpoint.port), timeout=self.timeout
            )

            try:
                # Send message length first, then message
                writer.write(message_length.to_bytes(4, byteorder="big"))
                writer.write(message)
                await writer.drain()

                # Read response length
                length_data = await asyncio.wait_for(reader.read(4), timeout=self.timeout)

                if len(length_data) != 4:
                    raise Exception("Invalid response length header")

                response_length = int.from_bytes(length_data, byteorder="big")

                # Read response data
                response_data = await asyncio.wait_for(
                    reader.read(response_length), timeout=self.timeout
                )

                if len(response_data) != response_length:
                    raise Exception("Incomplete response data")

                # Parse response
                response_json = json.loads(response_data.decode("utf-8"))

                if response_json.get("success"):
                    result = QueryResult(
                        node_id=endpoint.node_id,
                        query_id=request.query.query_id,
                        success=True,
                        data=response_json.get("data"),
                        execution_time_ms=response_json.get("execution_time_ms", 0),
                        metadata=response_json.get("metadata", {}),
                    )

                    return TransportResponse(
                        request_id=request.request_id,
                        success=True,
                        result=result,
                        metadata=response_json.get("metadata", {}),
                    )
                else:
                    return TransportResponse(
                        request_id=request.request_id,
                        success=False,
                        error=response_json.get("error", "Unknown error"),
                        metadata=response_json.get("metadata", {}),
                    )

            finally:
                writer.close()
                await writer.wait_closed()

        except asyncio.TimeoutError:
            return TransportResponse(
                request_id=request.request_id,
                success=False,
                error=f"TCP request timeout after {self.timeout}s",
            )
        except Exception as e:
            return TransportResponse(request_id=request.request_id, success=False, error=str(e))


class NetworkTransportManager:
    """
    Manages network transport for function shipping.
    Handles multiple protocols and connection pooling.
    """

    def __init__(self):
        self.http_transport = HTTPTransport()
        self.tcp_transport = TCPTransport()
        self.endpoints: Dict[str, NodeEndpoint] = {}
        self.stats = {
            "requests_sent": 0,
            "requests_successful": 0,
            "requests_failed": 0,
            "total_response_time": 0.0,
        }

    def register_endpoint(self, endpoint: NodeEndpoint) -> None:
        """Register a node endpoint for transport."""
        self.endpoints[endpoint.node_id] = endpoint
        logger.info(f"Registered endpoint: {endpoint.node_id} -> {endpoint.get_url()}")

    def unregister_endpoint(self, node_id: str) -> None:
        """Unregister a node endpoint."""
        if node_id in self.endpoints:
            del self.endpoints[node_id]
            logger.info(f"Unregistered endpoint: {node_id}")

    async def send_query(
        self, node_id: str, query: AnalyticalQuery, metadata: Optional[Dict[str, Any]] = None
    ) -> QueryResult:
        """
        Send query to a specific node.

        Args:
            node_id: Target node ID
            query: Query to execute
            metadata: Optional metadata

        Returns:
            Query result
        """
        if node_id not in self.endpoints:
            raise ValueError(f"Node endpoint not registered: {node_id}")

        endpoint = self.endpoints[node_id]
        request_id = str(uuid.uuid4())

        request = TransportRequest(
            request_id=request_id, query=query, timestamp=time.time(), metadata=metadata or {}
        )

        start_time = time.time()

        try:
            # Select transport based on protocol
            if endpoint.protocol in [TransportProtocol.HTTP, TransportProtocol.HTTPS]:
                response = await self.http_transport.send_request(endpoint, request)
            elif endpoint.protocol == TransportProtocol.TCP:
                response = await self.tcp_transport.send_request(endpoint, request)
            else:
                raise ValueError(f"Unsupported protocol: {endpoint.protocol}")

            # Update statistics
            response_time = time.time() - start_time
            self.stats["requests_sent"] += 1
            self.stats["total_response_time"] += response_time

            if response.success and response.result is not None:
                self.stats["requests_successful"] += 1
                return response.result
            else:
                self.stats["requests_failed"] += 1
                # Create error result
                return QueryResult(
                    node_id=node_id,
                    query_id=query.query_id,
                    success=False,
                    data=None,
                    execution_time_ms=response_time * 1000,
                    error=response.error,
                )

        except Exception as e:
            self.stats["requests_sent"] += 1
            self.stats["requests_failed"] += 1

            response_time = time.time() - start_time
            self.stats["total_response_time"] += response_time

            return QueryResult(
                node_id=node_id,
                query_id=query.query_id,
                success=False,
                data=None,
                execution_time_ms=response_time * 1000,
                error=str(e),
            )

    async def broadcast_query(
        self,
        query: AnalyticalQuery,
        node_ids: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, QueryResult]:
        """
        Broadcast query to multiple nodes.

        Args:
            query: Query to execute
            node_ids: Target node IDs (None for all)
            metadata: Optional metadata

        Returns:
            Dictionary mapping node IDs to results
        """
        target_nodes = node_ids or list(self.endpoints.keys())

        # Send requests in parallel
        tasks = []
        for node_id in target_nodes:
            if node_id in self.endpoints:
                task = self.send_query(node_id, query, metadata)
                tasks.append((node_id, task))

        # Wait for all responses
        results = {}
        completed_tasks = await asyncio.gather(*[task for _, task in tasks], return_exceptions=True)

        for (node_id, _), result in zip(tasks, completed_tasks):
            if isinstance(result, BaseException):
                results[node_id] = QueryResult(
                    node_id=node_id,
                    query_id=query.query_id,
                    success=False,
                    data=None,
                    execution_time_ms=0,
                    error=str(result),
                )
            else:
                results[node_id] = result

        return results

    def get_transport_stats(self) -> Dict[str, Any]:
        """Get transport statistics."""
        sent = max(self.stats["requests_sent"], 1)
        return {
            "requests_sent": self.stats["requests_sent"],
            "requests_successful": self.stats["requests_successful"],
            "requests_failed": self.stats["requests_failed"],
            "success_rate": self.stats["requests_successful"] / sent,
            "avg_response_time": self.stats["total_response_time"] / sent,
            "registered_endpoints": len(self.endpoints),
        }

    async def close(self) -> None:
        """Close all transport connections."""
        await self.http_transport.close()
        logger.info("Network transport manager closed")


# Mock HTTP server for testing
class MockKuzuNodeServer:
    """Mock HTTP server that simulates a KuzuDB node for testing."""

    def __init__(self, node_id: str, port: int = 8080):
        self.node_id = node_id
        self.port = port
        self.app: Any = None
        self.runner: Any = None
        self.site: Any = None

    async def handle_query(self, request):
        """Handle incoming query requests."""
        try:
            data = await request.json()
            data.get("query", {})

            # Simulate query execution
            await asyncio.sleep(0.1)  # Simulate processing time

            # Mock response
            response = {
                "success": True,
                "data": {"mock_result": f"processed by {self.node_id}"},
                "execution_time_ms": 100,
                "metadata": {"node_id": self.node_id},
            }

            if not AIOHTTP_AVAILABLE:
                raise ImportError("aiohttp required for mock server")
            return aiohttp.web.json_response(response)

        except Exception as e:
            if not AIOHTTP_AVAILABLE:
                raise ImportError("aiohttp required for mock server")
            return aiohttp.web.json_response({"success": False, "error": str(e)}, status=500)

    async def start(self) -> None:
        """Start the mock server."""
        if not AIOHTTP_AVAILABLE:
            raise ImportError("aiohttp required for mock server")

        self.app = aiohttp.web.Application()
        self.app.router.add_post("/query", self.handle_query)

        self.runner = aiohttp.web.AppRunner(self.app)
        await self.runner.setup()

        self.site = aiohttp.web.TCPSite(self.runner, "localhost", self.port)
        await self.site.start()

        logger.info(f"Mock KuzuDB node {self.node_id} started on port {self.port}")

    async def stop(self) -> None:
        """Stop the mock server."""
        if self.site:
            await self.site.stop()
        if self.runner:
            await self.runner.cleanup()
        logger.info(f"Mock KuzuDB node {self.node_id} stopped")


# Factory functions
def create_http_endpoint(node_id: str, host: str, port: int, **kwargs) -> NodeEndpoint:
    """Create HTTP endpoint configuration."""
    return NodeEndpoint(
        node_id=node_id, protocol=TransportProtocol.HTTP, host=host, port=port, **kwargs
    )


def create_tcp_endpoint(node_id: str, host: str, port: int, **kwargs) -> NodeEndpoint:
    """Create TCP endpoint configuration."""
    return NodeEndpoint(
        node_id=node_id, protocol=TransportProtocol.TCP, host=host, port=port, **kwargs
    )


async def create_mock_node_cluster(
    node_count: int, base_port: int = 8080
) -> List[MockKuzuNodeServer]:
    """Create a cluster of mock KuzuDB nodes for testing."""
    servers = []

    for i in range(node_count):
        node_id = f"node_{i+1}"
        port = base_port + i
        server = MockKuzuNodeServer(node_id, port)
        await server.start()
        servers.append(server)

    return servers
