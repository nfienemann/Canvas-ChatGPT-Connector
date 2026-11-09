"""Selected owned course export and transactional, reviewed restoration."""

from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy import select

from canvas_bridge.domain import DomainError, opaque_id
from canvas_bridge.evidence import fingerprint
from canvas_bridge.processes.models import ProcessState
from canvas_bridge.processes.state import apply, preview
from canvas_bridge.source_authorization import LocalPreferences
from canvas_bridge.storage import IndependentResource, PrincipalState, aware
from canvas_bridge.usefulness.packet import binding, fenced, snapshot
from canvas_bridge.usefulness.workspace_authority import authority, current_doc
from canvas_bridge.usefulness.workspace_package import SCHEMA, pack, refuse, unpack, version


def timestamp(value):
    return aware(datetime.fromisoformat(value))


def preference_id(owner):
    return sha256((owner + ":preferences").encode()).hexdigest()


def record_value(record):
    return record.model_dump(mode="json", exclude={"revision", "updated_at"})


def payload_eligible(privacy):
    return (
        privacy.get("content_status") == "text_inspected_visuals_unreviewed"
        and privacy.get("page_content_filtered") is False
        and privacy.get("auxiliary_content_status") not in {"incomplete", "not_assessed"}
    )


def rebind_review(record, tag, destination):
    """Rewrite only typed citation coordinates. Academic work keys and quotations are evidence."""
    data = deepcopy(record.data)
    review = data["value"]
    for work in review["dataset"]["work"]:
        for citation in work.get("evidence", []):
            if citation.get("document_id") == tag.id:
                citation["document_id"] = destination
    for decision in review["decisions"]:
        candidate = decision["candidate"]
        if candidate["document_id"] == tag.id:
            candidate["document_id"] = destination
            candidate["id"] = fingerprint(
                [
                    destination,
                    candidate["content_hash"],
                    candidate["part"],
                    candidate["start"],
                    candidate["quote"],
                ]
            )
        for citation in (decision.get("correction") or {}).get("evidence", []):
            if citation.get("document_id") == tag.id:
                citation["document_id"] = destination
    sources = tuple(
        s.model_copy(update={"id": destination}) if s == tag else s for s in record.sources
    )
    return record.model_copy(update={"data": data, "sources": sources})


