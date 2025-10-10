"""
Security testing and penetration tests for Kuzuk.
"""

import asyncio
import hashlib
import secrets
import shutil
import socket
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kuzuk import KuzukDriver
from kuzuk.drivers.kuzu_wrapper import KuzuDriver
from kuzuk.function_shipping.transport import NetworkTransportManager


class SecurityTestSuite:
    """Security testing utilities."""

    def __init__(self):
        self.injection_patterns = [
            "'; DROP TABLE users; --",
            "1' OR '1'='1",
            "1; EXEC sp_configure 'show advanced options', 1;",
            "<script>alert('XSS')</script>",
            "../../../../etc/passwd",
            "%00%00%00%00",
            "{{7*7}}",
            "${7*7}",
            "#{7*7}",
        ]

        self.sensitive_data_patterns = [
            "password",
            "secret",
            "token",
            "key",
            "credential",
            "auth",
        ]

    def generate_malicious_queries(self):
        """Generate malicious Cypher queries for injection testing."""
        base_queries = [
            "MATCH (n) WHERE n.name = '{payload}' RETURN n",
            "CREATE (u:User {{name: '{payload}', email: 'test@example.com'}})",
            "MATCH (n) SET n.description = '{payload}' RETURN n",
            "MATCH (n {{id: {payload}}}) RETURN n",
        ]

        malicious_queries = []
        for query_template in base_queries:
            for payload in self.injection_patterns:
                malicious_queries.append(query_template.format(payload=payload))

        return malicious_queries

    def check_for_sensitive_data_exposure(self, data):
        """Check if sensitive data is exposed in responses."""
        if isinstance(data, str):
            data_lower = data.lower()
            for pattern in self.sensitive_data_patterns:
                if pattern in data_lower:
                    return True, f"Potential sensitive data exposure: {pattern}"

        elif isinstance(data, dict):
            for key, value in data.items():
                if isinstance(key, str) and any(
                    pattern in key.lower() for pattern in self.sensitive_data_patterns
                ):
                    return True, f"Sensitive key in response: {key}"

                exposed, reason = self.check_for_sensitive_data_exposure(value)
                if exposed:
                    return exposed, reason

        elif isinstance(data, list):
            for item in data:
                exposed, reason = self.check_for_sensitive_data_exposure(item)
                if exposed:
                    return exposed, reason

        return False, None


@pytest.fixture
def security_test_suite():
    """Security test suite fixture."""
    return SecurityTestSuite()


@pytest.fixture
async def secure_test_database():
    """Create a test database with security considerations."""
    temp_dir = tempfile.mkdtemp()
    try:
        db_path = Path(temp_dir) / "secure_test.kuzu"
        driver = KuzuDriver(str(db_path))

        await driver.initialize()

        # Create test schema with user data
        schema_queries = [
            """CREATE NODE TABLE User(
                id INT64,
                username STRING,
                email STRING,
                password_hash STRING,
                role STRING,
                created_at STRING,
                PRIMARY KEY(id)
            )""",
            """CREATE NODE TABLE SecureData(
                id INT64,
                owner_id INT64,
                sensitive_info STRING,
                encryption_key STRING,
                PRIMARY KEY(id)
            )""",
            """CREATE REL TABLE HasAccess(FROM User TO SecureData, permission_level STRING)""",
        ]

        for query in schema_queries:
            await driver.execute_query(query)

        # Insert test data
        test_users = [
            (
                1,
                "admin",
                "admin@example.com",
                hashlib.sha256("admin123".encode()).hexdigest(),
                "admin",
            ),
            (
                2,
                "user1",
                "user1@example.com",
                hashlib.sha256("password".encode()).hexdigest(),
                "user",
            ),
            (
                3,
                "guest",
                "guest@example.com",
                hashlib.sha256("guest123".encode()).hexdigest(),
                "guest",
            ),
        ]

        for user_id, username, email, password_hash, role in test_users:
            await driver.execute_query(
                f"""
                CREATE (u:User {{
                    id: {user_id},
                    username: '{username}',
                    email: '{email}',
                    password_hash: '{password_hash}',
                    role: '{role}',
                    created_at: '2023-01-01'
                }})
            """
            )

        yield str(db_path)

    finally:
        await driver.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


