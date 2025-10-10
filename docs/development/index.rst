Developer Guide
===============

Welcome to the Kuzuk developer documentation. This section provides comprehensive information for developers who want to understand, contribute to, or extend Kuzuk.

.. toctree::
   :maxdepth: 2
   :caption: Developer Documentation

   architecture
   contributing
   testing
   releasing

Overview
--------

Kuzuk is built with modern Python async/await patterns and designed for enterprise production environments. The codebase follows established architectural patterns while providing the flexibility needed for scaling KuzuDB in diverse deployment scenarios.

Key Technologies
----------------

**Core Technologies**
   * **Python 3.8+**: Modern async/await patterns with asyncio
   * **KuzuDB**: High-performance graph database engine
   * **Docker**: Containerization and development environment
   * **Kubernetes**: Container orchestration and scaling

**Enterprise Integration**
   * **Prometheus**: Metrics collection and monitoring
   * **Grafana**: Visualization and dashboards
   * **Kubernetes Operator**: Native Kubernetes management
   * **CI/CD**: GitHub Actions with comprehensive testing

**Testing and Quality**
   * **pytest**: Comprehensive test suite with async support
   * **Docker Compose**: Integration testing environment
   * **Security Scanning**: Bandit and Trivy for vulnerability detection
   * **Performance Testing**: Load testing and benchmarking

Development Setup
-----------------

Quick Start
^^^^^^^^^^^

1. **Clone the Repository**::

    git clone https://github.com/your-org/kuzuk-01.git
    cd kuzuk-01

2. **Set Up Development Environment**::

    # Using Docker (recommended)
    docker-compose up dev
    
    # Or using local Python environment
    pip install -e ".[dev]"

3. **Run Tests**::

    # All tests
    docker-compose up kuzuk-test
    
    # Unit tests only
    docker-compose up unit-tests
    
    # Integration tests
    docker-compose up integration-tests

4. **Verify Setup**::

    docker-compose up verify-setup

Development Workflow
^^^^^^^^^^^^^^^^^^^^

1. **Create Feature Branch**::

    git checkout -b feature/your-feature-name

2. **Develop and Test**::

    # Run tests continuously during development
    docker-compose up unit-tests
    
    # Test specific functionality
    python -m pytest tests/unit/test_specific_module.py -v

3. **Quality Checks**::

    # Run all quality checks
    python -m pytest tests/ --cov=kuzuk --cov-report=html
    python -m bandit -r kuzuk/
    python -m mypy kuzuk/

4. **Integration Testing**::

    # Full integration test suite
    docker-compose up integration-tests
    
    # Performance validation
    docker-compose up performance-tests

5. **Submit Pull Request**::

    git push origin feature/your-feature-name
    # Create PR through GitHub interface

Code Organization
-----------------

Project Structure
^^^^^^^^^^^^^^^^^

.. code-block:: text

    kuzuk-01/
    ├── kuzuk/           # Main package
    │   ├── drivers/            # Database drivers and wrappers
    │   ├── scaling/            # Scaling and replica management
    │   ├── replication/        # WAL streaming and replication
    │   ├── function_shipping/  # Distributed query execution
    │   ├── monitoring/         # Health monitoring and metrics
    │   └── utils/              # Common utilities
    ├── tests/                  # Comprehensive test suite
    │   ├── unit/               # Unit tests
    │   ├── integration/        # Integration tests
    │   └── performance/        # Performance and load tests
    ├── k8s/                    # Kubernetes deployments
    │   ├── operator/           # Kubernetes operator
    │   ├── monitoring/         # Monitoring stack
    │   └── examples/           # Deployment examples
    ├── docs/                   # Documentation
    ├── examples/               # Usage examples
    └── .github/                # CI/CD workflows

Package Architecture
^^^^^^^^^^^^^^^^^^^^

**kuzuk.drivers**
   Core database connectivity and wrapper functionality

**kuzuk.scaling**
   Horizontal scaling logic and replica management

**kuzuk.replication**
   WAL streaming and data replication between master and replicas

**kuzuk.function_shipping**
   Distributed query execution and result aggregation

