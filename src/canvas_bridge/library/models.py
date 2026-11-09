"""Separate metadata keeps library bytes out of legacy logical backups."""

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from canvas_bridge.domain import opaque_id, utcnow
from canvas_bridge.storage_crypto import Protected


class Base(DeclarativeBase):
    pass


class Admission(Base):
    __tablename__ = "library_admission"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)


class Account(Base):
    __tablename__ = "library_accounts"
    __table_args__ = (
        CheckConstraint(
            "committed >= 0 AND reserved >= 0 AND slots >= 0 AND reserved_slots >= 0 AND derived_bytes >= 0",
            name="library_nonnegative_accounting",
        ),
    )
    owner: Mapped[str] = mapped_column(String(64), primary_key=True)
    state: Mapped[str] = mapped_column(String(24), default="active")
    generation: Mapped[int] = mapped_column(Integer, default=0)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    committed: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved: Mapped[int] = mapped_column(BigInteger, default=0)
    slots: Mapped[int] = mapped_column(Integer, default=0)
    reserved_slots: Mapped[int] = mapped_column(Integer, default=0)
    derived_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    heavy_key: Mapped[str | None] = mapped_column(String(64))
    heavy_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Owned:
    owner: Mapped[str] = mapped_column(String(64), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=opaque_id)


class OperationLease(Owned, Base):
    """Short-lived capacity reservations; an initial upload may precede Account."""

    __tablename__ = "library_operation_leases"
    kind: Mapped[str] = mapped_column(String(16), index=True)
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Metric(Base):
    __tablename__ = "library_metrics"
    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    event: Mapped[str] = mapped_column(String(24), primary_key=True)
    outcome: Mapped[str] = mapped_column(String(16), primary_key=True)
    count: Mapped[int] = mapped_column(BigInteger, default=0)
    bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    milliseconds: Mapped[int] = mapped_column(BigInteger, default=0)


class BackupRecord(Owned, Base):
    __tablename__ = "library_backups"
    size: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Item(Owned, Base):
    __tablename__ = "library_items"
    __table_args__ = (ForeignKeyConstraint(["owner"], ["library_accounts.owner"]),)
    current: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default="available")
    revision: Mapped[int] = mapped_column(Integer, default=1)
    metadata_value: Mapped[dict] = mapped_column(Protected("library.item", academic=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Version(Owned, Base):
    __tablename__ = "library_versions"
    __table_args__ = (
        ForeignKeyConstraint(["owner", "item"], ["library_items.owner", "library_items.id"]),
    )
    item: Mapped[str] = mapped_column(String(64), index=True)
    digest: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(BigInteger)
    object_key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(24), default="available")
    processing: Mapped[str] = mapped_column(String(24), default="not_requested")
    provenance: Mapped[dict] = mapped_column(Protected("library.provenance", academic=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Grant(Owned, Base):
    __tablename__ = "library_grants"
    __table_args__ = (
        ForeignKeyConstraint(["owner", "id"], ["library_versions.owner", "library_versions.id"]),
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    payload: Mapped[dict] = mapped_column(Protected("library.grants", academic=True))


class Representation(Owned, Base):
    __tablename__ = "library_representations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner", "version"], ["library_versions.owner", "library_versions.id"]
        ),
        UniqueConstraint("owner", "version"),
    )
    version: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(Protected("library.representation", academic=True))
    size: Mapped[int] = mapped_column(BigInteger)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Intake(Owned, Base):
    __tablename__ = "library_intakes"
    __table_args__ = (
        ForeignKeyConstraint(["owner"], ["library_accounts.owner"]),
        UniqueConstraint("owner", "idempotency"),
    )
    idempotency: Mapped[str] = mapped_column(String(128))
    fingerprint: Mapped[str] = mapped_column(String(64))
    session_digest: Mapped[str] = mapped_column(String(64))
    generation: Mapped[int] = mapped_column(Integer)
    principal_generation: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(24), default="created")
    payload: Mapped[dict] = mapped_column(Protected("library.intake", academic=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Selection(Owned, Base):
    __tablename__ = "library_selections"
    __table_args__ = (
        ForeignKeyConstraint(["owner", "intake"], ["library_intakes.owner", "library_intakes.id"]),
    )
    intake: Mapped[str] = mapped_column(String(64), index=True)
    state: Mapped[str] = mapped_column(String(24), default="created")
    size: Mapped[int] = mapped_column(BigInteger)
    reserved_slots: Mapped[int] = mapped_column(Integer, default=1)
    offset: Mapped[int] = mapped_column(BigInteger, default=0)
    object_key: Mapped[str] = mapped_column(String(64), default=opaque_id)
    payload: Mapped[dict] = mapped_column(Protected("library.selection", academic=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Job(Owned, Base):
    __tablename__ = "library_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner", "version"], ["library_versions.owner", "library_versions.id"]
        ),
        UniqueConstraint("owner", "version"),
    )
    version: Mapped[str] = mapped_column(String(64))
    generation: Mapped[int] = mapped_column(Integer)
    permission: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(24), default="queued")
    lease: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Tombstone(Owned, Base):
    __tablename__ = "library_tombstones"
    __table_args__ = (ForeignKeyConstraint(["owner"], ["library_accounts.owner"]),)
    generation: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(Protected("library.deletion", academic=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Export(Owned, Base):
    __tablename__ = "library_exports"
    __table_args__ = (
        ForeignKeyConstraint(["owner"], ["library_accounts.owner"]),
        UniqueConstraint("owner", "idempotency"),
    )
    idempotency: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict] = mapped_column(Protected("library.export", academic=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Legacy(Owned, Base):
    __tablename__ = "library_legacy"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner", "version"], ["library_versions.owner", "library_versions.id"]
        ),
    )
    version: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))


class Delivery(Owned, Base):
    __tablename__ = "library_deliveries"
    __table_args__ = (
        ForeignKeyConstraint(
            ["owner", "version"], ["library_versions.owner", "library_versions.id"]
        ),
    )
    version: Mapped[str] = mapped_column(String(64))
    permission: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def install_sqlite_constraints(connection):
    """Legacy SQLite connections do not enable FK pragmas; enforce this new schema too.

    PostgreSQL uses the declared owner-qualified foreign keys directly. SQLite
    triggers only reference trusted schema identifiers, never request arguments.
    """
    if connection.dialect.name != "sqlite":
        return
    for table in Base.metadata.sorted_tables:
        for number, constraint in enumerate(table.foreign_key_constraints):
            parent = constraint.elements[0].column.table.name
            predicate = " AND ".join(
                f'parent."{fk.column.name}" = NEW."{fk.parent.name}"' for fk in constraint.elements
            )
            for operation in ("INSERT", "UPDATE"):
                connection.exec_driver_sql(
                    f'CREATE TRIGGER IF NOT EXISTS "{table.name}_owner_fk_{number}_{operation}" BEFORE {operation} ON "{table.name}" BEGIN SELECT RAISE(ABORT, \'library owner relationship violation\') WHERE NOT EXISTS (SELECT 1 FROM "{parent}" AS parent WHERE {predicate}); END'  # noqa: S608 - trusted SQLAlchemy schema identifiers only.
                )