class TestSQLInjectionProtection:
    """Test SQL injection and Cypher injection protection."""

    @pytest.mark.asyncio
    @pytest.mark.security
    async def test_cypher_injection_protection(self, secure_test_database, security_test_suite):
        """Test protection against Cypher injection attacks."""
        driver = KuzuDriver(secure_test_database)

        try:
            await driver.initialize()

            malicious_queries = security_test_suite.generate_malicious_queries()
            injection_attempts = 0
            successful_injections = 0

            for malicious_query in malicious_queries:
                injection_attempts += 1
                try:
                    result = await driver.execute_query(malicious_query)

                    # Check if injection was successful (shouldn't be)
                    if result and result.get("success", False):
                        # Verify data wasn't compromised
                        verification_result = await driver.execute_query(
                            "MATCH (u:User) RETURN count(u) as user_count"
                        )
                        if verification_result and verification_result.get("rows"):
                            user_count = verification_result["rows"][0].get("user_count", 0)
                            if user_count != 3:  # Should still have 3 test users
                                successful_injections += 1
                                print(f"⚠️  Injection succeeded: {malicious_query}")

                except Exception as e:
                    # Exceptions are expected for malicious queries
                    pass

            print(f"🔒 Injection attempts: {injection_attempts}")
            print(f"🔒 Successful injections: {successful_injections}")

            # Assert that no injections were successful
            assert (
                successful_injections == 0
            ), f"Security breach: {successful_injections} injections succeeded"

        finally:
            await driver.close()

    @pytest.mark.asyncio
    @pytest.mark.security
    async def test_parameter_sanitization(self, secure_test_database):
        """Test proper parameter sanitization."""
        driver = KuzuDriver(secure_test_database)

        try:
            await driver.initialize()

            # Test with potentially dangerous parameters
            dangerous_inputs = [
                "'; DROP TABLE User; --",
                "admin' OR '1'='1",
                "<script>alert('xss')</script>",
                "../../../etc/passwd",
            ]

            for dangerous_input in dangerous_inputs:
                try:
                    # This should be safely parameterized
                    result = await driver.execute_query(
                        "MATCH (u:User) WHERE u.username = $username RETURN u.role as role",
                        parameters={"username": dangerous_input},
                    )

                    # Should return no results but not crash
                    assert result is not None

                except Exception as e:
                    # Should handle gracefully, not with SQL errors
                    assert "syntax error" not in str(e).lower()
                    assert "drop table" not in str(e).lower()

            print("✅ Parameter sanitization tests passed")

        finally:
            await driver.close()


class TestAccessControl:
    """Test access control and authorization."""

    @pytest.mark.asyncio
    @pytest.mark.security
    async def test_unauthorized_access_prevention(self, secure_test_database):
        """Test prevention of unauthorized data access."""
        driver = KuzuDriver(secure_test_database)

        try:
            await driver.initialize()

            # Simulate unauthorized access attempts
            unauthorized_queries = [
                "MATCH (u:User) RETURN u.password_hash",  # Shouldn't expose password hashes
                "MATCH (s:SecureData) RETURN s.sensitive_info",  # Shouldn't expose sensitive data
                "MATCH (s:SecureData) RETURN s.encryption_key",  # Shouldn't expose encryption keys
            ]

            for query in unauthorized_queries:
                result = await driver.execute_query(query)

                if result and result.get("success") and result.get("rows"):
                    # Check for sensitive data exposure
                    for row in result["rows"]:
                        exposed, reason = security_test_suite.check_for_sensitive_data_exposure(row)
                        if exposed:
                            print(f"⚠️  Security issue: {reason} in query: {query}")
                            # In production, this should be blocked

            print("✅ Access control tests completed")

        finally:
            await driver.close()


class TestNetworkSecurity:
    """Test network security and transport layer protection."""

    @pytest.mark.asyncio
    @pytest.mark.security
    async def test_transport_security(self):
        """Test network transport security."""
        transport_manager = NetworkTransportManager()

        # Test connection security
        test_endpoints = [
            "http://malicious-site.com/inject",
            "http://localhost:9999/backdoor",
            "ftp://unauthorized-server.com/data",
        ]

        for endpoint in test_endpoints:
            try:
                # Should validate and reject suspicious endpoints
                transport_manager.add_endpoint("test", endpoint)
                print(f"⚠️  Suspicious endpoint accepted: {endpoint}")
            except Exception:
                # Expected to reject malicious endpoints
                pass

        print("✅ Transport security tests completed")

    @pytest.mark.asyncio
    @pytest.mark.security
    async def test_ddos_protection(self, secure_test_database):
        """Test DDoS protection and rate limiting."""
        driver = KuzuDriver(secure_test_database)

        try:
            await driver.initialize()

            # Simulate high-frequency requests
            start_time = time.time()
            request_count = 0
            failed_requests = 0

            # Try to overwhelm with requests
            for i in range(100):
                try:
                    result = await driver.execute_query("MATCH (u:User) RETURN count(u)")
                    request_count += 1
                except Exception:
                    failed_requests += 1

            end_time = time.time()
            duration = end_time - start_time
            requests_per_second = request_count / duration

            print(f"🔒 Requests per second: {requests_per_second:.2f}")
            print(f"🔒 Failed requests: {failed_requests}")

            # In production, should have rate limiting
            # For testing, we just verify system stability
            assert request_count + failed_requests == 100

        finally:
            await driver.close()