**kuzuk.monitoring**
   Health monitoring, metrics collection, and alerting

**kuzuk.utils**
   Common utilities and helper functions

Coding Standards
----------------

Python Style Guide
^^^^^^^^^^^^^^^^^^

Kuzuk follows PEP 8 with these specific guidelines:

* **Line Length**: 88 characters (Black formatter standard)
* **Import Organization**: isort with Black compatibility
* **Type Hints**: Required for all public APIs
* **Docstrings**: Google-style docstrings for all public methods
* **Async/Await**: Preferred over callbacks for asynchronous operations

Example:

.. code-block:: python

    from typing import Dict, List, Optional, Any
    import asyncio
    
    class ExampleClass:
        """Example class demonstrating coding standards.
        
        Args:
            config: Configuration dictionary
            timeout: Optional timeout in seconds
        """
        
        def __init__(self, config: Dict[str, Any], timeout: Optional[float] = None):
            self._config = config
            self._timeout = timeout or 30.0
        
        async def process_data(self, data: List[str]) -> Dict[str, Any]:
            """Process data asynchronously.
            
            Args:
                data: List of data items to process
                
            Returns:
                Processing results with status and metrics
                
            Raises:
                ValueError: If data format is invalid
                TimeoutError: If processing exceeds timeout
            """
            # Implementation here
            pass

Error Handling
^^^^^^^^^^^^^^

* **Exception Hierarchy**: Use specific exception types
* **Error Context**: Provide meaningful error messages
* **Logging**: Use structured logging with appropriate levels
* **Recovery**: Implement graceful degradation where possible

.. code-block:: python

    import logging
    from typing import Optional
    
    logger = logging.getLogger(__name__)
    
    class KuzukError(Exception):
        """Base exception for Kuzuk operations."""
        pass
    
    class ReplicationError(KuzukError):
        """Raised when replication operations fail."""
        pass
    
    async def example_operation() -> Optional[str]:
        """Example with proper error handling."""
        try:
            result = await risky_operation()
            logger.info("Operation completed successfully", extra={"result_size": len(result)})
            return result
        except SpecificError as e:
            logger.warning("Specific error occurred", extra={"error": str(e)})
            # Attempt recovery
            return await fallback_operation()
        except Exception as e:
            logger.error("Unexpected error in operation", extra={"error": str(e)}, exc_info=True)
            raise KuzukError(f"Operation failed: {e}") from e

Testing Guidelines
------------------

Test Organization
^^^^^^^^^^^^^^^^^

* **Unit Tests**: Test individual components in isolation
* **Integration Tests**: Test component interactions
* **Performance Tests**: Validate performance characteristics
* **Security Tests**: Verify security controls and measures

Test Structure
^^^^^^^^^^^^^^

.. code-block:: python

    import pytest
    import asyncio
    from unittest.mock import AsyncMock, MagicMock
    
    from kuzuk.drivers.kuzu_wrapper import KuzuWrapper
    
    class TestKuzuWrapper:
        """Test suite for KuzuWrapper class."""
        
        @pytest.fixture
        def mock_database(self):
            """Mock KuzuDB database for testing."""
            mock_db = MagicMock()
            mock_connection = AsyncMock()
            mock_db.connection.return_value = mock_connection
            return mock_db, mock_connection
        
        @pytest.mark.asyncio
        async def test_successful_query_execution(self, mock_database):
            """Test successful query execution."""
            mock_db, mock_conn = mock_database
            wrapper = KuzuWrapper("/tmp/test.db")
            wrapper.database = mock_db
            wrapper.connection = mock_conn
            
            # Configure mock response
            mock_conn.execute.return_value.fetchall.return_value = [{"count": 42}]
            
            # Execute test
            result = await wrapper.execute_query("MATCH (n) RETURN count(n)")
            
            # Verify results
            assert result["status"] == "success"
            assert result["data"][0]["count"] == 42
            mock_conn.execute.assert_called_once_with("MATCH (n) RETURN count(n)")
        
        @pytest.mark.asyncio
        async def test_query_execution_with_error(self, mock_database):
            """Test query execution error handling."""
            mock_db, mock_conn = mock_database
            wrapper = KuzuWrapper("/tmp/test.db")
            wrapper.database = mock_db
            wrapper.connection = mock_conn
            
            # Configure mock to raise exception
            mock_conn.execute.side_effect = Exception("Database error")
            
            # Execute test and verify exception handling
            with pytest.raises(Exception, match="Database error"):
                await wrapper.execute_query("INVALID QUERY")

