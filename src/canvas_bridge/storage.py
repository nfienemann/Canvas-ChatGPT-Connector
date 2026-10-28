"""Scoped repositories shared by the API and worker.

No request sets a database-global tenant variable. Every lookup includes owner
and connection; connection row locks fence every mutation against disconnect.
"""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    event,
    select,
    update,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
    with_loader_criteria,
)
from sqlalchemy.pool import StaticPool

from canvas_bridge.domain import DomainError, opaque_id, utcnow
from canvas_bridge.retention_policy import (
    ANALYSIS_LIFETIME,
    CONNECTION_LIFETIME,
    RAW_FILE_LIFETIME,
    RAW_PAGE_LIFETIME,
)
from canvas_bridge.storage_crypto import Protected


class Base(DeclarativeBase):
    pass


class PrincipalState(Base):
    __tablename__ = "principal_states"
    owner: Mapped[str] = mapped_column(String(64), primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, default=0)
    tokens_valid_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IndependentResource(Base):
    __tablename__ = "independent_resources"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=opaque_id)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    version_hash: Mapped[str] = mapped_column(String(64), index=True)
    provenance: Mapped[dict] = mapped_column(
        Protected("independent_resources.provenance", academic=True)
    )
    content: Mapped[dict] = mapped_column(Protected("independent_resources.content", academic=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeploymentState(Base):
    __tablename__ = "deployment_state"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class Connection(Base):
    __tablename__ = "connections"
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=opaque_id)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    institution: Mapped[str] = mapped_column(String(100))
    canvas_user: Mapped[str] = mapped_column(Protected("connections.canvas_user"))
    state: Mapped[str] = mapped_column(String(30), default="active")
    authentication_state: Mapped[str] = mapped_column(String(30), default="unverified")
    epoch: Mapped[int] = mapped_column(Integer, default=0)
    credential: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(Protected("connections.timezone"), default="UTC")
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entitlement_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Owned:
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=opaque_id)
    owner: Mapped[str] = mapped_column(String(64), index=True)
    connection_id: Mapped[str] = mapped_column(ForeignKey("connections.id"), index=True)


class Course(Owned, Base):
    __tablename__ = "courses"
    source_id: Mapped[str] = mapped_column(Protected("courses.source_id"))
    name: Mapped[str] = mapped_column(Protected("courses.name"))
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    accessible: Mapped[bool] = mapped_column(Boolean, default=True)
    enrollment_state: Mapped[str] = mapped_column(String(50), default="active")
    version: Mapped[int] = mapped_column(Integer, default=1)


