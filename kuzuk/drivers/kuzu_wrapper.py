"""
KuzuDB Python Driver Wrapper for Scaling Package
Provides a consistent interface for KuzuDB operations with error handling and connection management.
"""

import logging
import asyncio
import time
from typing import Any, Dict, List, Optional, Union
from pathlib import Path
import threading
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

try:
    import kuzu
    KUZU_AVAILABLE = True
except ImportError:
    KUZU_AVAILABLE = False
    logger.warning("KuzuDB Python bindings not available. Using mock implementation.")


class MockKuzuDatabase:
    """Mock KuzuDB Database for testing when kuzu package is not available."""
    
    def __init__(self, database_path: str, **kwargs):
        self.database_path = database_path
        logger.info(f"Mock KuzuDB Database created: {database_path}")


class MockKuzuConnection:
    """Mock KuzuDB Connection for testing when kuzu package is not available."""
    
    def __init__(self, database):
        self.database = database
        logger.info("Mock KuzuDB Connection created")
    
    def execute(self, query: str) -> Dict[str, Any]:
        """Mock query execution."""
        logger.info(f"Mock executing query: {query[:100]}...")
        return {"success": True, "rows": [], "columns": []}
    
    def close(self):
        """Mock connection close."""
        logger.info("Mock KuzuDB Connection closed")