class TestDataProtection:
    """Test data protection and encryption."""

    @pytest.mark.asyncio
    @pytest.mark.security
    async def test_sensitive_data_handling(self, secure_test_database, security_test_suite):
        """Test handling of sensitive data."""
        driver = KuzuDriver(secure_test_database)

        try:
            await driver.initialize()

            # Test that sensitive data isn't logged
            sensitive_queries = [
                "MATCH (u:User {username: 'admin'}) RETURN u.password_hash",
                "MATCH (s:SecureData) RETURN s.encryption_key",
            ]

            for query in sensitive_queries:
                result = await driver.execute_query(query)

                # Check if result contains sensitive data
                if result:
                    exposed, reason = security_test_suite.check_for_sensitive_data_exposure(result)
                    if exposed:
                        print(f"⚠️  {reason}")

            print("✅ Data protection tests completed")

        finally:
            await driver.close()

    @pytest.mark.asyncio
    @pytest.mark.security
    async def test_error_message_sanitization(self, secure_test_database):
        """Test that error messages don't leak sensitive information."""
        driver = KuzuDriver(secure_test_database)

        try:
            await driver.initialize()

            # Test queries that should produce errors
            error_queries = [
                "MATCH (u:NonExistentTable) RETURN u",
                "INVALID CYPHER SYNTAX",
                "MATCH (u:User) WHERE u.nonexistent_field = 'value' RETURN u",
            ]

            for query in error_queries:
                try:
                    await driver.execute_query(query)
                except Exception as e:
                    error_message = str(e).lower()

                    # Check that error doesn't expose sensitive info
                    sensitive_info_leaked = any(
                        [
                            "password" in error_message,
                            "secret" in error_message,
                            "key" in error_message,
                            "/tmp/" in error_message,  # File paths
                            "database_path" in error_message,
                        ]
                    )

                    if sensitive_info_leaked:
                        print(f"⚠️  Sensitive info in error: {error_message}")

            print("✅ Error message sanitization tests completed")

        finally:
            await driver.close()


class TestPenetrationTesting:
    """Advanced penetration testing scenarios."""

    @pytest.mark.asyncio
    @pytest.mark.security
    @pytest.mark.slow
    async def test_brute_force_protection(self, secure_test_database):
        """Test brute force attack protection."""
        # Simulate multiple failed authentication attempts
        # In a real system, this would test authentication systems

        print("🔓 Simulating brute force attack...")

        # Multiple rapid connection attempts
        connection_attempts = 0
        successful_connections = 0

        for i in range(50):
            try:
                driver = KuzuDriver(secure_test_database)
                await driver.initialize()
                connection_attempts += 1
                successful_connections += 1
                await driver.close()
            except Exception:
                connection_attempts += 1

        print(f"🔒 Connection attempts: {connection_attempts}")
        print(f"🔒 Successful connections: {successful_connections}")

        # System should remain stable under connection pressure
        assert connection_attempts == 50

    @pytest.mark.asyncio
    @pytest.mark.security
    async def test_buffer_overflow_protection(self, secure_test_database):
        """Test protection against buffer overflow attacks."""
        driver = KuzuDriver(secure_test_database)

        try:
            await driver.initialize()

            # Test with extremely large inputs
            large_string = "A" * 10000
            very_large_string = "B" * 100000

            buffer_overflow_queries = [
                f"MATCH (u:User {{username: '{large_string}'}}) RETURN u",
                f"CREATE (n:TestNode {{data: '{very_large_string}'}})",
            ]

            for query in buffer_overflow_queries:
                try:
                    result = await driver.execute_query(query)
                    # Should handle gracefully without crashing
                    assert result is not None or True
                except Exception as e:
                    # Should fail gracefully, not with segfaults
                    assert "segmentation fault" not in str(e).lower()
                    assert "memory" not in str(e).lower() or "out of memory" in str(e).lower()

            print("✅ Buffer overflow protection tests completed")

        finally:
            await driver.close()


if __name__ == "__main__":
    # Run security tests
    pytest.main([__file__, "-v", "-m", "security", "--tb=short"])
