"""Current deletion continuity comes from a trusted live store, never the bundle."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from canvas_bridge.domain import DomainError
from canvas_bridge.storage import IndependentResource, aware
from canvas_bridge.usefulness.packet import binding
from canvas_bridge.usefulness.workspace_package import refuse


@contextmanager
def authority(bridge, local_session):
    path = bridge.settings.portability_origin_sqlite
    if path is None:
        yield local_session
        return
    path = Path(path).resolve()
    database = bridge.store.engine.url.database
    if database and Path(database).resolve() == path:
        yield local_session
        return
    # Only the operator configures this path. Read-only rollback-journal mode
    # holds a shared lock until the destination commit exits the inner context.
    engine = create_engine(
        "sqlite://",
        creator=lambda: sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=2),
    )
    engine.dialect.bridge_vault = bridge.vault
    try:
        with Session(engine) as session:
            conn = session.connection()
            if conn.exec_driver_sql("PRAGMA journal_mode").scalar().lower() != "delete":
                refuse("PORT_AUTHORITY_UNAVAILABLE", "Use a current supported source authority.")
            conn.exec_driver_sql("BEGIN")
            yield session
    except (SQLAlchemyError, sqlite3.Error, OSError, ValueError):
        refuse(
            "PORT_AUTHORITY_UNAVAILABLE", "The configured current source authority is unavailable."
        )
    finally:
        engine.dispose()


def current_doc(bridge, session, owner, ident, now):
    row = session.get(IndependentResource, ident)
    if (
        row is None
        or row.owner != owner
        or row.kind != "local_document"
        or aware(row.expires_at) <= now
        or row.content.get("portable_origin")
    ):
        refuse("PORT_SOURCE_UNAVAILABLE", "The original source is unavailable or expired.")
    bridge.independent.require_row(session, owner, row)
    contexts = session.scalars(
        select(IndependentResource).where(
            IndependentResource.owner == owner,
            IndependentResource.kind == "integrity_context",
            IndependentResource.expires_at > now,
        )
    )
    if any(
        ident in ctx.content.get("hashes", {}) and ctx.content.get("scope", {}).get("connection_id")
        for ctx in contexts
    ):
        refuse(
            "PORT_INSTITUTIONAL_EXPORT_UNAVAILABLE",
            "This source retains an institutional dependency.",
        )
    p = row.provenance
    if (
        p.get("owner") != owner
        or p.get("source_type") != "local_document"
        or p.get("content_identity") != row.version_hash
        or p.get("parents")
        or p.get("institutional_connection") is not None
        or p.get("origin") != "authenticated_browser_upload"
        or p.get("authorization") != "explicit_user_permission"
        or p.get("schema_version") != "source-provenance-1"
        or p.get("copyright") != "owner_attested"
        or p.get("source_category", "independent_import") != "independent_import"
    ):
        refuse("PORT_SOURCE_UNAVAILABLE", "Review current ownership and source eligibility.")
    bridge.independent.reject_institutional_copy(session, owner, row.version_hash)
    return row


def verify_restored_source(bridge, session, row):
    ref = row.content.get("portable_origin")
    if ref:
        with authority(bridge, session) as origin:
            source = current_doc(bridge, origin, row.owner, ref["source"], bridge.retention.clock())
            if (
                binding(source) != ref["binding"]
                or source.version_hash != row.version_hash
                or source.provenance.get("permission_version", 0) != ref["permission_version"]
            ):
                raise DomainError(
                    "permission_denied", "The original source policy or version changed."
                )


def require_original_grant(bridge, session, row, *, share, visual, scope, profile, external):
    ref = row.content.get("portable_origin")
    if not ref:
        return
    with authority(bridge, session) as origin:
        source = current_doc(bridge, origin, row.owner, ref["source"], bridge.retention.clock())
        p = source.provenance
        if (
            not set(scope) <= set(p.get("scope", []))
            or share
            and (
                not p.get("share_text")
                or not profile
                or p.get("egress_policy") != profile.model_dump(mode="json")
            )
            or visual
            and not p.get("share_visual")
            or external
            and p.get("external_egress_policy") != external.model_dump(mode="json")
        ):
            refuse(
                "PORT_ORIGINAL_GRANT_REQUIRED",
                "Review the permitted purpose and recipient at the original source.",
            )