class Workspace:
    def __init__(self, bridge):
        self.bridge = bridge
        self.repo = bridge.processes.repository

    def _download_link(self, owner, record, recipient):
        from canvas_bridge.approval_policy import CATEGORIES

        if (
            recipient is None
            or record.kind != "identity"
            or not record.data.get("canonical_link_proposal")
        ):
            refuse(
                "PORT_INSTITUTIONAL_EXPORT_UNAVAILABLE",
                "A current user-download policy is required.",
            )
        from canvas_bridge.processes.service import plain

        # Use the established public identity projection. The local revision is
        # separately reviewed as container version metadata, never inferred at restore.
        value = plain(record, public=True)
        value.pop("revision")
        wire = {"records": [value], "version": record.revision}
        for connection in {s.connection for s in record.sources if s.origin == "institutional"}:
            self.bridge.connection_policy(
                owner, connection, CATEGORIES, activity="share", recipient="user_download"
            )
            clean = self.bridge.egress.connection_export(owner, connection, recipient, wire)
            if clean != wire:
                refuse(
                    "PORT_INSTITUTIONAL_EXPORT_UNAVAILABLE",
                    "The selected link exceeded its current download permission.",
                )
        return wire

    def export(
        self,
        owner,
        course,
        ids,
        docs,
        *,
        originals=False,
        preferences=False,
        generation=None,
        recipient=None,
    ):
        self.bridge.usefulness.enabled()
        if (
            not (ids or docs or preferences)
            or len(ids) > 500
            or len(docs) > 20
            or not 1 <= len(course) <= 100
        ):
            refuse("PORT_SELECTION_REQUIRED", "Choose a bounded course and its records.")
        now = self.bridge.retention.clock()
        payloads, documents, records, omitted = {}, [], [], []
        approved_links, link_reasons, link_exports = {}, {}, {}
        if recipient is not None:
            for ident in ids:
                try:
                    candidate = self.repo.read(owner, ident)
                    if candidate.scope.course != course or not any(
                        s.origin == "institutional" for s in candidate.sources
                    ):
                        continue
                    link_exports[ident] = self._download_link(owner, candidate, recipient)
                    approved_links[ident] = candidate
                except DomainError as exc:
                    link_reasons[ident] = exc.reason_code or exc.status
        with self.bridge.store.transaction() as session:
            principal = self.bridge.store.principal(session, owner)
            if generation is not None and principal.generation != generation:
                refuse("PORT_ACCOUNT_CHANGED", "Sign in again to export.")
            row, state = self.repo._load(session, owner)
            pending = list(dict.fromkeys(ids))
            visited = set()
            doc_ids = set(docs)
            while pending:
                ident = pending.pop()
                if ident in visited:
                    continue
                visited.add(ident)
                rec = state.records.get(ident)
                if not rec or rec.scope.course != course:
                    omitted.append({"id": ident, "reason": "unavailable_in_selection"})
                    continue
                try:
                    self.repo._require(session, owner, rec, "export")
                except DomainError:
                    omitted.append({"id": ident, "reason": "source_unavailable"})
                    continue
                if (
                    any(s.origin == "institutional" for s in rec.sources)
                    and approved_links.get(ident) != rec
                ):
                    # Mixed-origin records require live provider reauthorization before release.
                    omitted.append(
                        {
                            "id": ident,
                            "reason": link_reasons.get(ident, "institutional_export_unavailable"),
                        }
                    )
                    continue
                records.append(
                    link_exports[ident]["records"][0]
                    if ident in approved_links
                    else rec.model_dump(mode="json")
                )
                pending.extend(rec.depends_on)
                doc_ids.update(s.id for s in rec.sources if s.origin == "local_document")
            for ident in sorted(doc_ids):
                try:
                    doc = current_doc(self.bridge, session, owner, ident, now)
                    if doc.content.get("course", "independent") != course:
                        raise DomainError("permission_denied", "Outside selected course.")
                    content = doc.content
                    versions = []
                    for h in content.get("version_history", []):
                        if h.get("original_bytes"):
                            self.bridge.independent.reject_institutional_copy(
                                session, owner, h["hash"]
                            )
                            versions.append(
                                version(
                                    h["original_bytes"],
                                    h["hash"],
                                    h["logical_path"],
                                    h["acquired_at"],
                                    originals and payload_eligible(h.get("privacy", {})),
                                    payloads,
                                )
                            )
                    versions.append(
                        version(
                            content["bytes"],
                            doc.version_hash,
                            content.get("packet", {}).get("current_path", content["filename"]),
                            doc.provenance["acquired_at"],
                            originals and payload_eligible(content["parsed"].get("privacy", {})),
                            payloads,
                        )
                    )
                    documents.append(
                        {
                            "id": ident,
                            "binding": binding(doc),
                            "hash": doc.version_hash,
                            "format": content["format"],
                            "purpose": content.get("purpose", "material"),
                            "term": content.get("packet", {}).get("term", "unspecified"),
                            "versions": versions,
                            "expires_at": aware(doc.expires_at).isoformat(),
                            "policy": fingerprint(doc.provenance),
                        }
                    )
                except DomainError as exc:
                    if exc.reason_code == "PORT_PACKAGE_LIMIT":
                        raise
                    omitted.append({"id": ident, "reason": exc.reason_code or "source_unavailable"})
            prefs = None
            if preferences:
                pref = session.get(IndependentResource, preference_id(owner))
                if (
                    pref
                    and pref.owner == owner
                    and pref.kind == "local_preferences"
                    and aware(pref.expires_at) > now
                ):
                    LocalPreferences.model_validate(pref.content["value"])
                    prefs = {
                        "id": pref.id,
                        "value": pref.content,
                        "hash": pref.version_hash,
                        "created_at": aware(pref.created_at).isoformat(),
                        "expires_at": aware(pref.expires_at).isoformat(),
                    }
                else:
                    omitted.append({"id": "preferences", "reason": "unavailable_in_selection"})
            manifest = {
                "schema_version": SCHEMA,
                "export_id": opaque_id(),
                "owner": owner,
                "generation": principal.generation,
                "course": course,
                "exported_at": now.isoformat(),
                "process": {
                    "schema_version": "academic-process-export-1",
                    "records": records,
                    "authority": "portable_evidence_only",
                    "external_transfer": False,
                },
                "selected": {
                    "records": sorted(set(ids)),
                    "documents": sorted(set(docs)),
                    "preferences": preferences,
                },
                "preferences": prefs,
                "link_versions": {
                    k: v["version"]
                    for k, v in link_exports.items()
                    if any(r["id"] == k for r in records)
                },
                "documents": documents,
                "omitted": omitted,
                "retention": (
                    {
                        "created_at": aware(row.created_at).isoformat(),
                        "expires_at": aware(row.expires_at).isoformat(),
                        "basis": "original_process_container",
                    }
                    if records
                    else None
                ),
            }
            payloads = {
                v["hash"]: payloads[v["hash"]]
                for d in documents
                for v in d["versions"]
                if v["payload"] == "included"
            }
            raw = pack(manifest, payloads)
            # A digest in a package is not authority. Retain independent issuance evidence.
            witnesses = session.scalars(
                select(IndependentResource.id)
                .where(
                    IndependentResource.owner == owner,
                    IndependentResource.kind == "workspace_export",
                    IndependentResource.expires_at > now,
                )
                .limit(100)
            ).all()
            if len(witnesses) >= 100:
                refuse("PORT_EXPORT_CAPACITY", "Allow earlier export receipts to expire.")
            session.add(
                IndependentResource(
                    id=manifest["export_id"],
                    owner=owner,
                    kind="workspace_export",
                    version_hash=sha256(raw).hexdigest(),
                    content={},
                    provenance={"generation": principal.generation},
                    created_at=now,
                    expires_at=now + timedelta(days=30),
                )
            )
        for ident, link in approved_links.items():
            if self.repo.read(owner, ident) != link:
                refuse("PORT_SOURCE_CHANGED", "The selected association changed during export.")
            self._download_link(owner, link, recipient)
        return raw

    def restore(self, owner, raw, *, generation, choices=(), confirmation=None, key=None):
        self.bridge.usefulness.enabled()
        manifest, docs, records, payloads = unpack(raw, owner)
        digest = sha256(raw).hexdigest()
        now = self.bridge.retention.clock()
        if (
            not isinstance(choices, (tuple, list))
            or len(choices) > 500
            or any(not isinstance(c, str) or len(c) > 200 for c in choices)
        ):
            refuse("PORT_CONFLICT_DECISION", "Choose individual record conflicts to replace.")
        if confirmation and (not isinstance(key, str) or not 1 <= len(key) <= 100):
            refuse("PORT_RETRY_KEY_REQUIRED", "Use the reviewed restore operation.")
        with self.bridge.store.transaction() as session:
            principal = self.bridge.store.principal(session, owner)
            if principal.generation != generation:
                refuse("PORT_ACCOUNT_CHANGED", "Sign in again to review the course restore.")
            with authority(self.bridge, session) as origin:
                witness = origin.get(IndependentResource, manifest["export_id"])
                original_owner = origin.get(PrincipalState, owner)
                if (
                    not witness
                    or witness.owner != owner
                    or witness.kind != "workspace_export"
                    or witness.version_hash != digest
                    or aware(witness.expires_at) <= now
                    or not original_owner
                    or original_owner.generation != manifest["generation"]
                    or generation != manifest["generation"]
                ):
                    refuse(
                        "PORT_AUTHORITY_UNAVAILABLE",
                        "Current owner and post-export deletion history could not be verified.",
                    )
                row, state = self.repo._load(session, owner)
                retry = fingerprint(["course-restore", owner, key])
                request_hash = fingerprint([digest, confirmation, sorted(choices), generation])
                prior = state.receipts.get(retry) if confirmation else None
                if prior:
                    if prior["request_hash"] != request_hash:
                        refuse(
                            "PORT_RETRY_CONFLICT", "This retry key belongs to a different restore."
                        )
                    return prior
                source_state = ProcessState()
                if records:
                    try:
                        source_state = self.repo._load(origin, owner)[1]
                    except DomainError as error:
                        if error.reason_code != "PROCESS_STATE_EXPIRED":
                            raise
                selected = RestoreUnit(self, session, origin, owner, now, manifest, state, choices)
                selected.documents(docs, payloads)
                selected.records(records, source_state)
                selected.preferences()
                report = {
                    "bundle_hash": digest,
                    "history_authority": "current_store"
                    if origin is session
                    else "paired_live_sqlite",
                    "generation": generation,
                    "state_version": state.version,
                    "documents": selected.doc_results,
                    "records": selected.record_results,
                    "preferences": selected.preference_result,
                    "omitted": manifest["omitted"],
                    "source_id_map": selected.mapping,
                    "external_writes": False,
                    "unit": "eligible_dependency_closed_course_records",
                    "record_id_map": {
                        k: k
                        for k, v in selected.record_results.items()
                        if v["action"] in {"create", "reuse", "replace"}
                    },
                }
                reviewed = fingerprint([owner, report, sorted(choices)])
                if confirmation is None:
                    report["preview_id"] = self.bridge.vault.seal(
                        {
                            "reviewed": reviewed,
                            "expires": (now + timedelta(minutes=15)).isoformat(),
                        },
                        owner,
                        "course-workspace-preview-1",
                    )
                    return report
                from cryptography.exceptions import InvalidTag

                try:
                    proof = self.bridge.vault.open(
                        confirmation, owner, "course-workspace-preview-1"
                    )
                except (ValueError, TypeError, InvalidTag):
                    refuse("PORT_PREVIEW_CHANGED", "Review a fresh restore preview.")
                report["preview_id"] = confirmation
                if reviewed != proof["reviewed"] or timestamp(proof["expires"]) <= now:
                    refuse(
                        "PORT_PREVIEW_CHANGED",
                        "The destination or a source changed. Review a fresh preview.",
                    )
                receipt = selected.commit(row, state, report, retry, request_hash)
                # Finish the destination commit while the external origin read lock is still held.
                session.commit()
                return receipt


