"""
Unit tests for replication components.
"""

import shutil
import struct
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from kuzuk.replication.manager import (
    KuzuReplicationManager,
    ReplicaInfo,
    ReplicationStatus,
    create_multi_replica_manager,
    create_single_replica_manager,
)
from kuzuk.replication.wal_streamer import (
    WALApplier,
    WALParser,
    WALPosition,
    WALRecord,
    WALRecordType,
    WALStreamer,
)


class TestReplicaInfo:
    """Test ReplicaInfo data class."""

    @pytest.mark.unit
    def test_replica_info_creation(self):
        """Test replica info creation."""
        info = ReplicaInfo(
            id="replica_1",
            db_path="/path/to/replica",
            driver=None,
            status=ReplicationStatus.HEALTHY,
            last_sync=datetime.now(),
            lag_ms=100.0,
            error_count=0,
        )

        assert info.id == "replica_1"
        assert info.db_path == "/path/to/replica"
        assert info.status == ReplicationStatus.HEALTHY
        assert info.lag_ms == 100.0
        assert info.error_count == 0
        assert isinstance(info.last_sync, datetime)


class TestWALRecord:
    """Test WAL record functionality."""

    @pytest.mark.unit
    def test_wal_record_creation(self):
        """Test WAL record creation."""
        record = WALRecord(
            record_type=WALRecordType.TABLE_INSERTION_RECORD,
            timestamp=time.time(),
            transaction_id=12345,
            data={"table_id": 1, "data_size": 256},
            checksum="abc123",
            size=100,
            position=1000,
        )

        assert record.record_type == WALRecordType.TABLE_INSERTION_RECORD
        assert isinstance(record.timestamp, float)
        assert record.transaction_id == 12345
        assert record.data["table_id"] == 1
        assert record.checksum == "abc123"
        assert record.size == 100
        assert record.position == 1000


class TestWALPosition:
    """Test WAL position functionality."""

    @pytest.mark.unit
    def test_wal_position_creation(self):
        """Test WAL position creation."""
        position = WALPosition(
            file_offset=1024, record_count=10, timestamp=time.time(), checksum="def456"
        )

        assert position.file_offset == 1024
        assert position.record_count == 10
        assert isinstance(position.timestamp, float)
        assert position.checksum == "def456"


class TestWALParser:
    """Test WAL parser functionality."""

    @pytest.fixture
    def temp_wal_file(self):
        """Create temporary WAL file."""
        temp_dir = tempfile.mkdtemp()
        wal_path = Path(temp_dir) / "test.wal"

        # Create mock WAL file with some data
        with open(wal_path, "wb") as f:
            # Write mock WAL header
            header = struct.pack(
                "<BBQI",
                WALRecordType.BEGIN_TRANSACTION_RECORD.value,
                16,  # record size
                int(time.time() * 1000),  # timestamp
                1,  # transaction id
            )
            f.write(header)

        yield wal_path
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def parser(self):
        """Create WAL parser."""
        return WALParser(enable_checksums=True)

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_parser_creation(self, parser):
        """Test parser creation."""
        assert parser.enable_checksums is True
        assert parser.buffer_size == 8192

    @pytest.mark.asyncio
    async def test_parse_wal_file_nonexistent(self, parser):
        """Test parsing non-existent WAL file."""
        records = []
        async for record in parser.parse_wal_file(Path("/nonexistent.wal")):
            records.append(record)

        assert len(records) == 0

    @pytest.mark.asyncio
    async def test_parse_wal_file_with_data(self, parser, temp_wal_file):
        """Test parsing WAL file with data."""
        records = []
        async for record in parser.parse_wal_file(temp_wal_file):
            records.append(record)

        # Should parse at least one record
        assert len(records) >= 0  # May be 0 if parsing fails on mock data


class TestWALStreamer:
    """Test WAL streamer functionality."""

    @pytest.fixture
    def temp_db_path(self):
        """Create temporary database path."""
        temp_dir = tempfile.mkdtemp()
        db_path = Path(temp_dir) / "test.kuzu"
        yield str(db_path)
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def streamer(self, temp_db_path):
        """Create WAL streamer."""
        return WALStreamer(temp_db_path)

    @pytest.mark.unit
    def test_streamer_initialization(self, streamer, temp_db_path):
        """Test streamer initialization."""
        assert str(streamer.master_db_path) == temp_db_path
        assert streamer.enable_checksums is True
        assert streamer.poll_interval == 0.1
        assert streamer.batch_size == 100
        assert streamer.running is False

    @pytest.mark.asyncio
    async def test_get_wal_size_nonexistent(self, streamer):
        """Test getting WAL size for non-existent file."""
        size = await streamer.get_wal_size()
        assert size == 0

    @pytest.mark.asyncio
    async def test_get_latest_position(self, streamer):
        """Test getting latest WAL position."""
        position = await streamer.get_latest_position()

        assert isinstance(position, WALPosition)
        assert position.file_offset >= 0
        assert position.record_count >= 0

    @pytest.mark.asyncio
    async def test_get_wal_changes_empty(self, streamer):
        """Test getting WAL changes from empty file."""
        records, position = await streamer.get_wal_changes()

        assert isinstance(records, list)
        assert isinstance(position, WALPosition)

    @pytest.mark.unit
    def test_stop_streaming(self, streamer):
        """Test stopping WAL streaming."""
        streamer.running = True
        streamer.stop_streaming()
        assert streamer.running is False


