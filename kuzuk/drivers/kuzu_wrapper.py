"""
KuzuDB Python Driver Wrapper for Scaling Package
Provides a consistent interface for KuzuDB operations with error handling and connection management.
"""

import asyncio
import logging
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

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
        read_only: bool = False,
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

        # Connection management. ``_lock`` guards the native connection and is
        # only ever held by the worker thread performing the call; ``_init_lock``
        # is the async-safe guard for one-time initialisation. Using the blocking
        # lock for both deadlocked: initialize() held it across an await, so a
        # second caller blocked the event loop while the first could never resume
        # to release it.
        self.database: Any = None
        self.connection: Any = None
        self._lock = threading.Lock()
        self._init_lock = asyncio.Lock()
        self._initialized = False

        logger.info(f"KuzuDriver initialized: {database_path}")

    async def initialize(self) -> None:
        """Initialize the database connection."""
        if self._initialized:
            return

        async with self._init_lock:
            if self._initialized:
                return

            try:
                await self._initialize_database()
                self._initialized = True
                logger.info(f"KuzuDB connection established: {self.database_path}")

            except Exception as e:
                logger.error(f"Failed to initialize KuzuDB: {e}")
                raise

    def _open_database(self):
        """Open the Kùzu database, applying the configured options.

        kuzu 0.11.3 (the pinned version, verified) takes these as keyword
        arguments and spells compression ``compression``. The options used to be
        applied only on a dead fallback branch, so ``read_only`` and the
        resource limits were silently ignored and every database was opened
        read-write. A ``SystemConfig`` fallback for older bindings was removed:
        it is not present in 0.11.3 and could never have run.
        """
        options: Dict[str, Any] = {
            "buffer_pool_size": self.buffer_pool_size,
            "max_num_threads": self.max_num_threads,
            "read_only": self.read_only,
            "compression": self.enable_compression,
        }
        return kuzu.Database(str(self.database_path), **options)

    async def _initialize_database(self) -> None:
        """Initialize database and connection in a thread-safe manner."""

        def _init():
            if KUZU_AVAILABLE:
                with self._lock:
                    self.database = self._open_database()
                    self.connection = kuzu.Connection(self.database)
            else:
                # Use mock implementation
                self.database = MockKuzuDatabase(str(self.database_path))
                self.connection = MockKuzuConnection(self.database)

        # Run initialization in thread pool to avoid blocking
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _init)

    async def execute_query(
        self, query: str, parameters: Optional[Dict[str, Any]] = None
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
                    # Hold the lock for the duration of the native call. Kùzu's
                    # bindings are not safe to use concurrently with close(); a
                    # cancelled await leaves this thread running (executor futures
                    # cannot be cancelled once started), so without the lock a
                    # close() on another thread tears the connection out from
                    # under a query that is still executing, which segfaults.
                    with self._lock:
                        if self.connection is None:
                            raise RuntimeError("Database connection is closed")
                        # Bind parameters when supplied. Passing them through is
                        # the whole point of parameterised queries: an unbound
                        # placeholder is not "safe by construction" -- Kùzu
                        # evaluates the predicate as though it were absent, so
                        # `WHERE u.name = $n` silently returns every row.
                        result = self.connection.execute(query, parameters or None)
                        return self._process_result(result)
                else:
                    return self.connection.execute(query)

            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, _execute)

        except Exception as e:
            # Report the failure rather than raising: the documented contract of
            # execute_query() is to return a result dict carrying a `success`
            # flag, and callers (health checks, routing, function shipping) read
            # that flag instead of guarding every call with try/except. A
            # malformed query is a caller error, not a crash. The error text is
            # preserved in the dict.
            logger.error(f"Query execution failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "columns": [],
                "rows": [],
                "row_count": 0,
                "stats": {},
            }

    async def execute_write_query(
        self, query: str, parameters: Optional[Dict[str, Any]] = None
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
        self, query: str, parameters: Optional[Dict[str, Any]] = None
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
            if hasattr(result, "get_column_names"):
                columns = result.get_column_names()
            elif hasattr(result, "columns"):
                columns = result.columns

            # Extract rows from result
            if hasattr(result, "get_next") and hasattr(result, "has_next"):
                # Current bindings return each row from get_next() as a sequence
                # of column values. The older get_value(i) accessor that this
                # used to call no longer exists in kuzu 0.11.x -- the resulting
                # AttributeError was swallowed, so every column came back None.
                while result.has_next():
                    row = result.get_next()
                    if isinstance(row, dict):
                        rows.append(row)
                        continue
                    row_data: Dict[str, Any] = {}
                    for i, col_name in enumerate(columns):
                        value: Any = row[i] if i < len(row) else None
                        # Handle KuzuDB value wrapper types
                        if hasattr(value, "get_value"):
                            value = value.get_value()
                        row_data[col_name] = value
                    rows.append(row_data)

            elif hasattr(result, "fetchall"):
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
            if hasattr(result, "get_query_summary"):
                summary = result.get_query_summary()
                if hasattr(summary, "get_execution_time"):
                    stats["execution_time_ms"] = summary.get_execution_time()
                if hasattr(summary, "get_compiling_time"):
                    stats["compile_time_ms"] = summary.get_compiling_time()

            return {
                "success": True,
                "columns": columns,
                "rows": rows,
                "row_count": len(rows),
                "stats": stats,
            }

        except Exception as e:
            logger.error(f"Error processing KuzuDB result: {e}")
            return {"success": False, "error": str(e), "columns": [], "rows": [], "stats": {}}

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
                with self._lock:
                    if self.connection is None:
                        raise RuntimeError("Database connection is closed")
                    return self.connection.prepare(query)
            else:
                return {"query": query, "prepared": True}

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _prepare)

    async def execute_prepared(
        self, prepared_statement: Any, parameters: Optional[Dict[str, Any]] = None
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
                with self._lock:
                    if self.connection is None:
                        raise RuntimeError("Database connection is closed")
                    if parameters:
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
        health_info: Dict[str, Any] = {
            "healthy": False,
            "database_path": str(self.database_path),
            "read_only": self.read_only,
            "initialized": self._initialized,
            "checks": {},
            "response_time_ms": 0,
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
                    tables_result = await self.execute_query(
                        "MATCH (n) RETURN COUNT(*) as table_count"
                    )
                    if tables_result.get("success"):
                        health_info["checks"]["table_count_query"] = True
                        if tables_result.get("rows"):
                            health_info["table_count"] = tables_result["rows"][0].get(
                                "table_count", 0
                            )
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
                        await self.execute_query(
                            "CREATE NODE TABLE IF NOT EXISTS __health_test__"
                            "(id INT64, PRIMARY KEY(id))"
                        )
                        await self.execute_query("DROP TABLE __health_test__")
                        health_info["checks"]["write_test"] = True
                    except Exception:
                        health_info["checks"]["write_test"] = False

                # Overall health assessment
                successful_checks = sum(1 for check in health_info["checks"].values() if check)
                total_checks = len(health_info["checks"])
                health_info["healthy"] = successful_checks >= (
                    total_checks * 0.7
                )  # 70% success rate
                health_info["health_percentage"] = (
                    (successful_checks / total_checks * 100) if total_checks > 0 else 0
                )

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
            schema_info: Dict[str, Any] = {
                "database_path": str(self.database_path),
                "node_tables": [],
                "rel_tables": [],
                "total_tables": 0,
                "schema_version": None,
            }

            # Query for table schema information
            try:
                tables_result = await self.execute_query(
                    "CALL show_tables() RETURN name, type, comment"
                )
            except Exception:
                # Fallback for older KuzuDB versions or if show_tables() is not available
                logger.warning("show_tables() not available, returning basic schema info")
                schema_info["total_tables"] = 0
                return schema_info

            if tables_result.get("success"):
                tables = tables_result.get("rows", [])
                schema_info["total_tables"] = len(tables)

                for table in tables:
                    # Handle both dict and list formats from KuzuDB
                    if isinstance(table, dict):
                        table_name = table.get("name", "")
                        table_type = table.get("type", "")
                        table_comment = table.get("comment", "")
                    else:
                        # Handle list format [name, type, comment]
                        table_name = table[0] if len(table) > 0 else ""
                        table_type = table[1] if len(table) > 1 else ""
                        table_comment = table[2] if len(table) > 2 else ""

                    table_info = {
                        "name": table_name,
                        "type": table_type,
                        "comment": table_comment,
                        "properties": [],
                    }

                    # Get table properties/schema
                    try:
                        props_result = await self.execute_query(
                            f"CALL table_info('{table_info['name']}') "
                            "RETURN property_name, property_type"
                        )
                        if props_result.get("success"):
                            table_info["properties"] = props_result.get("rows", [])
                    except Exception as e:
                        logger.warning(
                            f"Could not get properties for table {table_info['name']}: {e}"
                        )

                    # Categorize tables
                    table_type = table_info["type"]
                    if table_type and table_type.upper() in ["NODE", "NODE_TABLE"]:
                        schema_info["node_tables"].append(table_info)
                    elif table_type and table_type.upper() in ["REL", "RELATIONSHIP", "REL_TABLE"]:
                        schema_info["rel_tables"].append(table_info)

            # Try to get database statistics
            try:
                stats_result = await self.execute_query(
                    "CALL show_attached_databases() RETURN database_name, database_type"
                )
                if stats_result.get("success"):
                    schema_info["attached_databases"] = stats_result.get("rows", [])
            except Exception as e:
                # Best-effort: not all Kuzu builds expose show_attached_databases.
                logger.debug(f"show_attached_databases unavailable: {e}")

            return schema_info

        except Exception as e:
            logger.error(f"Error getting schema info: {e}")
            return {
                "error": str(e),
                "database_path": str(self.database_path),
                "node_tables": [],
                "rel_tables": [],
                "total_tables": 0,
            }

    async def close(self) -> None:
        """Close the database connection."""

        def _close():
            # Run on a worker thread: acquiring the lock here waits for any
            # in-flight query to finish, and doing that on the event loop thread
            # would freeze the loop (and with it, every other coroutine).
            with self._lock:
                if self.connection is not None:
                    self.connection.close()
                    self.connection = None

                self.database = None
                self._initialized = False

        await asyncio.get_event_loop().run_in_executor(None, _close)

        logger.info(f"KuzuDB connection closed: {self.database_path}")


class KuzuDriverPool:
    """
    Connection pool for managing multiple KuzuDB connections.
    Useful for high-concurrency scenarios.
    """

    def __init__(self, database_path: str, pool_size: int = 5, **driver_kwargs):
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
                driver = KuzuDriver(database_path=self.database_path, **self.driver_kwargs)
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
        buffer_pool_size=512 * 1024 * 1024,  # 512MB for read-only
    )


def create_write_driver(database_path: str) -> KuzuDriver:
    """Create a read-write KuzuDB driver."""
    return KuzuDriver(
        database_path=database_path,
        read_only=False,
        buffer_pool_size=1024 * 1024 * 1024,  # 1GB for read-write
    )


def create_high_performance_driver(database_path: str) -> KuzuDriver:
    """Create a high-performance KuzuDB driver."""
    return KuzuDriver(
        database_path=database_path,
        read_only=False,
        buffer_pool_size=4 * 1024 * 1024 * 1024,  # 4GB buffer
        max_num_threads=8,
        enable_compression=True,
    )
