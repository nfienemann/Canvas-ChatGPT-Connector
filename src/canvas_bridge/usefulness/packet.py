"""Reviewable packet observations. Authenticated settings supplies the owner and scope."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import PurePosixPath

from sqlalchemy import select

from canvas_bridge.domain import DomainError
from canvas_bridge.evidence import fingerprint
from canvas_bridge.storage import IndependentResource, aware


def changed():
    raise DomainError("source_changed", "The source selection changed. Review the packet again.")


def documents(session, owner, course, purpose, term, now):
    rows = session.scalars(
        select(IndependentResource).where(
            IndependentResource.owner == owner,
            IndependentResource.kind == "local_document",
            IndependentResource.expires_at > now,
        )
    )
    return [
        row
        for row in rows
        if row.content.get("course", "independent") == course
        and row.content.get("purpose", "material") == purpose
        and row.content.get("packet", {}).get("term", "unspecified") == term
    ]


def snapshot(row):
    return fingerprint(
        [
            row.id,
            row.version_hash,
            binding(row),
            row.provenance,
            row.content.get("metadata_revision"),
            aware(row.expires_at).isoformat(),
        ]
    )


def binding(row):
    return row.content.get("packet", {}).get("binding") or fingerprint(["legacy-source", row.id])


def locations(row):
    return row.content.get("packet", {}).get("locations") or [row.content.get("filename")]


@dataclass(frozen=True)
class Member:
    path: str
    digest: str
    term: str
    binding: str
    target: str | None
    before: str | None
    disposition: str
    batch_id: str | None = None
    index: int = 0
    attempt: str | None = None

    def fields(self):
        return {
            "logical_path": self.path,
            "content_hash": self.digest,
            "binding": self.binding,
            "target": self.target,
            "before": self.before,
            "disposition": self.disposition,
            "term": self.term,
        }

    def check(self, session, owner, course, purpose, now):
        rows = documents(session, owner, course, purpose, self.term, now)
        if any(self.path in locations(r) and r.id != self.target for r in rows):
            changed()
        if self.target:
            row = next((r for r in rows if r.id == self.target), None)
            if not row or snapshot(row) != self.before:
                changed()
            return row
        if fenced(session, owner, course, purpose, self.term, self.binding, self.digest, now=now):
            raise DomainError(
                "permission_denied",
                "A prior deletion excludes this packet source.",
                reason_code="PORT_SOURCE_DELETED",
            )
        if any(binding(row) == self.binding or self.path in locations(row) for row in rows):
            changed()
        return None

    def publish(self, session, owner, row, now):
        from copy import deepcopy

        if not self.batch_id:
            changed()
        receipt = session.get(IndependentResource, self.batch_id)
        if (
            not receipt
            or receipt.owner != owner
            or receipt.kind != "import_batch"
            or receipt.content.get("attempt") != self.attempt
            or receipt.content["state"] != "extracting"
            or aware(receipt.expires_at) <= now
        ):
            changed()
        content = deepcopy(receipt.content)
        item = content["items"][self.index]
        if item["content_hash"] != row.version_hash or item["binding"] != binding(row):
            changed()
        item.update(
            state="ready",
            document_id=row.id,
            extraction=row.content["parsed"].get("coverage", "unknown"),
        )
        receipt.content, receipt.version_hash = content, fingerprint(content)

    def metadata(self, row, now):
        paths = list(locations(row)) if row else []
        if self.path not in paths:
            if len(paths) >= 64:
                raise DomainError("needs_input", "This source reached its location history limit.")
            paths.append(self.path)
        return {
            "binding": self.binding,
            "term": self.term,
            "locations": paths,
            "current_path": self.path,
            "observed_at": now.isoformat(),
        }


def eligible_documents(bridge, session, owner, course, purpose, term, now):
    visible = []
    for row in documents(session, owner, course, purpose, term, now):
        try:
            bridge.independent.require_row(session, owner, row)
            bridge.independent.reject_institutional_copy(session, owner, row.version_hash)
        except DomainError:
            continue
        visible.append(row)
    return visible


def plan(session, owner, course, purpose, term, files, decisions, now, rows):
    if not all(isinstance(s, str) and 0 < len(s) <= 100 for s in (term, course)):
        raise DomainError("needs_input", "Choose a bounded course and term.")
    items = []
    for path, body, _ in files:
        digest = sha256(body).hexdigest()
        by_path = [r for r in rows if path in locations(r)]
        by_hash = [
            r
            for r in rows
            if r.version_hash == digest
            and PurePosixPath(path).suffix.lower().lstrip(".") == r.content["format"]
        ]
        candidates = {
            r.id: r
            for r in (
                by_path
                if by_path and all(r.version_hash == digest for r in by_path)
                else by_path + by_hash
            )
        }
        target = next(iter(candidates.values())) if len(candidates) == 1 else None
        ambiguous = len(candidates) > 1
        if ambiguous and path in decisions:
            target = candidates.get(decisions[path])
            if not target:
                changed()
            ambiguous = False
        disposition = (
            "ambiguous"
            if ambiguous
            else "new_binding"
            if not target
            else "new_version"
            if target.version_hash != digest
            else "unchanged"
            if path in locations(target)
            else "relocated"
        )
        ident = (
            binding(target)
            if target
            else fingerprint(["packet-source-1", owner, "independent", term, course, purpose, path])
        )
        if not target and fenced(session, owner, course, purpose, term, ident, digest, now=now):
            disposition = "deleted"
        item = Member(
            path,
            digest,
            term,
            ident,
            target.id if target else None,
            snapshot(target) if target else None,
            disposition,
        ).fields()
        if ambiguous or path in decisions:
            item["candidates"] = sorted(candidates)
            item["candidate_locations"] = {
                ident: candidates[ident]
                .content.get("packet", {})
                .get("current_path", candidates[ident].content["filename"])
                for ident in sorted(candidates)
            }
        items.append(item)
    if set(decisions) - {i["logical_path"] for i in items if "candidates" in i}:
        changed()
    # Two simultaneous versions cannot both become the current version of one source.
    for item in items:
        if item["target"] and any(
            other["target"] == item["target"] and other["content_hash"] != item["content_hash"]
            for other in items
        ):
            item["disposition"] = "conflicting_mapping"
    return items


def member(item, batch_id, index, attempt):
    return Member(
        item["logical_path"],
        item["content_hash"],
        item["term"],
        item["binding"],
        item["target"],
        item["before"],
        item["disposition"],
        batch_id,
        index,
        attempt,
    )


def invalidate_version(bridge, session, owner, ident, version, now):
    """Preserve work and its original basis while making affected derivations stale."""
    from canvas_bridge.processes.state import descendants, indexed

    repo = bridge.processes.repository
    row, state = repo._load(session, owner)
    direct = {
        r.id
        for r in state.records.values()
        if any(s.id == ident and s.version == version for s in r.sources)
    }
    affected = direct | {child for key in direct for child in descendants(state, key)}
    if affected:
        records = dict(state.records)
        for key in affected:
            old = records[key]
            records[key] = old.model_copy(
                update={
                    "state": "stale" if old.state == "valid" else old.state,
                    "revision": old.revision + 1,
                    "updated_at": now,
                }
            )
        repo._save(
            session,
            owner,
            row,
            indexed(
                records,
                version=state.version + 1,
                revisions=state.revisions,
                receipts=state.receipts,
            ),
        )


def coverage(session, owner, course, purpose, term, items, expected, now, retained):
    import re

    if (
        not isinstance(expected, dict)
        or len(expected) > 100
        or any(
            not isinstance(k, str)
            or not 1 <= len(k) <= 2048
            or (v is not None and (not isinstance(v, str) or not re.fullmatch("[a-f0-9]{64}", v)))
            for k, v in expected.items()
        )
    ):
        raise DomainError(
            "needs_input", "Choose bounded source paths and optional SHA-256 versions."
        )
    by_path = {p: r for r in retained for p in locations(r)}
    # Earlier receipts record unresolved selections for this exact owner, role,
    # term and course. An omission on retry does not discard the expected hash.
    pending = {}
    receipts = session.scalars(
        select(IndependentResource)
        .where(
            IndependentResource.owner == owner,
            IndependentResource.kind == "import_batch",
            IndependentResource.expires_at > now,
        )
        .order_by(IndependentResource.created_at, IndependentResource.id)
        .limit(40)
    )
    for receipt in receipts:
        data = receipt.content
        if (data.get("course"), data.get("purpose"), data.get("term")) != (course, purpose, term):
            continue
        for ref in data.get("coverage", {}).get("missing", []):
            path = ref["logical_path"]
            if path not in by_path:
                pending[path] = ref.get("expected_hash")
        for item in data.get("items", []):
            if (
                item.get("disposition") == "unexpected_version"
                and item.get("logical_path") not in by_path
            ):
                pending[item["logical_path"]] = item["expected_hash"]
    expected = {**pending, **{k: v or pending.get(k) for k, v in expected.items()}}
    if len(expected) > 100:
        raise DomainError(
            "needs_input", "The selected references exceed this course coverage budget."
        )
    selected = {i["logical_path"] for i in items}
    for item in items:
        wanted = expected.get(item["logical_path"])
        if wanted and wanted != item["content_hash"]:
            item["disposition"] = "unexpected_version"
            item["expected_hash"] = wanted
    missing = []
    for path in sorted(set(expected) - selected):
        row = by_path.get(path)
        if row and expected[path] and row.version_hash != expected[path]:
            row = None
        missing.append(
            {
                "logical_path": path,
                "expected_hash": expected[path],
                "observation": "not_observed",
                "retained_version": row.version_hash if row else None,
            }
        )
    observed = {i["target"] for i in items}
    return {
        "mode": "incremental",
        "missing": missing,
        "omitted_bindings": sorted(binding(r) for r in retained if r.id not in observed),
    }


def fence_id(owner, course, purpose, term, value):
    return fingerprint(["local-portability-fence-1", owner, course, purpose, term, value])


def fence_deletion(session, row, now):
    from datetime import timedelta

    content = row.content
    keys = {
        binding(row),
        row.version_hash,
        *(h["hash"] for h in content.get("version_history", [])),
    }
    for key in keys:
        ident = fence_id(
            row.owner,
            content.get("course", "independent"),
            content.get("purpose", "material"),
            content.get("packet", {}).get("term", "unspecified"),
            key,
        )
        fence = session.get(IndependentResource, ident)
        if fence is None:
            fence = IndependentResource(
                id=ident,
                owner=row.owner,
                kind="local_deletion_fence",
                provenance={"retention_class": "deletion_fence"},
                content={},
                version_hash=ident,
            )
            session.add(fence)
        fence.created_at = now
        fence.expires_at = now + timedelta(days=91)


def fenced(session, owner, course, purpose, term, *values, now):
    return any(
        f and aware(f.expires_at) > now
        for f in (
            session.get(IndependentResource, fence_id(owner, course, purpose, term, v))
            for v in values
        )
    )
