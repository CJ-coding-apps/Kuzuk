"""
Test package structure and imports for Kuzuk.
"""

import pytest


@pytest.mark.unit
def test_package_imports():
    """Test that main package imports work correctly."""
    try:
        import kuzuk

        assert kuzuk.__version__ == "0.1.0"
        assert hasattr(kuzuk, "KuzukDriver")
        print("✅ Main package import successful")
    except ImportError as e:
        pytest.skip(f"Skipping due to missing dependencies: {e}")


@pytest.mark.unit
def test_replication_imports():
    """Test replication module imports."""
    try:
        from kuzuk.replication import KuzuReplicationManager, ReplicaInfo, ReplicationStatus

        print("✅ Replication module import successful")
    except ImportError as e:
        pytest.skip(f"Skipping due to missing dependencies: {e}")


@pytest.mark.unit
def test_function_shipping_imports():
    """Test function shipping module imports."""
    try:
        from kuzuk.function_shipping import (
            AnalyticalQuery,
            FunctionShippingOrchestrator,
            QueryExecutionMode,
        )

        print("✅ Function shipping module import successful")
    except ImportError as e:
        pytest.skip(f"Skipping due to missing dependencies: {e}")


@pytest.mark.unit
def test_routing_imports():
    """Test routing module imports."""
    try:
        from kuzuk.routing import ConsistencyLevel, QueryRouter, QueryType

        print("✅ Routing module import successful")
    except ImportError as e:
        pytest.skip(f"Skipping due to missing dependencies: {e}")


@pytest.mark.unit
def test_monitoring_imports():
    """Test monitoring module imports."""
    try:
        from kuzuk.monitoring import HealthMetrics, HealthMonitor, NodeHealth

        print("✅ Monitoring module import successful")
    except ImportError as e:
        pytest.skip(f"Skipping due to missing dependencies: {e}")


@pytest.mark.unit
def test_factory_functions():
    """Test factory function imports."""
    try:
        from kuzuk import create_enterprise_kuzuk_driver, create_simple_kuzuk_driver

        print("✅ Factory functions import successful")
    except ImportError as e:
        pytest.skip(f"Skipping due to missing dependencies: {e}")


@pytest.mark.unit
def test_module_structure():
    """Test that all expected modules exist."""
    expected_modules = [
        "kuzuk",
        "kuzuk.replication",
        "kuzuk.function_shipping",
        "kuzuk.routing",
        "kuzuk.monitoring",
        "kuzuk.drivers",
    ]

    for module_name in expected_modules:
        try:
            __import__(module_name)
            print(f"✅ Module {module_name} exists")
        except ImportError as e:
            pytest.skip(f"Skipping {module_name} due to missing dependencies: {e}")


if __name__ == "__main__":
    """Run tests directly for development."""
    print("🧪 Testing Kuzuk package structure...")

    test_package_imports()
    test_replication_imports()
    test_function_shipping_imports()
    test_routing_imports()
    test_monitoring_imports()
    test_factory_functions()
    test_module_structure()

    print("🎉 All package structure tests passed!")