class RestoreUnit:
    def __init__(self, workspace, session, origin, owner, now, manifest, state, choices):
        self.bridge, self.repo = workspace.bridge, workspace.repo
        self.session, self.origin, self.owner, self.now = session, origin, owner, now
        self.manifest, self.state, self.choices = manifest, state, set(choices)
        self.mapping, self.doc_results, self.record_results = {}, {}, {}
        self.payloads = {}
        self.new_docs, self.after = [], []
        self.projected = state
        self.preference_result, self.pref = None, None

    def documents(self, docs, payloads):
        self.payloads = payloads
        current = self.session.scalars(
            select(IndependentResource).where(
                IndependentResource.owner == self.owner,
                IndependentResource.kind == "local_document",
            )
        ).all()
        for ident, item in docs.items():
            try:
                src = current_doc(self.bridge, self.origin, self.owner, ident, self.now)
                if (
                    binding(src) != item["binding"]
                    or src.version_hash != item["hash"]
                    or fingerprint(src.provenance) != item["policy"]
                    or timestamp(item["expires_at"]) <= self.now
                ):
                    refuse("PORT_SOURCE_CHANGED", "Current source version or permissions changed.")
                self.bridge.independent.reject_institutional_copy(
                    self.session, self.owner, src.version_hash
                )
                if fenced(
                    self.session,
                    self.owner,
                    self.manifest["course"],
                    item["purpose"],
                    item["term"],
                    item["binding"],
                    src.version_hash,
                    now=self.now,
                ):
                    refuse("PORT_SOURCE_DELETED", "A destination deletion excludes this source.")
                matches = [d for d in current if binding(d) == item["binding"]]
                if matches:
                    if (
                        len(matches) != 1
                        or matches[0].version_hash != src.version_hash
                        or aware(matches[0].expires_at) <= self.now
                    ):
                        refuse("PORT_SOURCE_COLLISION", "Review the destination source collision.")
                    dest = self.bridge.independent.require_row(self.session, self.owner, matches[0])
                    if (
                        dest.content.get("course", "independent") != self.manifest["course"]
                        or dest.content.get("purpose", "material") != item["purpose"]
                        or dest.content.get("packet", {}).get("term", "unspecified") != item["term"]
                    ):
                        refuse("PORT_SOURCE_COLLISION", "Review the destination source scope.")
                    self.mapping[ident] = dest.id
                    self.doc_results[ident] = {"action": "reuse", "target": snapshot(dest)}
                    continue
                if item["versions"][-1]["payload"] != "included":
                    refuse(
                        "PORT_REFERENCE_UNRESOLVED",
                        "Select the current matching source in this destination.",
                    )
                target = ident
                if self.session.get(IndependentResource, target):
                    target = fingerprint(["restored-document", self.owner, item["binding"]])
                if len(current) + len(self.new_docs) >= 20 or self.session.get(
                    IndependentResource, target
                ):
                    refuse(
                        "PORT_SOURCE_COLLISION",
                        "A destination identity or capacity limit prevents this create.",
                    )
                # Keep existing source and nested academic IDs when they are free.
                self.mapping[ident] = target
                self.new_docs.append((src, item))
                self.doc_results[ident] = {"action": "create", "target": None}
            except DomainError as error:
                self.doc_results[ident] = {
                    "action": "blocked",
                    "reason": error.reason_code or error.status,
                }

    def records(self, records, source_state):
        pending = {r.id: r for r in records}
        while pending:
            batch = [r for r in pending.values() if not set(r.depends_on) & pending.keys()]
            if not batch:
                refuse("PORT_DEPENDENCY_CYCLE", "The workspace contains a dependency cycle.")
            for rec in batch:
                del pending[rec.id]
                existing = self.projected.records.get(rec.id)
                action = self.record_action(rec, existing, source_state)
                self.record_results[rec.id] = {
                    "action": action,
                    "imported_revision": rec.revision,
                    "destination_revision": existing.revision if existing else None,
                }
                if action in {"create", "replace"}:
                    change = self.after[-1]
                    self.record_results[rec.id]["affected"] = list(change.affected)
                    self.projected = apply(self.projected, change, now=self.now)
        if self.choices - (set(self.record_results) | {"preferences"}):
            refuse("PORT_CONFLICT_DECISION", "Choose only conflicts from the selected workspace.")

    def record_action(self, rec, existing, source_state):
        deletion_key = fingerprint(["portable-record-deletion", self.owner, rec.id])
        for session in (self.session, self.origin):
            deletion = session.get(IndependentResource, deletion_key)
            if deletion and aware(deletion.created_at) >= timestamp(self.manifest["exported_at"]):
                return "blocked_deleted_record"
        if (
            rec.id not in source_state.records
            or timestamp(self.manifest["retention"]["expires_at"]) <= self.now
        ):
            return "blocked_expired_or_deleted"
        if rec.scope.course != self.manifest["course"] or rec.state != "valid":
            return "blocked_scope_or_state"
        if any(
            self.record_results.get(p, {}).get("action") not in {"create", "reuse", "replace"}
            for p in rec.depends_on
        ):
            return "unresolved_dependency"
        for tag in rec.sources:
            if not tag.observed_at <= self.now < tag.expires_at:
                return "blocked_source_expired"
            if tag.origin == "user_declaration":
                from canvas_bridge.usefulness.records import authorize_declaration

                authorize_declaration(self.session, self.owner, tag)
            elif tag.origin == "local_document":
                if tag.id not in self.mapping:
                    return "unresolved_source"
                doc = self.origin.get(IndependentResource, tag.id)
                if doc.version_hash != tag.version:
                    return "blocked_source_changed"
                if self.mapping[tag.id] != tag.id:
                    if (
                        rec.data.get("schema") != "usefulness-1"
                        or rec.data.get("subtype") != "import_review"
                    ):
                        return "unresolved_nested_identity"
                    rec = rebind_review(rec, tag, self.mapping[tag.id])
            elif tag.origin == "institutional" and rec.kind == "identity":
                try:
                    self.repo.authorize(self.origin, self.owner, tag, "read")
                    self.repo.authorize(self.session, self.owner, tag, "write")
                except DomainError:
                    return "unresolved_origin"
            else:
                return "unresolved_origin"
        if rec.kind in {"plan", "projection", "reminder"} or rec.data.get("subtype") == "plan":
            return "historical_replan_required"
        if self.origin is not self.session and rec.data.get("schema") == "usefulness-1":
            rec = rec.model_copy(
                update={"data": rec.data | {"share": False, "recipient_policy": None}}
            )
        if rec.data.get("subtype") == "import_review":
            local = next((s for s in rec.sources if s.origin == "local_document"), None)
            doc = self.session.get(IndependentResource, local.id) if local else None
            existing_review = doc.content.get("review", {}) if doc else {}
            if existing_review and existing_review.get("record_id") != rec.id:
                return "unresolved_destination_review"
        if existing and record_value(rec) == record_value(existing):
            return "reuse"
        if existing and (existing.scope != rec.scope or existing.kind != rec.kind):
            return "blocked_identity_collision"
        if existing and rec.id not in self.choices:
            return "conflict"
        if existing:
            try:
                self.repo._require(self.session, self.owner, existing, "write")
            except DomainError:
                return "blocked_destination_source"
        updated = rec.model_copy(update={"revision": existing.revision + 1 if existing else 1})
        self.after.append(
            preview(
                self.projected,
                self.owner,
                rec.id,
                updated,
                "correction" if existing else "create",
                now=self.now,
            )
        )
        return "replace" if existing else "create"

    def preferences(self):
        data = self.manifest["preferences"]
        if not data:
            return
        src = self.origin.get(IndependentResource, preference_id(self.owner))
        dest = self.session.get(IndependentResource, preference_id(self.owner))
        if (
            not src
            or src.owner != self.owner
            or src.kind != "local_preferences"
            or aware(src.expires_at) <= self.now
            or timestamp(data["expires_at"]) <= self.now
        ):
            self.preference_result = {"action": "blocked_expired_or_deleted"}
            return
        value = LocalPreferences.model_validate(data["value"]["value"]).validated()
        if dest and (
            dest.owner != self.owner
            or dest.kind != "local_preferences"
            or aware(dest.expires_at) <= self.now
        ):
            self.preference_result = {"action": "blocked_destination_state"}
            return
        current = dest.content["version"] if dest else 0
        action = (
            "reuse"
            if dest and dest.content["value"] == value
            else "conflict"
            if dest and "preferences" not in self.choices
            else "replace"
            if dest
            else "create"
        )
        self.preference_result = {
            "action": action,
            "destination_revision": current,
            "imported_revision": data["value"]["version"],
        }
        if action in {"create", "replace"}:
            self.pref = (dest, src, value, current + 1)

    def commit(self, row, state, report, retry, request_hash):
        for src, item in self.new_docs:
            # Parsed derivatives come only from the verified live source. Do not transfer recipient approvals.
            content = {
                k: deepcopy(v)
                for k, v in src.content.items()
                if k
                in {
                    "filename",
                    "course",
                    "purpose",
                    "format",
                    "parsed",
                    "bytes",
                    "packet",
                    "version_history",
                }
            }
            if "packet" not in content:
                content["packet"] = {
                    "binding": item["binding"],
                    "term": item["term"],
                    "locations": [content["filename"]],
                    "current_path": content["filename"],
                }
            import base64

            content["bytes"] = base64.b64encode(self.payloads[src.version_hash]).decode()
            included = {v["hash"] for v in item["versions"] if v["payload"] == "included"}
            for historical in content.get("version_history", []):
                if historical["hash"] not in included:
                    historical.pop("original_bytes", None)
                else:
                    historical["original_bytes"] = base64.b64encode(
                        self.payloads[historical["hash"]]
                    ).decode()
            content["portable_origin"] = {
                "source": src.id,
                "binding": item["binding"],
                "permission_version": src.provenance.get("permission_version", 0),
            }
            policy = src.provenance | {
                "share_text": False,
                "share_visual": False,
                "egress_policy": None,
                "external_egress_policy": None,
                "scope": ["document_reading", "study"],
            }
            policy["revocation_dependency"] = self.mapping[src.id]
            self.session.add(
                IndependentResource(
                    id=self.mapping[src.id],
                    owner=self.owner,
                    kind="local_document",
                    version_hash=src.version_hash,
                    content=content,
                    provenance=policy,
                    created_at=src.created_at,
                    expires_at=min(
                        aware(src.expires_at),
                        timestamp(item["expires_at"]),
                        self.now
                        + timedelta(hours=self.bridge.settings.independent_retention_hours),
                    ),
                )
            )
        self.session.flush()
        if self.pref:
            import json

            dest, src, value, revision = self.pref
            data = self.manifest["preferences"]
            if dest is None:
                dest = IndependentResource(
                    id=src.id,
                    owner=self.owner,
                    kind="local_preferences",
                    created_at=timestamp(data["created_at"]),
                    expires_at=timestamp(data["expires_at"]),
                )
                self.session.add(dest)
            dest.expires_at = min(
                aware(dest.expires_at), timestamp(data["expires_at"]), aware(src.expires_at)
            )
            dest.content = {"value": value, "version": revision}
            dest.version_hash = sha256(
                json.dumps(dest.content, sort_keys=True).encode()
            ).hexdigest()
            dest.provenance = src.provenance | {"content_identity": dest.version_hash}
        for change in self.after:
            rec = change.after
            self.repo._require(self.session, self.owner, rec, "write")
            state = apply(state, change, now=self.now)
            if (
                rec.data.get("schema") == "usefulness-1"
                and rec.data.get("subtype") == "import_review"
            ):
                doc = next(s for s in rec.sources if s.origin == "local_document")
                dest = self.session.get(IndependentResource, doc.id)
                dest.content = dest.content | {
                    "review": {
                        "record_id": rec.id,
                        "revision": rec.revision,
                        "source_hash": doc.version,
                        "observed_at": self.now.isoformat(),
                    },
                    "reviewed_dataset": rec.data["value"]["dataset"],
                }
        actions = [v["action"] for v in self.doc_results.values()] + [
            v["action"] for v in self.record_results.values()
        ]
        if self.preference_result:
            actions.append(self.preference_result["action"])
        receipt = {
            "request_hash": request_hash,
            "preview_id": report["preview_id"],
            "version": state.version,
            "external_writes": False,
            "unit": report["unit"],
            "history_authority": report["history_authority"],
            "outcomes": {k: report[k] for k in ("documents", "records", "preferences", "omitted")},
            "status": "complete"
            if all(a in {"create", "replace", "reuse"} for a in actions)
            and not self.manifest["omitted"]
            else "partial",
            "record_count": len(self.after),
            "document_count": len(self.new_docs),
            "source_id_map": self.mapping,
            "record_id_map": report["record_id_map"],
        }
        state = ProcessState.model_validate(
            state.model_dump()
            | {"receipts": dict(list((state.receipts | {retry: receipt}).items())[-500:])}
        )
        self.repo._save(self.session, self.owner, row, state)
        container = self.session.get(IndependentResource, self.repo.identity(self.owner))
        retention = self.manifest["retention"]
        if self.after and retention:
            if row is None:
                container.created_at = timestamp(retention["created_at"])
            container.expires_at = min(
                aware(container.expires_at), timestamp(retention["expires_at"])
            )
        return receipt