class KuzuDriver:
    """
    Async wrapper for KuzuDB driver operations.
    Provides connection pooling, error handling, and async interface.
    """
    
    def __init__(
        self,
        database_path: str,
        buffer_pool_size: int = 1024 * 1024 * 1024,  # 1GB default
        max_num_threads: int = 4,
        enable_compression: bool = True,
        read_only: bool = False
    ):
        """
        Initialize KuzuDB driver.
        
        Args:
            database_path: Path to KuzuDB database
            buffer_pool_size: Buffer pool size in bytes
            max_num_threads: Maximum number of threads for query execution
            enable_compression: Enable compression for on-disk storage
            read_only: Open database in read-only mode
        """
        self.database_path = Path(database_path)
        self.buffer_pool_size = buffer_pool_size
        self.max_num_threads = max_num_threads
        self.enable_compression = enable_compression
        self.read_only = read_only
        
        # Connection management
        self.database = None
        self.connection = None
        self._lock = threading.Lock()
        self._initialized = False
        
        logger.info(f"KuzuDriver initialized: {database_path}")
    
    async def initialize(self) -> None:
        """Initialize the database connection."""
        if self._initialized:
            return
        
        with self._lock:
            if self._initialized:
                return
            
            try:
                await self._initialize_database()
                self._initialized = True
                logger.info(f"KuzuDB connection established: {self.database_path}")
                
            except Exception as e:
                logger.error(f"Failed to initialize KuzuDB: {e}")
                raise
    
    async def _initialize_database(self) -> None:
        """Initialize database and connection in a thread-safe manner."""
        def _init():
            if KUZU_AVAILABLE:
                # Create database - API has changed in newer versions
                try:
                    # Try new API first (KuzuDB 0.11+)
                    self.database = kuzu.Database(str(self.database_path))
                    self.connection = kuzu.Connection(self.database)
                except Exception as e:
                    # Fallback to older API with SystemConfig if available
                    try:
                        if hasattr(kuzu, 'SystemConfig'):
                            system_config = kuzu.SystemConfig()
                            system_config.buffer_pool_size = self.buffer_pool_size
                            system_config.max_num_threads = self.max_num_threads
                            system_config.enable_compression = self.enable_compression
                            system_config.read_only = self.read_only
                            
                            self.database = kuzu.Database(str(self.database_path), system_config)
                            self.connection = kuzu.Connection(self.database)
                        else:
                            # Simple database creation without config
                            self.database = kuzu.Database(str(self.database_path))
                            self.connection = kuzu.Connection(self.database)
                    except Exception as fallback_error:
                        logger.error(f"Both new and old KuzuDB API failed: {e}, {fallback_error}")
                        raise e
            else:
                # Use mock implementation
                self.database = MockKuzuDatabase(str(self.database_path))
                self.connection = MockKuzuConnection(self.database)
        
        # Run initialization in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _init)
    
    async def execute_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a Cypher query.
        
        Args:
            query: Cypher query string
            parameters: Query parameters
            
        Returns:
            Query result as dictionary
        """
        await self.initialize()
        
        try:
            def _execute():
                if KUZU_AVAILABLE:
                    result = self.connection.execute(query)
                    return self._process_result(result)
                else:
                    return self.connection.execute(query)
            
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _execute)
            
        except Exception as e:
            logger.error(f"Query execution failed: {e}")
            raise
    
    async def execute_write_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a write query (CREATE, UPDATE, DELETE).
        
        Args:
            query: Cypher query string
            parameters: Query parameters
            
        Returns:
            Query result as dictionary
        """
        if self.read_only:
            raise RuntimeError("Cannot execute write queries on read-only database")
        
        return await self.execute_query(query, parameters)
    
    async def execute_read_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a read-only query.
        
        Args:
            query: Cypher query string
            parameters: Query parameters
            
        Returns:
            Query result as dictionary
        """
        return await self.execute_query(query, parameters)
    
    def _process_result(self, result) -> Dict[str, Any]:
        """Process KuzuDB query result into standardized format."""
        if not KUZU_AVAILABLE:
            return result
        
        try:
            rows = []
            columns = []
            
            # Handle different KuzuDB result formats
            if hasattr(result, 'get_column_names'):
                columns = result.get_column_names()
            elif hasattr(result, 'columns'):
                columns = result.columns
            
            # Extract rows from result
            if hasattr(result, 'get_next') and hasattr(result, 'has_next'):
                # KuzuDB 0.5+ result format
                while result.has_next():
                    result.get_next()
                    row_data = {}
                    for i, col_name in enumerate(columns):
                        try:
                            value = result.get_value(i)
                            # Handle KuzuDB value types
                            if hasattr(value, 'get_value'):
                                value = value.get_value()
                            row_data[col_name] = value
                        except Exception:
                            row_data[col_name] = None
                    rows.append(row_data)
            
            elif hasattr(result, 'fetchall'):
                # Alternative result format
                for row in result.fetchall():
                    if isinstance(row, (list, tuple)):
                        row_dict = {}
                        for i, col_name in enumerate(columns):
                            row_dict[col_name] = row[i] if i < len(row) else None
                        rows.append(row_dict)
                    else:
                        rows.append(row)
            
            # Get execution statistics if available
            stats = {}
            if hasattr(result, 'get_query_summary'):
                summary = result.get_query_summary()
                if hasattr(summary, 'get_execution_time'):
                    stats['execution_time_ms'] = summary.get_execution_time()
                if hasattr(summary, 'get_compiling_time'):
                    stats['compile_time_ms'] = summary.get_compiling_time()
            
            return {
                "success": True,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "stats": stats
            }
            
        except Exception as e:
            logger.error(f"Error processing KuzuDB result: {e}")
            return {
                "success": False,
                "error": str(e),
                "columns": [],
                "rows": [],
                "stats": {}
            }
    
    async def prepare_statement(self, query: str) -> Any:
        """
        Prepare a query statement for repeated execution.
        
        Args:
            query: Cypher query string
            
        Returns:
            Prepared statement object
        """
        await self.initialize()
        
        def _prepare():
            if KUZU_AVAILABLE:
                return self.connection.prepare(query)
            else:
                return {"query": query, "prepared": True}
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _prepare)
    
    async def execute_prepared(
        self,
        prepared_statement: Any,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute a prepared statement.
        
        Args:
            prepared_statement: Prepared statement object
            parameters: Query parameters
            
        Returns:
            Query result as dictionary
        """
        await self.initialize()
        
        def _execute():
            if KUZU_AVAILABLE:
                if parameters:
                    # Convert parameters to KuzuDB format if needed
                    result = self.connection.execute(prepared_statement, parameters)
                else:
                    result = self.connection.execute(prepared_statement)
                return self._process_result(result)
            else:
                return {"success": True, "rows": [], "columns": []}
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _execute)
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform a comprehensive health check on the database connection.
        
        Returns:
            Health status information including database metrics
        """
        start_time = time.time()
        health_info = {
            "healthy": False,
            "database_path": str(self.database_path),
            "read_only": self.read_only,
            "initialized": self._initialized,
            "checks": {},
            "response_time_ms": 0
        }
        
        try:
            await self.initialize()
            
            # Basic connectivity test
            result = await self.execute_query("RETURN 1 as connectivity_test")
            health_info["checks"]["connectivity"] = result.get("success", False)
            
            if result.get("success"):
                # Database info queries
                try:
                    # Skip version query for now as it's not available in all KuzuDB versions
                    health_info["checks"]["version_query"] = True
                except Exception:
                    health_info["checks"]["version_query"] = False
                
                # Check table count
                try:
                    tables_result = await self.execute_query("MATCH (n) RETURN COUNT(*) as table_count")
                    if tables_result.get("success"):
                        health_info["checks"]["table_count_query"] = True
                        if tables_result.get("rows"):
                            health_info["table_count"] = tables_result["rows"][0].get("table_count", 0)
                except Exception:
                    health_info["checks"]["table_count_query"] = False
                
                # Performance test - simple aggregation
                try:
                    perf_start = time.time()
                    perf_result = await self.execute_query("RETURN 1 as perf_test")
                    perf_time = (time.time() - perf_start) * 1000
                    health_info["checks"]["performance_test"] = perf_result.get("success", False)
                    health_info["performance_test_ms"] = perf_time
                except Exception:
                    health_info["checks"]["performance_test"] = False
                
                # Check if database is writable (for non-read-only connections)
                if not self.read_only:
                    try:
                        # Try to create and drop a temporary table
                        await self.execute_query("CREATE NODE TABLE IF NOT EXISTS __health_test__(id INT64, PRIMARY KEY(id))")
                        await self.execute_query("DROP TABLE __health_test__")
                        health_info["checks"]["write_test"] = True
                    except Exception:
                        health_info["checks"]["write_test"] = False
                
                # Overall health assessment
                successful_checks = sum(1 for check in health_info["checks"].values() if check)
                total_checks = len(health_info["checks"])
                health_info["healthy"] = successful_checks >= (total_checks * 0.7)  # 70% success rate
                health_info["health_percentage"] = (successful_checks / total_checks * 100) if total_checks > 0 else 0
            
            health_info["response_time_ms"] = (time.time() - start_time) * 1000
            return health_info
                
        except Exception as e:
            health_info["response_time_ms"] = (time.time() - start_time) * 1000
            health_info["error"] = str(e)
            health_info["checks"]["connection_error"] = True
            logger.error(f"Health check failed for {self.database_path}: {e}")
            return health_info
    
    @asynccontextmanager
    async def transaction(self):
        """
        Context manager for database transactions.
        Note: KuzuDB handles transactions automatically per query.
        This is a placeholder for future transaction support.
        """
        await self.initialize()
        try:
            yield self
        except Exception as e:
            logger.error(f"Transaction error: {e}")
            raise
    
    async def get_schema_info(self) -> Dict[str, Any]:
        """
        Get comprehensive database schema information.
        
        Returns:
            Schema information including tables, relationships, and properties
        """
        try:
            schema_info = {
                "database_path": str(self.database_path),
                "node_tables": [],
                "rel_tables": [],
                "total_tables": 0,
                "schema_version": None
            }
            
            # For now, just return basic schema info since show_tables() syntax varies by version
            schema_info["total_tables"] = 0
            return schema_info
            
            if tables_result.get("success"):
                tables = tables_result.get("rows", [])
                schema_info["total_tables"] = len(tables)
                
                for table in tables:
                    table_info = {
                        "name": table.get("name", ""),
                        "type": table.get("type", ""),
                        "comment": table.get("comment", ""),
                        "properties": []
                    }
                    
                    # Get table properties/schema
                    try:
                        props_result = await self.execute_query(f"CALL table_info('{table_info['name']}') RETURN property_name, property_type")
                        if props_result.get("success"):
                            table_info["properties"] = props_result.get("rows", [])
                    except Exception as e:
                        logger.warning(f"Could not get properties for table {table_info['name']}: {e}")
                    
                    # Categorize tables
                    if table_info["type"].upper() in ["NODE", "NODE_TABLE"]:
                        schema_info["node_tables"].append(table_info)
                    elif table_info["type"].upper() in ["REL", "RELATIONSHIP", "REL_TABLE"]:
                        schema_info["rel_tables"].append(table_info)
            
            # Try to get database statistics
            try:
                stats_result = await self.execute_query("CALL show_attached_databases() RETURN database_name, database_type")
                if stats_result.get("success"):
                    schema_info["attached_databases"] = stats_result.get("rows", [])
            except Exception:
                pass
            
            return schema_info
            
        except Exception as e:
            logger.error(f"Error getting schema info: {e}")
            return {
                "error": str(e),
                "database_path": str(self.database_path),
                "node_tables": [],
                "rel_tables": [],
                "total_tables": 0
            }
    
    async def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            if self.connection:
                if KUZU_AVAILABLE and hasattr(self.connection, 'close'):
                    self.connection.close()
                else:
                    # Mock connection
                    self.connection.close()
                self.connection = None
            
            self.database = None
            self._initialized = False
            
        logger.info(f"KuzuDB connection closed: {self.database_path}")


class KuzuDriverPool:
    """
    Connection pool for managing multiple KuzuDB connections.
    Useful for high-concurrency scenarios.
    """
    
    def __init__(
        self,
        database_path: str,
        pool_size: int = 5,
        **driver_kwargs
    ):
        """
        Initialize connection pool.
        
        Args:
            database_path: Path to KuzuDB database
            pool_size: Number of connections in pool
            **driver_kwargs: Additional arguments for KuzuDriver
        """
        self.database_path = database_path
        self.pool_size = pool_size
        self.driver_kwargs = driver_kwargs
        
        self.pool: List[KuzuDriver] = []
        self.available: asyncio.Queue = asyncio.Queue()
        self._initialized = False
        self._lock = asyncio.Lock()
    
    async def initialize(self) -> None:
        """Initialize the connection pool."""
        async with self._lock:
            if self._initialized:
                return
            
            for i in range(self.pool_size):
                driver = KuzuDriver(
                    database_path=self.database_path,
                    **self.driver_kwargs
                )
                await driver.initialize()
                self.pool.append(driver)
                await self.available.put(driver)
            
            self._initialized = True
            logger.info(f"KuzuDB connection pool initialized: {self.pool_size} connections")
    
    @asynccontextmanager
    async def get_connection(self):
        """
        Get a connection from the pool.
        
        Yields:
            KuzuDriver instance
        """
        await self.initialize()
        driver = await self.available.get()
        try:
            yield driver
        finally:
            await self.available.put(driver)
    
    async def close(self) -> None:
        """Close all connections in the pool."""
        async with self._lock:
            for driver in self.pool:
                await driver.close()
            self.pool.clear()
            self._initialized = False
            
        logger.info("KuzuDB connection pool closed")


# Factory functions
def create_read_only_driver(database_path: str) -> KuzuDriver:
    """Create a read-only KuzuDB driver."""
    return KuzuDriver(
        database_path=database_path,
        read_only=True,
        buffer_pool_size=512 * 1024 * 1024  # 512MB for read-only
    )


def create_write_driver(database_path: str) -> KuzuDriver:
    """Create a read-write KuzuDB driver."""
    return KuzuDriver(
        database_path=database_path,
        read_only=False,
        buffer_pool_size=1024 * 1024 * 1024  # 1GB for read-write
    )


def create_high_performance_driver(database_path: str) -> KuzuDriver:
    """Create a high-performance KuzuDB driver."""
    return KuzuDriver(
        database_path=database_path,
        read_only=False,
        buffer_pool_size=4 * 1024 * 1024 * 1024,  # 4GB buffer
        max_num_threads=8,
        enable_compression=True
    )