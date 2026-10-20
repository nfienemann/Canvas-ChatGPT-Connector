"""Scoped repositories shared by the API and worker.

No request sets a database-global tenant variable. Every lookup includes owner
and connection; connection row locks fence every mutation against disconnect.
"""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    select,
    update,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from canvas_bridge.domain import DomainError, opaque_id, utcnow


class Base(DeclarativeBase):
    pass


class PrincipalState(Base):
    __tablename__ = "principal_states"
    owner: Mapped[str] = mapped_column(String(64), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)


class Connection(Base):
    __tablename__ = "connections"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=opaque_id)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    institution: Mapped[str] = mapped_column(String(100))
    canvas_user: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(30), default="active")
    epoch: Mapped[int] = mapped_column(Integer, default=0)
    credential: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(100), default="UTC")
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entitlement_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Owned:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=opaque_id)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("connections.id"), index=True)


class Course(Owned, Base):
    __tablename__ = "courses"
    source_id: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(1000))
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    accessible: Mapped[bool] = mapped_column(Boolean, default=True)
    enrollment_state: Mapped[str] = mapped_column(String(50), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)


class Work(Owned, Base):
    __tablename__ = "work_items"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Snapshot(Owned, Base):
    __tablename__ = "snapshots"
    complete: Mapped[bool] = mapped_column(Boolean)
    course_ids: Mapped[list[str]] = mapped_column(JSON)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    coverage: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LocalRecord(Owned, Base):
    __tablename__ = "local_records"
    kind: Mapped[str] = mapped_column(String(50), index=True)
    key: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Material(Owned, Base):
    __tablename__ = "materials"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    source_id: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(20), default="page", server_default="page")
    title: Mapped[str] = mapped_column(String(1000))
    url: Mapped[str] = mapped_column(Text)
    version_hash: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    locators: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    limitations: Mapped[list[str]] = mapped_column(JSON)
    file_state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, server_default="{}")
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Owned, Base):
    __tablename__ = "jobs"
    kind: Mapped[str] = mapped_column(String(30))
    epoch: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(30), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class OAuthState(Base):
    __tablename__ = "oauth_states"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64))
    institution: Mapped[str] = mapped_column(String(100))
    redirect: Mapped[str] = mapped_column(Text)
    browser_digest: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[str | None] = mapped_column(Text)
    generation: Mapped[int] = mapped_column(Integer, default=0)


class BrowserSession(Base):
    __tablename__ = "browser_sessions"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner: Mapped[str] = mapped_column(String(64))
    credential: Mapped[str] = mapped_column(Text)
    csrf: Mapped[str] = mapped_column(String(100))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    generation: Mapped[int] = mapped_column(Integer, default=0)


class Tombstone(Base):
    __tablename__ = "deletion_tombstones"
    connection_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    epoch: Mapped[int] = mapped_column(Integer)
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


