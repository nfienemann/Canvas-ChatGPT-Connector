"""Immutable, encrypted, owner/scope-bound inventory continuation checkpoints.

Only metadata and allowlisted traversal state are stored. Replay repeats at most
the unfinished page, not the entire course. No snapshot grants source access.
"""

import copy
import json
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from canvas_bridge.domain import DomainError, opaque_id, utcnow
from canvas_bridge.storage import LocalRecord

KIND = "file_inventory_cursor"
LIFETIME = timedelta(hours=24)
MAX_STATE_BYTES = 2_000_000


def binding(connection, course):
    return {"epoch": connection.epoch, "course": course.id, "source": course.source_id}


def save(bridge, owner, ref, bound, state):
    try:
        return _save(bridge, owner, ref, bound, state)
    except SQLAlchemyError as exc:
        # Commit acknowledgement may be lost. No new cursor is advertised.
        raise DomainError(
            "operation_uncertain",
            "The checkpoint save could not be confirmed.",
            reason_code="CHECKPOINT_COMMIT_UNCERTAIN",
        ) from exc


def _save(bridge, owner, ref, bound, state):
    if len(json.dumps(state).encode()) > MAX_STATE_BYTES:
        raise DomainError(
            "partial_data",
            "Inventory checkpoint reached its metadata limit.",
            reason_code="INVENTORY_STATE_LIMIT",
        )
    identity = opaque_id()
    expires = (utcnow() + LIFETIME).timestamp()
    with bridge.store.transaction() as session:
        current = bridge.store.connection(session, owner, ref, lock=True)
        bridge.authorize(owner, ref, bound["course"], "course", session=session).require()
        if current.epoch != bound["epoch"]:
            raise DomainError(
                "source_changed",
                "Selected scope changed during inventory.",
                reason_code="INVENTORY_SCOPE_CHANGED",
            )
        session.execute(
            delete(LocalRecord).where(
                LocalRecord.owner == owner,
                LocalRecord.connection_id == ref,
                LocalRecord.kind == KIND,
                LocalRecord.updated_at <= utcnow() - LIFETIME,
            )
        )
        session.add(
            LocalRecord(
                id=identity,
                owner=owner,
                connection_id=ref,
                kind=KIND,
                key=identity,
                version=1,
                payload={"binding": bound, "state": copy.deepcopy(state), "expires": expires},
            )
        )
    return bridge.vault.seal({"id": identity, "expires": expires}, owner, ref + ":file-inventory")


def load(bridge, owner, ref, bound, token):
    try:
        if not isinstance(token, str) or len(token) > 4096:
            raise ValueError
        value = bridge.vault.open(token, owner, ref + ":file-inventory")
        if value["expires"] <= utcnow().timestamp():
            raise ValueError
        with bridge.store.transaction() as session:
            bridge.store.connection(session, owner, ref)
            bridge.authorize(owner, ref, bound["course"], "course", session=session).require()
            row = session.scalar(
                select(LocalRecord).where(
                    LocalRecord.id == value["id"],
                    LocalRecord.owner == owner,
                    LocalRecord.connection_id == ref,
                    LocalRecord.kind == KIND,
                )
            )
            if row is None:
                raise ValueError
            if row.kind != KIND or row.payload["expires"] != value["expires"]:
                raise ValueError
            if row.payload["binding"] != bound:
                raise DomainError(
                    "source_changed",
                    "Inventory scope changed. Start a fresh inventory; old checkpoints do not grant access.",
                    reason_code="INVENTORY_SCOPE_CHANGED",
                )
            return copy.deepcopy(row.payload["state"])
    except SQLAlchemyError as exc:
        raise DomainError(
            "operation_failed",
            "Checkpoint storage could not be read.",
            reason_code="CHECKPOINT_STORAGE_UNAVAILABLE",
        ) from exc
    except DomainError:
        raise
    except Exception as exc:
        raise DomainError(
            "needs_input",
            "Inventory continuation is invalid or expired. Start a fresh inventory; previously read file results may be retained only after revalidation.",
            reason_code="INVENTORY_CURSOR_INVALID",
        ) from exc