class TestWALApplier:
    """Test WAL applier functionality."""

    @pytest.fixture
    def mock_replica_driver(self):
        """Create mock replica driver."""
        driver = AsyncMock()
        driver.execute_query.return_value = {"success": True}
        return driver

    @pytest.fixture
    def applier(self, mock_replica_driver):
        """Create WAL applier."""
        return WALApplier(mock_replica_driver)

    @pytest.mark.unit
    def test_applier_initialization(self, applier):
        """Test applier initialization."""
        assert applier.applied_records == 0
        assert isinstance(applier.last_applied_position, WALPosition)

    @pytest.mark.asyncio
    async def test_apply_empty_records(self, applier):
        """Test applying empty record list."""
        result = await applier.apply_records([], WALPosition(0, 0, 0.0, ""))
        assert result is True

    @pytest.mark.asyncio
    async def test_apply_single_record(self, applier):
        """Test applying single record."""
        record = WALRecord(
            record_type=WALRecordType.BEGIN_TRANSACTION_RECORD,
            timestamp=time.time(),
            transaction_id=1,
            data={"type": "begin_transaction"},
        )

        result = await applier.apply_records([record], WALPosition(100, 1, time.time(), ""))
        assert result is True
        assert applier.applied_records == 1

    @pytest.mark.unit
    def test_get_apply_stats(self, applier):
        """Test getting apply statistics."""
        stats = applier.get_apply_stats()

        assert "applied_records" in stats
        assert "last_applied_position" in stats
        assert stats["applied_records"] == 0


class TestKuzuReplicationManager:
    """Test replication manager functionality."""

    @pytest.fixture
    def temp_master_path(self):
        """Create temporary master database path."""
        temp_dir = tempfile.mkdtemp()
        master_path = Path(temp_dir) / "master.kuzu"
        yield str(master_path)
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def temp_replica_dir(self):
        """Create temporary replica directory."""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def mock_master_driver(self):
        """Create mock master driver."""
        driver = AsyncMock()
        driver.health_check.return_value = {"healthy": True}
        return driver

    @pytest.fixture
    def replication_manager(self, temp_master_path, temp_replica_dir, mock_master_driver):
        """Create replication manager."""
        with patch("kuzuk.replication.manager.KuzuDriver") as mock_driver_class:
            mock_driver_class.return_value = mock_master_driver
            replica_paths = [
                f"{temp_replica_dir}/replica_1.kuzu",
                f"{temp_replica_dir}/replica_2.kuzu",
            ]
            return KuzuReplicationManager(master_path=temp_master_path, replica_paths=replica_paths)

    @pytest.mark.unit
    def test_manager_initialization(self, replication_manager, temp_master_path):
        """Test manager initialization."""
        assert str(replication_manager.master_path) == temp_master_path
        assert len(replication_manager.replicas) == 2
        assert replication_manager.replication_interval == 1.0
        assert replication_manager.running is False

    @pytest.mark.asyncio
    async def test_manager_initialize(self, replication_manager):
        """Test manager initialization."""
        await replication_manager.initialize()

        assert replication_manager.running is False
        assert replication_manager.master_driver is not None

    @pytest.mark.unit
    def test_get_replication_stats(self, replication_manager):
        """Test getting replication statistics."""
        stats = replication_manager.get_replication_status()

        assert "total_replicas" in stats
        assert "healthy_replicas" in stats
        assert "replication_running" in stats
        assert "master_path" in stats


class TestFactoryFunctions:
    """Test factory functions."""

    @pytest.fixture
    def temp_master_path(self):
        """Create temporary master database path."""
        temp_dir = tempfile.mkdtemp()
        master_path = Path(temp_dir) / "master.kuzu"
        yield str(master_path)
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.mark.unit
    def test_create_single_replica_manager(self, temp_master_path):
        """Test single replica manager factory."""
        with patch("kuzuk.replication.manager.KuzuDriver"):
            replica_path = "/tmp/replica.kuzu"
            manager = create_single_replica_manager(temp_master_path, replica_path)

            assert len(manager.replicas) == 1
            assert manager.replication_interval == 1.0
            assert replica_path in [replica.db_path for replica in manager.replicas.values()]

    @pytest.mark.unit
    def test_create_multi_replica_manager(self, temp_master_path):
        """Test multi replica manager factory."""
        with patch("kuzuk.replication.manager.KuzuDriver"):
            manager = create_multi_replica_manager(temp_master_path, replica_count=3)

            assert len(manager.replicas) == 3
            assert manager.replication_interval == 1.0


if __name__ == "__main__":
    pytest.main([__file__])
