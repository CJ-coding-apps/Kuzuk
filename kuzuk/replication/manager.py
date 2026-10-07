"""
KuzuDB Replication Manager for Enhanced RAG 6.2
Implements master-replica pattern with WAL streaming and health monitoring.
"""

import asyncio
import logging
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..drivers.kuzu_wrapper import KuzuDriver
from .wal_streamer import WALApplier, WALPosition, WALStreamer

logger = logging.getLogger(__name__)


class ReplicationStatus(Enum):
    """Replication status states."""

    HEALTHY = "healthy"
    LAGGING = "lagging"
    DISCONNECTED = "disconnected"
    FAILED = "failed"
    INITIALIZING = "initializing"


@dataclass
class ReplicaInfo:
    """Information about a replica node."""

    id: str
    db_path: str
    driver: Optional[KuzuDriver]
    status: ReplicationStatus
    last_sync: datetime
    lag_ms: float
    error_count: int

    def is_healthy(self) -> bool:
        """Check if replica is healthy for serving reads."""
        return (
            self.status == ReplicationStatus.HEALTHY
            and self.lag_ms < 1000  # Less than 1 second lag
            and self.error_count < 5
        )


# WALStreamer is now imported from wal_streamer.py


class KuzuReplicationManager:
    """Manages KuzuDB master-replica replication."""

    def __init__(
        self,
        master_path: str,
        replica_paths: List[str],
        replication_interval: float = 1.0,
        max_lag_seconds: float = 5.0,
    ):
        """
        Initialize replication manager.

        Args:
            master_path: Path to master KuzuDB instance
            replica_paths: List of paths for replica instances
            replication_interval: Seconds between replication checks
            max_lag_seconds: Maximum acceptable replication lag
        """
        self.master_path = Path(master_path)
        self.replication_interval = replication_interval
        self.max_lag_seconds = max_lag_seconds

        # Initialize master
        self.master_driver: Optional[KuzuDriver] = None

        # Initialize replicas
        self.replicas: Dict[str, ReplicaInfo] = {}
        for i, path in enumerate(replica_paths):
            replica_id = f"replica_{i+1}"
            self.replicas[replica_id] = ReplicaInfo(
                id=replica_id,
                db_path=path,
                driver=None,
                status=ReplicationStatus.INITIALIZING,
                last_sync=datetime.now(),
                lag_ms=0.0,
                error_count=0,
            )

        # WAL streaming
        self.wal_streamer = WALStreamer(str(self.master_path))
        self.replication_task: Optional[asyncio.Task] = None
        self.running = False

        # Statistics
        self.stats = {
            "replications_performed": 0,
            "total_replication_time": 0.0,
            "last_replication": None,
            "errors": 0,
        }

        logger.info(
            f"Initialized replication manager: master={master_path}, replicas={len(replica_paths)}"
        )

    async def initialize(self) -> None:
        """Initialize master and replica connections."""
        try:
            # Initialize master
            await self._ensure_directory(self.master_path.parent)
            self.master_driver = KuzuDriver(str(self.master_path))
            logger.info(f"Master initialized: {self.master_path}")

            # Initialize replicas
            for replica in self.replicas.values():
                await self._initialize_replica(replica)

            logger.info("Replication manager initialization complete")

        except Exception as e:
            logger.error(f"Failed to initialize replication manager: {e}")
            raise

    async def _initialize_replica(self, replica: ReplicaInfo) -> None:
        """Initialize a single replica."""
        try:
            replica_path = Path(replica.db_path)
            await self._ensure_directory(replica_path.parent)

            # If replica doesn't exist, create initial copy from master
            if not replica_path.exists() and self.master_path.exists():
                logger.info(f"Creating initial replica copy: {replica.id}")
                await self._create_initial_replica_copy(replica)

            # Initialize driver
            replica.driver = KuzuDriver(replica.db_path)
            replica.status = ReplicationStatus.HEALTHY
            replica.last_sync = datetime.now()

            logger.info(f"Replica initialized: {replica.id}")

        except Exception as e:
            replica.status = ReplicationStatus.FAILED
            replica.error_count += 1
            logger.error(f"Failed to initialize replica {replica.id}: {e}")

    async def _checkpoint_master(self) -> None:
        """Fold the master's write-ahead log into its database file.

        Kùzu keeps recently committed data in ``<database>.wal`` until a
        checkpoint. Copying only the database file copies a database that is
        missing those commits, and copying the file while it is being written
        can copy a torn one. Checkpointing first makes the on-disk database a
        complete, consistent snapshot to copy.
        """
        if not self.master_driver:
            return
        try:
            await self.master_driver.execute_query("CHECKPOINT")
        except Exception as e:
            logger.warning(f"Master CHECKPOINT failed; replicas may lag or be inconsistent: {e}")

    def _copy_database_files(self, source_path: Path, replica_path: Path) -> None:
        """Copy a Kùzu database and its companion WAL onto a replica path."""
        if source_path.is_file():
            shutil.copy2(str(source_path), str(replica_path))

            # The WAL lives beside the database as "<database>.wal". It must be
            # copied with the database, and a stale one left over from a
            # previous pass must not survive under a freshly copied database --
            # replaying it against the new file would corrupt the replica.
            wal_source = Path(str(source_path) + ".wal")
            wal_dest = Path(str(replica_path) + ".wal")
            if wal_source.exists():
                shutil.copy2(str(wal_source), str(wal_dest))
            elif wal_dest.exists():
                wal_dest.unlink()
        elif source_path.is_dir():
            if replica_path.exists():
                shutil.rmtree(str(replica_path))
            shutil.copytree(str(source_path), str(replica_path))

    async def _create_initial_replica_copy(self, replica: ReplicaInfo) -> None:
        """Create initial replica by copying master database."""
        try:
            await self._checkpoint_master()
            self._copy_database_files(self.master_path, Path(replica.db_path))
            logger.info(f"Initial replica copy created: {replica.id}")

        except Exception as e:
            logger.error(f"Failed to create initial replica copy for {replica.id}: {e}")
            raise

    async def start_replication(self) -> None:
        """Start the replication process."""
        if self.running:
            logger.warning("Replication already running")
            return

        self.running = True
        self.replication_task = asyncio.create_task(self._replication_loop())
        logger.info("Replication started")

    async def stop_replication(self) -> None:
        """Stop the replication process."""
        self.running = False
        if self.replication_task:
            self.replication_task.cancel()
            try:
                await self.replication_task
            except asyncio.CancelledError:
                pass
        logger.info("Replication stopped")

    async def _replication_loop(self) -> None:
        """Main replication loop.

        Replication is periodic and full-file: each pass checkpoints the master
        and copies its database file to every replica. Incremental WAL replay is
        not implemented -- Kùzu's write-ahead log is an internal format, not a
        supported streaming interface -- so replicas converge to the master at
        each interval rather than continuously.
        """
        while self.running:
            try:
                start_time = time.time()

                await self._checkpoint_master()
                for replica in self.replicas.values():
                    if replica.status == ReplicationStatus.FAILED:
                        continue
                    await self._replicate_to_replica(
                        replica,
                        [{"type": "snapshot", "source_path": str(self.master_path)}],
                    )
                self.stats["replications_performed"] += 1

                # Update statistics
                replication_time = time.time() - start_time
                self.stats["total_replication_time"] += replication_time
                self.stats["last_replication"] = datetime.now()

                # Health check replicas
                await self._health_check_replicas()

                # Wait for next interval
                await asyncio.sleep(self.replication_interval)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Error in replication loop: {e}")
                self.stats["errors"] += 1
                await asyncio.sleep(self.replication_interval)

    async def _replicate_changes(self, changes: List[Dict[str, Any]]) -> None:
        """Replicate changes to all replicas."""
        if not changes:
            return

        # Replicate to all replicas in parallel
        tasks = []
        for replica in self.replicas.values():
            if replica.status != ReplicationStatus.FAILED:
                task = self._replicate_to_replica(replica, changes)
                tasks.append(task)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            self.stats["replications_performed"] += 1

    async def _replicate_to_replica(
        self, replica: ReplicaInfo, changes: List[Dict[str, Any]]
    ) -> None:
        """Replicate changes to a single replica."""
        try:
            start_time = time.time()

            # Process replication changes
            for change in changes:
                if change["type"] == "snapshot":
                    await self._perform_snapshot_replication(replica, change)
                elif change["type"] == "wal_record":
                    await self._perform_wal_replication(replica, change)
                else:
                    logger.warning(f"Unknown change type: {change['type']}")

            # Update replica status
            replica.last_sync = datetime.now()
            replica.lag_ms = (time.time() - start_time) * 1000
            replica.status = ReplicationStatus.HEALTHY
            replica.error_count = 0

        except Exception as e:
            replica.error_count += 1
            replica.status = ReplicationStatus.FAILED
            logger.error(f"Failed to replicate to {replica.id}: {e}")

    async def _perform_snapshot_replication(
        self, replica: ReplicaInfo, change: Dict[str, Any]
    ) -> None:
        """Perform snapshot replication (full copy)."""
        try:
            # Close replica driver temporarily
            if replica.driver:
                await replica.driver.close()
                replica.driver = None

            # Copy database files
            source_path = Path(change["source_path"])
            replica_path = Path(replica.db_path)
            self._copy_database_files(source_path, replica_path)

            # Reinitialize driver
            replica.driver = KuzuDriver(replica.db_path)

        except Exception as e:
            logger.error(f"Snapshot replication failed for {replica.id}: {e}")
            raise

    async def _perform_wal_replication(self, replica: ReplicaInfo, change: Dict[str, Any]) -> None:
        """Perform WAL record replication."""
        # Not implemented, and deliberately not pretending otherwise: replaying
        # Kùzu's write-ahead log requires its internal record layout, which is
        # not a stable interface. Incremental replication is therefore not
        # offered; the manager converges replicas by snapshot instead.
        raise NotImplementedError(
            "Incremental WAL replication is not implemented; use snapshot replication"
        )

    async def _health_check_replicas(self) -> None:
        """Perform health checks on all replicas."""
        for replica in self.replicas.values():
            try:
                if replica.driver:
                    result = await replica.driver.execute_query("RETURN 1 AS ok")
                    replica.status = (
                        ReplicationStatus.HEALTHY
                        if result.get("success")
                        else ReplicationStatus.DISCONNECTED
                    )
                else:
                    replica.status = ReplicationStatus.DISCONNECTED
            except Exception as e:
                replica.error_count += 1
                replica.status = ReplicationStatus.FAILED
                logger.warning(f"Health check failed for {replica.id}: {e}")

    def get_healthy_replicas(self) -> List[ReplicaInfo]:
        """Get list of healthy replicas for read queries."""
        return [replica for replica in self.replicas.values() if replica.is_healthy()]

    def get_replication_status(self) -> Dict[str, Any]:
        """Get current replication status."""
        healthy_count = len(self.get_healthy_replicas())
        total_count = len(self.replicas)

        return {
            "healthy_replicas": healthy_count,
            "total_replicas": total_count,
            "replication_running": self.running,
            "master_path": str(self.master_path),
            "replicas": {
                replica.id: {
                    "status": replica.status.value,
                    "lag_ms": replica.lag_ms,
                    "last_sync": replica.last_sync.isoformat(),
                    "error_count": replica.error_count,
                }
                for replica in self.replicas.values()
            },
            "stats": self.stats,
        }

    async def _ensure_directory(self, path: Path) -> None:
        """Ensure directory exists."""
        path.mkdir(parents=True, exist_ok=True)

    async def close(self) -> None:
        """Clean up resources."""
        await self.stop_replication()

        # Close master
        if self.master_driver:
            await self.master_driver.close()

        # Close replicas
        for replica in self.replicas.values():
            if replica.driver:
                await replica.driver.close()

        logger.info("Replication manager closed")


# Factory functions for common configurations
def create_single_replica_manager(
    master_path: str, replica_path: str, replication_interval: float = 1.0
) -> KuzuReplicationManager:
    """Create a simple single-replica configuration."""
    return KuzuReplicationManager(
        master_path=master_path,
        replica_paths=[replica_path],
        replication_interval=replication_interval,
    )


def create_multi_replica_manager(
    master_path: str,
    replica_count: int = 2,
    base_replica_dir: str = "/app/data/replicas",
    replication_interval: float = 1.0,
) -> KuzuReplicationManager:
    """Create a multi-replica configuration."""
    replica_paths = [f"{base_replica_dir}/replica_{i+1}.kuzu" for i in range(replica_count)]

    return KuzuReplicationManager(
        master_path=master_path,
        replica_paths=replica_paths,
        replication_interval=replication_interval,
    )