class Store:
    def __init__(self, url: str):
        options: dict[str, Any] = {"pool_pre_ping": True}
        if url.startswith("postgresql"):
            options.update({"connect_args": {"connect_timeout": 5}, "pool_timeout": 5})
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url:
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_fixture_schema(self):
        if self.engine.dialect.name != "sqlite":
            raise RuntimeError("Use Alembic migrations for PostgreSQL.")
        Base.metadata.create_all(self.engine)

    @contextmanager
    def transaction(self):
        with self.sessions.begin() as session:
            yield session

    @staticmethod
    def principal(session: Session, owner: str) -> PrincipalState:
        # Always acquire this lock before any connection/authorization-state lock.
        if session.get_bind().dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        session.execute(
            insert(PrincipalState).values(owner=owner, generation=0).on_conflict_do_nothing()
        )
        return session.scalar(
            select(PrincipalState).where(PrincipalState.owner == owner).with_for_update()
        )

    @staticmethod
    def connection(session: Session, owner: str, ref: str, *, lock: bool = False) -> Connection:
        query = select(Connection).where(Connection.id == ref, Connection.owner == owner)
        if lock:
            query = query.with_for_update()
        row = session.scalar(query)
        if row is None:
            raise DomainError("permission_denied", "Connection unavailable.")
        if row.state != "active" or session.get(Tombstone, ref):
            raise DomainError(
                "reconnect_required", "This connection is disabled. Reconnect in settings."
            )
        return row

    @staticmethod
    def owned(session: Session, cls, owner: str, connection: str, ref: str):
        row = session.scalar(
            select(cls).where(cls.id == ref, cls.owner == owner, cls.connection_id == connection)
        )
        if row is None:
            raise DomainError("permission_denied", "Resource unavailable.")
        return row

    def disconnect(self, owner: str, ref: str) -> dict:
        with self.transaction() as session:
            row = session.scalar(
                select(Connection)
                .where(Connection.id == ref, Connection.owner == owner)
                .with_for_update()
            )
            if row is None:
                raise DomainError("permission_denied", "Connection unavailable.")
            return self.disconnect_in_session(session, row)

    @staticmethod
    def disconnect_in_session(session: Session, row: Connection) -> dict:
        credential, institution = row.credential, row.institution
        if row.state == "active":
            row.epoch += 1
        row.state = "disconnected"
        row.credential = None
        row.canvas_user = ""
        row.entitlement_at = None
        row.last_success = None
        tombstone = session.get(Tombstone, row.id)
        if tombstone is None:
            session.add(Tombstone(connection_id=row.id, epoch=row.epoch))
        for cls in (Job, Material, LocalRecord, Snapshot, Work, Course):
            session.execute(delete(cls).where(cls.owner == row.owner, cls.connection_id == row.id))
        # Return the credential only to the private lifecycle caller, never a tool result.
        return {"credential": credential, "institution": institution, "epoch": row.epoch}

    def save_local(
        self,
        owner: str,
        connection: str,
        kind: str,
        key: str,
        payload: dict,
        expected_version: int,
    ) -> dict:
        with self.transaction() as session:
            self.connection(session, owner, connection, lock=True)
            if kind == "progress":
                work = self.owned(session, Work, owner, connection, key)
                course = self.owned(session, Course, owner, connection, work.course_id)
                if not course.selected or not course.accessible:
                    raise DomainError("permission_denied", "Work is no longer selected.")
            elif kind == "plan":
                snapshot = self.owned(
                    session, Snapshot, owner, connection, payload.get("snapshot_id", "")
                )
                courses = session.scalars(
                    select(Course).where(
                        Course.owner == owner,
                        Course.connection_id == connection,
                        Course.selected.is_(True),
                        Course.accessible.is_(True),
                    )
                ).all()
                if set(snapshot.course_ids) - {c.id for c in courses}:
                    raise DomainError("permission_denied", "Plan is no longer in selected scope.")
            row = session.scalar(
                select(LocalRecord)
                .where(
                    LocalRecord.owner == owner,
                    LocalRecord.connection_id == connection,
                    LocalRecord.kind == kind,
                    LocalRecord.key == key,
                )
                .with_for_update()
            )
            old_version = row.version if row else 0
            if old_version != expected_version:
                raise DomainError(
                    "source_changed", "Saved state changed; read its current version first."
                )
            if row is None:
                row = LocalRecord(
                    owner=owner,
                    connection_id=connection,
                    kind=kind,
                    key=key,
                    version=1,
                    payload=payload,
                )
                session.add(row)
            else:
                row.version += 1
                row.payload = payload
                row.updated_at = utcnow()
            session.flush()
            return {"record_id": row.id, "old_version": old_version, "version": row.version}

    def purge_history(self, days: int = 30) -> int:
        with self.transaction() as session:
            result = session.execute(
                delete(Snapshot).where(Snapshot.created_at < utcnow() - timedelta(days=days))
            )
            session.execute(delete(OAuthState).where(OAuthState.expires_at < utcnow()))
            session.execute(delete(BrowserSession).where(BrowserSession.expires_at < utcnow()))
            return result.rowcount

    def purge_file_cache(self, hours: int = 24) -> int:
        with self.transaction() as session:
            result = session.execute(
                update(Material)
                .where(
                    Material.kind == "file",
                    Material.retrieved_at < utcnow() - timedelta(hours=hours),
                    Material.version_hash != "",
                )
                .values(
                    text="",
                    version_hash="",
                    locators=[],
                    limitations=[],
                    file_state={"stage": "available"},
                )
            )
            return result.rowcount

    def export_connection(self, owner: str, ref: str) -> dict:
        """Export retained records, excluding credentials and authentication secrets."""
        with self.transaction() as session:
            conn = self.connection(session, owner, ref, lock=True)
            records = {}
            for cls in (Course, Work, Snapshot, LocalRecord, Material, Job):
                rows = session.scalars(
                    select(cls).where(cls.owner == owner, cls.connection_id == ref)
                ).all()
                records[cls.__tablename__] = [
                    {
                        column.name: (
                            aware(value).isoformat() if isinstance(value, datetime) else value
                        )
                        for column in cls.__table__.columns
                        if column.name != "owner"
                        for value in [getattr(row, column.name)]
                    }
                    for row in rows
                ]
            return {
                "format": "canvas-bridge-export-2",
                "exported_at": utcnow().isoformat(),
                "connection": {
                    "id": conn.id,
                    "institution": conn.institution,
                    "canvas_user": conn.canvas_user,
                    "timezone": conn.timezone,
                    "state": conn.state,
                    "created_at": aware(conn.created_at).isoformat(),
                },
                "records": records,
                "excluded": [
                    "Credentials, authentication sessions and secret authorization state",
                    "Independent ChatGPT conversations and institution records",
                ],
            }

    @staticmethod
    def purge_courses(session: Session, owner: str, ref: str, course_ids: set[str]):
        """Caller holds the connection lock and persists a restore fence before calling."""
        if not course_ids:
            return
        work_ids = select(Work.id).where(
            Work.owner == owner, Work.connection_id == ref, Work.course_id.in_(course_ids)
        )
        session.execute(
            delete(LocalRecord).where(
                LocalRecord.owner == owner,
                LocalRecord.connection_id == ref,
                (LocalRecord.kind == "plan")
                | ((LocalRecord.kind == "progress") & LocalRecord.key.in_(work_ids)),
            )
        )
        # A snapshot or a saved plan may embed facts from several courses.
        for cls in (Snapshot, Job):
            session.execute(delete(cls).where(cls.owner == owner, cls.connection_id == ref))
        for cls in (Material, Work):
            session.execute(
                delete(cls).where(
                    cls.owner == owner, cls.connection_id == ref, cls.course_id.in_(course_ids)
                )
            )

    def close(self):
        self.engine.dispose()