class Work(Owned, Base):
    __tablename__ = "work_items"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    source_id: Mapped[str] = mapped_column(Protected("work_items.source_id"))
    payload: Mapped[dict[str, Any]] = mapped_column(Protected("work_items.payload", academic=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Snapshot(Owned, Base):
    __tablename__ = "snapshots"
    complete: Mapped[bool] = mapped_column(Boolean)
    course_ids: Mapped[list[str]] = mapped_column(Protected("snapshots.course_ids", academic=True))
    items: Mapped[list[dict[str, Any]]] = mapped_column(Protected("snapshots.items", academic=True))
    coverage: Mapped[list[dict[str, Any]]] = mapped_column(
        Protected("snapshots.coverage", academic=True)
    )
    workload_scope: Mapped[dict[str, Any]] = mapped_column(
        Protected("snapshots.workload_scope", academic=True), default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LocalRecord(Owned, Base):
    __tablename__ = "local_records"
    kind: Mapped[str] = mapped_column(String(50), index=True)
    key: Mapped[str] = mapped_column(String(100))
    version: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(
        Protected("local_records.payload", academic=True)
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Material(Owned, Base):
    __tablename__ = "materials"
    course_id: Mapped[str] = mapped_column(ForeignKey("courses.id"), index=True)
    source_id: Mapped[str] = mapped_column(Protected("materials.source_id"))
    kind: Mapped[str] = mapped_column(String(20), default="page", server_default="page")
    title: Mapped[str] = mapped_column(Protected("materials.title"))
    url: Mapped[str] = mapped_column(Protected("materials.url"))
    version_hash: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Protected("materials.text"))
    locators: Mapped[list[dict[str, Any]]] = mapped_column(
        Protected("materials.locators", academic=True)
    )
    limitations: Mapped[list[str]] = mapped_column(
        Protected("materials.limitations", academic=True)
    )
    file_state: Mapped[dict[str, Any]] = mapped_column(
        Protected("materials.file_state", academic=True), default=dict
    )
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Owned, Base):
    __tablename__ = "jobs"
    kind: Mapped[str] = mapped_column(String(30))
    epoch: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(30), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payload: Mapped[dict[str, Any]] = mapped_column(
        Protected("jobs.payload", academic=True), default=dict
    )


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
    csrf: Mapped[str] = mapped_column(Protected("browser_sessions.csrf"))
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
        options: dict[str, Any] = {"pool_pre_ping": True, "hide_parameters": True}
        if url.startswith("postgresql"):
            options.update({"connect_args": {"connect_timeout": 5}, "pool_timeout": 5})
        if url.startswith("sqlite"):
            options["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url:
                options["poolclass"] = StaticPool
        self.engine = create_engine(url, **options)
        self.now = utcnow
        self.raw_file_lifetime = lambda: RAW_FILE_LIFETIME
        self.engine.dialect.bridge_clock = lambda: self.now()
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        event.listen(self.sessions, "do_orm_execute", self._retention_filter)
        event.listen(self.sessions, "before_flush", self._remember_materials)

    def _remember_materials(self, session, *unused):
        from sqlalchemy import inspect

        for row in session.new | session.dirty | session.deleted:
            if isinstance(row, Material):
                versions = [row.version_hash, *inspect(row).attrs.version_hash.history.deleted]
                for version in versions:
                    self._remember_digest(session, row.owner, version)

    def _remember_digest(self, session, owner, version):
        import hashlib

        if not owner or not version or len(version) != 64:
            return
        if self.engine.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        session.execute(
            insert(IndependentResource)
            .values(
                id=hashlib.sha256((owner + ":institutional:" + version).encode()).hexdigest(),
                owner=owner,
                kind="institutional_lineage",
                version_hash=version,
                provenance={"source_type": "institutional", "origin": "owned_provider_material"},
                content={},
                created_at=self.now(),
                expires_at=self.now() + timedelta(days=91),
            )
            .on_conflict_do_nothing()
        )

    def _retention_filter(self, state):
        if (
            (state.is_update or state.is_delete)
            and getattr(state.statement, "table", None) is not None
            and state.statement.table.name == "materials"
        ):
            # Bulk cache clearing and scope deletion must retain content restrictions.
            for owner, version in state.session.execute(
                select(Material.owner, Material.version_hash).where(Material.version_hash != "")
            ):
                self._remember_digest(state.session, owner, version)
        if state.is_select and not state.execution_options.get("retention_admin"):
            cutoff = self.now() - ANALYSIS_LIFETIME
            state.statement = state.statement.options(
                with_loader_criteria(Work, Work.observed_at > cutoff),
                with_loader_criteria(Snapshot, Snapshot.created_at > cutoff),
                with_loader_criteria(LocalRecord, LocalRecord.updated_at > cutoff),
            )

    def protect(self, vault):
        self.engine.dialect.bridge_vault = vault

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
            raise DomainError(
                "permission_denied",
                "Connection unavailable.",
                reason_code="CONNECTION_OWNERSHIP_MISMATCH",
            )
        if row.state != "active" or session.get(Tombstone, ref):
            raise DomainError(
                "reconnect_required",
                "This connection is disabled. Reconnect in settings.",
                reason_code="CONNECTION_INACTIVE",
            )
        clock = getattr(session.get_bind().dialect, "bridge_clock", utcnow)
        if aware(row.created_at) + CONNECTION_LIFETIME <= clock():
            raise DomainError(
                "reconnect_required",
                "This connection reached its retention limit. Reconnect explicitly.",
                reason_code="CONNECTION_INACTIVE",
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
            self.principal(session, owner)
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
        from canvas_bridge.processes.purge import purge_sources

        purge_sources(session, row.owner, connection=row.id)
        credential, institution = row.credential, row.institution
        if row.state == "active":
            row.epoch += 1
        row.state = "disconnected"
        row.authentication_state = "revoked"
        row.credential = None
        row.token_expires_at = None
        row.refresh_lease_until = None
        row.canvas_user = ""
        row.entitlement_at = None
        row.last_success = None
        tombstone = session.get(Tombstone, row.id)
        if tombstone is None:
            session.add(
                Tombstone(
                    connection_id=row.id,
                    epoch=row.epoch,
                    deleted_at=session.get_bind().dialect.bridge_clock(),
                )
            )
        counts = {}
        for cls in (Job, Material, LocalRecord, Snapshot, Work, Course):
            counts[cls.__tablename__] = session.execute(
                delete(cls).where(cls.owner == row.owner, cls.connection_id == row.id)
            ).rowcount
        # Return the credential only to the private lifecycle caller, never a tool result.
        return {
            "credential": credential,
            "institution": institution,
            "epoch": row.epoch,
            "deleted_rows": counts,
        }

    def save_local(
        self,
        owner: str,
        connection: str,
        kind: str,
        key: str,
        payload: dict,
        expected_version: int,
        *,
        expected_epoch: int | None = None,
    ) -> dict:
        with self.transaction() as session:
            if kind == "preferences" and key == "default":
                from canvas_bridge.source_authorization import LocalPreferences

                try:
                    payload = LocalPreferences.model_validate(payload).validated()
                except ValidationError:
                    # Pydantic details may echo rejected input, including secrets.
                    raise DomainError(
                        "needs_input", "Local preference fields are invalid."
                    ) from None
                from canvas_bridge.evidence import fingerprint

                payload = {
                    **payload,
                    "_provenance": {
                        "source_category": "user_manual",
                        "owner": owner,
                        "parents": [],
                        "acquisition_mechanism": "authenticated_explicit_preferences",
                        "content_hash": fingerprint(payload),
                        "permitted_operations": ["preferences"],
                    },
                }
                conn = session.scalar(
                    select(Connection)
                    .where(Connection.id == connection, Connection.owner == owner)
                    .with_for_update()
                )
                if conn is None:
                    raise DomainError(
                        "permission_denied", "Local preference namespace is unavailable."
                    )
            else:
                conn = self.connection(session, owner, connection, lock=True)
            if expected_epoch is not None and conn.epoch != expected_epoch:
                raise DomainError("source_changed", "Course scope changed before state was saved.")
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
                if cls is Material:
                    for row, exported in zip(rows, records[cls.__tablename__], strict=True):
                        lifetime = (
                            self.raw_file_lifetime() if row.kind == "file" else RAW_PAGE_LIFETIME
                        )
                        if aware(row.retrieved_at) + lifetime <= self.now():
                            exported.update(
                                text="",
                                locators=[],
                                limitations=[],
                                version_hash="",
                                file_state={"stage": "available"},
                            )
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
                (LocalRecord.kind.in_({"plan", "semester_state"}))
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