Performance Testing
^^^^^^^^^^^^^^^^^^^

Performance tests validate system behavior under load:

.. code-block:: python

    import time
    import asyncio
    import pytest
    from kuzuk.scaling.driver import KuzukDriver
    
    class TestPerformance:
        """Performance test suite."""
        
        @pytest.mark.performance
        @pytest.mark.asyncio
        async def test_concurrent_query_performance(self):
            """Test concurrent query execution performance."""
            driver = KuzukDriver("/tmp/perf_test.db", replica_count=3)
            
            async def execute_query():
                start_time = time.time()
                result = await driver.execute_query("MATCH (n) RETURN count(n)")
                return time.time() - start_time
            
            # Execute 100 concurrent queries
            tasks = [execute_query() for _ in range(100)]
            response_times = await asyncio.gather(*tasks)
            
            # Performance assertions
            avg_response_time = sum(response_times) / len(response_times)
            max_response_time = max(response_times)
            
            assert avg_response_time < 0.1, f"Average response time too high: {avg_response_time}s"
            assert max_response_time < 1.0, f"Max response time too high: {max_response_time}s"
            assert len([t for t in response_times if t < 0.05]) >= 80, "80% of queries should complete in <50ms"

Contributing Guidelines
-----------------------

Pull Request Process
^^^^^^^^^^^^^^^^^^^^

1. **Fork and Clone**: Fork the repository and clone locally
2. **Create Branch**: Create a feature branch from main
3. **Develop**: Implement your feature with tests
4. **Test**: Run the full test suite
5. **Document**: Update documentation as needed
6. **Submit**: Create a pull request with clear description

Pull Request Requirements
^^^^^^^^^^^^^^^^^^^^^^^^

* **Tests**: All new code must have corresponding tests
* **Documentation**: Public APIs must be documented
* **Backwards Compatibility**: Maintain API compatibility
* **Security**: No security vulnerabilities introduced
* **Performance**: No significant performance regressions

Code Review Checklist
^^^^^^^^^^^^^^^^^^^^^

**Functionality**
   ✓ Code solves the intended problem
   ✓ Edge cases are handled appropriately
   ✓ Error conditions are managed correctly

**Quality**
   ✓ Code follows project style guidelines
   ✓ Complex logic is well-commented
   ✓ No obvious performance issues

**Testing**
   ✓ Comprehensive test coverage
   ✓ Tests are meaningful and thorough
   ✓ Integration tests cover key workflows

**Documentation**
   ✓ Public APIs are documented
   ✓ Complex algorithms are explained
   ✓ Breaking changes are noted

Release Process
---------------

Version Management
^^^^^^^^^^^^^^^^^

Kuzuk uses semantic versioning (MAJOR.MINOR.PATCH):

* **MAJOR**: Breaking API changes
* **MINOR**: New features, backwards compatible
* **PATCH**: Bug fixes, backwards compatible

Release Workflow
^^^^^^^^^^^^^^^

1. **Prepare Release**
   * Update version numbers
   * Update CHANGELOG.md
   * Run full test suite

2. **Create Release**
   * Tag release in Git
   * Build and publish packages
   * Deploy documentation

3. **Post-Release**
   * Monitor for issues
   * Address critical bugs
   * Plan next release

Getting Help
------------

* **Documentation**: Start with this comprehensive documentation
* **Issues**: Report bugs and request features on GitHub
* **Discussions**: Join community discussions for questions
* **Security**: Report security issues privately to maintainers

Contributing to Kuzuk helps build a robust, enterprise-ready database scaling solution. We welcome contributions of all sizes, from bug fixes to new features to documentation improvements.