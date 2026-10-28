"""Leased database queue; refresh is explicit and opt-in, never implied by a read."""

import asyncio
from contextlib import suppress
from datetime import timedelta

from sqlalchemy import or_, select

from canvas_bridge.domain import DomainError, utcnow
from canvas_bridge.storage import Connection, Job, Tombstone


def enqueue_refresh(bridge, owner: str, connection: str) -> str:
    with bridge.store.transaction() as session:
        conn = bridge.store.connection(session, owner, connection, lock=True)
        existing = session.scalar(
            select(Job).where(
                Job.owner == owner,
                Job.connection_id == connection,
                Job.kind == "refresh",
                Job.state.in_(["pending", "running"]),
            )
        )
        if existing:
            return existing.id
        job = Job(
            owner=owner,
            connection_id=connection,
            epoch=conn.epoch,
            kind="refresh",
            payload={},
            state="pending",
        )
        session.add(job)
        session.flush()
        return job.id


def claim(bridge) -> Job | None:
    with bridge.store.transaction() as session:
        job = session.scalar(
            select(Job)
            .where(
                Job.available_at <= utcnow(),
                Job.attempts < 3,
                or_(
                    Job.state == "pending", (Job.state == "running") & (Job.lease_until < utcnow())
                ),
            )
            .order_by(Job.available_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return None
        conn = session.scalar(
            select(Connection).where(
                Connection.id == job.connection_id,
                Connection.owner == job.owner,
            )
        )
        if (
            not conn
            or conn.state != "active"
            or conn.epoch != job.epoch
            or session.get(Tombstone, job.connection_id)
        ):
            job.state = "cancelled"
            return None
        job.state = "running"
        job.attempts += 1
        job.lease_until = utcnow() + timedelta(seconds=60)
        return job


async def work_once(bridge) -> bool:
    job = claim(bridge)
    if job is None:
        return False
    success = False
    try:
        if job.kind == "refresh":
            task = asyncio.create_task(bridge.refresh(job.owner, job.connection_id))
            try:
                while not task.done():
                    await asyncio.wait({task}, timeout=0.1)
                    with bridge.store.transaction() as session:
                        conn = session.get(Connection, job.connection_id)
                        current = session.get(Job, job.id)
                        if (
                            not conn
                            or not current
                            or conn.state != "active"
                            or conn.epoch != job.epoch
                        ):
                            raise DomainError(
                                "permission_denied", "Pending job authorization was revoked."
                            )
                snapshot = await task
            finally:
                if not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError, DomainError):
                    await task
            success = snapshot.complete
    except DomainError:
        pass
    with bridge.store.transaction() as session:
        current = session.get(Job, job.id)
        # A disconnect can remove the job while the request is in flight.
        if current is None or current.attempts != job.attempts:
            return True
        conn = session.get(Connection, job.connection_id)
        if not conn or conn.state != "active" or conn.epoch != job.epoch:
            current.state = "cancelled"
        else:
            current.state = (
                "succeeded" if success else ("failed" if current.attempts >= 3 else "pending")
            )
            current.available_at = utcnow() + timedelta(seconds=2**current.attempts)
        current.lease_until = None
    return True


async def worker(bridge):
    while True:
        await work_once(bridge)
        await bridge.retention.sweep()
        await asyncio.sleep(5)
